# 模块文档：说明 evolution 是整个自进化系统的入口包
# 系统的核心价值在于让 Agent 能从反馈中自动学习改进，而非依赖人工调参
"""
AgentX Evolution Engine - Self-Evolution System
Provides feedback analysis, improvement suggestions, memory consolidation, LoRA fine-tuning and evolution management
"""

# 只导出公开 API，隐藏内部实现细节（如 applier、scheduler 等内部组件）
# 这是遵循"最小公开接口"原则，减少外部模块的耦合
from .analyzer import EvolutionAnalyzer
from .suggester import EvolutionSuggester

# 显式声明 __all__ 是为了限制 `from app.evolution import *` 时导入的符号
# 防止内部工具类（如数据提取器、通知器等）意外暴露给调用方
__all__ = ['EvolutionAnalyzer', 'EvolutionSuggester']
