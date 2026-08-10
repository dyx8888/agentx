"""
工作记忆 (Working Memory) 数据类

定义 Agent 在单次任务周期内的运行时状态，替代分散在 State 中的字段。
按照认知心理学工作记忆模型（Baddeley & Hitch）设计：
- 目标导向 (goal): 当前任务的目标
- 执行步骤 (current_step): 当前所处的执行步骤
- 注意力焦点 (context_focus): 当前关注的核心上下文
- 临时变量 (temporary_variables): 任务执行中的中间结果
- 待处理动作 (pending_actions): 尚未完成的动作列表
"""

from dataclasses import dataclass, field  # dataclass 自动生成 __init__/__repr__/__eq__，减少样板代码；field 提供 default_factory 避免可变默认值陷阱


@dataclass  # 使用 dataclass 而非普通类：这些字段主要是数据容器，不需要复杂的行为逻辑
class WorkingMemory:
    """工作记忆 - Agent 单次任务周期的运行时状态

    整合了原本分散在 RuntimeState 中的：
    - plan (映射到 goal + pending_actions)
    - current_step (映射到 current_step)
    - step_results (映射到 temporary_variables)
    - plan_completed (映射到 pending_actions 为空)
    """

    goal: str = ""  # 默认空字符串而非 None：在 Prompt 模板中空字符串比 None 更安全，不会出现 "None" 文字
    """当前任务的总体目标描述"""

    current_step: str = ""  # 字符串类型而非枚举：步骤名称是动态的，运行时才能确定，枚举会限制灵活性
    """当前正在执行的步骤标识（如 'step_1', 'step_2', 'done'）"""

    context_focus: str = ""  # 注意力焦点，帮助 LLM 在大量上下文信息中聚焦当前最相关的部分
    """当前关注的核心上下文信息（如工具名称、关键参数等）"""

    temporary_variables: dict = field(default_factory=dict)  # field(default_factory=dict) 避免所有实例共享同一个 dict 对象
    """任务执行中的临时变量和中间结果
        
    示例: {
        'step_results': [...],
        'last_tool_output': '...',
        'retry_count': 0,
        'fingerprint_window': [...],
    }
    """

    pending_actions: list[str] = field(default_factory=list)  # 用 list 而非 set：动作顺序很重要，需要保留执行顺序
    """尚未完成的待处理动作列表"""

    @property
    def is_complete(self) -> bool:  # property 而非普通字段：状态由 pending_actions 派生，避免数据冗余和不一致
        """任务是否已完成（无待处理动作）"""
        return len(self.pending_actions) == 0

    @property
    def step_count(self) -> int:  # 派生属性：从 temporary_variables 中的 step_results 计算，而非单独维护一个计数器
        """已完成的步骤数"""
        results = self.temporary_variables.get("step_results", [])
        return len(results) if isinstance(results, list) else 0  # isinstance 防御性检查：step_results 可能被意外赋值为非 list 类型

    def to_dict(self) -> dict:  # 序列化方法：支持 JSON 序列化存入 checkpoint
        """序列化为 dict"""
        return {
            "goal": self.goal,
            "current_step": self.current_step,
            "context_focus": self.context_focus,
            "temporary_variables": self.temporary_variables,
            "pending_actions": self.pending_actions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkingMemory":  # classmethod 而非 staticmethod：需要访问 cls 来创建实例，支持子类继承
        """从 dict 反序列化"""
        return cls(
            goal=data.get("goal", ""),  # .get 提供默认值，兼容旧版本数据中缺少某字段的情况
            current_step=data.get("current_step", ""),
            context_focus=data.get("context_focus", ""),
            temporary_variables=data.get("temporary_variables", {}),
            pending_actions=data.get("pending_actions", []),
        )

    def reset(self):  # 原地重置而非创建新实例：避免在 Agent 循环中频繁分配内存
        """重置工作记忆，用于新任务开始"""
        self.goal = ""
        self.current_step = ""
        self.context_focus = ""
        self.temporary_variables = {}
        self.pending_actions = []