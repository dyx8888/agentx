"""LlamaIndex 对照向量检索器  # 用主流框架 LlamaIndex 实现一份与自研 HybridRetriever 可互换的检索器
LlamaIndex 对照向量检索器实现

目的：覆盖 JD 要求的"熟悉 LlamaIndex"。项目自研的 HybridRetriever 走 BM25+向量+RRF+Reranker
四阶段流水线，本文件用 LlamaIndex 标准框架实现一份对照版，证明同时掌握"自研"和"标准框架"两条路线。

设计要点：
- 复用现有 EmbeddingService（不重复造轮子），通过 LlamaIndex 的 BaseEmbedding 适配器包装
- 复用现有 Milvus 部署，通过 llama_index.vector_stores.milvus.MilvusVectorStore 接入
- 接口与 VectorRetriever 对齐：add_documents / search / delete / query，保证可互换
- 多租户：用 Milvus 的 metadata filter（MetadataFilters）按 company_id 隔离
- 熔断器保护：复用 core/circuit_breaker，失败降级返回空列表 + 日志，绝不崩溃

LlamaIndex 核心概念对照（详见 docs/求职准备/LlamaIndex对照实现说明.md）：
- Node        ≈ 自研的文档切片（一段文本 + metadata）
- Index       ≈ 自研的 Milvus Collection + embedding 索引
- Retriever   ≈ 自研的 VectorRetriever.search
- QueryEngine ≈ 自研的 Retriever + Reranker 组合（这里仅用 Retriever，不接 LLM 生成）
- Postprocessor ≈ 自研的 RRF/Reranker（本实现用 MetadataFilters 做多租户过滤）

安装方式（未在 requirements.txt 中声明，由依赖管理 agent 统一加入）：
    pip install llama-index llama-index-vector-stores-milvus
"""

import os  # 读取 Milvus 连接配置环境变量

from app.core.logging import get_logger  # 结构化日志，与自研版保持一致

logger = get_logger(__name__)  # 模块级 logger

# ── LlamaIndex 可选依赖导入 ──────────────────────────────────────
# 借鉴 graph_rag.py 的 NETWORKX_AVAILABLE 模式：未安装时降级为 stub + 警告，不影响其余模块加载
try:  # llama_index 是可选依赖，未安装时整个模块降级
    from llama_index.core import VectorStoreIndex  # Index 容器 + Document 文档对象
    from llama_index.core.embeddings import (
        BaseEmbedding,  # 自定义 embedding 的抽象基类，需实现 _get_text_embedding 等方法
    )
    from llama_index.core.retrievers import VectorIndexRetriever  # LlamaIndex 标准向量检索器
    from llama_index.core.schema import (
        QueryBundle,  # 查询包装对象，可携带 embedding
        TextNode,  # Node 是 LlamaIndex 的最小检索单元
    )
    from llama_index.vector_stores.milvus import MilvusVectorStore  # LlamaIndex 官方 Milvus 适配器

    LLAMAINDEX_AVAILABLE = True  # 标记可用，后续类定义走真实实现分支
except ImportError:  # llama_index 未安装时的降级策略
    LLAMAINDEX_AVAILABLE = False  # 标记不可用
    logger.warning(  # 一次性告警，启动时即可发现功能缺失
        "llama_index_not_installed_llamaindex_retriever_disabled",
        hint="安装方式: pip install llama-index llama-index-vector-stores-milvus",
    )

# 复用自研版的 SearchResult 数据结构，保证返回格式与 HybridRetriever 完全一致（可互换的关键）
from .hybrid_retriever import SearchResult  # noqa: E402  统一数据结构，避免上层调用方感知后端差异

