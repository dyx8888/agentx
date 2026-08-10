# 模块文档：Analyser 是监控面板的数据层，为管理员提供"哪些 Agent/Tool 被改得最多"的量化指标
# 这个模块独立于 LLM 调用，仅依赖 SQLite 统计数据，保证低延迟和高可靠性
"""
Evolution Analyzer - Feedback Analysis and Modification Rate Tracking
Provides statistical analysis of agent and tool performance based on feedback data
"""

import os
import sqlite3
# 用 dataclass 而非普通 dict，是因为修改率数据需要类型安全传递给前端图表组件，避免字段名拼写错误在运行时才发现
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ModificationRate:
    """Data class for modification rate statistics"""
    # 分开存储 total/ modified_count/ rate 三个值是为了让前端可以灵活展示（百分比+柱状图+数值），而不需要重新计算
    total_feedback: int
    modified_count: int
    modification_rate: float
    # agent_id/agent_name/tool_name 设为可选，因为不同查询场景（按Agent查 vs 按Tool查）返回的维度不同
    agent_id: int | None = None
    agent_name: str | None = None
    tool_name: str | None = None

@dataclass
class AgentEvolutionData:
    """Data class for agent evolution statistics"""
    agent_id: int
    agent_name: str
    company_id: int  # company_id 是必须字段，因为所有查询都需要租户隔离，不能遗漏
    modification_rate: float
    total_feedback: int
    modified_count: int
    # top_modified_tools 用于快速定位问题工具，只取 Top3 是为了避免信息过载，让管理员聚焦关键问题
    top_modified_tools: list[str]

