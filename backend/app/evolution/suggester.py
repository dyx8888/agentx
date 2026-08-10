# 模块文档：Suggester 是进化系统的"大脑"——调用 LLM 分析人类修改模式，生成可执行的改进建议
# 核心思路：对比"原始输出 vs 人工修改后"的差异，让 LLM 提取可泛化的改进模式
"""
Evolution Suggester - LLM-based Improvement Suggestions
Generates improvement suggestions based on human-edited feedback patterns
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.database import db

logger = get_logger(__name__)

@dataclass
class FeedbackPair:
    """Data class for original vs edited feedback pairs"""
    # 同时保存原始输出和人工修改版本，让 LLM 通过对比差异来学习"人类期望的修改模式"
    original_output: str
    human_edited_output: str
    tool_name: str  # tool_name 是必须的，因为不同工具的错误模式不同，需要分开分析
    created_at: str

@dataclass
class EvolutionSuggestion:
    """Data class for evolution suggestions"""
    agent_id: int
    # suggested_prompt_changes 是纯文本而非结构化 JSON，因为 Prompt 修改建议需要灵活表达，不适合用固定模板
    suggested_prompt_changes: str
    # knowledge_entries 是独立的知识条目列表，每条可单独存入 ChromaDB，方便检索和去重
    knowledge_entries: list[str]
    analysis_summary: str
    # confidence_score 帮助管理员判断是否值得采纳此建议
    confidence_score: float

class EvolutionSuggester:
    """Suggester for generating LLM-based improvement suggestions"""

    def __init__(self, db_path: str = None):
        # 数据库路径与 Analyzer 共享同一个 feedback.db，保证数据一致性
        self.db_path = db_path or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "feedback.db")

    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)

    def extract_feedback_pairs(self, agent_id: int, tool_name: str = None, days: int = 7) -> list[FeedbackPair]:
        """
        Extract original vs edited feedback pairs for analysis
        
        Args:
            agent_id: Agent ID to analyze
            tool_name: Optional tool name to filter by
            days: Number of days to look back
            
        Returns:
            List of FeedbackPair objects
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate date threshold
            threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Query for modified feedback pairs
            # 只查询有修改记录的反馈，因为未被修改的反馈无法提供"人类期望"的对比信号
            query = """
                SELECT original_output, human_edited_output, tool_name, created_at
                FROM feedback
                WHERE agent_id = ? AND status = 'modified' AND created_at >= ?
            """
            params = [agent_id, threshold_date]

            if tool_name:
                query += " AND tool_name = ?"
                params.append(tool_name)

            query += " ORDER BY created_at DESC"

            cursor.execute(query, params)

            feedback_pairs = []
            for row in cursor.fetchall():
                original_output, human_edited_output, tool_name, created_at = row

                # Only include pairs where human actually made changes
                # 过滤掉 original == edited 的记录，这些是"标记为修改但实际未改"的无效数据
                if human_edited_output and human_edited_output != original_output:
                    feedback_pairs.append(FeedbackPair(
                        original_output=original_output,
                        human_edited_output=human_edited_output,
                        tool_name=tool_name,
                        created_at=created_at
                    ))

            return feedback_pairs

    def generate_suggestion(self, agent_id: int, tool_name: str = None) -> EvolutionSuggestion:
        """
        Generate improvement suggestions using LLM analysis
        
        Args:
            agent_id: Agent ID to analyze
            tool_name: Optional tool name to focus on
            
        Returns:
            EvolutionSuggestion object with improvements
        """
        try:
            # Extract feedback pairs
            feedback_pairs = self.extract_feedback_pairs(agent_id, tool_name)

            # 无反馈时返回空建议而非抛异常，因为"没有数据"是正常场景，不是错误
            if not feedback_pairs:
                return EvolutionSuggestion(
                    agent_id=agent_id,
                    suggested_prompt_changes="No modified feedback found for analysis.",
                    knowledge_entries=[],
                    analysis_summary="Insufficient data for analysis.",
                    confidence_score=0.0
                )

            # Prepare feedback summary for LLM
            feedback_summary = self._prepare_feedback_summary(feedback_pairs)

            # Generate LLM suggestions
            llm_response = self._call_llm_for_suggestions(feedback_summary, tool_name)

            # Parse LLM response
            suggestion = self._parse_llm_response(llm_response, agent_id)

            return suggestion

        except Exception as e:
            # 异常时返回空建议而非抛出，因为 LLM 调用可能会因网络问题失败，不应阻塞整个流程
            return EvolutionSuggestion(
                agent_id=agent_id,
                suggested_prompt_changes=f"Error generating suggestions: {str(e)}",
                knowledge_entries=[],
                analysis_summary="Failed to analyze feedback patterns.",
                confidence_score=0.0
            )

    def _prepare_feedback_summary(self, feedback_pairs: list[FeedbackPair]) -> str:
        """Prepare feedback summary for LLM analysis"""
        summary = "以下是人类修改AI输出的样本分析：\n\n"

        # 只取前 10 条，因为 LLM 上下文窗口有限，且 10 条足以发现模式
        for i, pair in enumerate(feedback_pairs[:10], 1):  # Limit to 10 pairs
            summary += f"样本 {i} (工具: {pair.tool_name}):\n"
            # 每条截断到 200 字符，防止超长输出占用过多 token
            summary += f"原始输出: {pair.original_output[:200]}...\n"
            summary += f"人工修改后: {pair.human_edited_output[:200]}...\n"
            summary += f"修改时间: {pair.created_at}\n\n"

        summary += f"\n总计分析了 {len(feedback_pairs)} 个修改样本。"

        return summary

    def _call_llm_for_suggestions(self, feedback_summary: str, tool_name: str = None) -> str:
        """Call LLM to generate improvement suggestions with structured Meta Prompt"""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            # 从 Meta Prompt 标准模块导入标准化的角色定义、约束和输出格式
            # 这些是 AgentX 系统统一的 Prompt 工程规范，确保所有 LLM 调用遵循相同的质量标准
            from app.core.meta_prompt_standards import (
                META_ANALYST_ROLE,
                META_CONSTRAINTS,
                META_FEWSHOT_EXTRACTION,
                META_OUTPUT_FORMAT,
            )
            from app.services.model_gateway import ModelGateway

            model_gateway = ModelGateway()
            llm = model_gateway.get_llm()

            # 将 Meta Prompt 标准组件拼装为完整的 System Prompt
            system_content = f"""{META_ANALYST_ROLE}

{META_CONSTRAINTS}

{META_OUTPUT_FORMAT}

{META_FEWSHOT_EXTRACTION}"""

            human_content = f"""基于以下人类修改AI输出的反馈分析，请提取改进模式和建议：

{feedback_summary}
{f'特别关注工具：{tool_name}' if tool_name else ''}

请按照上述 System Prompt 中的格式要求，返回 JSON。"""

            # 使用 invoke 而非 stream，因为需要完整响应来解析 JSON
            response = llm.invoke([
                SystemMessage(content=system_content),
                HumanMessage(content=human_content),
            ])
            return response.content

        except Exception as e:
            return f"LLM调用失败: {str(e)}"

    def _parse_llm_response(self, llm_response: str, agent_id: int) -> EvolutionSuggestion:
        """Parse LLM response into EvolutionSuggestion object"""
        try:
            import json

            # Try to extract JSON from response
            # LLM 可能返回带 markdown 代码块的 JSON，需要先提取纯净的 JSON 字符串
            if "```json" in llm_response:
                json_start = llm_response.find("```json") + 7
                json_end = llm_response.find("```", json_start)
                json_str = llm_response[json_start:json_end].strip()
            else:
                # Try to parse the entire response as JSON
                json_str = llm_response.strip()

            parsed = json.loads(json_str)

            # 使用 .get() 而非直接索引，防止 LLM 返回的 JSON 缺少某些字段导致崩溃
            return EvolutionSuggestion(
                agent_id=agent_id,
                suggested_prompt_changes=parsed.get('suggested_prompt_changes', ''),
                knowledge_entries=parsed.get('knowledge_entries', []),
                analysis_summary=parsed.get('analysis_summary', ''),
                confidence_score=float(parsed.get('confidence_score', 0.5))  # 默认 0.5 表示"不确定"
            )

        except (json.JSONDecodeError, KeyError, ValueError):
            # Fallback: extract text from response
            # JSON 解析失败时将整个 LLM 响应作为建议文本，至少保留了分析内容
            return EvolutionSuggestion(
                agent_id=agent_id,
                suggested_prompt_changes=llm_response,
                knowledge_entries=[],
                analysis_summary="LLM响应解析失败，返回原始内容。",
                confidence_score=0.3  # 解析失败时置信度设为 0.3，低于正常值，提示管理员需要人工审核
            )

    def save_suggestion_to_log(self, agent_id: int, tool_name: str, suggestion: str, training_data_path: str = None) -> bool:
        """Save evolution suggestion to database log"""
        try:
            # 通过 db.get_connection() 而非 self.get_connection()，因为 db 可能是 SQLAlchemy 模式
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO evolution_log (agent_id, tool_name, suggestion_text, training_data_path)
                    VALUES (?, ?, ?, ?)
                """, (agent_id, tool_name, suggestion, training_data_path))
                conn.commit()
            return True
        except Exception as e:
            logger.error("evolution_suggester_save_error", error=str(e))
            return False

    def generate_lightweight_suggestion(self, agent_id: int, task_result: str = None) -> EvolutionSuggestion:
        """
        基于单次任务结果生成轻量级进化建议。
        适用于实时触发场景，不需要大量的历史反馈数据。
        
        Args:
            agent_id: Agent ID
            task_result: 本次任务的执行结果文本
            
        Returns:
            EvolutionSuggestion 对象
        """
        try:
            # 如果有任务结果，直接分析
            if task_result:
                analysis_summary = "基于本次任务执行结果的实时分析"
                # 调用 LLM 对单次结果进行快速分析
                # 与 generate_suggestion 不同，这里只分析单次结果，置信度由 LLM 内的校准规则控制
                llm_response = self._call_llm_for_single_result(task_result)
                return self._parse_llm_response(llm_response, agent_id)
            else:
                # 降级到全量分析（原逻辑）
                # 没有任务结果时，回退到基于历史反馈的批量分析
                return self.generate_suggestion(agent_id)
        except Exception as e:
            return EvolutionSuggestion(
                agent_id=agent_id,
                suggested_prompt_changes="",
                knowledge_entries=[],
                analysis_summary=f"实时分析失败: {str(e)}",
                confidence_score=0.0
            )

    def _call_llm_for_single_result(self, task_result: str) -> str:
        """对单次任务结果调用 LLM 进行快速分析（含单样本置信度校准）"""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from app.services.model_gateway import ModelGateway

            model_gateway = ModelGateway()
            llm = model_gateway.get_llm()

            # 单样本分析的 System Prompt 与批量分析不同：特别强调置信度校准规则
            # 因为单样本信息量有限，必须防止 LLM 过度自信地给出建议
            system_content = """你是 Prompt 优化分析师。基于单次任务结果快速评估是否有改进空间。

