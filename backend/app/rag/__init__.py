"""# RAG 引擎模块，作为整个 rag 子包的入口，统一暴露所有对外接口
RAG (Retrieval-Augmented Generation) 引擎模块  # 核心设计理念：检索增强生成，让 LLM 回答基于企业真实数据而非幻觉

提供：  # 列出所有子模块，方便开发者快速了解包内有哪些能力
- HybridRAG: BM25 + 向量检索 + RRF + Reranker 混合检索引擎  # 多路召回 + 融合排序，确保检索既不遗漏关键词也不丢失语义
- CompanyContextBus: 三层公司数据注入架构  # 分层设计是为了将静态资料、动态知识、经验记忆解耦，各层独立维护
- EmbeddingService: 文本向量化服务  # 统一向量化入口，带缓存减少重复计算，支持 fallback 降级
- DataInjector: Agent 上下文自动注入  # 在 Agent 执行前后自动注入上下文，业务层无需关心注入细节
- MultiModalRetriever: CLIP Embedding + Milvus 以图搜图  # 视觉设计师 Agent 需要图像检索能力，用 CLIP 实现图文跨模态
- GraphRAG: 知识图谱关系推理检索引擎  # 纯向量检索缺乏关系推理，知识图谱补全实体间的结构化关联
- DocumentParser: 多格式文档解析器 + 解析器注册表热插拔  # 借鉴 RAG-Anything 注册表模式，支持切换解析器后端
- Resilience: 弹性机制（重试+熔断）  # 借鉴 RAG-Anything resilience.py，为网络依赖操作提供容错保护
- TextChunker: 文本切片器  # 切片是 RAG 的关键预处理步骤，切片质量直接影响检索召回率
- RAGPrompt: 标准 Prompt 模板构建  # 统一 Prompt 模板确保 LLM 回答风格一致，引用标注可追溯
- RAGEvaluator: RAG 检索与生成质量评估  # 量化评估是持续优化的基础，无评估则无法判断改进是否有效
"""

from .company_context_bus import CompanyContextBus  # 企业上下文总线，三层数据架构的核心调度器
from .context_extractor import (  # 上下文提取器，借鉴 RAG-Anything 设计
    ContextConfig,
    ContextExtractor,
    get_context_extractor,
)
from .data_injector import (
    DataInjector,  # Agent 上下文自动注入器（向后兼容，新代码建议直接用 CompanyContextBus）
)
from .doc_status import (  # 文档状态追踪，借鉴 RAG-Anything 设计
    DocState,  # 文档状态枚举
    DocStatus,  # 文档状态追踪器
    DocStatusManager,  # 文档状态管理器
    get_doc_status_manager,  # 工厂函数
)
from .document_parser import (  # 多格式文档解析器 + 解析器注册表，借鉴 RAG-Anything 设计
    PARSER_REGISTRY,  # 解析器注册表
    BaseParser,  # 解析器抽象基类
    DocumentParser,  # 向后兼容的门面类
    get_parser,  # 工厂函数
    register_parser,  # 注册自定义解析器
    set_parser,  # 切换解析器
)
from .embedding_service import (  # 文本向量化服务 + 模型热插拔，借鉴 RAG-Anything 设计
    EMBEDDING_MODEL_REGISTRY,  # 嵌入模型注册表
    EmbeddingService,  # 向量化服务类
    list_available_models,  # 列出可用模型
    register_embedding_model,  # 注册嵌入模型
)
from .graph_rag import GraphRAGRetriever  # 知识图谱检索器，v2 支持 LLM 驱动的实体抽取
from .hybrid_retriever import HybridRetriever  # 混合检索引擎，BM25 + 向量 + RRF + Reranker 四合一

