"""
SQLAlchemy Database Models
Defines ORM models for User, Company, Agent, Task, Feedback, and EvolutionLog
"""

from datetime import datetime  # 所有时间戳字段统一使用 UTC 时间，避免时区转换带来的不一致问题

from sqlalchemy import (
    Boolean,  # 明确的是/否语义，比用 Integer(0/1) 更可读，且会被 ORM 自动转为 Python bool
    Column,  # 声明式映射的核心：每个类属性通过 Column() 映射到数据库列
    DateTime,  # 统一时间类型，支持默认值和索引
    Float,  # 价格字段需要支持小数（如 9.99 元/月），Integer 无法满足
    ForeignKey,  # 数据库级引用完整性约束，防止孤儿记录，ORM 层面也用于 relationship 的 join 条件推导
    Index,  # 复合索引，覆盖多列 WHERE + ORDER BY 查询，避免 filesort
    Integer,  # 主键和外键的通用类型，自增整型主键性能优于 UUID（尤其 SQLite 下）
    String,  # 变长字符串，指定长度是为了让数据库优化存储和索引（MySQL 下尤其重要）
    Text,  # 无长度限制的大文本，适合存储 JSON 序列化数据和大段描述
    TypeDecorator,  # 自定义类型的基类，在原生类型之上添加序列化/反序列化逻辑（此处用于透明加密）
    UniqueConstraint,  # 复合唯一约束，比单列 unique=True 更灵活——保证多列组合不重复（如公司+Agent+工具三元组）
)
from sqlalchemy.ext.declarative import (
    declarative_base,  # 经典声明式基类（非 2.0 风格），提供 metadata 和映射能力
)
from sqlalchemy.orm import relationship  # ORM 的关系导航，避免手动 JOIN，支持懒加载和反向引用

from app.utils.encryption import (  # 字段级加解密工具，敏感数据（API Key、凭证）入库前加密、出库后解密
    decrypt_data,
    encrypt_data,
)

Base = (
    declarative_base()
)  # 全局单例 Base，所有模型继承它，共享 metadata，create_all 一次性创建全部表


class EncryptedText(TypeDecorator):
    """
    加密文本字段类型
    自动处理文本的加密存储和解密读取

    设计原因：敏感字段（如 API Key、平台凭证）不能以明文存入数据库，
    但业务代码又不想每次读写时手动加解密。通过 SQLAlchemy 的 TypeDecorator
    机制，将加解密逻辑内嵌到类型系统中，对上层代码完全透明。
    """

    impl = Text()  # 底层存储类型仍然是 Text，加密后的密文也是字符串

    def process_bind_param(self, value, dialect):
        """存储时加密数据
        SQLAlchemy 在将 Python 对象写入数据库之前调用此方法，
        此时 value 还是明文，加密后存入 DB"""
        if value is not None:
            return encrypt_data(
                str(value)
            )  # str() 防御性转换：万一传入数字等非字符串类型也不会崩溃
        return value

    def process_result_value(self, value, dialect):
        """读取时解密数据
        SQLAlchemy 在从数据库读取结果后、返回给应用之前调用此方法，
        此时 value 是密文，解密后应用拿到的就是明文"""
        if value is not None:
            try:
                return decrypt_data(value)
            except Exception:
                return value  # 解密失败时返回原始值——可能是历史遗留的未加密数据，不应因解密异常导致整个请求崩溃
        return value


