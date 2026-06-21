"""
Feedback API for collecting human feedback and enabling self-evolution
"""

import os  # 用于构建数据库文件路径
import sqlite3  # 使用 SQLite 存储反馈数据，轻量级且无需额外数据库服务
from datetime import datetime  # 用于记录反馈时间戳
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.logging import get_logger  # 结构化日志，追踪反馈处理和知识库写入

# Import add_knowledge function from knowledge_retrieval_server
from app.mcp_servers.knowledge_retrieval_server import add_knowledge  # 将人工编辑结果写入知识库，驱动自我进化

logger = get_logger(__name__)

# Get project root directory for absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 向上三级获取项目根目录，确保路径一致性

# Initialize APIRouter
router = APIRouter(tags=["feedback"])

class FeedbackRequest(BaseModel):
    """Request model for feedback submission"""
    session_id: str  # 会话 ID，用于追踪一次对话中的反馈
    tool_name: str  # 产生反馈的工具名称，便于按工具分析改进
    original_output: str  # 原始 AI 输出，用于对比学习
    human_edited_output: str  # 人工编辑后的输出，作为训练/知识库的优质数据
    kol_name: str = None  # 可选：关联的达人名称
    product_name: str = None  # 可选：关联的产品名称
    company_id: str = 'default'  # 租户隔离，默认值确保向后兼容
    agent_id: str = None  # Optional agent ID for tracking  # 可选：关联的 Agent ID，用于按 Agent 维度分析

class FeedbackResponse(BaseModel):
    """Response model for feedback submission"""
    status: str
    id: int = None  # 反馈记录 ID，创建时可能为 None

class FeedbackDB:
    """Database handler for feedback storage"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(BASE_DIR, "data", "feedback.db")  # 默认路径在项目 data 目录下，确保数据持久化
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
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS feedback (  # IF NOT EXISTS 确保幂等性，多次执行不报错
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        original_output TEXT NOT NULL,
                        human_edited_output TEXT NOT NULL,
                        kol_name TEXT,
                        product_name TEXT,
                        company_id TEXT DEFAULT 'default',  # 默认值保证向后兼容
                        agent_id TEXT,
                        action TEXT DEFAULT 'modified',  # modified 表示人工修改过，adopted 表示直接采纳
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes for better performance
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_tool_name 
                    ON feedback(tool_name)  # 按工具名称查询反馈——进化分析需要按工具维度统计修改率
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_created_at 
                    ON feedback(created_at)  # 按时间范围查询——统计报表需要按时间段过滤
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_feedback_session_id 
                    ON feedback(session_id)  # 按会话 ID 查询——调试和追踪单次对话需要
                """)

                conn.commit()
                logger.info("feedback_db_initialized")

        except Exception as e:
            logger.error("feedback_db_init_error", error=str(e))
            raise  # 数据库初始化失败是致命错误，不能继续运行

_feedback_db = None  # 模块级单例，避免重复创建数据库连接


def get_feedback_db() -> FeedbackDB:
    global _feedback_db
    if _feedback_db is None:  # 懒加载，首次调用时才初始化
        _feedback_db = FeedbackDB()
    return _feedback_db