# ═══════════════════════════════════════════════════════════════
# EmbeddingService 适配器：把现有 EmbeddingService 包装成 LlamaIndex 的 BaseEmbedding
# ═══════════════════════════════════════════════════════════════
# 这是"不重复造轮子"的关键：LlamaIndex 自带 OpenAI/HuggingFace embedding，但项目已有
# EmbeddingService（含本地/API 双模式 + 缓存 + 降级）。通过适配器模式复用，避免双套 embedding 逻辑。
if LLAMAINDEX_AVAILABLE:  # 仅在 LlamaIndex 可用时定义真实适配器类

    class EmbeddingServiceAdapter(BaseEmbedding):  # 继承 LlamaIndex 的 BaseEmbedding
        """把现有 EmbeddingService 包装成 LlamaIndex BaseEmbedding 的适配器。

        LlamaIndex 的检索流程会调用 _get_text_embedding（建索引时）和 _get_query_embedding
        （检索时）两个钩子，本适配器把这两个钩子委托给现有 EmbeddingService，从而：
        - 复用项目已有的本地/API 双模式 embedding
        - 复用 LRU + Redis 双重缓存
        - 复用降级策略（API 失败 → 本地 → 空向量）
        """

        def __init__(self, embedding_service):  # 接收已初始化的 EmbeddingService 实例
            # 先暂存 service，再调父类 __init__（BaseEmbedding 会在 __init__ 中读 model_name 等）
            self._svc = embedding_service  # 复用的现有 embedding 服务
            super().__init__(  # 向 LlamaIndex 声明模型名和维度，便于日志和调试
                model_name=getattr(embedding_service, "model_name", "embedding-service"),
            )

        def _get_query_embedding(self, query: str) -> list[float]:  # LlamaIndex 检索时调用
            # 查询向量化：委托给 EmbeddingService.encode_single
            vec = self._svc.encode_single(query)  # 返回 np.ndarray
            return vec.tolist()  # LlamaIndex 需要 list[float]

        def _get_text_embedding(self, text: str) -> list[float]:  # LlamaIndex 建索引时调用（单条）
            # 文档向量化：委托给 EmbeddingService.encode_single（query 和 text 走同一模型）
            vec = self._svc.encode_single(text)  # 返回 np.ndarray
            return vec.tolist()  # 转 list[float]

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:  # 批量建索引时调用
            # 批量向量化：委托给 EmbeddingService.encode，比逐条调用效率高
            mat = self._svc.encode(texts)  # 返回 np.ndarray, shape=(n, dim)
            if mat.size == 0:  # 空输入保护
                return []
            return mat.tolist()  # 转 list[list[float]]

        # ── 异步版本：LlamaIndex 异步检索时会调用 ──
        async def _aget_query_embedding(self, query: str) -> list[float]:  # 异步查询向量化
            vec = await self._svc.encode_async([query])  # 走 API 异步批量编码
            if vec.size == 0:  # 降级返回空
                return []
            return vec[0].tolist()  # 取第一条

        async def _aget_text_embedding(self, text: str) -> list[float]:  # 异步单条向量化
            vec = await self._svc.encode_async([text])  # 异步批量编码
            if vec.size == 0:
                return []
            return vec[0].tolist()

        async def _aget_text_embeddings(
            self, texts: list[str]
        ) -> list[list[float]]:  # 异步批量向量化
            mat = await self._svc.encode_async(texts)  # 一次 API 调用编码多文本
            if mat.size == 0:
                return []
            return mat.tolist()

else:  # llama_index 未安装时定义 stub，保证模块可被 import（类定义存在但实例化时降级）

    class EmbeddingServiceAdapter:  # type: ignore[no-redef]  # stub 版本，仅占位
        """llama_index 未安装时的 stub 占位类，实例化时记录警告。"""

        def __init__(self, *args, **kwargs):  # 任意参数都接受
            logger.warning("llamaindex_adapter_unavailable_stub_only")