## 单样本置信度校准规则
- 如果任务结果清晰完整、信息充足，置信度可为 0.6-0.75
- 如果任务结果部分缺失或仅有片段信息，置信度必须 ≤0.4
- 如果任务结果仅有1-2句话，置信度必须 ≤0.2 并注明"信息不足"
- 仅当发现明确的、可复现的问题模式时，才输出非空建议

## 输出格式
必须返回合法 JSON：
- suggested_prompt_changes: 具体建议或空字符串
- knowledge_entries: 可沉淀的知识条目列表或空列表
- analysis_summary: 1-2句话分析总结
- confidence_score: 0-1 小数，严格遵循校准规则"""

            human_content = f"""任务结果：
{task_result[:500]}  # 截断到 500 字符，与批量分析的截断策略一致

请按上述规则分析并返回 JSON。记住：单样本分析的置信度上限为 0.75。"""

            response = llm.invoke([
                SystemMessage(content=system_content),
                HumanMessage(content=human_content),
            ])
            # 使用 hasattr 检查 content 属性，兼容不同 LLM 返回类型
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            # 失败时返回一个合法的 JSON 空结果，避免上游解析崩溃
            return f'{{"suggested_prompt_changes": "", "knowledge_entries": [], "analysis_summary": "LLM分析失败: {str(e)}", "confidence_score": 0.0}}'
