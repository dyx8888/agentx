"""
Feedback API for collecting human feedback and enabling self-evolution
"""

import os  # 用于构建数据库文件路径
import sqlite3  # 使用 SQLite 存储反馈数据，轻量级且无需额外数据库服务
from datetime import datetime  # 用于记录反馈时间戳
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.core.logging import get_logger  # 结构化日志，追踪反馈处理和知识库写入
from app.database import User

logger = get_logger(__name__)

# Get project root directory for absolute paths
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)  # 向上三级获取项目根目录，确保路径一致性

# Initialize APIRouter
router = APIRouter(tags=["feedback"])


def add_knowledge(text: str, metadata: dict, company_id: str = "default") -> str:
    """Lazy wrapper to avoid constructing MCP servers during app import."""
    from app.mcp_servers.knowledge_retrieval_server import add_knowledge as _add_knowledge

    return _add_knowledge(text=text, metadata=metadata, company_id=company_id)


class FeedbackRequest(BaseModel):
    """Request model for feedback submission"""

    session_id: str | None = None  # 会话 ID，用于追踪一次对话中的反馈
    tool_name: str = "general"  # 产生反馈的工具名称，便于按工具分析改进
    original_output: str | None = None  # 原始 AI 输出，用于对比学习
    human_edited_output: str | None = None  # 人工编辑后的输出，作为训练/知识库的优质数据
    feedback_text: str | None = None  # 轻量反馈文本，支持前端点赞/点踩/评论
    comment: str | None = None  # feedback_text 的常见别名
    rating: int | None = None  # 轻量评分/点赞点踩值
    kol_name: str = None  # 可选：关联的达人名称
    product_name: str = None  # 可选：关联的产品名称
    company_id: str = "default"  # 租户隔离，默认值确保向后兼容
    agent_id: str = (
        None  # Optional agent ID for tracking  # 可选：关联的 Agent ID，用于按 Agent 维度分析
    )


class FeedbackResponse(BaseModel):
    """Response model for feedback submission"""

    status: str
    id: int = None  # 反馈记录 ID，创建时可能为 None