class EvolutionAnalyzer:
    """Analyzer for agent and tool modification rates"""

    def __init__(self, db_path: str = None):
        # 数据库路径默认在 backend/data/feedback.db，而非 evolution 目录下，因为 feedback 数据是整个系统的共享资源
        self.db_path = db_path or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "feedback.db")

    def get_connection(self):
        """Get database connection"""
        # 每次调用都创建新连接而非连接池，因为 SQLite 在低并发场景下简单连接比连接池更可靠且无竞态问题
        return sqlite3.connect(self.db_path)

    def get_agent_modification_rate(self, agent_id: int, days: int = 7) -> ModificationRate:
        """
        Get modification rate for a specific agent
        
        Args:
            agent_id: Agent ID to analyze
            days: Number of days to look back
            
        Returns:
            ModificationRate object with statistics
        """
        # 使用上下文管理器自动提交/回滚，避免忘记 commit 导致数据丢失或连接泄漏
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate date threshold
            # 将日期格式化为 'YYYY-MM-DD' 字符串，因为 SQLite 的日期比较依赖字符串格式的一致性
            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Get total feedback count for agent
            # 使用参数化查询而非字符串拼接，防止 SQL 注入和日期格式错误
            cursor.execute("""
                SELECT COUNT(*) FROM feedback 
                WHERE agent_id = ? AND created_at >= ?
            """, (agent_id, threshold_date))
            total_feedback = cursor.fetchone()[0]

            # Get modified feedback count for agent
            cursor.execute("""
                SELECT COUNT(*) FROM feedback 
                WHERE agent_id = ? AND status = 'modified' AND created_at >= ?
            """, (agent_id, threshold_date))
            modified_count = cursor.fetchone()[0]

            # Calculate modification rate
            # 先判断分母是否为零，避免 ZeroDivisionError 导致整个查询崩溃
            modification_rate = (modified_count / total_feedback * 100) if total_feedback > 0 else 0.0

            return ModificationRate(
                total_feedback=total_feedback,
                modified_count=modified_count,
                modification_rate=modification_rate,
                agent_id=agent_id
            )

    def get_tool_modification_rate(self, tool_name: str, company_id: int, days: int = 7) -> ModificationRate:
        """
        Get modification rate for a specific tool within a company
        
        Args:
            tool_name: Tool name to analyze
            company_id: Company ID for multi-tenant isolation
            days: Number of days to look back
            
        Returns:
            ModificationRate object with statistics
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate date threshold
            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Get total feedback count for tool in company
            # JOIN agents 表是为了确保 company_id 的租户隔离，防止跨租户数据泄露
            cursor.execute("""
                SELECT COUNT(*) FROM feedback f
                JOIN agents a ON f.agent_id = a.id
                WHERE a.company_id = ? AND f.tool_name = ? AND f.created_at >= ?
            """, (company_id, tool_name, threshold_date))
            total_feedback = cursor.fetchone()[0]

            # Get modified feedback count for tool in company
            cursor.execute("""
                SELECT COUNT(*) FROM feedback f
                JOIN agents a ON f.agent_id = a.id
                WHERE a.company_id = ? AND f.tool_name = ? AND f.status = 'modified' AND f.created_at >= ?
            """, (company_id, tool_name, threshold_date))
            modified_count = cursor.fetchone()[0]

            # Calculate modification rate
            modification_rate = (modified_count / total_feedback * 100) if total_feedback > 0 else 0.0

            return ModificationRate(
                total_feedback=total_feedback,
                modified_count=modified_count,
                modification_rate=modification_rate,
                tool_name=tool_name
            )

    def get_top_modified_agents(self, min_feedback: int = 5, days: int = 7) -> list[AgentEvolutionData]:
        """
        Get agents with highest modification rates that have minimum feedback
        
        Args:
            min_feedback: Minimum number of feedback entries to consider
            days: Number of days to look back
            
        Returns:
            List of AgentEvolutionData objects sorted by modification rate
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate date threshold
            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Get agents with their modification rates and top modified tools
            # 用 LEFT JOIN 而非 INNER JOIN，是为了保留没有反馈的 Agent（修改率为0），让管理员看到全局
            # HAVING 过滤样本量不足的 Agent，避免小样本导致的统计偏差（如1条反馈被修改=100%修改率）
            cursor.execute("""
                SELECT 
                    a.id,
                    a.name,
                    a.company_id,
                    COUNT(f.id) as total_feedback,
                    SUM(CASE WHEN f.status = 'modified' THEN 1 ELSE 0 END) as modified_count,
                    ROUND(SUM(CASE WHEN f.status = 'modified' THEN 1 ELSE 0 END) * 100.0 / COUNT(f.id), 2) as modification_rate
                FROM agents a
                LEFT JOIN feedback f ON a.id = f.agent_id AND f.created_at >= ?
                GROUP BY a.id, a.name, a.company_id
                HAVING COUNT(f.id) >= ?
                ORDER BY modification_rate DESC
            """, (threshold_date, min_feedback))

            results = []
            for row in cursor.fetchall():
                agent_id, agent_name, company_id, total_feedback, modified_count, modification_rate = row

                # Get top modified tools for this agent
                # 在循环内再次查询每个 Agent 的 Top3 工具，虽然会产生 N+1 查询问题，但 Agent 数量通常只有个位数，性能影响可忽略
                cursor.execute("""
                    SELECT f.tool_name, COUNT(*) as modified_count
                    FROM feedback f
                    WHERE f.agent_id = ? AND f.status = 'modified' AND f.created_at >= ?
                    GROUP BY f.tool_name
                    ORDER BY modified_count DESC
                    LIMIT 3
                """, (agent_id, threshold_date))

                # 列表推导式只取 tool_name（索引0），丢弃计数，因为前端只需要排名不需要具体数字
                top_modified_tools = [tool_row[0] for tool_row in cursor.fetchall()]

                results.append(AgentEvolutionData(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    company_id=company_id,
                    modification_rate=modification_rate,
                    total_feedback=total_feedback,
                    modified_count=modified_count,
                    top_modified_tools=top_modified_tools
                ))

            return results

    def get_suggestions_for_agent(self, agent_id: int) -> list[dict]:
        """Get evolution suggestions for a specific agent"""
        # 此处不通过 self.get_connection() 而是手动管理连接，因为该方法可能被批量调用，避免上下文管理器的重复开销
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'feedback.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 按创建时间降序排列，让最新建议排在前面，符合"最新最重要"的业务直觉
        cursor.execute("""
            SELECT id, agent_id, tool_name, suggestion_text, created_at, applied
            FROM evolution_log
            WHERE agent_id = ? ORDER BY created_at DESC
        """, (agent_id,))
        rows = cursor.fetchall()
        # 手动关闭连接，因为没用 with 语句
        conn.close()

        # 将 applied 字段 (0/1) 显式转为 bool，因为前端 JS 期望 true/false 而非 0/1
        return [
            {
                "id": row[0],
                "agent_id": row[1],
                "tool_name": row[2],
                "suggestion_text": row[3],
                "created_at": row[4],
                "applied": bool(row[5])
            }
            for row in rows
        ]

    def get_company_evolution_report(self, company_id: int, days: int = 7) -> list[AgentEvolutionData]:
        """
        Get evolution report for a specific company
        
        Args:
            company_id: Company ID for multi-tenant isolation
            days: Number of days to look back
            
        Returns:
            List of AgentEvolutionData objects for the company
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate date threshold
            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Get agents for the company with their modification rates
            # WHERE a.company_id = ? 确保只查询指定租户的 Agent，配合 LEFT JOIN 实现租户级别的隔离统计
            cursor.execute("""
                SELECT 
                    a.id,
                    a.name,
                    a.company_id,
                    COUNT(f.id) as total_feedback,
                    SUM(CASE WHEN f.status = 'modified' THEN 1 ELSE 0 END) as modified_count,
                    ROUND(SUM(CASE WHEN f.status = 'modified' THEN 1 ELSE 0 END) * 100.0 / COUNT(f.id), 2) as modification_rate
                FROM agents a
                LEFT JOIN feedback f ON a.id = f.agent_id AND f.created_at >= ?
                WHERE a.company_id = ?
                GROUP BY a.id, a.name, a.company_id
                ORDER BY modification_rate DESC
            """, (threshold_date, company_id))

            results = []
            for row in cursor.fetchall():
                agent_id, agent_name, company_id, total_feedback, modified_count, modification_rate = row

                # Get top modified tools for this agent
                cursor.execute("""
                    SELECT f.tool_name, COUNT(*) as modified_count
                    FROM feedback f
                    WHERE f.agent_id = ? AND f.status = 'modified' AND f.created_at >= ?
                    GROUP BY f.tool_name
                    ORDER BY modified_count DESC
                    LIMIT 3
                """, (agent_id, threshold_date))

                top_modified_tools = [tool_row[0] for tool_row in cursor.fetchall()]

                results.append(AgentEvolutionData(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    company_id=company_id,
                    modification_rate=modification_rate,
                    total_feedback=total_feedback,
                    modified_count=modified_count,
                    top_modified_tools=top_modified_tools
                ))

            return results

    def get_suggestions_for_agent(self, agent_id: int) -> list[dict]:
        """Get evolution suggestions for a specific agent"""
        # 此处方法重复定义（与上方同签名），可能是合并冲突遗留。第二个定义会覆盖第一个，运行时以这个为准。
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'feedback.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, agent_id, tool_name, suggestion_text, created_at, applied
            FROM evolution_log
            WHERE agent_id = ? ORDER BY created_at DESC
        """, (agent_id,))
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row[0],
                "agent_id": row[1],
                "tool_name": row[2],
                "suggestion_text": row[3],
                "created_at": row[4],
                "applied": bool(row[5])
            }
            for row in rows
        ]
