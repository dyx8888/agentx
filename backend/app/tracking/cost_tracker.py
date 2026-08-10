"""
Cost tracker for LLM usage monitoring and cost calculation
"""

from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.database import db

logger = get_logger(__name__)


class CostTracker:
    """Cost tracking service for LLM usage"""

    @staticmethod
    def record_usage(model_name: str, input_tokens: int, output_tokens: int,
                   cost: float, request_id: str = None, agent_id: int = None) -> bool:
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
            conn = db.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO llm_usage 
                (model_name, input_tokens, output_tokens, cost, request_id, agent_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                model_name,
                input_tokens,
                output_tokens,
                cost,
                request_id,
                agent_id,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error("cost_record_usage_failed", error=str(e))
            return False

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
            conn = db.get_connection()
            cursor = conn.cursor()

            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                SELECT 
                    SUM(cost) as total_cost,
                    COUNT(*) as total_requests,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens
                FROM llm_usage 
                WHERE created_at >= ?
            """, (threshold_date,))

            result = cursor.fetchone()
            conn.close()

            if result and result[0]:
                return {
                    "total_cost": round(result[0], 6),
                    "total_requests": result[1],
                    "total_input_tokens": result[2] or 0,
                    "total_output_tokens": result[3] or 0,
                    "period_days": days
                }
            else:
                return {
                    "total_cost": 0.0,
                    "total_requests": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "period_days": days
                }

        except Exception as e:
            logger.error("cost_get_total_failed", error=str(e))
            return {
                "total_cost": 0.0,
                "total_requests": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "period_days": days
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
            conn = db.get_connection()
            cursor = conn.cursor()

            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                SELECT 
                    model_name,
                    SUM(cost) as total_cost,
                    COUNT(*) as total_requests,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens
                FROM llm_usage 
                WHERE created_at >= ?
                GROUP BY model_name
                ORDER BY total_cost DESC
            """, (threshold_date,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "model_name": row[0],
                    "total_cost": round(row[1], 6),
                    "total_requests": row[2],
                    "total_input_tokens": row[3] or 0,
                    "total_output_tokens": row[4] or 0
                })

            conn.close()
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
            conn = db.get_connection()
            cursor = conn.cursor()

            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                SELECT 
                    model_name,
                    SUM(cost) as total_cost,
                    COUNT(*) as total_requests,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens
                FROM llm_usage 
                WHERE agent_id = ? AND created_at >= ?
                GROUP BY model_name
                ORDER BY total_cost DESC
            """, (agent_id, threshold_date))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "model_name": row[0],
                    "total_cost": round(row[1], 6),
                    "total_requests": row[2],
                    "total_input_tokens": row[3] or 0,
                    "total_output_tokens": row[4] or 0
                })

            conn.close()
            return results

        except Exception as e:
            logger.error("cost_get_by_agent_failed", error=str(e))
            return []

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
            conn = db.get_connection()
            cursor = conn.cursor()

            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                SELECT 
                    DATE(created_at) as date,
                    SUM(cost) as daily_cost,
                    COUNT(*) as daily_requests,
                    SUM(input_tokens) as daily_input_tokens,
                    SUM(output_tokens) as daily_output_tokens
                FROM llm_usage 
                WHERE created_at >= ?
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """, (threshold_date,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "date": row[0],
                    "daily_cost": round(row[1], 6),
                    "daily_requests": row[2],
                    "daily_input_tokens": row[3] or 0,
                    "daily_output_tokens": row[4] or 0
                })

            conn.close()
            return results

        except Exception as e:
            logger.error("cost_get_daily_trend_failed", error=str(e))
            return []