class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer, primary_key=True, index=True
    )  # 自增整型主键，单表百万级以下性能最优；加 index=True 是因为按 id 查询是最频繁操作
    username = Column(
        String(50), unique=True, index=True, nullable=False
    )  # 50 字符足够显示名使用；unique 防止重名混淆；index 加速登录查找
    email = Column(
        String(100), unique=True, index=True, nullable=True
    )  # nullable=True 而非 False：某些 OAuth 提供商不返回邮箱，允许为空更灵活
    password_hash = Column(
        String(255), nullable=False
    )  # 255 长度：bcrypt/argon2 哈希通常 60-100 字符，留足余量应对未来算法升级
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True
    )  # nullable=True：超级管理员可能不属于任何公司
    is_admin = Column(
        Boolean, default=False, nullable=False
    )  # 默认不是管理员——最小权限原则，管理员权限需要显式授予
    disabled = Column(
        Boolean, default=False, nullable=False
    )  # 软禁用而非删除：保留用户数据用于审计和追溯，同时阻止登录
    # is_active 是 disabled 的逻辑反字段（is_active = NOT disabled，True 表示启用）。
    # 历史上 users 表只存 disabled，但部分原生 SQL 查询与 API 响应字段使用 is_active 语义，
    # 缺少该列会导致 sqlite3.OperationalError: no such column: is_active。
    # 由迁移 006 补列并按 NOT disabled 回填历史值，保持两字段语义一致。
    is_active = Column(Boolean, default=True, nullable=False)
    bio = Column(Text, nullable=True)
    token_version = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime, default=datetime.utcnow
    )  # UTC 时间无时区，避免跨地域部署时的时间转换混乱

    # Relationships
    company = relationship(
        "Company", back_populates="users"
    )  # back_populates 实现双向关联：user.company 和 company.users 互相导航

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', company_id={self.company_id})>"


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 公司内部名称
    brand_name = Column(
        String(100), nullable=False
    )  # 品牌名称可能与公司名不同，如"字节跳动" vs "抖音"
    category = Column(String(50), nullable=False)  # 行业分类，用于 Agent 推荐和数据分析维度
    platforms_json = Column(
        Text, nullable=False
    )  # Text 而非 String(固定长度)：各公司对接的平台数量不同，JSON 灵活适应
    platform_credentials = Column(
        EncryptedText, nullable=True, default=None
    )  # 第三方平台密钥必须加密存储，防止数据库泄露直接暴露凭证
    llm_api_key = Column(
        EncryptedText, nullable=True, default=None
    )  # LLM API Key 同样是高价值敏感数据，加密是安全合规的基本要求
    subscription_status = Column(
        String(20), default="inactive"
    )  # 默认 inactive——要求主动订阅才能使用，避免未付费即享受服务
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="company")
    agents = relationship("Agent", back_populates="company")
    tasks = relationship("Task", back_populates="company")
    subscriptions = relationship("CompanySubscription", back_populates="company")

    def __repr__(self):
        return f"<Company(id={self.id}, name='{self.name}', brand_name='{self.brand_name}')>"


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )  # Agent 属于公司，不允许孤立 Agent 存在
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)  # Text：Agent 的能力描述可能很长，String 有截断风险
    tools_json = Column(
        Text, nullable=False
    )  # 工具列表用 JSON 存储，支持无需数据库迁移即可增删工具（热插拔）
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="agents")
    feedback_entries = relationship("Feedback", back_populates="agent")
    evolution_logs = relationship("EvolutionLog", back_populates="agent")
    source_tasks = relationship(
        "Task", foreign_keys="Task.source_agent_id", back_populates="source_agent"
    )  # 必须显式指定 foreign_keys，因为 Task 表还有其他外键指向 Agent 表

    def __repr__(self):
        return f"<Agent(id={self.id}, name='{self.name}', company_id={self.company_id})>"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    source_agent_id = Column(
        Integer, ForeignKey("agents.id"), nullable=True, index=True
    )  # nullable=True：系统任务可能无源 Agent，如手动创建的任务
    target_agent_name = Column(
        String(100), nullable=False
    )  # 目标 Agent 名称，用于跨 Agent 的任务路由
    task_description = Column(Text, nullable=False)
    status = Column(
        String(20), default="pending", nullable=False
    )  # 用 String 而非 SQL ENUM：更灵活，新状态无需 ALTER TABLE
    result = Column(
        Text, nullable=True
    )  # nullable=True：任务可能在 pending/processing 状态时尚无结果
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(
        DateTime, nullable=True
    )  # 仅在任务完成时设值，可用于计算任务耗时和 SLA 达标率

    # Relationships
    company = relationship("Company", back_populates="tasks")
    source_agent = relationship(
        "Agent", foreign_keys=[source_agent_id], back_populates="source_tasks"
    )  # 显式指定外键，避免与 Task 表中其他指向 Agent 的外键混淆

    def __repr__(self):
        return f"<Task(id={self.id}, status='{self.status}', company_id={self.company_id})>"


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False)  # 记录是哪个具体工具的反馈，便于针对性改进
    original_output = Column(
        Text, nullable=False
    )  # 必须保存原始输出，才能对比人工修改后的差异用于训练
    human_edited_output = Column(
        Text, nullable=True
    )  # nullable=True：有些反馈可能只是评分，不提供修改后的文本
    status = Column(
        String(20), default="pending", nullable=False
    )  # pending 表示未处理，需人工审核后才能用于模型改进
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    agent = relationship("Agent", back_populates="feedback_entries")

    def __repr__(self):
        return f"<Feedback(id={self.id}, agent_id={self.agent_id}, status='{self.status}')>"