# ═══════════════════════════════════════════════════════════════
# LlamaIndexRetriever：对照向量检索器主类
# ═══════════════════════════════════════════════════════════════
class LlamaIndexRetriever:
    """LlamaIndex 对照向量检索器。

    用 LlamaIndex 的 VectorStoreIndex + MilvusVectorStore 实现与自研 VectorRetriever
    相同的接口（add_documents / search / delete / query），保证可互换。

    与自研 HybridRetriever 的差异：
    - 仅做纯向量检索（无 BM25、无 RRF、无 Reranker），用于对照"标准框架"的基线效果
    - 用 LlamaIndex 的 MetadataFilters 实现多租户隔离（自研版用 Milvus expr 字符串）
    - 用 LlamaIndex 的 VectorIndexRetriever 封装检索逻辑（自研版直接调 Collection.search）

    Args:
        company_id: 公司 ID，用于多租户隔离（与 HybridRetriever 一致）
        collection_name: Milvus Collection 名，默认读环境变量
    """

    def __init__(self, company_id: str = "default", collection_name: str = None):  # 按公司隔离
        self.company_id = company_id  # 公司 ID，检索时作为 metadata filter 隔离数据
        self.collection_name = (
            collection_name
            or os.getenv(  # Collection 名，与自研版共用同一 Collection
                "MILVUS_COLLECTION", "company_knowledge"
            )
        )
        self._index = None  # LlamaIndex VectorStoreIndex 实例（懒加载）
        self._vector_store = None  # LlamaIndex MilvusVectorStore 实例（懒加载）
        self._retriever = None  # LlamaIndex VectorIndexRetriever 实例（懒加载）
        self._embedding_adapter = None  # EmbeddingService 适配器（懒加载）
        self._initialized = False  # 是否已完成初始化
        # 熔断器：复用 core/circuit_breaker，保护 Milvus 检索（与自研版同等保护力度）
        # 延迟导入避免循环依赖，且仅在 LlamaIndex 可用时才需要熔断器
        self._breaker = None  # 延迟初始化

    # ── 懒加载工具方法 ──────────────────────────────────────────
    def _get_breaker(self):  # 获取熔断器实例
        if self._breaker is None:  # 首次使用时创建
            from app.core.circuit_breaker import get_circuit_breaker  # 延迟导入

            # 熔断阈值 5 次失败，30 秒恢复，与 embedding_api 熔断器参数一致
            self._breaker = get_circuit_breaker(
                "llamaindex_milvus", failure_threshold=5, recovery_timeout=30
            )
        return self._breaker

    def _get_embedding_service(self):  # 复用现有 EmbeddingService 单例
        if self._embedding_adapter is None:  # 首次使用时初始化
            from .embedding_service import get_embedding_service  # 延迟导入避免循环依赖

            svc = get_embedding_service()  # 获取全局单例（含缓存、降级逻辑）
            self._embedding_adapter = EmbeddingServiceAdapter(svc)  # 用适配器包装
        return self._embedding_adapter

    # ── 初始化：构建 MilvusVectorStore + VectorStoreIndex ──
    def _ensure_initialized(self) -> bool:  # 懒加载模式，首次调用才连接 Milvus
        if self._initialized:  # 已初始化则跳过
            return True
        if not LLAMAINDEX_AVAILABLE:  # llama_index 未安装时直接返回 False
            logger.warning("llamaindex_not_available_skip_init")
            return False

        try:  # Milvus 连接可能失败
            host = os.getenv("MILVUS_HOST", "localhost")  # 与自研版读取相同环境变量
            port = os.getenv("MILVUS_PORT", "19530")  # Milvus 默认 gRPC 端口
            # 构造 LlamaIndex 的 MilvusVectorStore —— 对应 LlamaIndex 的 VectorStore 抽象
            # overwrite=False：不覆盖已有 Collection，与自研版共用 company_knowledge
            self._vector_store = MilvusVectorStore(  # LlamaIndex 概念：VectorStore（向量存储后端）
                uri=f"http://{host}:{port}",  # LlamaIndex 用 uri 而非 host+port
                collection_name=self.collection_name,
                dim=self._infer_dim(),  # 向量维度，与 embedding 服务对齐
                overwrite=False,  # 不覆盖，复用自研版已建好的 Collection
            )
            embed = self._get_embedding_service()  # 获取 embedding 适配器
            # 构建 VectorStoreIndex —— 对应 LlamaIndex 的 Index 概念（索引容器）
            # from_vector_store：用已有 Milvus Collection 构建 Index，不重新灌数据
            self._index = VectorStoreIndex.from_vector_store(  # LlamaIndex 概念：Index
                vector_store=self._vector_store,
                embed_model=embed,  # 注入复用的 embedding 适配器
            )
            # 构建检索器 —— 对应 LlamaIndex 的 Retriever 概念
            # similarity_top_k 是默认召回数，search 时可被 top_k 参数覆盖
            self._retriever = VectorIndexRetriever(  # LlamaIndex 概念：Retriever
                index=self._index,
                similarity_top_k=20,  # 默认召回 20 条，与自研版的 top_k*2 相近
            )
            self._initialized = True  # 标记已初始化
            logger.info(  # 记录初始化成功
                "llamaindex_retriever_initialized",
                company_id=self.company_id,
                collection=self.collection_name,
            )
            return True
        except Exception as e:  # 初始化失败（Milvus 不可达 / llama_index 内部错误）
            logger.warning(  # 告警但不崩溃，后续操作降级返回空
                "llamaindex_init_failed_degrade_empty",
                error=str(e),
                company_id=self.company_id,
            )
            return False

    def _infer_dim(self) -> int:  # 推断向量维度，与 embedding 服务保持一致
        # 复用 EmbeddingService 的 dimension 属性，避免维度不匹配导致 Milvus 写入失败
        try:
            from .embedding_service import get_embedding_service  # 延迟导入

            return get_embedding_service().dimension  # 本地/API 模式都能推断出正确维度
        except Exception:  # 推断失败时回退到本地默认维度
            return 512  # 与 EmbeddingService._fallback_embedding 的默认维度一致

    # ── 接口方法：add_documents / search / delete / query ──
    # 与自研 VectorRetriever 接口对齐，保证上层可互换调用
    def add_documents(self, documents: list[dict]) -> bool:  # 灌入文档（对应自研 index_documents）
        """灌入文档到 LlamaIndex 索引。

        Args:
            documents: [{'id': str, 'content': str, 'metadata': dict}, ...]
                       格式与 HybridRetriever.index_documents 完全一致

        Returns:
            True 表示成功，False 表示降级（Milvus 不可用或 llama_index 未安装）
        """
        if not LLAMAINDEX_AVAILABLE:  # 未安装 llama_index 直接降级
            logger.warning("llamaindex_add_documents_unavailable")
            return False
        if not documents:  # 空列表直接返回
            return True
        if not self._ensure_initialized():  # 确保已初始化，失败则降级
            return False

        try:  # 灌入可能失败（Milvus 写入异常）

            def _do_insert():  # 同步插入函数，交给熔断器保护
                # 把文档转为 LlamaIndex 的 TextNode —— 对应 LlamaIndex 的 Node 概念
                # Node 是 LlamaIndex 的最小检索单元，等价于自研版的"一条 Milvus 记录"
                nodes = []
                for d in documents:  # 逐条构造 Node
                    doc_id = d.get("id", "")  # 文档 ID
                    content = d.get("content", "")  # 文本内容
                    metadata = dict(d.get("metadata", {}))  # 深拷贝避免污染原数据
                    metadata["company_id"] = self.company_id  # 注入 company_id，多租户隔离的关键
                    metadata["doc_id"] = doc_id  # 保留 doc_id 便于删除
                    # TextNode：LlamaIndex 的核心数据结构，含 text + embedding + metadata
                    node = TextNode(  # LlamaIndex 概念：Node
                        text=content,
                        metadata=metadata,
                        id_=doc_id if doc_id else None,  # 用 doc_id 作为 Node ID，便于按 ID 删除
                    )
                    nodes.append(node)
                # 通过 VectorStoreIndex 的 insert_nodes 批量写入 —— LlamaIndex 会自动调 embedding
                self._index.insert_nodes(nodes)  # LlamaIndex 概念：Index.insert_nodes
                return len(nodes)

            breaker = self._get_breaker()  # 获取熔断器
            count = breaker.call_sync(_do_insert)  # 受熔断器保护的同步调用
            logger.info(  # 记录成功
                "llamaindex_documents_added",
                count=count,
                company_id=self.company_id,
            )
            return True
        except Exception as e:  # 灌入失败：降级为空 + 日志，不抛异常
            logger.warning(  # 告警但不崩溃，符合"失败降级"约束
                "llamaindex_add_documents_failed_degrade",
                error=str(e),
                company_id=self.company_id,
            )
            return False

    def search(  # 检索主方法（对应自研 VectorRetriever.search）
        self,
        query: str,  # 查询文本
        top_k: int = 10,  # 返回数量
    ) -> list[SearchResult]:  # 返回与自研版相同的 SearchResult 列表
        """向量检索，返回与 HybridRetriever 相同格式的 SearchResult 列表。

        实现说明：
        - 用 LlamaIndex 的 VectorIndexRetriever 检索
        - 通过 MetadataFilters 做多租户过滤（company_id 隔离）
        - 把 LlamaIndex 的 NodeWithScore 转成自研的 SearchResult，保证可互换
        """
        if not LLAMAINDEX_AVAILABLE:  # 未安装直接降级返回空
            logger.warning("llamaindex_search_unavailable")
            return []
        if not self._ensure_initialized():  # 确保已初始化
            return []
        if not query:  # 空查询返回空
            return []

        try:  # 检索可能失败（Milvus 异常 / 熔断器开启）

            def _do_search():  # 同步检索函数，交给熔断器保护
                # 构造 QueryBundle —— LlamaIndex 概念：QueryBundle（查询包装，可携带 embedding）
                # 这里不预计算 embedding，让 LlamaIndex 内部调 embed_model
                bundle = QueryBundle(query_str=query)
                # 构造多租户过滤器 —— LlamaIndex 概念：MetadataFilters（后处理器）
                # 等价于自研版的 expr=f'company_id == "{self.company_id}"'，但用 LlamaIndex 标准方式
                from llama_index.core.vector_stores import (  # 延迟导入，避免模块加载期依赖
                    MetadataFilter,
                    MetadataFilters,
                )

                filters = MetadataFilters(  # LlamaIndex 概念：Postprocessor（元数据过滤）
                    filters=[
                        MetadataFilter(
                            key="company_id",
                            value=self.company_id,  # 只检索当前公司的文档
                            operator="==",  # 等值匹配
                        )
                    ]
                )
                # 执行检索 —— LlamaIndex 概念：Retriever.retrieve
                # retriever 在构造时已绑定 index，这里传 QueryBundle + filters
                # 注意：VectorIndexRetriever 的 filters 参数支持元数据过滤
                nodes = self._retriever.retrieve(  # 返回 list[NodeWithScore]
                    bundle,
                    filters=filters,  # 多租户隔离
                )
                return nodes

            breaker = self._get_breaker()  # 获取熔断器
            nodes = breaker.call_sync(_do_search)  # 受熔断器保护

            # 把 LlamaIndex 的 NodeWithScore 转成自研的 SearchResult —— 保证可互换的关键
            results: list[SearchResult] = []
            for node_with_score in nodes[:top_k]:  # 截断到 top_k
                node = node_with_score.node  # 取出 Node
                score = float(node_with_score.score or 0.0)  # 相似度分数
                metadata = dict(node.metadata or {})  # 取出 metadata
                results.append(
                    SearchResult(  # 构造与自研版一致的 SearchResult
                        content=node.get_content(),  # 文本内容
                        metadata=metadata,  # 元数据
                        vector_score=score,  # 向量分数（自研版非向量来源时为 0，这里都是向量来源）
                        rrf_score=score,  # LlamaIndex 无 RRF，直接用向量分数占位，保证排序字段有值
                        source="llamaindex_vector",  # 标记来源，便于排查
                        source_file=metadata.get("source_file", ""),  # 源文件名，对齐自研版字段
                        chunk_index=metadata.get("chunk_index", 0),  # 切片序号，对齐自研版字段
                        source_page=metadata.get("source_page", 0),  # 源页码，对齐自研版字段
                    )
                )
            logger.info(  # 记录检索成功
                "llamaindex_search_done",
                query=query[:50],  # 截断避免日志过长
                top_k=top_k,
                returned=len(results),
                company_id=self.company_id,
            )
            return results
        except Exception as e:  # 检索失败：降级返回空列表 + 日志，绝不崩溃
            logger.warning(  # 告警但不抛异常，符合"失败降级"约束
                "llamaindex_search_failed_degrade_empty",
                error=str(e),
                query=query[:50],
                company_id=self.company_id,
            )
            return []

    async def query(  # LlamaIndex QueryEngine 风格的查询接口（async，对齐项目 async 风格）
        self,
        query: str,  # 查询文本
        top_k: int = 10,  # 返回数量
    ) -> list[SearchResult]:  # 返回格式与 search 一致
        """异步查询接口（LlamaIndex QueryEngine 风格）。

        与 search 的区别：
        - 异步：走 LlamaIndex 的 aretrieve，适合高并发场景
        - 命名 query：对应 LlamaIndex 的 QueryEngine 概念（本实现仅 Retriever，不接 LLM 生成）

        失败时同样降级返回空列表。
        """
        if not LLAMAINDEX_AVAILABLE:  # 未安装降级
            logger.warning("llamaindex_query_unavailable")
            return []
        if not self._ensure_initialized():  # 确保已初始化
            return []
        if not query:  # 空查询返回空
            return []

        try:  # 异步检索可能失败
            # 构造多租户过滤器（与 search 同逻辑，异步路径独立构造）
            from llama_index.core.vector_stores import (  # 延迟导入
                MetadataFilter,
                MetadataFilters,
            )

            filters = MetadataFilters(  # 多租户隔离
                filters=[
                    MetadataFilter(
                        key="company_id",
                        value=self.company_id,
                        operator="==",
                    )
                ]
            )
            bundle = QueryBundle(query_str=query)  # 查询包装对象

            # 异步检索函数，交给熔断器保护
            async def _do_aretrieve():  # 异步检索协程
                # LlamaIndex 概念：Retriever.aretrieve（异步版本）
                nodes = await self._retriever.aretrieve(
                    bundle,
                    filters=filters,
                )
                return nodes

            breaker = self._get_breaker()  # 获取熔断器
            nodes = await breaker.call(_do_aretrieve)  # 异步熔断调用

            # 转换结果（与 search 同逻辑）
            results: list[SearchResult] = []
            for node_with_score in nodes[:top_k]:
                node = node_with_score.node
                score = float(node_with_score.score or 0.0)
                metadata = dict(node.metadata or {})
                results.append(
                    SearchResult(
                        content=node.get_content(),
                        metadata=metadata,
                        vector_score=score,
                        rrf_score=score,
                        source="llamaindex_vector",
                        source_file=metadata.get("source_file", ""),
                        chunk_index=metadata.get("chunk_index", 0),
                        source_page=metadata.get("source_page", 0),
                    )
                )
            logger.info(
                "llamaindex_async_query_done",
                query=query[:50],
                top_k=top_k,
                returned=len(results),
                company_id=self.company_id,
            )
            return results
        except Exception as e:  # 异步检索失败：降级返回空
            logger.warning(
                "llamaindex_query_failed_degrade_empty",
                error=str(e),
                query=query[:50],
                company_id=self.company_id,
            )
            return []

    def delete(self, doc_id: str) -> bool:  # 删除文档（对应自研 delete_document）
        """按 doc_id 删除文档。

        使用 LlamaIndex 的 delete_ref_doc 或 MilvusVectorStore 的 delete 接口。

        Args:
            doc_id: 文档 ID

        Returns:
            True 表示成功，False 表示降级
        """
        if not LLAMAINDEX_AVAILABLE:  # 未安装降级
            logger.warning("llamaindex_delete_unavailable")
            return False
        if not self._ensure_initialized():  # 确保已初始化
            return False
        if not doc_id:  # 空 ID 直接返回
            return False

        try:  # 删除可能失败

            def _do_delete():  # 同步删除函数，交给熔断器保护
                # LlamaIndex 概念：Index.delete_ref_doc —— 按 ref_doc_id 删除所有关联 Node
                # 建索引时把 doc_id 作为 Node id_，这里按 id 删除
                self._index.delete_ref_doc(doc_id, delete_from_docstore=True)
                return True

            breaker = self._get_breaker()  # 获取熔断器
            breaker.call_sync(_do_delete)  # 受熔断器保护
            logger.info(  # 记录删除成功
                "llamaindex_document_deleted",
                doc_id=doc_id,
                company_id=self.company_id,
            )
            return True
        except Exception as e:  # 删除失败：降级返回 False + 日志
            logger.warning(  # 告警但不崩溃
                "llamaindex_delete_failed_degrade",
                error=str(e),
                doc_id=doc_id,
                company_id=self.company_id,
            )
            return False


# ═══════════════════════════════════════════════════════════════
# 模块级缓存 + 工厂函数（与自研版 get_hybrid_retriever 对齐）
# ═══════════════════════════════════════════════════════════════
_retriever_cache: dict[str, LlamaIndexRetriever] = {}  # 按 company_id 缓存单例


def get_llamaindex_retriever(company_id: str = "default") -> LlamaIndexRetriever:  # 工厂函数
    """获取或创建 LlamaIndexRetriever 单例（按 company_id 隔离）。

    与 get_hybrid_retriever 对齐，便于上层通过 RAG_FRAMEWORK 配置切换后端。
    """
    if company_id not in _retriever_cache:  # 缓存未命中
        _retriever_cache[company_id] = LlamaIndexRetriever(company_id)  # 创建并缓存
    return _retriever_cache[company_id]  # 返回单例
