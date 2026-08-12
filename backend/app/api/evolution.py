"""
Evolution Management API
Provides endpoints for agent evolution analysis and improvement suggestions
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.database import User, db
from app.evolution import (  # 进化分析器和建议生成器，核心业务逻辑
    EvolutionAnalyzer,
    EvolutionSuggester,
)

logger = get_logger(__name__)

router = APIRouter(tags=["evolution"])


# Pydantic models for API responses
class EvolutionReport(BaseModel):
    agent_id: int
    agent_name: str
    company_id: int
    modification_rate: float  # 修改率（百分比），反映 Agent 输出质量
    total_feedback: int
    modified_count: int  # 被人工修改的次数
    top_modified_tools: list[str]  # 修改率最高的工具列表


class SuggestionResponse(BaseModel):
    agent_id: int
    suggested_prompt_changes: str  # LLM 建议的提示词修改
    knowledge_entries: list[str]  # 建议的知识条目
    analysis_summary: str  # 分析摘要
    confidence_score: float  # 置信度 0-1


class EvolutionSuggestionResponse(BaseModel):
    agent_id: int
    suggested_prompt_changes: str
    knowledge_entries: list[str]
    analysis_summary: str
    confidence_score: float


class ApplySuggestionRequest(BaseModel):
    agent_id: int
    tool_name: str | None = None  # 可选：指定工具
    approved_text: str  # 审核通过的建议文本
    suggestion_type: str  # "prompt" or "knowledge"


class EvolutionReportResponse(BaseModel):
    reports: list[EvolutionReport]
    high_modification_agents: list[EvolutionReport]  # 高修改率 Agent，需要重点关注
    analysis_period_days: int


@router.get("/report", response_model=EvolutionReportResponse)
async def get_evolution_report(
    days: int = 7,
    min_feedback: int = 5,  # 最少反馈数：样本太少则统计意义不足
    current_user: User = Depends(get_current_active_user),
):
    """
    Get evolution report for current user's company
    Shows modification rates and high-modification agents
    """
    try:
        analyzer = EvolutionAnalyzer()

        # Get company evolution report. Empty or partially migrated feedback stores
        # should render an empty state instead of breaking the admin page.
        try:
            company_reports = analyzer.get_company_evolution_report(current_user.company_id, days)
        except Exception as e:
            logger.warning("evolution_report_unavailable", error=str(e))
            company_reports = []

        # Filter agents with minimum feedback and identify high modification agents
        filtered_reports = []
        high_modification_agents = []

        for report in company_reports:
            if report.total_feedback >= min_feedback:  # 过滤样本不足的 Agent
                filtered_reports.append(
                    EvolutionReport(
                        agent_id=report.agent_id,
                        agent_name=report.agent_name,
                        company_id=report.company_id,
                        modification_rate=report.modification_rate,
                        total_feedback=report.total_feedback,
                        modified_count=report.modified_count,
                        top_modified_tools=report.top_modified_tools,
                    )
                )

                # Identify high modification agents (rate > 30%)
                if report.modification_rate > 30.0:  # 30% 阈值：超过此值认为需要进化
                    high_modification_agents.append(
                        EvolutionReport(
                            agent_id=report.agent_id,
                            agent_name=report.agent_name,
                            company_id=report.company_id,
                            modification_rate=report.modification_rate,
                            total_feedback=report.total_feedback,
                            modified_count=report.modified_count,
                            top_modified_tools=report.top_modified_tools,
                        )
                    )

        return EvolutionReportResponse(
            reports=filtered_reports,
            high_modification_agents=high_modification_agents,
            analysis_period_days=days,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/suggestions/{agent_id:int}", response_model=list[EvolutionSuggestionResponse])
async def get_evolution_suggestions(
    agent_id: int, current_user: User = Depends(get_current_active_user)
):
    """Get evolution suggestions for a specific agent"""
    try:
        # Get agent to verify company access
        agent = db.get_agent(agent_id)
        if not agent or agent.company_id != current_user.company_id:  # 租户隔离 + 存在性检查
            raise HTTPException(status_code=404, detail="Agent not found")

        # Get evolution logs
        suggestions = EvolutionAnalyzer().get_suggestions_for_agent(agent_id)

        return [
            EvolutionSuggestionResponse(
                agent_id=s["agent_id"],
                tool_name=s.get("tool_name"),
                suggestion_text=s["suggestion_text"],
                created_at=s["created_at"],
                applied=s["applied"],  # 是否已应用，用于前端标记状态
            )
            for s in suggestions
        ]

    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/training-data/{agent_id:int}")
async def get_training_data(agent_id: int, current_user: User = Depends(get_current_active_user)):
    """Get training data files for a specific agent"""
    try:
        # Get agent to verify company access
        agent = db.get_agent(agent_id)
        if not agent or agent.company_id != current_user.company_id:  # 租户隔离
            raise HTTPException(status_code=404, detail="Agent not found")

        # Get training data files
        from app.evolution.notifier import EvolutionNotifier  # 延迟导入，避免循环依赖

        notifier = EvolutionNotifier()
        training_files = notifier.get_training_data_files(agent_id)

        return {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "training_files": training_files,
            "total_files": len(training_files),
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/suggestions/{agent_id:int}/generate", response_model=SuggestionResponse)
async def get_agent_suggestions(
    agent_id: int,
    tool_name: str | None = None,  # 可选：指定工具生成针对性建议
    current_user: User = Depends(get_current_active_user),
):
    """
    Generate improvement suggestions for a specific agent
    Uses LLM to analyze feedback patterns and suggest improvements
    """
    try:
        # Verify agent belongs to current user's company
        agent = db.get_agent(agent_id)
        if not agent or agent.company_id != current_user.company_id:  # 租户隔离
            raise HTTPException(status_code=404, detail="Agent not found or access denied")

        suggester = EvolutionSuggester()
        suggestion = suggester.generate_suggestion(
            agent_id, tool_name
        )  # 使用 LLM 分析反馈模式并生成建议

        # Save suggestion to evolution log
        suggester.save_suggestion_to_log(suggestion, tool_name)  # 持久化建议记录，便于追踪

        return SuggestionResponse(
            agent_id=suggestion.agent_id,
            suggested_prompt_changes=suggestion.suggested_prompt_changes,
            knowledge_entries=suggestion.knowledge_entries,
            analysis_summary=suggestion.analysis_summary,
            confidence_score=suggestion.confidence_score,
        )

    except Exception:
        logger.exception("generate_suggestions_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/apply")
async def apply_suggestion(
    request: ApplySuggestionRequest, current_user: User = Depends(get_current_active_user)
):
    """
    Apply approved suggestion to knowledge base
    Updates knowledge base and marks suggestion as applied
    """
    try:
        # Verify agent belongs to current user's company
        agent = db.get_agent(request.agent_id)
        if not agent or agent.company_id != current_user.company_id:  # 租户隔离
            raise HTTPException(status_code=404, detail="Agent not found or access denied")

        if request.suggestion_type == "knowledge":
            # Add to knowledge base
            from app.mcp_servers.knowledge_retrieval_server import add_knowledge  # 延迟导入

            # Parse knowledge entries (assuming they're separated by semicolons)
            knowledge_entries = request.approved_text.split(";")  # 用分号分隔多条知识

            added_count = 0
            for entry in knowledge_entries:
                entry = entry.strip()
                if entry:
                    try:
                        add_knowledge(
                            content=entry,
                            category=f"agent_{request.agent_id}_improvement",  # 分类标记为进化优化
                            tags=["evolution", f"tool_{request.tool_name}"]
                            if request.tool_name
                            else ["evolution"],
                        )
                        added_count += 1
                    except Exception as e:
                        logger.error(
                            "evolution_api_knowledge_add_failed", error=str(e)
                        )  # 单条失败不影响其他条目

            # Mark suggestion as applied in evolution log
            _mark_suggestion_applied(request.agent_id, request.tool_name)

            return {
                "message": f"Successfully added {added_count} knowledge entries",
                "applied_count": added_count,
            }

        elif request.suggestion_type == "prompt":
            # For now, just log the prompt changes
            # In a full implementation, this would update agent configuration
            _mark_suggestion_applied(request.agent_id, request.tool_name)

            return {
                "message": "Prompt changes logged for review",  # 提示词修改需要人工实现，当前仅记录
                "note": "Manual implementation required for prompt updates",
            }

        else:
            raise HTTPException(status_code=400, detail="Invalid suggestion type")

    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/history/{agent_id:int}")
async def get_evolution_history(
    agent_id: int, current_user: User = Depends(get_current_active_user)
):
    """
    Get evolution history for a specific agent
    Returns all past suggestions and their application status
    """
    try:
        # Verify agent belongs to current user's company
        agent = db.get_agent(agent_id)
        if not agent or agent.company_id != current_user.company_id:  # 租户隔离
            raise HTTPException(status_code=404, detail="Agent not found or access denied")

        from sqlalchemy import text  # SQLAlchemy text() 统一封装 SQL，支持命名参数

        from app.database.core import get_engine

        with get_engine().connect() as conn:  # 使用连接管理器，自动关闭
            result = conn.execute(
                text("""
                    SELECT id, agent_id, tool_name, suggestion_text, created_at, applied
                    FROM evolution_log
                    WHERE agent_id = :agent_id
                    ORDER BY created_at DESC
                """),
                {"agent_id": agent_id},
            )

            history = []
            for row in result.fetchall():
                history.append(
                    {
                        "id": row[0],
                        "agent_id": row[1],
                        "tool_name": row[2],
                        "suggestion_text": row[3],
                        "created_at": row[4],
                        "applied": row[5],
                    }
                )

            return {"history": history}

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("evolution_history_unavailable", agent_id=agent_id, error=str(e))
        return {"history": []}


def _mark_suggestion_applied(agent_id: int, tool_name: str = None):
    """Mark the most recent suggestion as applied"""
    try:
        from sqlalchemy import text

        from app.database.core import get_engine

        with get_engine().connect() as conn:
            conn.execute(
                text("""
                    UPDATE evolution_log
                    SET applied = TRUE
                    WHERE id = (
                        SELECT id FROM evolution_log
                        WHERE agent_id = :agent_id AND tool_name = :tool_name AND applied = FALSE
                        ORDER BY created_at DESC
                        LIMIT 1
                    )
                """),
                {"agent_id": agent_id, "tool_name": tool_name},
            )
            conn.commit()

    except Exception as e:
        logger.error("evolution_api_mark_applied_failed", error=str(e))  # 标记失败不阻塞主流程


# Admin review endpoints for semi-automatic evolution — 半自动进化：管理员审核后才能应用建议
class EvolutionReviewResponse(BaseModel):
    id: int  # 审核记录 ID
    agent_id: int  # 关联的 Agent ID
    agent_name: str  # Agent 名称，便于管理员快速识别
    tool_name: str  # 相关工具名称
    suggestion_text: str  # 进化建议的原始文本
    knowledge_entries: str  # 建议的知识条目（JSON 字符串）
    prompt_changes: str  # 建议的提示词修改
    status: str  # 审核状态：pending / approved / rejected
    admin_id: int  # 审核管理员 ID
    applied_at: str  # 应用时间
    created_at: str  # 创建时间


@router.get("/reviews", response_model=list[EvolutionReviewResponse])
async def get_pending_reviews(current_user: User = Depends(get_current_active_user)):
    """
    Get all pending evolution reviews for admin approval
    """
    try:
        # Check if user is admin
        if not current_user.is_admin:  # 只有管理员可以审核进化建议
            raise HTTPException(status_code=403, detail="Admin access required")

        # Get all pending reviews
        reviews = db.get_pending_reviews()

        return [
            EvolutionReviewResponse(
                id=review["id"],
                agent_id=review["agent_id"],
                agent_name=review["agent_name"],
                tool_name=review["tool_name"],
                suggestion_text=review["suggestion_text"],
                knowledge_entries=review["knowledge_entries"],
                prompt_changes=review["prompt_changes"],
                status=review["status"],
                admin_id=review["admin_id"],
                applied_at=review["applied_at"],
                created_at=review["created_at"],
            )
            for review in reviews
        ]

    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/reviews/{review_id:int}/approve")
async def approve_review(review_id: int, current_user: User = Depends(get_current_active_user)):
    """
    Approve an evolution review and apply changes automatically
    """
    try:
        # Check if user is admin
        if not current_user.is_admin:  # 管理员权限
            raise HTTPException(status_code=403, detail="Admin access required")

        # Get review details
        reviews = db.get_pending_reviews()
        review_data = next((r for r in reviews if r["id"] == review_id), None)  # 在待审核列表中查找

        if not review_data:
            raise HTTPException(status_code=404, detail="Review not found")

        # Apply the evolution changes
        from app.evolution.applier import EvolutionApplier  # 延迟导入

        applier = EvolutionApplier()

        # Get agent details for company context
        agent = db.get_agent(review_data["agent_id"])
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        success = True

        # Apply knowledge entries if present
        if review_data["knowledge_entries"]:
            try:
                import json

                knowledge_entries = json.loads(
                    review_data["knowledge_entries"]
                )  # 知识条目以 JSON 数组存储
                company_id = str(agent.company_id)  # 转为字符串保持一致性
                success &= applier.apply_knowledge_entries(  # 按位与确保所有操作都成功
                    agent_id=review_data["agent_id"],
                    knowledge_entries=knowledge_entries,
                    company_id=company_id,
                )
                logger.info(
                    "evolution_api_knowledge_applied",
                    count=len(knowledge_entries),
                    agent=review_data["agent_name"],
                )
            except Exception as e:
                logger.error("evolution_api_knowledge_apply_failed", error=str(e))
                success = False

        # Apply prompt changes if present
        if review_data["prompt_changes"]:
            try:
                success &= applier.apply_prompt_changes(
                    agent_id=review_data["agent_id"],
                    prompt_changes_text=review_data["prompt_changes"],
                )
                logger.info("evolution_api_prompt_applied", agent=review_data["agent_name"])
            except Exception as e:
                logger.error("evolution_api_prompt_apply_failed", error=str(e))
                success = False

        if success:
            # Update review status to approved
            db.update_review_status(review_id, "approved", current_user.id)  # 记录审核人 ID
            return {"message": "Review approved and changes applied successfully"}
        else:
            return {
                "message": "Review approved but some changes failed to apply"
            }  # 部分成功也告知用户

    except HTTPException:
        raise
    except Exception:
        logger.exception("operation_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/reviews/{review_id:int}/reject")
async def reject_review(review_id: int, current_user: User = Depends(get_current_active_user)):
    """
    Reject an evolution review
    """
    try:
        # Check if user is admin
        if not current_user.is_admin:  # 管理员权限
            raise HTTPException(status_code=403, detail="Admin access required")

        # Update review status to rejected
        success = db.update_review_status(review_id, "rejected", current_user.id)

        if success:
            return {"message": "Review rejected successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update review status")

    except HTTPException:
        raise
    except Exception:
        logger.exception("reject_review_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")


# ── 7.1-7.3 记忆系统 & 睡眠巩固 API ─────────────────────────────────


class MemoryConsolidationRequest(BaseModel):
    company_id: int  # 要触发记忆巩固的公司 ID


class MemoryConsolidationResponse(BaseModel):
    status: str  # 巩固状态：success / partial / failed
    company_id: int  # 所属公司 ID
    input_memories: int = 0  # 输入的短时记忆数量：反映当前待处理的记忆量
    compressed: int = 0  # 被压缩的记忆数量：实际被整合到长期记忆中的数量
    patterns_extracted: int = 0  # 提取的模式数量：从记忆中归纳出的行为模式
    patterns: list[dict] = []  # 提取的模式详情列表


@router.post("/memory/consolidate", response_model=MemoryConsolidationResponse)
async def trigger_memory_consolidation(
    request: MemoryConsolidationRequest,
    current_user: User = Depends(get_current_active_user),
):
    """手动触发睡眠巩固：压缩短期记忆→提取模式→写入长期记忆"""
    if not current_user.is_admin:  # 管理员权限
        raise HTTPException(status_code=403, detail="Admin access required")

    # company_id 强制从认证用户获取，防止跨租户伪造（忽略请求体中的 company_id）
    from app.services.evolution import get_consolidation_engine  # 延迟导入

    engine = get_consolidation_engine()
    result = engine.consolidate(current_user.company_id)  # 执行巩固流程
    return MemoryConsolidationResponse(**result)  # 解包字典到 Pydantic 模型


@router.get("/memory/consolidation-status")
async def get_consolidation_status(
    current_user: User = Depends(get_current_active_user),
):
    """获取睡眠巩固状态"""
    # company_id 强制从认证用户获取，防止跨租户伪造
    company_id = current_user.company_id
    from app.services.evolution import get_consolidation_engine, get_memory_writer  # 延迟导入

    engine = get_consolidation_engine()
    writer = get_memory_writer()
    return {
        "company_id": company_id,
        "short_term_count": engine._short_term_counts.get(company_id, 0),  # 当前短时记忆数量
        "threshold_for_trigger": engine.threshold_count,  # 触发巩固的阈值
        "last_consolidation": engine._last_consolidation.get(company_id),  # 上次巩固时间
        "pending_writes": writer.get_pending_count(),  # 待写入的长期记忆数量
        "scheduler_running": engine._running,  # 调度器是否运行中
    }


# ── 7.4 演化日志 API ─────────────────────────────────────────────────


class EvolutionLogQuery(BaseModel):
    event_type: str | None = None  # 可选：按事件类型过滤（如 consolidation、memory_consolidation）
    agent_key: str | None = None  # 可选：按 Agent 标识过滤
    limit: int = 50  # 返回条数上限，防止一次查询过多数据


@router.get("/log")
async def get_evolution_logs(
    event_type: str | None = None,  # 可选：按事件类型过滤
    agent_key: str | None = None,  # 可选：按 Agent 过滤
    limit: int = 50,
    current_user=Depends(get_current_active_user),
):
    """查询演化日志"""
    from app.services.evolution import EvolutionEventType, get_evolution_logger  # 延迟导入

    evt = EvolutionEventType(event_type) if event_type else None  # 字符串转枚举
    logger_instance = get_evolution_logger()
    logs = logger_instance.query(
        company_id=current_user.company_id,
        event_type=evt,
        agent_key=agent_key,
        limit=limit,
    )
    return {
        "logs": [
            {
                "event_type": log.event_type.value,  # 返回枚举值字符串
                "description": log.description,
                "detail": log.detail,
                "agent_key": log.agent_key,
                "operator": log.operator,
                "timestamp": log.timestamp,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.get("/log/feed")
async def get_evolution_feed(
    limit: int = 20,
    current_user=Depends(get_current_active_user),
):
    """获取演化动态推送"""
    from app.services.evolution import get_evolution_logger

    return {
        "feed": get_evolution_logger().get_evolution_feed(current_user.company_id, limit),
    }


# ── 7.5 反馈驱动进化 API ──────────────────────────────────────────────


class FeedbackRecordRequest(BaseModel):
    agent_key: str  # Agent 标识，用于关联到具体 Agent
    task_id: str  # 关联的任务 ID
    decision: str  # 审核决定：approved（批准）/ rejected（拒绝）/ modified（修改后通过）
    reviewer_notes: str = ""  # 审核备注：记录审核人的修改意见
    original_output: str = ""  # 原始输出：用于对比学习，分析 Agent 哪些输出被人工修改了


@router.post("/feedback/record")
async def record_feedback(
    request: FeedbackRecordRequest,
    current_user=Depends(get_current_active_user),
):
    """记录审核反馈，驱动 Agent 偏好进化"""
    from app.services.evolution import get_feedback_evolution  # 延迟导入

    evolution = get_feedback_evolution()
    evolution.record_feedback(
        company_id=current_user.company_id,
        agent_key=request.agent_key,
        task_id=request.task_id,
        decision=request.decision,
        reviewer_notes=request.reviewer_notes,
        original_output=request.original_output,
    )
    return {"status": "recorded"}


@router.get("/feedback/preferences/{agent_key}")
async def get_agent_preferences(
    agent_key: str,
    current_user=Depends(get_current_active_user),
):
    """获取 Agent 已学习的偏好"""
    from app.services.evolution import get_feedback_evolution

    evolution = get_feedback_evolution()
    return {
        "agent_key": agent_key,
        "preferences": evolution.get_preferences(
            current_user.company_id, agent_key
        ),  # 按公司+Agent 维度获取偏好
        "summary": evolution.get_feedback_summary(current_user.company_id, agent_key),
    }


# ── 7.6 Skill 优化建议 API ───────────────────────────────────────────


@router.get("/skill/suggestions/{agent_key}")
async def get_skill_suggestions(
    agent_key: str,
    current_user=Depends(get_current_active_user),
):
    """分析历史任务数据，获取 Skill 优化建议"""
    from app.services.evolution import get_skill_optimizer  # 延迟导入

    optimizer = get_skill_optimizer()
    suggestions = optimizer.analyze_and_suggest(
        current_user.company_id, agent_key
    )  # 分析并生成建议
    return {
        "agent_key": agent_key,
        "suggestions": suggestions,
        "total": len(suggestions),
    }


@router.get("/skill/suggestions")
async def get_all_pending_suggestions(
    agent_key: str | None = None,  # 可选：不传则返回所有 Agent
    current_user=Depends(get_current_active_user),
):
    """获取所有待处理优化建议"""
    from app.services.evolution import get_skill_optimizer

    suggestions = get_skill_optimizer().get_pending_suggestions(
        company_id=current_user.company_id,
        agent_key=agent_key,
    )
    return {"suggestions": suggestions, "total": len(suggestions)}