class EvolutionLog(Base):
    __tablename__ = "evolution_log"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    tool_name = Column(
        String(100), nullable=True
    )  # nullable=True：进化建议可能不针对特定工具，而是通用性改进
    suggestion_text = Column(
        Text, nullable=False
    )  # 进化建议内容，不可为空——没有建议内容就没有记录意义
    training_data_path = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    applied = Column(
        Boolean, default=False, nullable=False
    )  # 默认未应用：改进建议不应自动生效，需人工审核后手动标记

    # Relationships
    agent = relationship("Agent", back_populates="evolution_logs")

    def __repr__(self):
        return f"<EvolutionLog(id={self.id}, agent_id={self.agent_id}, applied={self.applied})>"


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 套餐名称，面向用户的展示字段
    description = Column(Text, nullable=True)  # nullable=True：简单套餐可能不需要描述
    price_per_month = Column(Float, nullable=False)  # Float 而非 Integer：支持 9.99 元等非整数定价
    capabilities = Column(
        Text, nullable=True
    )  # JSON 存储能力列表，不同套餐的能力项不同，Text+JSON 比多对多关系表更简洁
    is_active = Column(
        Boolean, default=True
    )  # 软删除标志：下架套餐后历史订阅记录仍能找到对应的 Plan
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("CompanySubscription", back_populates="plan")

    def __repr__(self):
        return f"<SubscriptionPlan(id={self.id}, name='{self.name}', price={self.price_per_month})>"


class CompanySubscription(Base):
    __tablename__ = "company_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    plan_id = Column(
        Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True
    )  # 关联到具体套餐，通过 plan 关系可获取价格和能力
    agent_name = Column(
        String(100), nullable=False
    )  # 订阅与具体 Agent 绑定：一个公司可能有多个 Agent，各 Agent 可订阅不同套餐
    status = Column(
        String(20), default="active"
    )  # active/cancelled/expired，用于计费逻辑和权限判断
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)  # nullable=True：续订中的订阅没有确定的结束日期
    auto_renew = Column(Boolean, default=False)  # 默认不自动续费——财务敏感操作应由用户主动确认
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")

    def __repr__(self):
        return f"<CompanySubscription(id={self.id}, company_id={self.company_id}, status='{self.status}')>"


class CompanyAgentTool(Base):
    """公司级 MCP 工具开关（热插拔支持）
    设计原因：不同公司可能需要启用/禁用特定的 Agent 工具，
    用独立表管理开关而不是在 Agent 的 tools_json 中硬写，支持运行时热插拔无需重启服务"""

    __tablename__ = "company_agent_tools"

    id = Column(
        Integer, primary_key=True, autoincrement=True
    )  # autoincrement 显式声明，确保 SQLite 兼容性
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    agent_name = Column(String(50), nullable=False)
    tool_name = Column(String(100), nullable=False)
    enabled = Column(
        Boolean, default=True
    )  # 默认启用：新工具上线后自动对公司可见，降低手动配置成本
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "agent_name", "tool_name", name="uq_company_agent_tool"
        ),  # 三元组唯一：防止同一公司同一 Agent 下重复添加同一工具
    )

    def __repr__(self):
        return f"<CompanyAgentTool(id={self.id}, company_id={self.company_id}, tool_name='{self.tool_name}', enabled={self.enabled})>"


class CompanyAgentSkill(Base):
    """公司级 Skill 开关
    设计原因：与 Tool 开关同理，Skill 也需要按公司粒度独立控制启停"""

    __tablename__ = "company_agent_skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    agent_name = Column(String(50), nullable=False)
    skill_name = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True)  # 默认启用，降低手动干预频率
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "agent_name", "skill_name", name="uq_company_agent_skill"
        ),  # 三元组唯一约束，防止重复配置
    )

    def __repr__(self):
        return f"<CompanyAgentSkill(id={self.id}, company_id={self.company_id}, skill_name='{self.skill_name}', enabled={self.enabled})>"


