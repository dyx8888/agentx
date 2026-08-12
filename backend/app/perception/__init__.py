"""
感知管道 (Perception Pipeline) 模块

统一感知管道按顺序执行：
  InputFilter → QueryRewriter → IntentExtractor → RagRetriever → ToolResultParser

提供统一的感知上下文，供下游 Agent 消费。
"""
# 以上 docstring 之所以要列出处理管线顺序，是因为下游调用方需要一目了然地理解数据流转方向

from app.perception.context_package import ContextPackage  # T2.2: 增强流程的综合上下文包
from app.perception.input_filter import (
    InputFilter,  # 对外暴露输入过滤器，让 Agent 可以独立调用过滤能力
)
from app.perception.intent_extractor import (  # 同时导出数据类和枚举，避免调用方需要跨模块导入
    Intent,
    IntentExtractor,
    IntentType,
)
from app.perception.pipeline import (  # 核心编排器和上下文，是模块的主要入口
    PerceptionContext,
    PerceptionPipeline,
)
from app.perception.query_rewriter import (
    QueryRewriter,  # 独立暴露改写器，支持可选跳过改写阶段的场景
)
from app.perception.rag_retriever import (  # 导出结果数据结构，让类型标注更清晰
    RagResult,
    RagRetriever,
)
from app.perception.tool_result_parser import (  # 工具解析器可用于管线外的后处理场景
    ParsedToolResult,
    ToolResultParser,
)

__all__ = [  # 用 __all__ 严格控制 `from perception import *` 的导出范围，避免内部实现细节泄露
    "PerceptionPipeline",
    "PerceptionContext",
    "ContextPackage",
    "InputFilter",
    "QueryRewriter",
    "IntentExtractor",
    "Intent",
    "IntentType",
    "RagRetriever",
    "RagResult",
    "ToolResultParser",
    "ParsedToolResult",
]