class FeedbackDB:
    """Database handler for feedback storage"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(
                BASE_DIR, "data", "feedback.db"
            )  # 默认路径在项目 data 目录下，确保数据持久化
        self.db_path = db_path
        self.ensure_db_directory()  # 确保目录存在，防止连接失败
        self.init_database()  # 初始化表结构，幂等操作

    def ensure_db_directory(self):
        """Ensure database directory exists"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)  # exist_ok=True 避免并发创建时的竞态条件

    def init_database(self):
        """Initialize feedback database"""
        try:
            with sqlite3.connect(self.db_path) as conn:  # 使用上下文管理器，自动提交和关闭连接
                cursor = conn.cursor()

                # Create feedback table
                # IF NOT EXISTS 确保幂等性，多次执行不报错
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        original_output TEXT NOT NULL,
                        human_edited_output TEXT NOT NULL,
                        kol_name TEXT,
                        product_name TEXT,
                        company_id TEXT DEFAULT 'default',
                        agent_id TEXT,
                        action TEXT DEFAULT 'modified',
                        status TEXT DEFAULT 'modified',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                self._ensure_feedback_schema(cursor)

                # Create indexes for better performance
                # 按工具名称查询反馈——进化分析需要按工具维度统计修改率
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_tool_name
                    ON feedback(tool_name)
                """)

                # 按时间范围查询——统计报表需要按时间段过滤
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_created_at
                    ON feedback(created_at)
                """)

                # 按会话 ID 查询——调试和追踪单次对话需要
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_session_id
                    ON feedback(session_id)
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_company_created
                    ON feedback(company_id, created_at)
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_agent_status_created
                    ON feedback(agent_id, status, created_at)
                """)

                conn.commit()
                logger.info("feedback_db_initialized")

        except Exception as e:
            logger.error("feedback_db_init_error", error=str(e))
            raise  # 数据库初始化失败是致命错误，不能继续运行

    @staticmethod
    def _ensure_feedback_schema(cursor):
        """Backfill columns required by newer stats/evolution queries."""
        cursor.execute("PRAGMA table_info(feedback)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        migrations = {
            "company_id": "company_id TEXT DEFAULT 'default'",
            "agent_id": "agent_id TEXT",
            "action": "action TEXT DEFAULT 'modified'",
            "status": "status TEXT DEFAULT 'modified'",
        }
        for column_name, ddl in migrations.items():
            if column_name not in existing_columns:
                cursor.execute(f"ALTER TABLE feedback ADD COLUMN {ddl}")

        if "status" not in existing_columns:
            cursor.execute("""
                UPDATE feedback
                SET status = COALESCE(action, 'modified')
            """)
        else:
            cursor.execute("""
                UPDATE feedback
                SET status = COALESCE(status, action, 'modified')
                WHERE status IS NULL
            """)


_feedback_db = None  # 模块级单例，避免重复创建数据库连接


def get_feedback_db() -> FeedbackDB:
    global _feedback_db
    if _feedback_db is None:  # 懒加载，首次调用时才初始化
        _feedback_db = FeedbackDB()
    return _feedback_db


def _first_non_empty_text(*values) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _request_to_dict(request: FeedbackRequest) -> dict[str, Any]:
    if hasattr(request, "model_dump"):
        return request.model_dump()
    return request.dict()


def _normalize_feedback_payload(
    request: FeedbackRequest,
    current_user: User,
) -> dict[str, Any]:
    data = _request_to_dict(request)
    data["session_id"] = _first_non_empty_text(
        data.get("session_id"),
        f"feedback-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
    )
    data["tool_name"] = _first_non_empty_text(data.get("tool_name"), "general")
    data["company_id"] = (
        str(current_user.company_id) if current_user.company_id is not None else "default"
    )

    original = _first_non_empty_text(data.get("original_output"))
    human = _first_non_empty_text(data.get("human_edited_output"))
    feedback_text = _first_non_empty_text(data.get("feedback_text"), data.get("comment"))
    rating = data.get("rating")

    has_legacy_edit = data.get("original_output") is not None and data.get(
        "human_edited_output"
    ) is not None
    if has_legacy_edit:
        data["original_output"] = original
        data["human_edited_output"] = human
        data["action"] = "modified" if original != human else "adopted"
        data["add_to_knowledge_base"] = original != human
        return data

    if not feedback_text and rating is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Feedback must include original_output + human_edited_output, "
                "or a lightweight rating/comment/feedback_text"
            ),
        )

    data["original_output"] = original
    data["human_edited_output"] = feedback_text or f"rating:{rating}"
    data["action"] = "feedback"
    data["add_to_knowledge_base"] = False
    return data


@router.post("/", response_model=FeedbackResponse)
async def receive_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Receive feedback from frontend"""
    try:
        data = _normalize_feedback_payload(request, current_user)

        # Store feedback in database
        feedback_id = store_feedback(data)  # 先存储反馈记录，再处理知识库写入

        # If the content was modified, add to knowledge base
        if data.get("add_to_knowledge_base"):
            add_to_knowledge_base(data)

        return FeedbackResponse(status="ok", id=feedback_id)

    except HTTPException:
        raise
    except Exception:
        logger.exception("process_feedback_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


def store_feedback(data: dict[str, Any]) -> int:
    """Store feedback in database"""
    try:
        with sqlite3.connect(get_feedback_db().db_path) as conn:
            cursor = conn.cursor()

            # 使用参数化查询防止 SQL 注入
            status = data.get("action") or (
                "modified"
                if data["original_output"] != data["human_edited_output"]
                else "adopted"
            )
            cursor.execute(
                """
                INSERT INTO feedback
                (session_id, tool_name, original_output, human_edited_output, kol_name, product_name, company_id, agent_id, action, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    data["session_id"],
                    data["tool_name"],
                    data["original_output"],
                    data["human_edited_output"],
                    data.get("kol_name"),
                    data.get("product_name"),
                    data.get("company_id", "default"),
                    data.get("agent_id"),
                    status,
                    status,
                ),
            )

            feedback_id = cursor.lastrowid  # 获取自增 ID
            conn.commit()

            logger.info("feedback_stored", feedback_id=feedback_id, tool=data["tool_name"])
            return feedback_id

    except Exception as e:
        logger.error("feedback_store_error", error=str(e))
        raise  # 重新抛出，让上层 API 处理并返回 500


def add_to_knowledge_base(data: dict[str, Any]):
    """Add modified content to knowledge base"""
    try:
        # Determine category and scenario based on content
        category = determine_category(data)  # 自动分类，减少人工标注成本
        scenario = determine_scenario(data)  # 自动识别场景，便于后续按场景检索

        # Create metadata for knowledge base
        metadata = {
            "category": category,
            "scenario": scenario,
            "source": "human_feedback",  # 标记来源为人工反馈，区别于 API 上传和文件导入
            "tool_name": data["tool_name"],
            "kol_name": data.get("kol_name", "unknown"),
            "product_name": data.get("product_name", "unknown"),
            "session_id": data["session_id"],
            "created_at": datetime.now().isoformat(),
        }

        # Add agent_id to metadata if available
        if data.get("agent_id"):
            metadata["agent_id"] = data["agent_id"]  # Agent ID 用于按 Agent 维度分析进化效果

        # Add to knowledge base
        result = add_knowledge(
            data["human_edited_output"], metadata, data.get("company_id", "default")
        )  # 写入人工编辑结果，作为优质知识
        logger.info("feedback_knowledge_added", result=str(result))

    except Exception as e:
        logger.error(
            "feedback_knowledge_add_error", error=str(e)
        )  # 知识库写入失败不阻塞反馈存储，仅记录日志


def determine_category(data: dict[str, Any]) -> str:
    """Determine category from feedback data"""
    content = data["human_edited_output"].lower()  # 转小写后匹配，避免大小写不一致

    if any(keyword in content for keyword in ["beauty", "makeup", "skincare", "cosmetic"]):
        return "beauty"  # 美妆类关键词匹配，优先返回最具体的分类
    elif any(keyword in content for keyword in ["fashion", "clothing", "style", "outfit"]):
        return "fashion"
    elif any(keyword in content for keyword in ["food", "restaurant", "cuisine", "taste"]):
        return "food"
    elif any(keyword in content for keyword in ["tech", "digital", "device", "gadget"]):
        return "tech"
    else:
        return "general"  # 无法匹配任何分类时返回通用分类


def determine_scenario(data: dict[str, Any]) -> str:
    """Determine scenario from feedback data"""
    content = data["human_edited_output"].lower()

    if any(
        keyword in content for keyword in ["hi", "hello", "introduce", "would you be interested"]
    ):
        return "initial_contact"  # 初次联系场景
    elif any(keyword in content for keyword in ["thank you", "following up", "more details"]):
        return "follow_up"  # 跟进场景
    elif any(keyword in content for keyword in ["introducing", "features", "benefits"]):
        return "product_intro"  # 产品介绍场景
    elif any(keyword in content for keyword in ["partnership", "collaboration", "compensation"]):
        return "cooperation_plan"  # 合作方案场景
    else:
        return "general"


@router.get("/stats")
async def get_feedback_stats(
    current_user: User = Depends(get_current_active_user),
):
    """Get feedback statistics"""
    try:
        # company_id 强制从认证用户获取，防止跨租户伪造
        # feedback 表的 company_id 为 TEXT，需将 int 转为 str 保持一致
        company_id = (
            str(current_user.company_id) if current_user.company_id is not None else "default"
        )

        with sqlite3.connect(get_feedback_db().db_path) as conn:
            cursor = conn.cursor()

            # Get overall stats
            # 默认统计最近 7 天，聚焦近期数据；按当前用户的公司过滤，实现租户隔离
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_feedback,
                    COUNT(CASE WHEN original_output != human_edited_output THEN 1 END) as modified_count,
                    COUNT(CASE WHEN original_output = human_edited_output THEN 1 END) as adopted_count,
                    tool_name
                FROM feedback
                WHERE created_at >= datetime('now', '-7 days')
                  AND company_id = ?
                GROUP BY tool_name
            """,
                (company_id,),
            )

            stats = cursor.fetchall()

            result = []
            for row in stats:
                total, modified, adopted, tool_name = row
                modification_rate = (
                    (modified / total * 100) if total > 0 else 0
                )  # 计算修改率，避免除零

                result.append(
                    {
                        "tool_name": tool_name,
                        "total_feedback": total,
                        "modified_count": modified,
                        "adopted_count": adopted,
                        "modification_rate": round(
                            modification_rate, 2
                        ),  # 保留两位小数，便于前端展示
                    }
                )

            return {
                "stats": result,
                "status": "ok",
                "total": sum(item["total_feedback"] for item in result),
            }

    except Exception as exc:
        logger.warning("get_feedback_stats_unavailable", error=str(exc))
        return {
            "stats": [],
            "status": "unavailable",
            "total": 0,
            "reason": "feedback_storage_unavailable",
            "message": "feedback storage unavailable",
        }


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    # Create FastAPI app for standalone testing
    app = FastAPI(title="Feedback API", version="1.0.0")
    app.include_router(router, prefix="/feedback")  # 独立运行时添加前缀，与主应用路由一致

    uvicorn.run(
        app,
        host=os.getenv("FEEDBACK_HOST", "0.0.0.0"),
        port=int(os.getenv("FEEDBACK_PORT", "8001")),
    )  # 独立测试端口默认 8001，避免与主服务冲突