class TaskBoard(Base):
    """任务看板 - 管理项目任务状态
    设计原因：Task 表偏向 Agent 间任务流转，TaskBoard 面向项目管理视图，
    支持父子任务层级和看板状态（待办/进行中/已完成）"""

    __tablename__ = "task_board"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    project_name = Column(String(100), nullable=False)  # 所属项目，用于分组和过滤
    task_description = Column(Text, nullable=False)
    assigned_agent = Column(
        String(50), nullable=False
    )  # 字符串引用 Agent 名而非 FK：支持 Agent 被删除后任务仍然可追溯
    status = Column(
        String(20), default="pending", nullable=False
    )  # String 而非 ENUM：新增状态无需 DDL 变更
    priority = Column(
        Integer, default=2, nullable=False
    )  # 默认中等优先级(2/5)——避免所有任务都是最高/最低，中位默认值最合理
    parent_task_id = Column(
        Integer, ForeignKey("task_board.id"), nullable=True, index=True
    )  # 自引用外键支持父子任务拆分
    result_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow
    )  # 独立于 created_at，支持按最近修改时间排序

    # Relationships
    parent_task = relationship(
        "TaskBoard", remote_side=[id]
    )  # remote_side 必须指定：自引用关系需要告诉 ORM "远端"是哪一侧（父任务端）

    def __repr__(self):
        return (
            f"<TaskBoard(id={self.id}, project_name='{self.project_name}', status='{self.status}')>"
        )


class ResultCache(Base):
    """结果缓存 - 缓存 Agent 执行结果
    设计原因：避免相同输入重复调用 Agent（尤其是 LLM），节省 API 费用和响应时间"""

    __tablename__ = "result_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    project_id = Column(Integer, nullable=True)  # nullable=True：缓存可能跨项目共享（如通用性查询）
    agent_name = Column(String(50), nullable=False)
    task_type = Column(
        String(50), nullable=False
    )  # 任务类型用于缓存键匹配：不同任务类型即便输入相同，输出语义也不同
    input_summary = Column(
        Text, nullable=False
    )  # 输入摘要作为缓存键，需要不可为空——没有输入就没有缓存的匹配依据
    output_summary = Column(Text, nullable=False)
    key_data = Column(Text, nullable=True)  # JSON 格式的键值数据，灵活适应不同任务类型的输出结构
    file_paths = Column(Text, nullable=True)  # JSON 格式文件路径列表，输出可能包含多个生成文件
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ResultCache(id={self.id}, agent_name='{self.agent_name}', task_type='{self.task_type}')>"


class DecisionLog(Base):
    """决策日志 - 记录 Agent 的关键决策
    设计原因：AI Agent 的决策过程需要可审计、可追溯，
    记录所有备选方案和最终选择的理由，便于事后分析和模型优化"""

    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    project_id = Column(Integer, nullable=True)
    agent_name = Column(String(50), nullable=False)
    decision_point = Column(Text, nullable=False)  # 决策节点描述，如"选择小红书笔记主图"
    options_considered = Column(
        Text, nullable=False
    )  # JSON 格式备选方案列表，保留完整上下文用于审计
    chosen_option = Column(String(200), nullable=False)  # 最终选择的方案简称（200 字符足够描述）
    reasoning = Column(Text, nullable=True)  # nullable=True：简单决策可能不需要额外解释
    outcome = Column(
        String(20), default="pending", nullable=False
    )  # pending/success/failed——用于回测决策质量
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DecisionLog(id={self.id}, agent_name='{self.agent_name}', decision_point='{self.decision_point[:30]}')>"


class FeedbackLog(Base):
    """用户反馈日志 - 记录用户对 Agent 输出的反馈
    设计原因：用户反馈是 Agent 进化的核心数据源，
    记录原始输出、用户反馈内容和评分，形成训练数据集"""

    __tablename__ = "feedback_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)  # nullable=True：支持匿名用户反馈
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    agent_name = Column(String(50), nullable=False)
    task_type = Column(String(50), nullable=False)  # 记录任务类型，便于按场景分析 Agent 表现
    original_output = Column(Text, nullable=False)  # 原始输出不可为空——没有原输出就无从对比改进
    user_feedback = Column(Text, nullable=True)  # nullable=True：用户可能只评分不写文字反馈
    rating = Column(
        Integer, nullable=True
    )  # 1-5 李克特量表，用于量化满意度；nullable=True 表示可不评分
    corrected_output = Column(Text, nullable=True)  # 用户修正后的输出，是 RLHF 训练数据的理想来源
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<FeedbackLog(id={self.id}, agent_name='{self.agent_name}', rating={self.rating})>"


