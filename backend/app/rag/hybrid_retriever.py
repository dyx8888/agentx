"""  # HybridRAG 混合检索引擎，多路召回 + 融合排序
HybridRAG 混合检索引擎  # "混合" 的核心：BM25（关键词）+ 向量（语义）+ RRF（融合）+ Reranker（精排）
实现: BM25 关键词检索 + Milvus 向量检索 + RRF 融合 + Cross-Encoder Reranker  # 四阶段流水线：粗排 → 粗排 → 融合 → 精排
"""

import os  # 读取 Milvus 连接配置环境变量
from dataclasses import dataclass, field  # dataclass 用于 SearchResult 数据类

import numpy as np  # BM25 IDF 计算和向量运算

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


@dataclass  # 使用 dataclass 而非 dict，提供类型安全和 IDE 自动补全
class SearchResult:
    """搜索结果"""  # 统一的数据结构，BM25/向量/RRF/Rerank 结果都用此类
    content: str  # 文本内容
    metadata: dict = field(default_factory=dict)  # 元数据，使用 field 避免共享引用
    bm25_score: float = 0.0  # BM25 分数，非 BM25 来源时为 0
    vector_score: float = 0.0  # 向量相似度分数，非向量来源时为 0
    rrf_score: float = 0.0  # RRF 融合分数，最终排序的主要依据
    rerank_score: float | None = None  # Reranker 精排分数，None 表示未经过重排
    source: str = ""  # 检索来源：bm25/vector/hybrid
    source_file: str = ""  # 源文件名，用于引文标注
    chunk_index: int = 0  # 切片序号
    source_page: int = 0  # 源页码


class BM25Retriever:  # BM25 关键词检索引擎，Okapi BM25 算法
    """BM25 关键词检索引擎 (Okapi BM25)"""  # BM25 是对 TF-IDF 的改进，引入了文档长度归一化

    def __init__(self, k1: float = 1.5, b: float = 0.75):  # k1 控制词频饱和度，b 控制文档长度归一化力度
        self.k1 = k1  # 经典 BM25 参数，k1=1.5 平衡了词频的线性增长和饱和
        self.b = b  # b=0.75 对长文档做适度惩罚，避免长文档仅因篇幅占优
        self._documents: list[str] = []  # 原始文档列表
        self._doc_ids: list[str] = []  # 文档 ID 列表，与 _documents 一一对应
        self._doc_lengths: list[int] = []  # 每个文档的 token 数
        self._avgdl: float = 0.0  # 平均文档长度，BM25 公式中的分母
        self._idf: dict[str, float] = {}  # 每个词的 IDF 值
        self._doc_freqs: list[dict[str, int]] = []  # 每个文档的词频统计

    def _tokenize(self, text: str) -> list[str]:  # 分词：简单空格分割
        return text.lower().split()  # 小写化 + 空格分词，中文场景需要上游先做分词预处理

    def index(self, documents: list[str], doc_ids: list[str] = None):  # 构建 BM25 索引
        self._documents = documents  # 保存原始文档
        self._doc_ids = doc_ids or [str(i) for i in range(len(documents))]  # 未提供 ID 时自动生成
        self._doc_lengths = []  # 重置文档长度列表
        self._doc_freqs = []  # 重置词频列表

        df: dict[str, int] = {}  # 文档频率：每个词出现在多少文档中
        for doc in documents:  # 遍历每个文档
            tokens = self._tokenize(doc)  # 分词
            self._doc_lengths.append(len(tokens))  # 记录文档长度
            tf = {}  # 当前文档的词频
            for t in tokens:  # 统计词频
                tf[t] = tf.get(t, 0) + 1
            for t in set(tokens):  # 统计文档频率（用 set 去重，每个词在一个文档中只计一次）
                df[t] = df.get(t, 0) + 1
            self._doc_freqs.append(tf)  # 保存词频

        n = len(documents)  # 文档总数
        self._avgdl = sum(self._doc_lengths) / max(n, 1)  # 平均文档长度，max(n,1) 避免除零
        self._idf = {}  # 计算 IDF
        for term, freq in df.items():  # BM25 IDF 公式：log(1 + (N-n+0.5)/(n+0.5))
            self._idf[term] = np.log(1 + (n - freq + 0.5) / (freq + 0.5))  # 加 0.5 平滑，避免除零

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:  # BM25 检索
        query_tokens = self._tokenize(query)  # 查询分词
        scores = []  # (文档索引, 分数) 列表

        for i, (doc_len, tf) in enumerate(zip(self._doc_lengths, self._doc_freqs, strict=False)):  # 遍历每个文档
            score = 0.0  # 累积分数
            for t in query_tokens:  # 遍历查询词
                if t in self._idf:  # 只计算索引中存在的词
                    ttf = tf.get(t, 0)  # 词在文档中的频率
                    score += self._idf[t] * (  # BM25 公式核心
                        ttf * (self.k1 + 1)  # 词频部分，k1+1 是归一化因子
                        / (ttf + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl))  # 文档长度归一化
                    )
            if score > 0:  # 只保留有分数的文档
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)  # 按分数降序
        return scores[:top_k]  # 返回 top_k


