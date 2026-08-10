"""  # RAG 引擎模块，作为整个 rag 子包的入口，统一暴露所有对外接口
RAG (Retrieval-Augmented Generation) 引擎模块  # 核心设计理念：检索增强生成，让 LLM 回答基于企业真实数据而非幻觉

提供：  # 列出所有子模块，方便开发者快速了解包内有哪些能力
- HybridRAG: BM25 + 向量检索 + RRF + Reranker 混合检索引擎  # 多路召回 + 融合排序，确保检索既不遗漏关键词也不丢失语义
- CompanyContextBus: 三层公司数据注入架构  # 分层设计是为了将静态资料、动态知识、经验记忆解耦，各层独立维护
- EmbeddingService: 文本向量化服务  # 统一向量化入口，带缓存减少重复计算，支持 fallback 降级
- DataInjector: Agent 上下文自动注入  # 在 Agent 执行前后自动注入上下文，业务层无需关心注入细节
- MultiModalRetriever: CLIP Embedding + Milvus 以图搜图  # 视觉设计师 Agent 需要图像检索能力，用 CLIP 实现图文跨模态
- GraphRAG: 知识图谱关系推理检索引擎  # 纯向量检索缺乏关系推理，知识图谱补全实体间的结构化关联
- DocumentParser: 多格式文档解析器 (PDF/Word/HTML/TXT)  # 企业文档格式多样，统一解析入口减少上层适配成本
- TextChunker: 文本切片器  # 切片是 RAG 的关键预处理步骤，切片质量直接影响检索召回率
- RAGPrompt: 标准 Prompt 模板构建  # 统一 Prompt 模板确保 LLM 回答风格一致，引用标注可追溯
- RAGEvaluator: RAG 检索与生成质量评估  # 量化评估是持续优化的基础，无评估则无法判断改进是否有效
"""

from .company_context_bus import CompanyContextBus  # 企业上下文总线，三层数据架构的核心调度器
from .data_injector import DataInjector  # Agent 上下文自动注入器，封装注入逻辑让上层调用更简洁
from .document_parser import DocumentParser  # 多格式文档解析器，支持 PDF/Word/HTML/TXT 统一解析
from .embedding_service import EmbeddingService  # 文本向量化服务，内部有缓存和 fallback 降级策略
from .graph_rag import GraphRAGRetriever  # 知识图谱检索器，提供实体关系推理能力
from .hybrid_retriever import HybridRetriever  # 混合检索引擎，BM25 + 向量 + RRF + Reranker 四合一
from .multimodal_retriever import MultiModalRetriever, get_multimodal_retriever  # 多模态检索器及其工厂函数，支持以图搜图
from .rag_evaluator import RAGEvaluator  # RAG 质量评估器，用于监控检索和生成效果
from .rag_prompt import build_rag_prompt, parse_citations  # Prompt 构建和引用解析，确保回答可追溯
from .text_splitter import TextChunker  # 文本切片器，递归语义切片比简单固定长度切片召回率更高

__all__ = [  # 显式声明公开接口，防止 from rag import * 时污染命名空间
    "HybridRetriever",  # 混合检索器，最常用的检索入口
    "EmbeddingService",  # 向量化服务，外部可能需要直接调用做编码
    "CompanyContextBus",  # 上下文总线，Agent 编排时需要获取多层上下文
    "DataInjector",  # 数据注入器，简化 Agent 上下文注入的调用
    "MultiModalRetriever",  # 多模态检索器，视觉设计 Agent 专用
    "get_multimodal_retriever",  # 工厂函数，保证单例避免重复加载 CLIP 模型
    "GraphRAGRetriever",  # 知识图谱检索器，关系推理场景专用
    "DocumentParser",  # 文档解析器，上传文档入库时使用
    "TextChunker",  # 文本切片器，文档预处理和自建索引时使用
    "RAGEvaluator",  # 评估器，QA 测试和质量监控使用
    "build_rag_prompt",  # Prompt 构建函数，Agent 调用 LLM 前组装上下文
    "parse_citations",  # 引用解析函数，从 LLM 回复中提取引用编号
]