class SkillEvolutionLog(Base):
    """Skill 进化记录 - 记录 Skill 的改进历史
    设计原因：Skill 的每次改进都需要版本化管理，
    方便回滚和追溯每次变更的触发原因和效果"""

    __tablename__ = "skill_evolution_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_name = Column(String(100), nullable=False)
    version = Column(
        String(20), nullable=False
    )  # 语义化版本号，如 "1.2.0"，比纯数字更能表达变更程度
    improvement_suggestion = Column(Text, nullable=False)  # 改进建议正文，不可为空
    trigger_reason = Column(Text, nullable=True)  # nullable=True：触发原因可能不明确（如手动触发）
    applied = Column(
        Boolean, default=False, nullable=False
    )  # 默认未应用：改进不应自动生效，需人工审核
    applied_at = Column(DateTime, nullable=True)  # 仅在 applied=True 时设值，记录实际部署时间

    def __repr__(self):
        return f"<SkillEvolutionLog(id={self.id}, skill_name='{self.skill_name}', version='{self.version}', applied={self.applied})>"


class UserBehavior(Base):
    """用户行为 - 记录用户的操作行为
    设计原因：产品迭代需要数据支撑，记录用户行为用于漏斗分析、功能使用频率统计、
    用户画像构建；session_id 将离散操作关联为完整会话"""

    __tablename__ = "user_behavior"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, nullable=True
    )  # nullable=True：匿名用户（未登录访客）的行为也需要记录
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    action_type = Column(
        String(50), nullable=False
    )  # 如 chat/tool_call/feedback——枚举值用于分组统计
    action_detail = Column(Text, nullable=True)  # JSON 格式，不同 action_type 的详情结构不同
    session_id = Column(String(50), nullable=True)  # 将同一会话内的多次操作串联为完整用户旅程
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserBehavior(id={self.id}, user_id={self.user_id}, action_type='{self.action_type}')>"


class UserLora(Base):
    """DEPRECATED: LoRA 功能已移除（T2.6），企业版/未来再启用。表保留以容纳历史数据，请勿新增写入。
    历史用途：用户 LoRA 适配器记录 - 记录用户个性化微调模型，
    设计原因：每个用户可能有自己专属的 LoRA 微调权重，
    需要记录模型路径、基座模型和训练信息以便管理和切换"""

    __tablename__ = "user_lora"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)  # LoRA 必须绑定用户，不允许匿名
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    lora_path = Column(String(255), nullable=False)  # 文件系统路径，255 足够常见的路径长度
    base_model = Column(
        String(100), nullable=False
    )  # 基座模型名，如 "qwen-7b"——LoRA 必须与基座匹配才能加载
    training_samples_count = Column(
        Integer, default=0, nullable=False
    )  # 0 表示尚未训练，非 0 表示训练样本数，用于评估模型质量
    last_trained_at = Column(DateTime, nullable=True)  # nullable=True：可能从未被训练过
    is_active = Column(
        Boolean, default=True, nullable=False
    )  # 一个用户可能有多个 LoRA，但只有一个是当前激活的

    def __repr__(self):
        return f"<UserLora(id={self.id}, user_id={self.user_id}, base_model='{self.base_model}', is_active={self.is_active})>"


class A2AMessage(Base):
    """A2A Agent-to-Agent 消息表
    设计原因：Agent 间需要异步通信和任务委托，
    message_id 唯一性保证消息幂等——重试不会重复处理"""

    __tablename__ = "a2a_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(
        String(64), unique=True, nullable=False
    )  # 64 字符唯一 ID（类 UUID），unique 约束保证幂等性
    sender_agent_name = Column(String(100), nullable=False)
    recipient_agent_name = Column(
        Text, nullable=False
    )  # Text 而非 String：接收方可能是逗号分隔的多个 Agent 名称，长度不可预测
    task_description = Column(Text, nullable=False)
    task_type = Column(String(50), nullable=False)
    payload = Column(Text, nullable=True)  # JSON 格式的可选附加数据，灵活传递上下文
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)  # 用于计算消息处理耗时，监控 Agent 通信延迟

    def __repr__(self):
        return f"<A2AMessage(id={self.id}, message_id='{self.message_id}', status='{self.status}')>"