class VectorRetriever:  # Milvus 向量检索引擎
    """Milvus 向量检索引擎"""  # 基于向量相似度的语义检索

    def __init__(self):  # 懒加载模式，首次 search 才连接 Milvus
        self._collection = None  # Milvus Collection 对象
        self._initialized = False  # 是否已初始化

    def _ensure_initialized(self):  # 确保 Milvus 已连接并使用
        if self._initialized:  # 已初始化则跳过
            return
        try:  # Milvus 连接可能失败
            from pymilvus import Collection, connections, utility  # 延迟导入
            host = os.getenv("MILVUS_HOST", "localhost")  # 从环境变量读取，支持不同部署环境
            port = int(os.getenv("MILVUS_PORT", "19530"))  # Milvus 默认 gRPC 端口
            collection_name = os.getenv("MILVUS_COLLECTION", "company_knowledge")  # Collection 名称

            connections.connect(host=host, port=port, timeout=3)  # 3 秒超时，快速失败
            if utility.has_collection(collection_name):  # 检查 Collection 是否存在
                self._collection = Collection(collection_name)  # 获取 Collection
                self._collection.load()  # 加载到内存，后续检索才有数据
            self._initialized = True  # 标记已初始化
        except ImportError:  # pymilvus 未安装
            logger.warning("pymilvus_not_installed_vector_disabled")  # 告警但不崩溃
        except Exception as e:  # 连接失败等
            logger.warning("milvus_connect_failed_vector_disabled", error=str(e))  # 记录详细错误

    def search(self, query_vector: np.ndarray, top_k: int = 20) -> list[tuple[str, float, str]]:  # 向量检索
        self._ensure_initialized()  # 确保已连接
        if self._collection is None:  # 未成功连接时返回空
            return []

        try:  # 检索可能失败
            search_params = {"metric_type": "IP", "params": {"nprobe": 10}}  # IP=内积(余弦相似度)，nprobe 控制搜索精度
            results = self._collection.search(  # 执行 ANN 搜索
                data=[query_vector.tolist()],  # Milvus 需要 list 格式
                anns_field="embedding",  # 向量字段名
                param=search_params,  # 搜索参数
                limit=top_k,  # 返回数量
                output_fields=["content", "metadata"],  # 额外返回的字段
            )
            formatted = []  # 格式化结果
            for hits in results:  # results 是 list[list[Hit]]，因为 data 是多个查询向量的列表
                for hit in hits:  # 遍历每个命中
                    formatted.append((  # (内容, 分数, 元数据)
                        hit.entity.get("content", ""),
                        hit.score,  # 相似度分数
                        hit.entity.get("metadata", ""),
                    ))
            return formatted  # 返回格式化结果
        except Exception as e:  # 检索异常
            logger.error("milvus_search_error", error=str(e))  # 记录错误
            return []  # 降级返回空


