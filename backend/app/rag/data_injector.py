"""  # DataInjector 模块，Agent 上下文自动注入器，封装三层数据注入逻辑
DataInjector - Agent 上下文自动注入器  # "注入器"模式：在 Agent 执行前后自动插入/提取数据，业务层无感知

负责在 Agent 执行任务前后自动注入公司三层数据:  # 设计目标：Agent 开发者只需关注业务逻辑，上下文由注入器自动管理
- 执行前: 加载 Layer1(基础资料) → Layer2(知识库RAG) → Layer3(经验记忆)  # 按层级顺序注入，确保基础信息先于检索结果
- 执行后: 自动记录经验到 Layer3  # 自动积累经验，形成正向反馈循环
"""

from dataclasses import dataclass  # dataclass 用于 InjectionConfig 配置类，减少样板代码

from app.core.logging import get_logger  # 结构化日志，追踪注入操作

logger = get_logger(__name__)  # 模块级 logger


@dataclass  # 使用 dataclass 而非普通类，因为 InjectionConfig 是纯配置数据容器
class InjectionConfig:
    """注入配置"""  # 通过配置对象控制各层注入行为，比散落的布尔参数更清晰
    layer1_enabled: bool = True  # 默认开启 Layer1，公司基础资料是 Agent 回答的基础上下文
    layer2_enabled: bool = True  # 默认开启 Layer2，知识库检索是 RAG 的核心价值
    layer2_top_k: int = 3  # Layer2 默认返回 3 条，平衡信息量和 token 消耗
    layer3_enabled: bool = True  # 默认开启 Layer3，经验积累是 Agent 持续进化的关键
    layer3_top_k: int = 3  # Layer3 默认返回 3 条经验，避免过多历史干扰
    layer3_auto_record: bool = True  # 默认自动记录经验，形成闭环学习


class DataInjector:  # Agent 上下文注入器，封装注入和记录逻辑
    """Agent 上下文注入器"""  # 对外暴露简洁接口，隐藏三层架构的复杂性

    def __init__(self, company_id: str = "default", config: InjectionConfig = None):  # 支持自定义配置和公司隔离
        self.company_id = company_id  # 公司 ID，用于数据隔离
        self.config = config or InjectionConfig()  # 未传入配置时使用默认配置

    def _get_bus(self):  # 懒加载 CompanyContextBus，避免不必要的初始化
        from .company_context_bus import get_company_context_bus  # 延迟导入避免循环依赖
        return get_company_context_bus(self.company_id)  # 按公司 ID 获取独立实例

    def inject_context(self, system_prompt: str, task_query: str = "",  # 核心方法：在 System Prompt 后追加公司上下文
                       agent_name: str = None) -> str:
        """在 Agent 执行前注入公司上下文"""  # 执行前注入，让 Agent 在生成回答时拥有完整上下文
        bus = self._get_bus()  # 获取上下文总线
        context_parts = []  # 收集各层上下文片段

        if self.config.layer1_enabled:  # 配置层控制，关闭 Layer1 可节省 token
            l1 = bus.get_layer1_context()  # 获取公司基础资料
            if l1:  # 有资料才添加
                context_parts.append(l1)

        if self.config.layer2_enabled and task_query:  # Layer2 需要 task_query 才能检索
            l2 = bus.get_layer2_context(task_query, top_k=self.config.layer2_top_k)  # 按配置的 top_k 检索
            if l2:  # 检索到知识才添加
                context_parts.append(l2)

        if self.config.layer3_enabled and task_query:  # Layer3 同样需要 task_query 来匹配经验
            l3 = bus.get_layer3_context(  # 按 Agent 名称过滤经验
                task_query, agent_name=agent_name, top_k=self.config.layer3_top_k
            )
            if l3:  # 有匹配经验才添加
                context_parts.append(l3)

        if not context_parts:  # 所有层都为空时，不做任何注入，直接返回原始 prompt
            return system_prompt

        injected = system_prompt + "\n\n" + "\n\n".join(context_parts)  # 双换行分隔原始 prompt 和注入上下文
        logger.info("context_injected", company_id=self.company_id,  # 记录注入操作
                     agent=agent_name, layers=len(context_parts))
        return injected  # 返回注入后的完整 prompt

    def record_completion(self, agent_name: str, task_type: str,  # Agent 任务完成后记录经验
                          task_query: str, result: str,  # result 是 Agent 的完整输出
                          outcome: str = ""):  # outcome 可选，用于标记任务结果
        """Agent 任务完成后自动记录经验"""  # 自动记录，无需业务层手动调用
        if not self.config.layer3_auto_record:  # 配置关闭自动记录时直接返回
            return

        bus = self._get_bus()  # 获取上下文总线

        summary = f"任务: {task_query[:200]}"  # 截断到 200 字符，控制经验摘要长度
        if result:  # 有结果时才追加
            summary += f"\n结果摘要: {result[:500]}"  # 截断到 500 字符，避免经验过长

        bus.record_experience(  # 调用总线记录经验
            agent_name=agent_name,
            task_type=task_type,
            summary=summary,  # 任务描述 + 结果摘要
            outcome=outcome,  # 任务结果
            tags=[task_type, agent_name],  # 用任务类型和 Agent 名作为标签
        )

    def set_profile(self, **kwargs):  # 便捷方法：直接传参设置公司资料
        """设置公司基础资料"""  # 封装 Profile 构建，外部只需传关键字段
        from .company_context_bus import CompanyProfile  # 延迟导入
        bus = self._get_bus()  # 获取总线
        profile = CompanyProfile(**kwargs)  # 用 kwargs 构建 Profile 对象
        bus.set_profile(profile)  # 设置到总线

    def add_knowledge(self, content: str, metadata: dict = None, doc_id: str = None):  # 快捷添加知识
        """添加知识到知识库"""  # 直接代理到 bus.add_knowledge
        bus = self._get_bus()  # 获取总线
        return bus.add_knowledge(content, metadata, doc_id)  # 透传调用


_injector_cache: dict[str, DataInjector] = {}  # 模块级缓存，按 company_id 存储单例


def get_data_injector(company_id: str = "default") -> DataInjector:  # 工厂函数，保证单例
    if company_id not in _injector_cache:  # 缓存未命中时创建
        _injector_cache[company_id] = DataInjector(company_id)  # 创建并缓存
    return _injector_cache[company_id]  # 返回缓存的实例