class Workflow(Base):
    """工作流表
    设计原因：多 Agent 协作需要编排为工作流 DAG，
    definition_json 存储完整的工作流定义，result_json 存储执行后的输出"""

    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    definition_json = Column(Text, nullable=False)  # 工作流 DAG 定义，JSON 序列化，不可为空
    result_json = Column(Text, nullable=True)  # nullable=True：工作流执行前无结果
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)  # 用于计算工作流总耗时

    def __repr__(self):
        return f"<Workflow(id={self.id}, name='{self.name}', status='{self.status}')>"


# ============================================================
# 新增表（MVP 阶段 - Task 1.1）
# ============================================================


class Conversation(Base):
    """对话会话表 — 管理用户的多轮对话会话"""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False, default="新对话")
    status = Column(String(20), nullable=False, default="active")
    message_count = Column(Integer, nullable=False, default=0)
    last_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", backref="conversations")
    company = relationship("Company", backref="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    # 复合索引：会话列表按 company_id 过滤 + updated_at 倒序分页，单列索引无法覆盖排序
    __table_args__ = (Index("ix_conversations_company_updated", "company_id", "updated_at"),)

    def __repr__(self):
        return f"<Conversation(id={self.id}, title='{self.title}', status='{self.status}')>"


class Message(Base):
    """对话消息表 — 存储每条对话消息的完整内容"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(String(30), nullable=False, default="text")
    metadata_json = Column(Text, nullable=True)
    references_json = Column(Text, nullable=True)
    trace_id = Column(String(64), nullable=True)
    token_count = Column(Integer, nullable=True)
    sequence_num = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    user = relationship("User", backref="messages")

    # 复合索引：会话内消息按 conversation_id 过滤 + sequence_num 排序，覆盖 WHERE + ORDER BY
    __table_args__ = (Index("ix_messages_conv_seq", "conversation_id", "sequence_num"),)

    def __repr__(self):
        return f"<Message(id={self.id}, role='{self.role}', content_type='{self.content_type}')>"


class KolProfile(Base):
    """达人档案表 — 存储达人基础信息与数据指标"""

    __tablename__ = "kol_profiles"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False)
    platform = Column(String(20), nullable=False)
    platform_uid = Column(String(100), nullable=True)
    followers = Column(Integer, nullable=False, default=0)
    engagement_rate = Column(Float, nullable=False, default=0)
    category = Column(String(50), nullable=False, default="其他")
    sub_category = Column(String(50), nullable=True)
    avg_views = Column(Integer, nullable=False, default=0)
    avg_likes = Column(Integer, nullable=False, default=0)
    avg_comments = Column(Integer, nullable=False, default=0)
    avg_shares = Column(Integer, nullable=False, default=0)
    price_range_low = Column(Integer, nullable=True)
    price_range_high = Column(Integer, nullable=True)
    location = Column(String(100), nullable=True)
    verified = Column(Boolean, nullable=False, default=False)
    bio = Column(Text, nullable=True)
    avatar_url = Column(String(500), nullable=True)
    contact_info = Column(Text, nullable=True)
    data_source = Column(String(50), nullable=False, default="manual")
    source_url = Column(String(1000), nullable=True)
    source_note = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "platform", "platform_uid", name="uq_kol_platform_uid"),
    )

    def __repr__(self):
        return f"<KolProfile(id={self.id}, name='{self.name}', platform='{self.platform}')>"


class KolSearchHistory(Base):
    """达人搜索历史表 — 记录用户的达人搜索历史"""

    __tablename__ = "kol_search_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query = Column(String(500), nullable=False)
    rewritten_query = Column(String(500), nullable=True)
    platform_filter = Column(String(20), nullable=True)
    category_filter = Column(String(50), nullable=True)
    result_count = Column(Integer, nullable=False, default=0)
    clicked_kol_ids = Column(Text, nullable=True)
    search_duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<KolSearchHistory(id={self.id}, query='{self.query[:30]}')>"


class ContentScript(Base):
    """内容脚本表 — 存储 Agent 产出的内容脚本"""

    __tablename__ = "content_scripts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id = Column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title = Column(String(200), nullable=False)
    script_type = Column(String(30), nullable=False, default="livestream")
    platform = Column(String(20), nullable=True)
    content = Column(Text, nullable=False)
    segments_json = Column(Text, nullable=True)
    products_json = Column(Text, nullable=True)
    kol_name = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    review_comment = Column(Text, nullable=True)
    reviewed_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at = Column(DateTime, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ContentScript(id={self.id}, title='{self.title}', status='{self.status}')>"


class LogisticsTracking(Base):
    """物流跟踪表 — 记录样品物流跟踪信息"""

    __tablename__ = "logistics_tracking"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracking_number = Column(String(100), nullable=False)
    carrier = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    status_detail = Column(String(200), nullable=True)
    origin = Column(String(200), nullable=True)
    destination = Column(String(200), nullable=True)
    estimated_delivery = Column(DateTime, nullable=True)
    actual_delivery = Column(DateTime, nullable=True)
    kol_name = Column(String(100), nullable=True)
    sample_name = Column(String(200), nullable=True)
    tracking_history = Column(Text, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<LogisticsTracking(id={self.id}, tracking_number='{self.tracking_number}', carrier='{self.carrier}')>"


class ReviewApproval(Base):
    """审核确认记录表 — 记录所有审核确认操作，用于审计追溯"""

    __tablename__ = "review_approvals"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_type = Column(String(30), nullable=False)
    content_id = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    comment = Column(Text, nullable=True)
    previous_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ReviewApproval(id={self.id}, content_type='{self.content_type}', action='{self.action}')>"


class EmbeddingConfig(Base):
    """嵌入服务配置表 — 每公司一条配置，支持本地/API 多模式热切换
    设计原因：T1.2 的 REST API 原本用进程内 dict 临时存储配置，重启即丢。
    此表持久化各公司的嵌入模式与 API 凭证，配合 EncryptedText 保证 API Key 加密落盘。
    company_id 加 unique 约束：业务上每公司只允许一份当前生效配置，避免多份配置歧义。"""

    __tablename__ = "embedding_config"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True
    )  # unique=True 强制每公司一条
    mode = Column(
        String(20), nullable=False, default="local"
    )  # local / api_siliconflow / api_deepseek / api_openai，与 EmbeddingMode 枚举对齐
    api_base_url = Column(String(500), nullable=True)  # nullable=True：local 模式下不需要此字段
    api_key = Column(
        EncryptedText, nullable=True, default=None
    )  # 复用 EncryptedText：API Key 必须加密落盘，与 company.llm_api_key 同等保护级别
    model_name = Column(
        String(100), nullable=True
    )  # nullable=True：local 模式由 EMBEDDING_MODEL_REGISTRY 决定，不需要此字段
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow
    )  # 配置每次 PUT 更新时刷新，便于排查"配置何时被改"的问题

    def __repr__(self):
        return f"<EmbeddingConfig(id={self.id}, company_id={self.company_id}, mode='{self.mode}')>"


class CostRecord(Base):
    """费用记录表 — 记录每次 LLM 调用产生的 token 用量与成本
    设计原因：多租户场景下需按 company_id 隔离计费数据，供仪表盘与配额告警查询。
    表结构对应 alembic 001_initial_schema 中的 cost_records 表，task_type 列由 004_p4_cost_audit 迁移追加。"""

    __tablename__ = "cost_records"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )  # 按 company_id 查询最频繁，必须建索引
    agent_key = Column(String(50), nullable=True)  # nullable=True：部分调用可能未绑定具体 Agent
    model_name = Column(String(100), nullable=False)
    provider = Column(String(30), nullable=False)  # 提供商，用于按厂商维度统计成本分布
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)  # 美元成本，Float 满足精度需求且与 cost_tracker 一致
    task_type = Column(
        String(50), nullable=True
    )  # 任务类型归因（chat/tool_call/rag），由 004 迁移追加
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<CostRecord(id={self.id}, company_id={self.company_id}, model_name='{self.model_name}')>"


class LLMUsage(Base):
    """兼容旧 CostTracker 的 LLM 用量表。

    现有成本归因主表是 cost_records，但 app.tracking.cost_tracker 仍用于本地和
    管理端汇总，写入 llm_usage。将表纳入 ORM metadata，避免新环境/旧 SQLite
    因缺表产生 OperationalError。
    """

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(100), nullable=False, index=True)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    request_id = Column(String(100), nullable=True, index=True)
    agent_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<LLMUsage(id={self.id}, model_name='{self.model_name}', cost={self.cost})>"


class EvolutionReview(Base):
    """进化审核表 — 存储 Agent 进化建议的人工审核记录
    设计原因：进化建议需人工审核后才能应用到 Agent，避免错误建议直接生效。
    对应 alembic 001_initial_schema 中的 evolution_reviews 表。
    注意：agent_id 与 reviewed_by 在迁移中仅为 Integer（非外键），保留为普通列以匹配 DB schema。"""

    __tablename__ = "evolution_reviews"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(
        Integer, nullable=False, index=True
    )  # 迁移中非 FK，但按 agent_id 查询频繁，仍建索引
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True
    )  # nullable=True：部分建议可能跨公司共享
    tool_name = Column(String(100), nullable=True)  # nullable=True：通用性建议不针对特定工具
    suggestion_text = Column(Text, nullable=True)
    knowledge_entries = Column(Text, nullable=True)  # JSON 格式的知识条目变更
    prompt_changes = Column(Text, nullable=True)  # JSON 格式的提示词变更
    status = Column(String(20), default="pending")  # pending/approved/rejected，审核状态机
    reviewed_by = Column(Integer, nullable=True)  # 审核人 ID，迁移中非 FK
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<EvolutionReview(id={self.id}, agent_id={self.agent_id}, status='{self.status}')>"


class PlatformToken(Base):
    """平台 OAuth Token 表 — 存储各公司通过 OAuth 授权获取的平台访问令牌

    设计原因：Company.platform_credentials 以 EncryptedText JSON 存储全部凭证，
    适合读写但不便于按 expires_at 进行定时扫描刷新。将 token 独立建表后：
    - 定时刷新任务可高效查询即将过期的 token（按 expires_at 索引）
    - token 与凭证分离，刷新时只更新此表 + 同步写回 credentials JSON
    - access_token / refresh_token 复用 EncryptedText 加密落盘
    """

    __tablename__ = "platform_tokens"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform = Column(
        String(50), nullable=False, index=True
    )  # taobao / douyin_shop / pinduoduo_open
    access_token = Column(EncryptedText, nullable=True, default=None)  # 加密存储 access_token
    refresh_token = Column(EncryptedText, nullable=True, default=None)  # 加密存储 refresh_token
    expires_at = Column(
        DateTime, nullable=True, index=True
    )  # access_token 过期时间（UTC），定时扫描依据
    refresh_expires_at = Column(DateTime, nullable=True)  # refresh_token 过期时间（UTC）
    updated_at = Column(DateTime, default=datetime.utcnow)  # 最近一次刷新时间

    __table_args__ = (
        UniqueConstraint(
            "company_id", "platform", name="uq_platform_token_company_platform"
        ),  # 每公司每平台一条 token
    )

    def __repr__(self):
        return f"<PlatformToken(id={self.id}, company_id={self.company_id}, platform='{self.platform}')>"


class BrowserConnectorEvent(Base):
    """Sanitized read-only capture events received from the browser connector."""

    __tablename__ = "browser_connector_events"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    source = Column(String(80), nullable=False)
    platform = Column(String(50), nullable=False, index=True)
    matched_rule = Column(String(120), nullable=False, index=True)
    api_url_hash = Column(String(64), nullable=False)
    api_method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=True)
    response_mime = Column(String(120), nullable=True)
    sanitized_payload_json = Column(Text, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    duplicate_of_event_id = Column(Integer, ForeignKey("browser_connector_events.id"), nullable=True)
    captured_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "payload_hash", name="uq_browser_connector_event_payload"),
    )

    def __repr__(self):
        return (
            f"<BrowserConnectorEvent(id={self.id}, company_id={self.company_id}, "
            f"platform='{self.platform}', matched_rule='{self.matched_rule}')>"
        )