# LlamaIndex 对照检索器：用 try/except 保护，未装 llama-index 时降级跳过导出，不影响其余模块
try:  # llama_index 是可选依赖
    from .llamaindex_retriever import (  # 对照版检索器，证明掌握 LlamaIndex 标准框架
        LLAMAINDEX_AVAILABLE,  # 可用性标记，供上层判断是否启用 LlamaIndex 后端
        LlamaIndexRetriever,  # LlamaIndex 对照检索器主类
        get_llamaindex_retriever,  # 工厂函数，与 get_hybrid_retriever 对齐
    )
except ImportError:  # llama_index 未安装时不影响 rag 包其余功能
    LLAMAINDEX_AVAILABLE = False  # 标记不可用
from .multimodal_retriever import (  # 多模态检索器及其工厂函数，支持以图搜图
    MultiModalRetriever,
    get_multimodal_retriever,
)
from .parse_cache import ParseCache, get_parse_cache  # 解析缓存，借鉴 RAG-Anything 设计
from .rag_evaluator import RAGEvaluator  # RAG 质量评估器，用于监控检索和生成效果
from .rag_prompt import build_rag_prompt, parse_citations  # Prompt 构建和引用解析，确保回答可追溯
from .resilience import (  # 弹性机制，借鉴 RAG-Anything 设计
    CircuitBreaker,  # 熔断器
    CircuitBreakerOpenError,  # 熔断器打开异常
    async_retry,  # 异步重试装饰器
    retry,  # 同步重试装饰器
)
from .text_splitter import TextChunker  # 文本切片器，递归语义切片比简单固定长度切片召回率更高

__all__ = [  # 显式声明公开接口，防止 from rag import * 时污染命名空间
    "HybridRetriever",  # 混合检索器，最常用的检索入口
    "LlamaIndexRetriever",  # LlamaIndex 对照检索器，可互换后端
    "get_llamaindex_retriever",  # LlamaIndex 检索器工厂函数
    "LLAMAINDEX_AVAILABLE",  # LlamaIndex 可用性标记
    "EmbeddingService",  # 向量化服务，支持模型热插拔
    "EMBEDDING_MODEL_REGISTRY",  # 嵌入模型注册表
    "register_embedding_model",  # 注册嵌入模型
    "list_available_models",  # 列出可用模型
    "CompanyContextBus",  # 上下文总线（含 inject_context/record_completion）
    "DataInjector",  # 数据注入器（向后兼容）
    "ContextExtractor",  # 上下文提取器
    "ContextConfig",  # 上下文提取配置
    "get_context_extractor",  # 上下文提取器工厂函数
    "DocStatus",  # 文档状态追踪器
    "DocState",  # 文档状态枚举
    "DocStatusManager",  # 文档状态管理器
    "get_doc_status_manager",  # 文档状态管理器工厂函数
    "MultiModalRetriever",  # 多模态检索器，视觉设计 Agent 专用
    "get_multimodal_retriever",  # 工厂函数，保证单例避免重复加载 CLIP 模型
    "GraphRAGRetriever",  # 知识图谱检索器，v2 支持 LLM 实体抽取
    "DocumentParser",  # 文档解析器，上传文档入库时使用
    "BaseParser",  # 解析器抽象基类，自定义解析器需继承
    "PARSER_REGISTRY",  # 解析器注册表，支持热插拔
    "get_parser",  # 解析器工厂函数
    "set_parser",  # 切换全局解析器
    "register_parser",  # 注册自定义解析器
    "ParseCache",  # 解析缓存管理器
    "get_parse_cache",  # 解析缓存工厂函数
    "TextChunker",  # 文本切片器，文档预处理和自建索引时使用
    "RAGEvaluator",  # 评估器，QA 测试和质量监控使用
    "build_rag_prompt",  # Prompt 构建函数，Agent 调用 LLM 前组装上下文
    "parse_citations",  # 引用解析函数，从 LLM 回复中提取引用编号
    "async_retry",  # 异步重试装饰器，用于 LLM/Milvus 等网络调用
    "retry",  # 同步重试装饰器，用于文档解析等同步调用
    "CircuitBreaker",  # 熔断器，隔离故障服务
    "CircuitBreakerOpenError",  # 熔断器打开时的异常
]