class CrossEncoderReranker:  # Cross-Encoder 精排，对粗排结果重排序
    """Cross-Encoder 精排"""  # Cross-Encoder 比 Bi-Encoder（向量检索）更准确，但更慢

    def __init__(self, model_name: str = None):  # 可选模型名
        self.model_name = model_name or os.getenv(  # 环境变量 > 默认值
            "RERANK_MODEL", "BAAI/bge-reranker-base"  # bge-reranker 是中文精排的 SOTA 模型
        )
        self._model = None  # 懒加载模型

    def _load(self):  # 加载 Reranker 模型
        if self._model is not None:  # 已加载则跳过
            return
        try:  # sentence-transformers 可能未安装
            from sentence_transformers import CrossEncoder  # 延迟导入
            self._model = CrossEncoder(self.model_name)  # 加载模型
            logger.info("reranker_loaded", model=self.model_name)  # 记录成功
        except ImportError:  # 未安装
            logger.warning("sentence_transformers_not_installed_reranker_disabled")  # 降级

    def rerank(self, query: str, documents: list[str], top_k: int = 10) -> list[tuple[int, float]]:  # 精排
        self._load()  # 确保模型已加载
        if self._model is None:  # 模型不可用时返回原始顺序
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]  # 返回 0 分，保持原始顺序

        pairs = [(query, doc) for doc in documents]  # 构造 (查询, 文档) 对
        scores = self._model.predict(pairs)  # Cross-Encoder 同时编码 query 和 doc，交互式建模
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)  # 按分数降序
        return ranked[:top_k]  # 返回 top_k


