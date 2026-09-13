"""
感知管道 - 统一感知管道编排器
按顺序编排：InputFilter → QueryRewriter → IntentExtractor → RagRetriever → ToolResultParser

变更② T2.2：增强为输出 ContextPackage 的新流程
  InputFilter → QueryRewriter → IntentExtractor
  → MemoryRetriever(预检索层) → 缓存命中则直接返回
  → RagRetriever → SkillMatcher → ToolContextBuilder
  → ContextPackage
"""
# docstring 列出管线顺序，原因是下游调用方常需要确认哪一步可跳过、哪一步依赖前一步的输出

from dataclasses import dataclass, field  # dataclass 天然适合承载多个阶段的结果数据

from app.core.logging import get_logger
from app.perception.context_package import ContextPackage
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

    def __init__(
        self, model_gateway=None, pre_retrieval_layer=None
    ):  # gateaway 可注入可延迟，方便测试时 mock
        self._model_gateway = model_gateway
        self._input_filter = (
            InputFilter()
        )  # InputFilter 使用类方法，实例化仅为了保持管线组件风格统一
        self._query_rewriter = QueryRewriter(
            model_gateway=model_gateway
        )  # 传递 gateaway 给子组件共享 LLM 实例
        self._intent_extractor = IntentExtractor(model_gateway=model_gateway)
        self._rag_retriever = RagRetriever()  # RAG 检索器通过内部分发获取连接，不依赖 gateaway
        self._tool_result_parser = ToolResultParser()  # 工具解析器无外部依赖，直接实例化
        # T2.2: 预检索层延迟初始化，避免模块加载时强依赖 DB/Redis/Milvus
        self._pre_retrieval_layer = pre_retrieval_layer

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
            logger.info(
                "perception_pipeline_start", stage="input_filter"
            )  # info 级别标记管线开始，用于性能追踪
            ctx.filtered_input = self._input_filter.filter(
                raw_input
            )  # 先过滤再改写，因为有害内容会影响改写质量
            logger.debug("perception_input_filtered", length=len(ctx.filtered_input))

            # Stage 2: QueryRewriter - 改写查询
            if not skip_rewrite:  # 允许跳过改写，适用于短查询或已经结构化的输入
                logger.info("perception_pipeline_stage", stage="query_rewriter")
                ctx.rewritten_query = self._query_rewriter.rewrite(
                    ctx.filtered_input, company_id=company_id
                )
            else:
                ctx.rewritten_query = ctx.filtered_input  # 跳过时直接用过滤后的输入，保持字段非空

            # Stage 3: IntentExtractor - 提取意图
            query_for_intent = (
                ctx.rewritten_query or ctx.filtered_input
            )  # 优先用改写结果，兜底用过滤输入
            if not skip_intent:  # 意图跳过的典型场景：内部分发时已知意图类型
                logger.info("perception_pipeline_stage", stage="intent_extractor")
                ctx.intent = self._intent_extractor.extract(
                    query_for_intent, company_id=company_id
                )
            else:
                ctx.intent = Intent()  # 默认意图 = GENERAL + 0.5 置信度

            # Stage 4: RagRetriever - 检索知识库
            if (
                not skip_rag and company_id
            ):  # 同时检查 skip 标记和 company_id，无公司 ID 时检索无意义
                logger.info("perception_pipeline_stage", stage="rag_retriever")
                ctx.rag_results = self._rag_retriever.retrieve(
                    query=query_for_intent,
                    company_id=company_id,
                    agent_name=agent_name,  # agent_name 用于按 Agent 过滤专属知识
                    intent_type=ctx.intent.intent_type.value,  # 意图类型影响检索策略
                )
                ctx.augmented_message = (
                    self._rag_retriever.augment_message(  # 将 RAG 上下文拼接到消息头部
                        ctx.rewritten_query or ctx.filtered_input,  # 优先改写版本，更清晰
                        ctx.rag_results,
                    )
                )
            else:
                ctx.augmented_message = (
                    ctx.rewritten_query or ctx.filtered_input
                )  # 跳过 RAG 时消息不增强

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

    # ==================== T2.2: 增强流程（输出 ContextPackage）====================

    async def build_context_package(
        self,
        raw_input: str,
        company_id: str = "",
        thread_id: str | None = None,
        agent_name: str = "master",
        skip_rewrite: bool = False,
        skip_intent: bool = False,
        skip_rag: bool = False,
    ) -> ContextPackage:
        """构建综合上下文包 — master Agent 路由决策的输入。

        流程：
        1. InputFilter → QueryRewriter → IntentExtractor（复用 run，跳过 RAG）
        2. MemoryRetriever: 调 PreRetrievalLayer → 缓存命中则直接返回 ContextPackage(cache_hit=True)
        3. RagRetriever: 知识库检索
        4. SkillMatcher: 语义匹配技能
        5. ToolContextBuilder: 构建可用工具/子 Agent 清单
        6. 组装 ContextPackage

        Args:
            raw_input: 原始用户输入
            company_id: 公司 ID（多租户隔离 + RAG 检索 + 缓存键）
            thread_id: 会话 ID（工作记忆隔离）
            agent_name: Agent 名称，master 架构下统一为 "master"
            skip_rewrite/skip_intent/skip_rag: 跳过对应阶段

        Returns:
            ContextPackage: cache_hit=True 时调用方应直接返回 direct_return
        """
        # Step 1: 复用现有 run() 跑前三个阶段（InputFilter → QueryRewriter → IntentExtractor）
        # 用 skip_rag=True 跳过 RAG，因为 RAG 要在 MemoryRetriever 之后执行
        base_ctx = self.run(
            raw_input=raw_input,
            company_id=company_id,
            agent_name=agent_name,
            skip_rewrite=skip_rewrite,
            skip_intent=skip_intent,
            skip_rag=True,  # RAG 延后到 Step 3
        )

        # Step 2: MemoryRetriever — 调预检索层
        # 缓存命中 → 直接返回，跳过后续所有步骤（省 LLM 调用）
        memory_result = await self._run_memory_retriever(
            company_id=company_id,
            user_input=raw_input,
            thread_id=thread_id,
            agent_name=agent_name,
        )
        if memory_result.cache_hit:
            logger.info(
                "context_package_cache_hit",
                company_id=company_id,
                cache_key=memory_result.cache_key,
            )
            return ContextPackage(
                raw_input=raw_input,
                company_id=company_id,
                cache_hit=True,
                direct_return=memory_result.direct_return,
                cache_key=memory_result.cache_key,
            )

        # Step 3: RagRetriever — 知识库检索（缓存未命中才执行）
        rag_chunks: list[dict] = []
        rag_references: list[dict] = []
        rag_evidence_chunks: list[dict] = []
        if not skip_rag and company_id:
            query_for_rag = base_ctx.rewritten_query or base_ctx.filtered_input
            rag_result = self._rag_retriever.retrieve(
                query=query_for_rag,
                company_id=company_id,
                agent_name=agent_name,
                intent_type=base_ctx.intent.intent_type.value,
            )
            raw_references = getattr(rag_result, "references", []) or []
            raw_evidence_chunks = getattr(rag_result, "evidence_chunks", []) or []
            rag_references = raw_references if isinstance(raw_references, list) else []
            rag_evidence_chunks = (
                raw_evidence_chunks if isinstance(raw_evidence_chunks, list) else []
            )
            # 兼容字段暂时保持为短引用，避免前端/持久化收到长证据。
            rag_chunks = rag_references
            if rag_result.context:
                if not rag_references:
                    rag_references = [
                        {
                            "content": rag_result.context[:200],
                            "source": "rag_context",
                        }
                    ]
                    rag_chunks = rag_references
                if not rag_evidence_chunks:
                    rag_evidence_chunks = [
                        {"content": rag_result.context[:800], "source": "rag_context"}
                    ]

        # Step 4: SkillMatcher — 语义匹配技能
        matched_skills = self._run_skill_matcher(
            user_message=base_ctx.rewritten_query or base_ctx.filtered_input,
            agent_name=agent_name,
        )

        # Step 5: ToolContextBuilder — 构建可用工具/子 Agent 清单
        available_tools, available_agents = self._run_tool_context_builder(agent_name=agent_name)

        # Step 6: 组装 ContextPackage
        package = ContextPackage(
            rewritten_query=base_ctx.rewritten_query or base_ctx.filtered_input,
            raw_input=raw_input,
            intent_type=base_ctx.intent.intent_type.value,
            intent_entities=base_ctx.intent.entities,
            rag_chunks=rag_chunks,
            rag_evidence_chunks=rag_evidence_chunks,
            rag_references=rag_references,
            memory_context=memory_result.memory_context,
            similar_answers=memory_result.similar_answers,
            matched_skills=matched_skills,
            available_tools=available_tools,
            available_agents=available_agents,
            company_id=company_id,
            company_context=self._build_company_context(company_id),
            cache_key=memory_result.cache_key,
        )

        logger.info(
            "context_package_built",
            intent_type=package.intent_type,
            rag_count=len(package.rag_chunks),
            rag_evidence_count=len(package.rag_evidence_chunks),
            rag_reference_count=len(package.rag_references),
            memory_count=len(package.memory_context),
            similar_count=len(package.similar_answers),
            skill_count=len(package.matched_skills),
            tool_count=len(package.available_tools),
            agent_count=len(package.available_agents),
        )

        return package

    # ---------- T2.2 子组件 ----------

    def _get_pre_retrieval_layer(self):
        """延迟获取预检索层实例。

        延迟获取原因：PreRetrievalLayer 依赖 DB/Redis/Milvus，
        在模块加载时获取会在 import 时触发连接。
        """
        if self._pre_retrieval_layer is not None:
            return self._pre_retrieval_layer
        try:
            from app.runtime.pre_retrieval import PreRetrievalLayer

            self._pre_retrieval_layer = PreRetrievalLayer()
            return self._pre_retrieval_layer
        except Exception as e:
            logger.warning("pre_retrieval_layer_unavailable", error=str(e))
            return None

    async def _run_memory_retriever(
        self,
        company_id: str,
        user_input: str,
        thread_id: str | None,
        agent_name: str,
    ):
        """MemoryRetriever: 调预检索层查缓存和记忆。

        预检索层不可用时降级为空结果（cache_hit=False, 空列表），
        不阻塞主流程。
        """
        layer = self._get_pre_retrieval_layer()
        if layer is None:
            # 预检索层不可用 → 返回空结果，走正常 Agent 流程
            from app.runtime.pre_retrieval import PreRetrievalResult

            return PreRetrievalResult.enhance_result(
                memory_context=[],
                similar_answers=[],
                cache_key="",
            )

        # company_id 转整数（PreRetrievalLayer 按 int 设计，缓存键需要数值类型）
        try:
            company_id_int = int(company_id) if company_id else 0
        except (ValueError, TypeError):
            company_id_int = 0

        return await layer.retrieve(
            company_id=company_id_int,
            user_input=user_input,
            thread_id=thread_id,
            agent_name=agent_name,
        )

    def _run_skill_matcher(self, user_message: str, agent_name: str) -> list:
        """SkillMatcher: 语义匹配技能清单。

        从 SkillRegistry 匹配当前 agent 的技能，
        语义匹配优先，降级为关键词匹配。

        Returns:
            匹配到的 SkillMeta 列表（通常 0 或 1 个，预留 list 类型便于扩展多技能）
        """
        try:
            from app.skills.registry import skill_registry

            # match_skill 返回单个最佳匹配，包成 list 供 ContextPackage 统一消费
            matched = skill_registry.match_skill(user_message, agent_name)
            return [matched] if matched else []
        except Exception as e:
            logger.warning("skill_match_failed", error=str(e))
            return []

    def _run_tool_context_builder(self, agent_name: str) -> tuple[list[str], list[str]]:
        """ToolContextBuilder: 构建可用工具和可委派子 Agent 清单。

        - available_tools: ToolRegistry 中已注册的全部工具名
        - available_agents: AGENT_REGISTRY 中除 master 外的全部子 Agent

        master 架构下，master 可委派所有子 Agent，因此返回全部非 master agent。
        """
        available_tools: list[str] = []
        available_agents: list[str] = []

        # 工具清单
        try:
            from app.tools.registry import registry as tool_registry

            available_tools = tool_registry.list_registered_tools()
        except Exception as e:
            logger.warning("tool_context_build_failed", error=str(e))

        # 子 Agent 清单（排除 master 自身，master 不能委派给自己）
        try:
            from app.agents import AGENT_REGISTRY

            available_agents = [key for key in AGENT_REGISTRY if key != "master"]
        except Exception as e:
            logger.warning("agent_list_build_failed", error=str(e))

        return available_tools, available_agents

    def _build_company_context(self, company_id: str) -> dict:
        """构建公司画像上下文。

        返回结构化 dict（company_name/brand_name/category/platforms），
        供下游 build_system_message 按 key 取用，与 chat._build_company_context_from_db 结构一致。
        不可用时返回空 dict，不阻塞主流程。

        注意:此处不通过 CompanyContextBus.get_context_for_agent 获取,
        因为后者返回 Layer1 文本(str),与 ContextPackage.company_context: dict 类型
        及下游 .get('company_name') 的 dict 访问方式不兼容。
        """
        if not company_id:
            return {}
        try:
            import json

            from app.database import db as db_proxy
            from app.database.models import Company as ORMCompany

            with db_proxy.get_session() as session:
                company = session.query(ORMCompany).filter(ORMCompany.id == int(company_id)).first()
                if company:
                    return {
                        "company_name": company.name,
                        "brand_name": getattr(company, "brand_name", "") or "",
                        "category": getattr(company, "category", "") or "",
                        "platforms": json.loads(company.platforms_json)
                        if company.platforms_json
                        else [],
                    }
        except (ValueError, TypeError):
            logger.debug("company_context_invalid_id", company_id=company_id)
        except Exception as e:
            logger.warning("company_context_unavailable", error=str(e))
        return {}

    def parse_tool_result(
        self, tool_name: str, output: object
    ) -> ParsedToolResult:  # 单一解析入口，用于即时解析场景
        """解析工具执行结果（供后续调用）"""
        return self._tool_result_parser.parse(tool_name, output)

    def parse_tool_results(
        self, results: list[tuple[str, object]]
    ) -> list[ParsedToolResult]:  # 批量解析减少调用开销
        """批量解析工具执行结果"""
        parsed = []
        for tool_name, output in results:
            parsed.append(self._tool_result_parser.parse(tool_name, output))
        return parsed
