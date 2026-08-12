"""
Cost tracker for LLM usage monitoring and cost calculation
"""

from datetime import datetime, timedelta

from sqlalchemy import bindparam, text

from app.core.logging import get_logger
from app.database import db

logger = get_logger(__name__)


# 嵌入 API 单价表（元/次，按文本数计费）—— 变更① T1.5
# 依据：硅基流动免费额度用完后约 0.0005 元/次；DeepSeek 约 0.001 元/次；
# OpenAI text-embedding-3-small 约 $0.02/1M tokens，按汇率估算约 0.0007 元/次
EMBEDDING_API_PRICING: dict[str, float] = {
    "api_siliconflow": 0.0005,
    "api_deepseek": 0.001,
    "api_openai": 0.0007,
    "local": 0.0,
}


class CostTracker:
    """Cost tracking service for LLM usage"""

    @staticmethod
    def record_usage(
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        request_id: str = None,
        agent_id: int = None,
    ) -> bool:
        """
        Record LLM usage to database

        Args:
            model_name: Name of the model used
            input_tokens: Number of input tokens consumed
            output_tokens: Number of output tokens generated
            cost: Total cost for this request
            request_id: Unique identifier for the request
            agent_id: ID of the agent that made the request

        Returns:
            bool: Success status
        """
        try:
            engine = getattr(db, "engine", None)
            if engine is None:
                return False

            # 使用 SQLAlchemy text() + 命名参数，避免 DBAPI cursor（ConnectionContext 无 cursor 属性）
            # 命名参数同时兼容 SQLite 与 PostgreSQL
            with engine.connect() as conn:
                conn.execute(
                    text("""
                    INSERT INTO llm_usage
                    (model_name, input_tokens, output_tokens, cost, request_id, agent_id, created_at)
                    VALUES (:model_name, :input_tokens, :output_tokens, :cost, :request_id, :agent_id, :created_at)
                """),
                    {
                        "model_name": model_name,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost": cost,
                        "request_id": request_id,
                        "agent_id": agent_id,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                conn.commit()
            return True

        except Exception as e:
            logger.error("cost_record_usage_failed", error=str(e))
            return False

    @staticmethod
    def record_embedding_usage(
        mode: str,
        model_name: str,
        text_count: int,
        request_id: str = None,
    ) -> bool:
        """记录嵌入 API 调用成本 —— 变更① T1.5

        嵌入 API 按文本数计费（非 token 数），与 LLM 聊天调用的计费模型不同。
        此方法复用 llm_usage 表（output_tokens=0），通过 model_name 前缀
        "embedding_api:{mode}:{model}" 区分供应商和模型，便于 get_cost_by_model 分组统计。

        Args:
            mode: EmbeddingMode.value（local / api_siliconflow / api_deepseek / api_openai）
            model_name: 嵌入模型名称（如 BAAI/bge-large-zh-v1.5）
            text_count: 编码的文本数量
            request_id: 可选请求 ID

        Returns:
            bool: 是否成功记录
        """
        unit_price = EMBEDDING_API_PRICING.get(mode, 0.0)
        cost = text_count * unit_price
        # provider 前缀 "embedding_api" 与 LLM 调用区分；mode 编入 model_name 便于按模型分组统计
        composite_model = f"embedding_api:{mode}:{model_name}"
        return CostTracker.record_usage(
            model_name=composite_model,
            input_tokens=text_count,  # 嵌入按文本数计费，复用 input_tokens 字段
            output_tokens=0,  # 嵌入不产生输出 token
            cost=cost,
            request_id=request_id,
        )

    @staticmethod
    def get_total_cost(days: int = 30) -> dict:
        """
        Get total cost for the specified period

        Args:
            days: Number of days to look back

        Returns:
            Dict with total cost and breakdown
        """
        try:
            engine = getattr(db, "engine", None)
            if engine is None:
                return {
                    "total_cost": 0.0,
                    "total_requests": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "period_days": days,
                }

            threshold_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT
                        SUM(cost) as total_cost,
                        COUNT(*) as total_requests,
                        SUM(input_tokens) as total_input_tokens,
                        SUM(output_tokens) as total_output_tokens
                    FROM llm_usage
                    WHERE created_at >= :threshold_date
                """),
                    {"threshold_date": threshold_date},
                )

                row = result.fetchone()

            if row and row[0]:
                return {
                    "total_cost": round(row[0], 6),
                    "total_requests": row[1],
                    "total_input_tokens": row[2] or 0,
                    "total_output_tokens": row[3] or 0,
                    "period_days": days,
                }
            else:
                return {
                    "total_cost": 0.0,
                    "total_requests": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "period_days": days,
                }

        except Exception as e:
            logger.error("cost_get_total_failed", error=str(e))
            return {
                "total_cost": 0.0,
                "total_requests": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "period_days": days,
            }

    @staticmethod
    def get_cost_by_model(days: int = 30) -> list[dict]:
        """
        Get cost breakdown by model

        Args:
            days: Number of days to look back

        Returns:
            List of cost data by model
        """
        try:
            engine = getattr(db, "engine", None)
            if engine is None:
                return []

            threshold_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT
                        model_name,
                        SUM(cost) as total_cost,
                        COUNT(*) as total_requests,
                        SUM(input_tokens) as total_input_tokens,
                        SUM(output_tokens) as total_output_tokens
                    FROM llm_usage
                    WHERE created_at >= :threshold_date
                    GROUP BY model_name
                    ORDER BY total_cost DESC
                """),
                    {"threshold_date": threshold_date},
                )

                results = []
                for row in result.fetchall():
                    results.append(
                        {
                            "model_name": row[0],
                            "total_cost": round(row[1], 6),
                            "total_requests": row[2],
                            "total_input_tokens": row[3] or 0,
                            "total_output_tokens": row[4] or 0,
                        }
                    )

            return results

        except Exception as e:
            logger.error("cost_get_by_model_failed", error=str(e))
            return []

    @staticmethod
    def get_cost_by_agent(agent_id: int, days: int = 30) -> list[dict]:
        """
        Get cost breakdown by agent

        Args:
            agent_id: ID of the agent
            days: Number of days to look back

        Returns:
            List of cost data by agent
        """
        try:
            engine = getattr(db, "engine", None)
            if engine is None:
                return []

            threshold_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT
                        model_name,
                        SUM(cost) as total_cost,
                        COUNT(*) as total_requests,
                        SUM(input_tokens) as total_input_tokens,
                        SUM(output_tokens) as total_output_tokens
                    FROM llm_usage
                    WHERE agent_id = :agent_id AND created_at >= :threshold_date
                    GROUP BY model_name
                    ORDER BY total_cost DESC
                """),
                    {"agent_id": agent_id, "threshold_date": threshold_date},
                )

                results = []
                for row in result.fetchall():
                    results.append(
                        {
                            "model_name": row[0],
                            "total_cost": round(row[1], 6),
                            "total_requests": row[2],
                            "total_input_tokens": row[3] or 0,
                            "total_output_tokens": row[4] or 0,
                        }
                    )

            return results

        except Exception as e:
            logger.error("cost_get_by_agent_failed", error=str(e))
            return []

    @staticmethod
    def get_cost_summary_by_agents(agent_ids: list[int], days: int = 30) -> dict[int, dict]:
        """批量获取多个 agent 的用量汇总（P0-4 优化：用一次 GROUP BY 替代 N 次 get_cost_by_agent）

        将 admin_get_usage 的 N+M 查询模式（companies × agents × get_cost_by_agent）
        降为 1 次聚合 SQL，按 agent_id 分组返回 token 总数和 cost 总数。

        Args:
            agent_ids: 需要汇总的 agent_id 列表；为空时返回空 dict
            days: 统计周期（天）

        Returns:
            {agent_id: {"total_tokens": int, "total_cost": float, "total_requests": int}}
        """
        if not agent_ids:
            return {}
        try:
            engine = getattr(db, "engine", None)
            if engine is None:
                return {}

            threshold_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            params = {"threshold_date": threshold_date, "agent_ids": agent_ids}
            sql = text(
                """
                SELECT
                    agent_id,
                    SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) as total_tokens,
                    SUM(COALESCE(cost, 0)) as total_cost,
                    COUNT(*) as total_requests
                FROM llm_usage
                WHERE agent_id IN :agent_ids AND created_at >= :threshold_date
                GROUP BY agent_id
            """
            ).bindparams(bindparam("agent_ids", expanding=True))
            with engine.connect() as conn:
                result = conn.execute(sql, params)
                summary: dict[int, dict] = {}
                for row in result.fetchall():
                    aid = row[0]
                    if aid is None:
                        continue  # agent_id 为 NULL 的记录（如嵌入调用）不计入 agent 用量
                    summary[aid] = {
                        "total_tokens": int(row[1] or 0),
                        "total_cost": round(float(row[2] or 0.0), 6),
                        "total_requests": int(row[3] or 0),
                    }
            return summary

        except Exception as e:
            logger.error("cost_get_summary_by_agents_failed", error=str(e))
            return {}

    @staticmethod
    def get_daily_cost_trend(days: int = 30) -> list[dict]:
        """
        Get daily cost trend for charting

        Args:
            days: Number of days to look back

        Returns:
            List of daily cost data
        """
        try:
            engine = getattr(db, "engine", None)
            if engine is None:
                return []

            threshold_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    SELECT
                        DATE(created_at) as date,
                        SUM(cost) as daily_cost,
                        COUNT(*) as daily_requests,
                        SUM(input_tokens) as daily_input_tokens,
                        SUM(output_tokens) as daily_output_tokens
                    FROM llm_usage
                    WHERE created_at >= :threshold_date
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                """),
                    {"threshold_date": threshold_date},
                )

                results = []
                for row in result.fetchall():
                    results.append(
                        {
                            "date": row[0],
                            "daily_cost": round(row[1], 6),
                            "daily_requests": row[2],
                            "daily_input_tokens": row[3] or 0,
                            "daily_output_tokens": row[4] or 0,
                        }
                    )

            return results

        except Exception as e:
            logger.error("cost_get_daily_trend_failed", error=str(e))
            return []