class HybridRetriever:  # 混合检索引擎，组合 BM25 + 向量 + RRF + Reranker
    """混合检索引擎: BM25 + 向量 + RRF + Reranker"""  # 四合一，每个公司独立实例

    def __init__(self, company_id: str = "default"):  # 按公司隔离
        self.company_id = company_id  # 公司 ID
        self.bm25 = BM25Retriever()  # BM25 检索器实例
        self.vector = VectorRetriever()  # 向量检索器实例
        self.reranker = CrossEncoderReranker()  # 精排器实例
        self._embedding_service = None  # 懒加载 embedding 服务
        self._documents: dict[str, dict] = {}  # 文档存储：doc_id → 文档 dict
        self._indexed = False  # 是否已索引

    def _get_embedding_service(self):  # 懒加载 EmbeddingService
        if self._embedding_service is None:  # 首次使用时加载
            from .embedding_service import get_embedding_service  # 延迟导入
            self._embedding_service = get_embedding_service()  # 获取全局单例
        return self._embedding_service

    def index_documents(self, documents: list[dict]):  # 批量索引文档
        """索引文档: [{'id': str, 'content': str, 'metadata': dict}, ...]"""  # 标准接口
        if not documents:  # 空列表直接返回
            return

        texts = [d["content"] for d in documents]  # 提取文本内容
        doc_ids = [d.get("id", str(i)) for i, d in enumerate(documents)]  # 提取或生成 ID

        self.bm25.index(texts, doc_ids)  # 构建 BM25 索引
        for d in documents:  # 保存文档到本地存储
            self._documents[d.get("id", str(documents.index(d)))] = d
        self._indexed = True  # 标记已索引

        emb_service = self._get_embedding_service()  # 获取 embedding 服务
        embeddings = emb_service.encode(texts)  # 批量向量化

        try:  # 写入 Milvus，失败不影响 BM25
            self.vector._ensure_initialized()  # 确保 Milvus 可用
            col = self.vector._collection  # 获取 Collection
            if col is not None:  # Milvus 可用时才写入
                data = []  # 构建写入数据
                for i, (doc_id, content, metadata) in enumerate(  # 逐条构造
                    zip(doc_ids, texts, [d.get("metadata", {}) for d in documents], strict=False)
                ):
                    import json  # 延迟导入
                    data.append({
                        "id": doc_id,  # 文档 ID
                        "content": content,  # 文本内容
                        "embedding": embeddings[i].tolist(),  # 向量转 list
                        "metadata": json.dumps(metadata) if metadata else "",  # JSON 序列化元数据
                        "company_id": self.company_id,  # 公司 ID 用于多租户隔离
                    })
                col.insert(data)  # 批量插入
                col.flush()  # 刷新确保数据持久化
        except Exception as e:  # Milvus 写入失败
            logger.warning("milvus_index_warning", error=str(e))  # 告警，不影响 BM25

    def search(  # 混合检索主方法
        self,
        query: str,  # 查询文本
        top_k: int = 10,  # 最终返回数量
        use_reranker: bool = True,  # 是否启用精排
        bm25_weight: float = 0.3,  # BM25 权重，0.3 意味着语义检索更重要
        vector_weight: float = 0.7,  # 向量权重，0.7 偏向语义理解
    ) -> list[SearchResult]:
        """混合检索"""  # 四阶段流水线
        emb_service = self._get_embedding_service()  # 获取 embedding 服务
        query_vector = emb_service.encode_single(query)  # 查询向量化

        bm25_results = self.bm25.search(query, top_k=top_k * 2)  # 第一阶段：BM25 检索，2 倍候选
        vector_results = self.vector.search(query_vector, top_k=top_k * 2)  # 第二阶段：向量检索，2 倍候选

        fused = self._rrf_fuse(bm25_results, vector_results, bm25_weight, vector_weight)  # 第三阶段：RRF 融合

        sorted_results = sorted(fused.values(), key=lambda x: x.rrf_score, reverse=True)  # 按 RRF 分数排序
        candidates = sorted_results[:top_k * 2]  # 取 2 倍候选进入精排

        if use_reranker and len(candidates) > 0:  # 第四阶段：Reranker 精排
            contents = [r.content for r in candidates]  # 提取候选文本
            reranked = self.reranker.rerank(query, contents, top_k=top_k)  # 精排
            final = []  # 构建最终结果
            for idx, score in reranked:  # 设置精排分数
                candidates[idx].rerank_score = float(score)
                final.append(candidates[idx])
            return final  # 返回精排结果

        return candidates[:top_k]  # 无精排时返回 RRF 排序结果

    def _rrf_fuse(  # RRF (Reciprocal Rank Fusion) + 加权融合
        self,
        bm25_results: list[tuple[int, float]],  # BM25 结果：(文档索引, 分数)
        vector_results: list[tuple[str, float, str]],  # 向量结果：(内容, 分数, 元数据)
        bm25_weight: float = 0.3,  # BM25 权重
        vector_weight: float = 0.7,  # 向量权重
    ) -> dict[str, SearchResult]:
        """RRF (Reciprocal Rank Fusion) + 加权融合"""  # 核心：用排名倒数做加权融合，规避不同来源分数不可比的问题
        rrf_k = 60  # RRF 常数，经典值 60，平衡高位和低位排名的权重
        fused: dict[str, SearchResult] = {}  # 融合结果 dict

        for rank, (doc_idx, bm25_score) in enumerate(bm25_results):  # 处理 BM25 结果
            doc_id = self.bm25._doc_ids[doc_idx]  # 获取文档 ID
            content = self.bm25._documents[doc_idx]  # 获取文档内容
            metadata = self._documents.get(doc_id, {}).get("metadata", {})  # 获取元数据
            rrf_bm25 = 1.0 / (rrf_k + rank + 1)  # RRF 公式：1/(k+排名)
            fused[doc_id] = SearchResult(  # 创建结果对象
                content=content,
                metadata=metadata,
                bm25_score=bm25_score,
                rrf_score=bm25_weight * rrf_bm25,  # 加权 RRF 分数
                source="bm25",
            )

        for rank, (content, vec_score, raw_metadata) in enumerate(vector_results):  # 处理向量结果
            import json  # 延迟导入
            metadata = {}  # 解析元数据
            try:  # JSON 可能非法
                if raw_metadata:
                    metadata = json.loads(raw_metadata)
            except (json.JSONDecodeError, TypeError):  # 解析失败
                pass  # 静默跳过，使用空 metadata

            candidate_id = f"vec_{rank}"  # 向量结果 ID：vec_排名
            rrf_vec = 1.0 / (rrf_k + rank + 1)  # RRF 分数

            if candidate_id in fused:  # BM25 和向量都有此文档：hybrid 来源
                fused[candidate_id].vector_score = vec_score  # 补充向量分数
                fused[candidate_id].rrf_score += vector_weight * rrf_vec  # 累加向量 RRF 分数
                fused[candidate_id].source = "hybrid"  # 标记为混合来源
            else:  # 仅向量检索命中
                fused[candidate_id] = SearchResult(  # 创建新结果
                    content=content,
                    metadata=metadata,
                    vector_score=vec_score,
                    rrf_score=vector_weight * rrf_vec,
                    source="vector",
                )

        return fused  # 返回融合后的结果


_retriever_cache: dict[str, HybridRetriever] = {}  # 模块级缓存，按 company_id 存储单例


def get_hybrid_retriever(company_id: str = "default") -> HybridRetriever:  # 工厂函数
    if company_id not in _retriever_cache:  # 缓存未命中
        _retriever_cache[company_id] = HybridRetriever(company_id)  # 创建并缓存
    return _retriever_cache[company_id]  # 返回单例
