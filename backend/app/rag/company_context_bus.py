"""# CompanyContextBus 模块，企业上下文总线，三层架构的核心调度器
CompanyContextBus - 企业上下文总线  # "总线" 设计模式：统一的数据通道，各层数据通过总线汇聚和分发
三层数据架构:  # 分层原因：静态资料、动态知识、经验记忆的生命周期和更新频率完全不同，需要解耦管理
  Layer 1: 公司基础资料 (PostgreSQL, 结构体注入)  # 静态数据，直接从数据库读取，不需要检索
  Layer 2: 公司知识库 (Milvus, RAG 检索 + 手动维护)  # 半结构化知识，需要语义检索，支持手动增删
  Layer 3: 公司经验记忆 (Milvus, Agent 完成后自动写入摘要)  # 动态经验，自动积累，通过睡眠巩固去重
"""

import json  # 用于序列化 metadata 中的 tags 等复杂字段到 Milvus
import os
import hashlib
import threading  # get_company_context_bus 单例锁,保护 check-then-act 免遭竞态
from dataclasses import dataclass, field  # dataclass 减少样板代码，field 用于可变默认值避免共享引用
from datetime import datetime  # 记录知识添加和经验记录的时间戳，用于后续的时间衰减排序

import numpy as np  # 用于睡眠巩固中的向量相似度计算和去重

from app.core.logging import get_logger  # 结构化日志，追踪数据注入和检索的完整链路

logger = get_logger(__name__)  # 模块级 logger，按 company_id 区分日志上下文

RAG_CHUNKER_MODE_RECURSIVE = "recursive"
RAG_CHUNKER_MODE_SMART = "smart"
RAG_CHUNKER_ALLOWED_MODES = {RAG_CHUNKER_MODE_RECURSIVE, RAG_CHUNKER_MODE_SMART}
STRUCTURED_SUPPLEMENT_SERVICE_HINTS = (
    "f_service",
    "qpack_service",
    "qpack_05",
    "05_",
    "service",
    "after_sales",
    "sop",
    "售后",
    "客服",
)
STRUCTURED_SUPPLEMENT_CONTENT_HINTS = (
    "f_content",
    "qpack_content",
    "qpack_07",
    "07_",
    "content",
    "script",
    "copy",
    "内容",
    "内容规范",
    "内容素材",
    "口播",
    "脚本",
    "素材",
    "短视频",
)


def _resolve_rag_chunker_mode() -> str:
    """Resolve ingestion chunker mode with recursive as the safe fallback."""
    from app.core import config

    mode = str(getattr(config, "RAG_CHUNKER_MODE", RAG_CHUNKER_MODE_RECURSIVE) or "").strip().lower()
    if mode in RAG_CHUNKER_ALLOWED_MODES:
        return mode
    logger.warning("rag_chunker_mode_invalid_fallback", fallback_mode=RAG_CHUNKER_MODE_RECURSIVE)
    return RAG_CHUNKER_MODE_RECURSIVE


