"""
感知管道 - 统一感知管道编排器
按顺序编排：InputFilter → QueryRewriter → IntentExtractor → RagRetriever → ToolResultParser
"""
# docstring 列出管线顺序，原因是下游调用方常需要确认哪一步可跳过、哪一步依赖前一步的输出

from dataclasses import dataclass, field  # dataclass 天然适合承载多个阶段的结果数据

from app.core.logging import get_logger
from app.perception.input_filter import InputFilter
from app.perception.intent_extractor import Intent, IntentExtractor
from app.perception.query_rewriter import QueryRewriter
from app.perception.rag_retriever import RagResult, RagRetriever
from app.perception.tool_result_parser import ParsedToolResult, ToolResultParser

logger = get_logger(__name__)


@dataclass
class PerceptionContext:  # dataclass 而非普通 dict，因为类型安全 + IDE 自动补全能大幅减少拼写错误
    """感知管道上下文 - 承载管道各阶段的处理结果"""
    raw_input: str = ""  # 保留原始输入用于日志审计和调试
    rewritten_query: str = ""  # 改写后的查询，为空表示未执行改写阶段
    intent: Intent = field(default_factory=Intent)  # 用 field 防止所有实例共享同一个 Intent 默认值
    rag_results: RagResult = field(default_factory=RagResult)
    tool_results: list[ParsedToolResult] = field(default_factory=list)  # 工具解析结果，可能为空列表
    metadata: dict = field(default_factory=dict)  # 预留元数据字段，方便不同 Agent 注入自定义信息
    filtered_input: str = ""  # 过滤后的输入，独立字段便于比较过滤前后的差异
    augmented_message: str = ""  # 经过 RAG 增强后的最终消息，发给下游 LLM


class PerceptionPipeline:
    """
    统一感知管道

    按顺序执行以下阶段：
    1. InputFilter     - 验证和清洗输入
    2. QueryRewriter   - 补全省略 + 口语转结构化
    3. IntentExtractor - 提取结构化意图
    4. RagRetriever    - 根据意图检索知识库
    5. ToolResultParser - 解析工具执行结果（可选，后续调用）

    使用示例:
        pipeline = PerceptionPipeline()
        ctx = pipeline.run(raw_input="帮我查一下最近的销售数据")
        # ctx.rewritten_query, ctx.intent, ctx.rag_results 均已填充
    """

    def __init__(self, model_gateway=None):  # gateaway 可注入可延迟，方便测试时 mock
        self._model_gateway = model_gateway
        self._input_filter = InputFilter()  # InputFilter 使用类方法，实例化仅为了保持管线组件风格统一
        self._query_rewriter = QueryRewriter(model_gateway=model_gateway)  # 传递 gateaway 给子组件共享 LLM 实例
        self._intent_extractor = IntentExtractor(model_gateway=model_gateway)
        self._rag_retriever = RagRetriever()  # RAG 检索器通过内部分发获取连接，不依赖 gateaway
        self._tool_result_parser = ToolResultParser()  # 工具解析器无外部依赖，直接实例化

    def run(
        self,
        raw_input: str,
        company_id: str = "",
        agent_name: str = "",
        skip_rewrite: bool = False,
        skip_intent: bool = False,
        skip_rag: bool = False,
    ) -> PerceptionContext:
        """
        执行完整的感知管道

        Args:
            raw_input: 原始用户输入
            company_id: 公司 ID（用于 RAG 检索）
            agent_name: Agent 名称（用于 RAG 检索和意图路由）
            skip_rewrite: 跳过查询改写阶段
            skip_intent: 跳过意图提取阶段
            skip_rag: 跳过 RAG 检索阶段

        Returns:
            PerceptionContext 包含所有阶段的处理结果

        Raises:
            ValueError: 输入验证失败（空输入、超长等）
        """
        ctx = PerceptionContext(raw_input=raw_input)  # 先把原始输入写入上下文，后续阶段逐步填充
        ctx.metadata = {  # 元数据记录调用参数，方便后续 Agent 判断跳过逻辑
            "company_id": company_id,
            "agent_name": agent_name,
            "skip_rewrite": skip_rewrite,
            "skip_intent": skip_intent,
            "skip_rag": skip_rag,
        }

        try:
            # Stage 1: InputFilter - 验证和清洗
            logger.info("perception_pipeline_start", stage="input_filter")  # info 级别标记管线开始，用于性能追踪
            ctx.filtered_input = self._input_filter.filter(raw_input)  # 先过滤再改写，因为有害内容会影响改写质量
            logger.debug("perception_input_filtered", length=len(ctx.filtered_input))

            # Stage 2: QueryRewriter - 改写查询
            if not skip_rewrite:  # 允许跳过改写，适用于短查询或已经结构化的输入
                logger.info("perception_pipeline_stage", stage="query_rewriter")
                ctx.rewritten_query = self._query_rewriter.rewrite(ctx.filtered_input)
            else:
                ctx.rewritten_query = ctx.filtered_input  # 跳过时直接用过滤后的输入，保持字段非空

            # Stage 3: IntentExtractor - 提取意图
            query_for_intent = ctx.rewritten_query or ctx.filtered_input  # 优先用改写结果，兜底用过滤输入
            if not skip_intent:  # 意图跳过的典型场景：内部分发时已知意图类型
                logger.info("perception_pipeline_stage", stage="intent_extractor")
                ctx.intent = self._intent_extractor.extract(query_for_intent)
            else:
                ctx.intent = Intent()  # 默认意图 = GENERAL + 0.5 置信度

            # Stage 4: RagRetriever - 检索知识库
            if not skip_rag and company_id:  # 同时检查 skip 标记和 company_id，无公司 ID 时检索无意义
                logger.info("perception_pipeline_stage", stage="rag_retriever")
                ctx.rag_results = self._rag_retriever.retrieve(
                    query=query_for_intent,
                    company_id=company_id,
                    agent_name=agent_name,  # agent_name 用于按 Agent 过滤专属知识
                    intent_type=ctx.intent.intent_type.value,  # 意图类型影响检索策略
                )
                ctx.augmented_message = self._rag_retriever.augment_message(  # 将 RAG 上下文拼接到消息头部
                    ctx.rewritten_query or ctx.filtered_input,  # 优先改写版本，更清晰
                    ctx.rag_results,
                )
            else:
                ctx.augmented_message = ctx.rewritten_query or ctx.filtered_input  # 跳过 RAG 时消息不增强

            logger.info(
                "perception_pipeline_complete",
                input_length=len(raw_input),
                intent_type=ctx.intent.intent_type.value,
                rag_context_length=len(ctx.rag_results.context),
            )

            return ctx

        except ValueError:  # 输入验证错误直接向上抛，调用方应该处理此异常
            raise
        except Exception as e:  # 其他异常统一捕获记录后重新抛，确保管线错误可追溯
            logger.error("perception_pipeline_error", error=str(e))
            raise

    def parse_tool_result(self, tool_name: str, output: object) -> ParsedToolResult:  # 单一解析入口，用于即时解析场景
        """解析工具执行结果（供后续调用）"""
        return self._tool_result_parser.parse(tool_name, output)

    def parse_tool_results(self, results: list[tuple[str, object]]) -> list[ParsedToolResult]:  # 批量解析减少调用开销
        """批量解析工具执行结果"""
        parsed = []
        for tool_name, output in results:
            parsed.append(self._tool_result_parser.parse(tool_name, output))
        return parsed