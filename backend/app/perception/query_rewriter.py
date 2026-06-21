"""
感知管道 - 查询改写器
使用 LLM 补全省略主语 + 将口语化表达转化为结构化查询
"""
# 两个核心能力（补全省略、口语转结构化）直接影响下游意图提取和 RAG 检索的准确率

from app.core.logging import get_logger

logger = get_logger(__name__)

REWRITE_SYSTEM_PROMPT = """你是一个查询改写助手。你的任务是将用户的自然语言查询改写为更清晰、更结构化的表达。

规则：
1. 补全省略的主语和宾语（如"上次那个"→"上次提到的XX方案"）
2. 将口语化表达转化为正式、结构化的查询
3. 保持原意不变，不要添加用户未提及的信息
4. 如果原始查询已经很清晰，直接返回原句
5. 只返回改写后的查询文本，不要添加任何解释或前缀

输入可能包含历史对话上下文（以 <previous_*> 标签包裹），请结合上下文理解指代。"""
# 在 prompt 中预设 <previous_*> 标签规则，让 LLM 自己识别上下文标记，而不用在代码中解析标签结构


class QueryRewriter:
    """使用 LLM 改写用户查询，补全省略 + 口语转结构化"""

    def __init__(self, model_gateway=None):  # 支持注入 gateaway 实现测试 mock
        """
        Args:
            model_gateway: ModelGateway 实例，如果为 None 则延迟获取
        """
        self._model_gateway = model_gateway

    def _get_llm(self):  # 与 IntentExtractor 相同的延迟加载模式，保持模块间一致性
        if self._model_gateway is None:
            from app.services.model_gateway import get_global_model_gateway  # 延迟导入防止循环依赖
            self._model_gateway = get_global_model_gateway()
        return self._model_gateway.get_llm()

    def rewrite(self, text: str) -> str:
        """
        改写用户查询

        Args:
            text: 过滤后的原始用户输入

        Returns:
            改写后的查询文本；如果输入为空或 LLM 调用失败，返回原始文本
        """
        if not text or not text.strip():  # 空输入直接返回，不浪费 LLM 调用
            return text

        if len(text.strip()) < 4:  # 极短输入（如"你好"）改写无意义，直接返回
            return text.strip()

        try:
            llm = self._get_llm()
            from langchain_core.messages import HumanMessage, SystemMessage  # 延迟导入，与 intent_extractor 保持一致

            messages = [
                SystemMessage(content=REWRITE_SYSTEM_PROMPT),  # SystemMessage 设定改写规则角色
                HumanMessage(content=text),
            ]
            response = llm.invoke(messages)
            rewritten = response.content.strip() if hasattr(response, 'content') else str(response).strip()  # 兼容不同 LLM 响应结构

            if not rewritten:  # LLM 可能返回空，此时用原文兜底
                return text

            logger.info("query_rewritten", original_length=len(text), rewritten_length=len(rewritten))  # info 级别追踪改写效果
            return rewritten
        except Exception as e:
            logger.warning("query_rewrite_failed", error=str(e))  # warning 而非 error，改写失败不影响管线继续
            return text  # 返回原文保证降级可用性