def _build_chunk_id(source_file: str, chunk_index: int, content: str) -> str:
    seed = f"{source_file}:{chunk_index}:{content[:80]}"
    return hashlib.md5(seed.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass  # 使用 dataclass 而非普通类，因为 CompanyProfile 本质是数据容器，不需要复杂行为
class CompanyProfile:
    """Layer 1: 公司基础资料"""  # 静态数据，极少变动，直接从数据库加载

    company_name: str = ""  # 公司名称，空字符串默认值避免 None 检查
    industry: str = ""  # 行业分类，用于 Prompt 中的行业背景描述
    brand_description: str = ""  # 品牌描述，帮助 LLM 理解品牌定位
    target_audience: str = ""  # 目标受众，用于内容运营和营销策略的上下文
    product_categories: list[str] = field(
        default_factory=list
    )  # 使用 field(default_factory=list) 而非 =[]，防止所有实例共享同一个列表
    core_products: list[dict] = field(
        default_factory=list
    )  # 核心产品列表，dict 格式存储产品名称和描述
    brand_voice: str = ""  # 品牌调性，决定内容生成的语气和风格
    competitors: list[str] = field(default_factory=list)  # 竞品列表，用于品牌商务和选品分析
    usp: str = ""  # 独特卖点(Unique Selling Proposition)，营销策略的核心
    social_media_accounts: dict[str, str] = field(
        default_factory=dict
    )  # 社媒账号映射，用于跨平台内容策略

    def to_context_string(self) -> str:  # 将结构化数据转为 LLM 可读的文本格式
        parts = [  # 逐段拼接，确保格式整洁
            "【公司基础信息】",  # 用中文方括号标记，在 Prompt 中视觉上清晰分隔
            f"公司名称: {self.company_name}",
            f"行业: {self.industry}",
            f"品牌描述: {self.brand_description}",
            f"目标受众: {self.target_audience}",
            f"品牌调性: {self.brand_voice}",
            f"独特卖点(USP): {self.usp}",
        ]
        if self.product_categories:  # 只在有数据时才添加，避免空字段占用 Prompt 空间
            parts.append(f"产品类目: {', '.join(self.product_categories)}")
        if self.core_products:  # 核心产品用列表格式展示，便于 LLM 解析
            parts.append("核心产品:")
            for p in self.core_products:
                parts.append(f"  - {p.get('name', '')}: {p.get('description', '')}")
        if self.competitors:  # 竞品信息，品牌商务 Agent 的关键参考
            parts.append(f"竞品: {', '.join(self.competitors)}")
        if self.social_media_accounts:  # 社媒账号，用于跨平台运营策略
            accounts = [f"{k}: {v}" for k, v in self.social_media_accounts.items()]
            parts.append(f"社媒账号: {', '.join(accounts)}")
        return "\n".join(parts)  # 换行分隔，清晰可读


class CompanyContextBus:  # 企业上下文总线，三层架构的中央调度器
    """企业上下文总线"""  # 设计理念：集中管理三层数据，对外提供统一接口

    def __init__(self, company_id: str = "default"):  # company_id 用于多租户数据隔离
        self.company_id = company_id  # 标识当前总线所属的公司
        self._profile: CompanyProfile | None = None  # 懒加载的 Layer1 缓存，None 表示尚未加载
        self._knowledge_indexed = False  # 标识知识库是否已建立索引，用于判断是否需要重建

    # ═══ Layer 1: 公司基础资料 ═══  # 静态数据层，从 PostgreSQL 加载，极少变动

    def set_profile(self, profile: CompanyProfile):  # 手动设置公司资料，覆盖数据库加载的结果
        """设置公司基础资料"""  # 允许外部覆盖，用于管理后台更新后的即时生效
        self._profile = profile  # 直接替换，不做增量合并
        logger.info("company_profile_set", company_id=self.company_id)  # 记录操作审计

    def get_profile(self) -> CompanyProfile | None:  # 获取公司资料，优先返回缓存
        if self._profile is None:  # 缓存未命中时从数据库加载
            self._load_profile_from_db()  # 懒加载策略：首次访问时才查询数据库
        return self._profile  # 可能仍然为 None（数据库中也无记录）

    def _load_profile_from_db(self):  # 从 PostgreSQL 加载公司资料，私有方法不对外暴露
        """从 PostgreSQL 加载公司资料"""  # 设计为私有方法，防止外部直接调用破坏缓存一致性
        try:  # 数据库查询可能失败，需要捕获异常防止系统崩溃
            from app.database import db  # 延迟导入避免循环依赖，database 模块可能在 app 层

            company = (
                db.get_company(int(self.company_id)) if self.company_id.isdigit() else None
            )  # 只有纯数字 ID 才查询数据库，default 等非数字 ID 跳过
            if company:  # 数据库有记录时才构建 Profile
                self._profile = CompanyProfile(  # 仅填充数据库有字段的三个属性
                    company_name=getattr(
                        company, "name", ""
                    ),  # 使用 getattr 安全取值，避免属性缺失导致异常
                    industry=getattr(company, "industry", ""),
                    brand_description=getattr(company, "description", ""),
                )
        except Exception as e:  # 数据库不可用时的降级策略
            logger.warning(
                "profile_load_failed", error=str(e)
            )  # warning 级别，因为系统仍可运行但缺少上下文

    def get_layer1_context(self) -> str:  # 获取 Layer1 的文本格式上下文
        """获取 Layer 1 上下文（直接注入到 System Prompt）"""  # Layer1 通常直接拼接到 System Prompt 开头
        profile = self.get_profile()  # 触发懒加载
        if profile:  # 有资料才返回，否则返回空字符串
            return profile.to_context_string()  # 转为 LLM 可读的文本格式
        return ""  # 空字符串表示无数据，调用方可以安全拼接

    def get_context_for_agent(self, agent_key: str) -> str:  # 为指定 Agent 获取上下文
        """获取指定 Agent 的上下文（Layer 1 公司资料）"""  # 当前所有 Agent 共享同一份 Layer1 资料
        return self.get_layer1_context()  # 直接复用 Layer1，未来可按 agent_key 做差异化过滤

    # ═══ Layer 2: 公司知识库 ═══  # 半结构化知识层，支持 RAG 检索和手动增删

    def add_knowledge(
        self, content: str, metadata: dict = None, doc_id: str = None
    ):  # 手动添加知识条目
        """添加知识到知识库"""  # 知识添加后同时写入向量索引以支持检索
        import uuid  # 延迟导入，只在需要时加载

        from .hybrid_retriever import get_hybrid_retriever  # 延迟导入，避免循环依赖

        doc_id = doc_id or uuid.uuid4().hex[:12]  # 自动生成 12 位唯一 ID，足够短且冲突概率低
        metadata = metadata or {}  # 避免后续操作遇到 None
        metadata["company_id"] = self.company_id  # 强制注入 company_id 实现多租户隔离
        metadata["layer"] = "knowledge"  # 标记数据层级，后续检索时可以按 layer 过滤
        metadata["created_at"] = (
            datetime.utcnow().isoformat()
        )  # UTC 时间避免时区问题，ISO 格式便于解析

        retriever = get_hybrid_retriever(self.company_id)  # 获取公司专属的混合检索器
        retriever.index_documents(
            [
                {  # 包装为列表格式，满足 index_documents 的批量接口
                    "id": doc_id,
                    "content": content,
                    "metadata": metadata,
                }
            ]
        )
        logger.info("knowledge_added", company_id=self.company_id, doc_id=doc_id)  # 审计日志

        self._schedule_graph_entity_extraction(content)

        return doc_id  # 返回文档 ID，调用方可以用于后续的删除或更新

    def _schedule_graph_entity_extraction(self, content: str) -> None:
        """Run optional GraphRAG entity extraction without blocking uploads."""
        mode = os.getenv("GRAPH_RAG_DYNAMIC_EXTRACTION_MODE", "async").strip().lower()
        if mode in {"0", "false", "no", "off", "disabled"}:
            logger.info("graph_entity_extraction_disabled", company_id=self.company_id)
            return

        def _extract() -> None:
            try:
                from .graph_rag import get_graph_rag  # 延迟导入

                graph_rag = get_graph_rag()  # 全局图谱实例
                graph_rag.add_dynamic_entities(content)  # 使用 LLM 从文本中提取实体和关系
            except Exception as e:  # 图谱提取失败不应影响知识入库的主流程
                logger.debug(
                    "graph_entity_extraction_skipped", error=str(e)
                )  # debug 级别，因为这是辅助功能

        if mode == "sync":
            _extract()
            return

        thread = threading.Thread(
            target=_extract,
            name=f"graph-rag-extract-{self.company_id}",
            daemon=True,
        )
        thread.start()
        logger.info("graph_entity_extraction_scheduled", company_id=self.company_id, mode=mode)

    def search_knowledge(self, query: str, top_k: int = 5) -> list[dict]:  # 知识库语义检索
        """搜索公司知识库"""  # 返回的是结构化 dict 列表，而非原始 SearchResult 对象
        from .hybrid_retriever import get_hybrid_retriever  # 延迟导入

        retriever = get_hybrid_retriever(self.company_id)  # 获取公司专属检索器
        results = retriever.search(query, top_k=top_k)  # 混合检索(BM25+向量+RRF+Reranker)
        results = [r for r in results if self._is_relevant_knowledge_result(r)]
        return [  # 将 SearchResult 对象转为简化的 dict，隐藏内部实现细节
            {
                "content": r.content,  # 文本内容
                "metadata": r.metadata,  # 原始元数据
                "score": r.rerank_score or r.rrf_score,  # 优先使用 rerank 分数，回退到 RRF 分数
                "source": r.source,  # 检索来源：bm25/vector/hybrid
                "bm25_score": r.bm25_score,
                "vector_score": r.vector_score,
                "rrf_score": r.rrf_score,
                "rerank_score": r.rerank_score,
                "source_file": r.source_file,  # 原始文件名
                "chunk_index": r.chunk_index,  # 切片序号
                "source_page": r.source_page,  # 原始页码
            }
            for r in results
        ]

    @staticmethod
    def _is_relevant_knowledge_result(result) -> bool:
        """Filter weak vector-only matches before they force a RAG answer.

        RRF is a rank-fusion score, so a single unrelated Milvus hit can still
        get a high-looking rank score. Use the raw vector/BM25 signals as the
        relevance gate.
        """
        min_vector = float(os.getenv("RAG_MIN_VECTOR_SCORE", "0.55"))
        min_bm25 = float(os.getenv("RAG_MIN_BM25_SCORE", "0.05"))
        vector_score = float(getattr(result, "vector_score", 0.0) or 0.0)
        bm25_score = float(getattr(result, "bm25_score", 0.0) or 0.0)

        if CompanyContextBus._is_structured_metadata_supplement_evidence(result):
            return True
        if bm25_score >= min_bm25:
            return True
        if vector_score >= min_vector:
            return True

        metadata = getattr(result, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        logger.info(
            "knowledge_result_filtered_low_relevance",
            company_id=metadata.get("company_id", ""),
            source=getattr(result, "source", ""),
            vector_score=round(vector_score, 4),
            bm25_score=round(bm25_score, 4),
            min_vector=min_vector,
            min_bm25=min_bm25,
        )
        return False

    @staticmethod
    def _is_structured_metadata_supplement_evidence(result) -> bool:
        if getattr(result, "source", "") != "metadata_supplement":
            return False
        metadata = getattr(result, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            return False
        if str(metadata.get("chunk_type") or "").strip().lower() != "fact_line":
            return False

        fact_ids = CompanyContextBus._metadata_string_list(metadata.get("fact_ids"))
        markers = CompanyContextBus._metadata_string_list(metadata.get("markers"))
        if CompanyContextBus._has_prefixed_value(fact_ids, "f_service") or CompanyContextBus._has_prefixed_value(
            markers, "qpack_service"
        ):
            return True
        if CompanyContextBus._has_prefixed_value(fact_ids, "f_content") or CompanyContextBus._has_prefixed_value(
            markers, "qpack_content"
        ):
            return True

        structured_parts = [
            str(getattr(result, "source_file", "") or ""),
            str(metadata.get("source_file") or ""),
            str(metadata.get("filename") or ""),
            str(metadata.get("original_filename") or ""),
            str(metadata.get("section_title") or ""),
            str(metadata.get("category") or ""),
            str(metadata.get("scenario") or ""),
        ]
        structured_text = " ".join(structured_parts).casefold()
        return any(
            hint.casefold() in structured_text
            for hint in (
                *STRUCTURED_SUPPLEMENT_SERVICE_HINTS,
                *STRUCTURED_SUPPLEMENT_CONTENT_HINTS,
            )
        )

    @staticmethod
    def _metadata_string_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if item not in (None, "")]
        return [str(value)] if value != "" else []

    @staticmethod
    def _has_prefixed_value(values: list[str], prefix: str) -> bool:
        prefix = prefix.casefold()
        return any(value.casefold().startswith(prefix) for value in values)

    def ingest_document(
        self, filename: str, content: bytes, metadata: dict = None
    ) -> dict:  # 文档入库全流程
        """解析文档并入库：解析 → 切片 → 嵌入 → 索引"""  # 完整的 ETL 流水线
        import uuid  # 延迟导入

        from .document_parser import DocumentParser  # 延迟导入文档解析器
        from .doc_status import get_doc_status_manager
        from .text_splitter import TextChunker  # 延迟导入文本切片器

        doc_id = uuid.uuid4().hex[:12]  # 文档级 ID，供上传响应、列表和状态接口一致使用
        status = get_doc_status_manager().get_or_create(doc_id, filename)
        status.start_text_processing()

        try:
            text = DocumentParser.parse(filename, content)  # 第一步：解析文档为纯文本
            metadata = metadata or {}  # 避免 None
            metadata["original_filename"] = filename  # 保留原始文件名，用于溯源
            metadata["company_id"] = self.company_id  # 强制注入公司 ID
            metadata["layer"] = "knowledge"  # 标记为知识库层
            metadata["document_id"] = doc_id  # 文档级 ID，区别于 chunk_id

            chunker_mode = _resolve_rag_chunker_mode()
            if chunker_mode == RAG_CHUNKER_MODE_SMART:
                from .smart_chunker import SmartChunker  # 延迟导入，默认 recursive 路径不加载

                chunker = SmartChunker()
                chunks = chunker.chunk(
                    text, source_file=filename, metadata=metadata
                )  # SmartChunker 返回 dict，后续适配为统一索引格式
            else:
                chunker = TextChunker(
                    chunk_size=512, chunk_overlap=64
                )  # 第二步：创建切片器，512 是中文 Embedding 模型的最佳窗口
                chunks = chunker.chunk(
                    text, source_file=filename, metadata=metadata
                )  # 执行切片，保留源文件信息

            from .hybrid_retriever import get_hybrid_retriever  # 延迟导入

            retriever = get_hybrid_retriever(self.company_id)  # 获取公司检索器

            documents = []  # 构建批量索引文档列表
            total_chunks = len(chunks)
            for chunk_index, chunk in enumerate(chunks):  # 第三步：将切片转为索引格式
                if isinstance(chunk, dict):
                    chunk_content = str(chunk.get("content") or "")
                    chunk_metadata = dict(chunk.get("metadata") or {})
                    chunk_id = _build_chunk_id(filename, chunk_index, chunk_content)
                else:
                    chunk_content = chunk.content
                    chunk_metadata = {}
                    chunk_id = chunk.chunk_id

                chunk_metadata.update(metadata)  # 系统字段优先，避免 SmartChunker 覆盖租户/文档归属
                chunk_metadata["chunk_index"] = chunk_index  # 记录最终切片序号
                chunk_metadata["total_chunks"] = total_chunks  # 记录最终总切片数
                chunk_metadata["source_file"] = filename  # 记录源文件
                documents.append(
                    {
                        "id": chunk_id,  # 使用稳定 MD5 生成的唯一 chunk ID
                        "content": chunk_content,  # 切片文本
                        "metadata": chunk_metadata,  # 完整元数据
                    }
                )

            retriever.index_documents(documents)  # 第四步：批量索引到 BM25 和 Milvus
            status.complete_text_processing(chunk_count=len(chunks))
            status.start_multimodal_processing()
            status.complete_multimodal_processing(count=0)
            logger.info(
                "document_ingested",
                company_id=self.company_id,
                doc_id=doc_id,
                filename=filename,  # 记录入库结果
                chunks=len(chunks),
                text_length=len(text),
                chunker_mode=chunker_mode,
            )
        except Exception as exc:
            status.fail_text_processing(str(exc))
            raise

        return {  # 返回入库摘要信息
            "doc_id": doc_id,
            "filename": filename,
            "chunks": len(chunks),  # 切片数量
            "text_length": len(text),  # 文本总长度
        }

    def get_layer2_context(
        self,
        query: str,
        top_k: int = 3,  # 获取 Layer2 上下文的文本格式
        results: list[dict] = None,
    ) -> str:  # results: 预检索结果,传入则跳过内部 search_knowledge
        """获取 Layer 2 上下文（RAG 检索结果注入）"""  # Layer2 是 RAG 检索的核心输出
        # results 参数支持调用方传入预检索结果,避免 retrieve_structured 等场景下重复查询 Milvus
        if results is None:  # 未传入预检索结果时自行检索
            results = self.search_knowledge(query, top_k=top_k)  # 语义检索知识库
        if not results:  # 无结果时返回空字符串，避免向 Prompt 注入 "暂无数据"
            return ""

        parts = ["\n【公司知识库相关内容】"]  # 用中文方括号标记，与 Layer1 和 Layer3 格式统一
        for i, r in enumerate(results, 1):  # 从 1 开始编号，与引用标注 [来源1] 对应
            source_info = ""  # 构建来源信息字符串
            if r.get("source_file"):  # 有源文件时才显示
                source_info = f" (文件: {r['source_file']}"  # 文件信息开头
                if r.get("source_page"):  # 有页码时才显示
                    source_info += f", 第{r['source_page']}页"  # 追加页码
                source_info += ")"  # 闭合括号
            parts.append(
                f"[来源{i}]{source_info}\n{r['content']}"
            )  # 格式：引用标记 + 来源信息 + 内容
            if r.get("metadata", {}).get("category"):  # 有分类时才显示，避免冗余
                parts.append(f"   (分类: {r['metadata']['category']})")  # 缩进显示分类标签
        return "\n".join(parts)  # 拼接为完整文本

    # ═══ Layer 3: 公司经验记忆 ═══  # 动态经验层，Agent 任务完成后自动记录

    def record_experience(
        self,
        agent_name: str,
        task_type: str,  # 记录 Agent 执行经验
        summary: str,
        outcome: str = "",  # outcome 可选，用于记录任务结果
        tags: list[str] = None,
    ):  # tags 用于后续的按标签检索
        """Agent 任务完成后自动写入经验摘要"""  # 自动化记录，无需人工干预
        import uuid  # 延迟导入

        from .hybrid_retriever import get_hybrid_retriever  # 延迟导入

        doc_id = f"exp_{agent_name}_{uuid.uuid4().hex[:8]}"  # 经验 ID 格式：exp_Agent名_随机8位，便于识别来源
        metadata = {  # 经验元数据包含完整的上下文信息
            "company_id": self.company_id,  # 多租户隔离
            "layer": "experience",  # 标记为经验层，检索时用于过滤
            "agent_name": agent_name,  # 记录执行 Agent，支持按 Agent 过滤经验
            "task_type": task_type,  # 任务类型，支持按类型检索
            "outcome": outcome,  # 任务结果，成功/失败/部分完成
            "tags": json.dumps(tags or []),  # JSON 序列化标签列表，Milvus 只支持字符串类型
            "recorded_at": datetime.utcnow().isoformat(),  # 记录时间，用于时间衰减排序
        }
        retriever = get_hybrid_retriever(self.company_id)  # 获取公司检索器
        retriever.index_documents(
            [
                {  # 索引到向量库
                    "id": doc_id,
                    "content": summary,  # 经验摘要作为检索内容
                    "metadata": metadata,
                }
            ]
        )
        logger.info(
            "experience_recorded",
            company_id=self.company_id,  # 审计日志
            agent=agent_name,
            task_type=task_type,
        )

    def search_experiences(
        self,
        query: str,
        agent_name: str = None,  # 搜索经验记忆
        top_k: int = 3,
    ) -> list[dict]:  # 默认返回 3 条，避免过多经验干扰
        """搜索公司经验记忆"""  # 先检索再按 layer 和 agent_name 过滤
        from .hybrid_retriever import get_hybrid_retriever  # 延迟导入

        retriever = get_hybrid_retriever(self.company_id)  # 获取公司检索器
        results = retriever.search(query, top_k=top_k * 2)  # 检索 2 倍数量，补偿过滤造成的损失

        filtered = []  # 过滤后的结果
        for r in results:  # 手动过滤，因为 Milvus 的 expr 过滤在复杂条件下性能不佳
            meta = r.metadata  # 获取元数据
            if meta.get("layer") != "experience":  # 只保留经验层数据
                continue
            if agent_name and meta.get("agent_name") != agent_name:  # 指定了 Agent 则精确匹配
                continue
            filtered.append(r)  # 通过过滤
            if len(filtered) >= top_k:  # 达到目标数量后提前终止
                break

        return [  # 转为简化 dict
            {
                "content": r.content,
                "agent_name": r.metadata.get("agent_name", ""),  # 安全取值
                "task_type": r.metadata.get("task_type", ""),
                "outcome": r.metadata.get("outcome", ""),
                "score": r.rerank_score or r.rrf_score,  # 优先 rerank 分数
            }
            for r in filtered
        ]

    def get_layer3_context(
        self,
        query: str,
        agent_name: str = None,  # 获取 Layer3 文本上下文
        top_k: int = 3,  # 经验检索数量
        results: list[dict] = None,
    ) -> str:  # results: 预检索结果,传入则跳过内部 search_experiences
        """获取 Layer 3 上下文（经验记忆注入）"""  # Layer3 提供历史经验参考
        # results 参数支持调用方传入预检索结果,避免 retrieve_structured 等场景下重复查询 Milvus
        if results is None:  # 未传入预检索结果时自行检索
            results = self.search_experiences(query, agent_name=agent_name, top_k=top_k)  # 检索经验
        if not results:  # 无经验时返回空
            return ""

        parts = ["\n【公司历史经验】"]  # 用中文方括号标记
        for i, r in enumerate(results, 1):  # 编号展示
            parts.append(
                f"{i}. [{r['agent_name']}] {r['content']}"
            )  # 格式：序号 + Agent 名 + 经验内容
            if r.get("outcome"):  # 有结果才显示
                parts.append(f"   结果: {r['outcome']}")  # 缩进显示结果
        return "\n".join(parts)

    # ═══ 全量上下文注入 ═══  # 三层上下文一次性全部获取

    def get_full_context(
        self,
        task_query: str = "",  # 全量上下文，包含三层数据
        agent_name: str = None,
    ) -> str:
        """获取三层上下文全量注入"""  # 用于需要完整上下文的复杂决策场景
        parts = []  # 收集各层内容

        l1 = self.get_layer1_context()  # Layer1：公司基础资料，始终需要
        if l1:
            parts.append(l1)

        if task_query:  # 有任务查询时才检索 Layer2 和 Layer3
            l2 = self.get_layer2_context(task_query)  # Layer2：知识库检索
            if l2:
                parts.append(l2)

            l3 = self.get_layer3_context(task_query, agent_name=agent_name)  # Layer3：经验检索
            if l3:
                parts.append(l3)

        return "\n\n".join(parts)  # 双换行分隔各层内容

    # ═══ 睡眠巩固 ═══  # 认知科学中的"睡眠巩固"概念：定期整理和压缩记忆

    def sleep_consolidate(
        self, agent_name: str = None, max_per_agent: int = 20
    ):  # 睡眠巩固：去重+压缩经验
        """
        睡眠巩固: 将近期经验压缩为精炼摘要并去重  # 防止经验库无限膨胀，定期去重合并
        可在定时任务中调用  # 建议每天凌晨低峰期执行
        """
        import uuid  # 延迟导入

        all_contexts = self.search_experiences(  # 检索所有经验
            query="总结 经验 教训 成功 失败",  # 用通用查询词尽可能多地召回经验
            agent_name=agent_name,  # 可选按 Agent 过滤
            top_k=max_per_agent,  # 限制处理数量，避免一次性处理过多
        )

        if len(all_contexts) < 5:  # 经验太少不需要巩固，避免无意义操作
            return

        from .hybrid_retriever import get_hybrid_retriever  # 延迟导入

        retriever = get_hybrid_retriever(self.company_id)  # 获取检索器用于写入

        from .embedding_service import get_embedding_service  # 延迟导入

        emb_service = get_embedding_service()  # 获取向量化服务用于相似度计算

        contents = [c["content"] for c in all_contexts]  # 提取纯文本内容
        embeddings = emb_service.encode(contents)  # 批量向量化

        deduped_indices = [0]  # 去重后的索引列表，第一条始终保留
        threshold = 0.92  # 相似度阈值，超过 0.92 认为重复（余弦相似度归一化后）

        for i in range(1, len(contents)):  # 从第二条开始比较
            is_dup = False  # 是否重复标记
            for kept_idx in deduped_indices:  # 与已保留的每条比较
                sim = np.dot(
                    embeddings[i], embeddings[kept_idx]
                )  # 点积计算余弦相似度（向量已归一化）
                if sim > threshold:  # 超过阈值视为重复
                    is_dup = True
                    break
            if not is_dup:  # 不重复则保留
                deduped_indices.append(i)

        deduped = [all_contexts[idx] for idx in deduped_indices]  # 按去重索引提取

        summary_parts = []  # 构建精炼摘要
        for exp in deduped:
            summary_parts.append(f"[{exp['agent_name']}] {exp['content']}")  # 保留 Agent 名和内容

        # 加日期标识，构建精炼摘要
        summary = (
            "公司经验巩固摘要 ("
            + datetime.utcnow().strftime("%Y-%m-%d")
            + "):\n"
            + "\n".join(f"- {p}" for p in summary_parts)
        )  # 列表格式展示

        doc_id = f"consolidated_{uuid.uuid4().hex[:8]}"  # 巩固摘要的文档 ID
        retriever.index_documents(
            [
                {  # 写入索引
                    "id": doc_id,
                    "content": summary,  # 精炼后的摘要
                    "metadata": {
                        "company_id": self.company_id,
                        "layer": "experience",  # 仍然属于经验层
                        "type": "consolidated",  # 标记为巩固类型，区分于原始经验
                        "source_count": len(deduped),  # 记录来源数量，便于追溯
                        "consolidated_at": datetime.utcnow().isoformat(),  # 巩固时间
                    },
                }
            ]
        )

        logger.info(
            "sleep_consolidated",
            company_id=self.company_id,  # 审计日志
            deduped_count=len(deduped),
            total=len(all_contexts),
        )

    # ═══ 上下文注入（v2 新增，合并原 DataInjector 功能） ═══

    def inject_context(
        self,
        system_prompt: str,
        task_query: str = "",  # 注入上下文到 System Prompt
        agent_name: str = None,
        layer1: bool = True,
        layer2: bool = True,
        layer3: bool = True,
        layer2_top_k: int = 3,
        layer3_top_k: int = 3,
    ) -> str:
        """在 Agent 执行前注入公司上下文到 System Prompt。

        v2 新增：合并原 DataInjector.inject_context() 功能，减少一层间接调用。
        """
        context_parts = []

        if layer1:
            l1 = self.get_layer1_context()
            if l1:
                context_parts.append(l1)

        if layer2 and task_query:
            l2 = self.get_layer2_context(task_query, top_k=layer2_top_k)
            if l2:
                context_parts.append(l2)

        if layer3 and task_query:
            l3 = self.get_layer3_context(task_query, agent_name=agent_name, top_k=layer3_top_k)
            if l3:
                context_parts.append(l3)

        if not context_parts:
            return system_prompt

        injected = system_prompt + "\n\n" + "\n\n".join(context_parts)
        logger.info(
            "context_injected",
            company_id=self.company_id,
            agent=agent_name,
            layers=len(context_parts),
        )
        return injected

    def record_completion(
        self,
        agent_name: str,
        task_type: str,  # 记录 Agent 任务完成经验
        task_query: str,
        result: str,
        outcome: str = "",
    ):
        """Agent 任务完成后自动记录经验（v2 新增，合并原 DataInjector.record_completion()）。"""
        summary = f"任务: {task_query[:200]}"
        if result:
            summary += f"\n结果摘要: {result[:500]}"

        self.record_experience(
            agent_name=agent_name,
            task_type=task_type,
            summary=summary,
            outcome=outcome,
            tags=[task_type, agent_name],
        )


_bus_cache: dict[str, CompanyContextBus] = {}  # 模块级缓存，按 company_id 存储单例
_bus_cache_lock = (
    threading.Lock()
)  # 保护 get_company_context_bus 的 check-then-act,避免并发重复创建实例


def get_company_context_bus(company_id: str = "default") -> CompanyContextBus:  # 工厂函数，保证单例
    # 双重检查锁:快速路径(缓存命中)无需加锁,避免热路径性能损失
    if company_id in _bus_cache:  # 快速路径:缓存命中直接返回
        return _bus_cache[company_id]
    with _bus_cache_lock:  # 缓存未命中,加锁创建
        # 二次检查:等待锁期间可能已被其他线程创建
        if company_id not in _bus_cache:
            _bus_cache[company_id] = CompanyContextBus(company_id)  # 创建并缓存
        return _bus_cache[company_id]  # 返回缓存的实例