@router.post("/", response_model=FeedbackResponse)
async def receive_feedback(request: FeedbackRequest):
    """Receive feedback from frontend"""
    try:
        # Validate required fields
        required_fields = ['session_id', 'tool_name', 'original_output', 'human_edited_output']
        for field in required_fields:
            if field not in request.dict():  # 额外校验：虽然 Pydantic 已做必填校验，但这里防止 None 值
                raise HTTPException(status_code=400, detail=f'Missing required field: {field}')

        # Store feedback in database
        feedback_id = store_feedback(request.dict())  # 先存储反馈记录，再处理知识库写入

        # If the content was modified, add to knowledge base
        if request.original_output != request.human_edited_output:  # 只有真正修改过的才写入知识库，避免冗余数据
            add_to_knowledge_base(request.dict())

        return FeedbackResponse(
            status="ok",
            id=feedback_id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing feedback: {str(e)}")

def store_feedback(data: dict[str, Any]) -> int:
    """Store feedback in database"""
    try:
        with sqlite3.connect(get_feedback_db().db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO feedback 
                (session_id, tool_name, original_output, human_edited_output, kol_name, product_name, company_id, agent_id, action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)  # 使用参数化查询防止 SQL 注入
            """, (
                data['session_id'],
                data['tool_name'],
                data['original_output'],
                data['human_edited_output'],
                data.get('kol_name'),  # 使用 .get() 安全获取可选字段
                data.get('product_name'),
                data.get('company_id', 'default'),
                data.get('agent_id'),
                'modified' if data['original_output'] != data['human_edited_output'] else 'adopted'  # 动态判断操作类型
            ))

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
            'category': category,
            'scenario': scenario,
            'source': 'human_feedback',  # 标记来源为人工反馈，区别于 API 上传和文件导入
            'tool_name': data['tool_name'],
            'kol_name': data.get('kol_name', 'unknown'),
            'product_name': data.get('product_name', 'unknown'),
            'session_id': data['session_id'],
            'created_at': datetime.now().isoformat()
        }

        # Add agent_id to metadata if available
        if data.get('agent_id'):
            metadata['agent_id'] = data['agent_id']  # Agent ID 用于按 Agent 维度分析进化效果

        # Add to knowledge base
        result = add_knowledge(data['human_edited_output'], metadata, data.get('company_id', 'default'))  # 写入人工编辑结果，作为优质知识
        logger.info("feedback_knowledge_added", result=str(result))

    except Exception as e:
        logger.error("feedback_knowledge_add_error", error=str(e))  # 知识库写入失败不阻塞反馈存储，仅记录日志

def determine_category(data: dict[str, Any]) -> str:
    """Determine category from feedback data"""
    content = data['human_edited_output'].lower()  # 转小写后匹配，避免大小写不一致

    if any(keyword in content for keyword in ['beauty', 'makeup', 'skincare', 'cosmetic']):
        return 'beauty'  # 美妆类关键词匹配，优先返回最具体的分类
    elif any(keyword in content for keyword in ['fashion', 'clothing', 'style', 'outfit']):
        return 'fashion'
    elif any(keyword in content for keyword in ['food', 'restaurant', 'cuisine', 'taste']):
        return 'food'
    elif any(keyword in content for keyword in ['tech', 'digital', 'device', 'gadget']):
        return 'tech'
    else:
        return 'general'  # 无法匹配任何分类时返回通用分类

def determine_scenario(data: dict[str, Any]) -> str:
    """Determine scenario from feedback data"""
    content = data['human_edited_output'].lower()

    if any(keyword in content for keyword in ['hi', 'hello', 'introduce', 'would you be interested']):
        return 'initial_contact'  # 初次联系场景
    elif any(keyword in content for keyword in ['thank you', 'following up', 'more details']):
        return 'follow_up'  # 跟进场景
    elif any(keyword in content for keyword in ['introducing', 'features', 'benefits']):
        return 'product_intro'  # 产品介绍场景
    elif any(keyword in content for keyword in ['partnership', 'collaboration', 'compensation']):
        return 'cooperation_plan'  # 合作方案场景
    else:
        return 'general'

@router.get("/stats")
async def get_feedback_stats():
    """Get feedback statistics"""
    try:
        with sqlite3.connect(get_feedback_db().db_path) as conn:
            cursor = conn.cursor()

            # Get overall stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_feedback,
                    COUNT(CASE WHEN original_output != human_edited_output THEN 1 END) as modified_count,  # 条件聚合，统计修改次数
                    COUNT(CASE WHEN original_output = human_edited_output THEN 1 END) as adopted_count,  # 统计直接采纳次数
                    tool_name
                FROM feedback
                WHERE created_at >= datetime('now', '-7 days')  # 默认统计最近 7 天，聚焦近期数据
                GROUP BY tool_name
            """)

            stats = cursor.fetchall()

            result = []
            for row in stats:
                total, modified, adopted, tool_name = row
                modification_rate = (modified / total * 100) if total > 0 else 0  # 计算修改率，避免除零

                result.append({
                    'tool_name': tool_name,
                    'total_feedback': total,
                    'modified_count': modified,
                    'adopted_count': adopted,
                    'modification_rate': round(modification_rate, 2)  # 保留两位小数，便于前端展示
                })

            return {"stats": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    # Create FastAPI app for standalone testing
    app = FastAPI(title="Feedback API", version="1.0.0")
    app.include_router(router, prefix="/feedback")  # 独立运行时添加前缀，与主应用路由一致

    uvicorn.run(app, host="0.0.0.0", port=8001)  # 独立测试端口 8001，避免与主服务冲突
