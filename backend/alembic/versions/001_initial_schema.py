# ============================================
# Alembic 数据库迁移脚本 - 初始数据库结构
# ============================================
# 文件作用：
# 这是项目的"第一个版本"数据库迁移脚本，用于创建所有初始数据表。
# 当你第一次部署项目或运行 alembic upgrade 时，会执行这个脚本创建数据库结构。
#
# 什么是迁移脚本？
# 迁移脚本就像"数据库的版本记录"，记录了数据库结构从无到有的过程。
# Alembic 通过执行这些脚本，让不同环境的数据库保持相同的结构。
#
# 文件命名规则：
# - 001_initial_schema.py: 这是第 001 个版本，用于初始化数据库
# - revision ID: '001_initial' 是这个版本的唯一标识符
# - down_revision: None 表示这是第一个版本，没有上一个版本
#
# 核心函数：
# - upgrade(): 执行这个函数会"升级"数据库结构（创建表、添加字段）
# - downgrade(): 执行这个函数会"降级"数据库结构（删除表、删除字段）
# ============================================


# 文档字符串：描述这个迁移脚本的基本信息
"""initial schema

Revision ID: 001_initial
Revises: （表示这个版本基于哪个版本，None 表示是最早的版本）
Create Date: 2026-05-29 （创建日期）

Full PostgreSQL schema with all AgentX models.
（完整的 PostgreSQL 数据库结构，包含所有 AgentX 模型）
"""

# 导入类型提示相关的 Sequence 类，用于类型注解
from collections.abc import Sequence

# 导入 SQLAlchemy 库，简写为 sa，方便后续使用
# SQLAlchemy 是 Python 中最流行的 ORM（对象关系映射）库
# 用于用 Python 代码描述数据库结构
import sqlalchemy as sa

# 导入 Alembic 的 op 对象，op 提供了创建表、字段、索引等数据库操作
# op 是 "operations" 的缩写，意为"操作"
from alembic import op

# ============================================
# 版本标识部分
# ============================================

# revision: 这个迁移脚本的唯一标识符，类似于 Git 的 commit hash
revision: str = '001_initial'

# down_revision: 这个版本"基于"哪个版本
# None 表示这是第一个版本，没有父版本
# 如果有下一个版本，它的 down_revision 应该指向 '001_initial'
down_revision: str | None = None

# branch_labels: 用于创建分支的标签，这里设置为 None
branch_labels: str | Sequence[str] | None = None

# depends_on: 依赖于其他分支，用于解决复杂的版本依赖关系
depends_on: str | Sequence[str] | None = None


# ============================================
# upgrade() 函数 - 升级数据库结构
# ============================================
# 这个函数会在运行 "alembic upgrade head" 时被调用
# 函数的作用是"创建"所有数据表
# ============================================

def upgrade() -> None:
    # 创建 companies 表（公司/企业表）
    # 这个表存储所有注册的企业账户信息
    op.create_table(
        'companies',
        # id: 主键（Primary Key），每条记录的唯一标识符，类似于身份证号
        # sa.Integer(): 整数类型
        # autoincrement=True: 自动增长，每次插入新记录时 id 自动 +1
        # nullable=False: 不能为空（必填字段）
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # name: 公司名称
        # sa.String(100): 字符串类型，最多 100 个字符
        # nullable=False: 必填字段
        sa.Column('name', sa.String(100), nullable=False),
        
        # brand_name: 品牌名称（可选）
        sa.Column('brand_name', sa.String(100), nullable=True),
        
        # category: 公司类别（如"电商"、"教育"等）
        sa.Column('category', sa.String(50), nullable=True),
        
        # platforms_json: 平台配置（JSON 格式存储，可存储任意结构的数据）
        # sa.Text(): 文本类型，可以存储很长的字符串
        sa.Column('platforms_json', sa.Text(), nullable=True),
        
        # llm_api_key: LLM（大语言模型）的 API 密钥
        # 存储第三方 AI 服务的密钥，如 OpenAI、DeepSeek 等
        sa.Column('llm_api_key', sa.Text(), nullable=True),
        
        # platform_credentials: 平台凭证（加密存储）
        sa.Column('platform_credentials', sa.Text(), nullable=True),
        
        # encrypted_dek: 加密的数据密钥（DEK = Data Encryption Key）
        # 用于对敏感数据进行加密存储
        sa.Column('encrypted_dek', sa.Text(), nullable=True),
        
        # subscription_plan: 订阅计划
        # sa.String(20): 字符串，最多 20 个字符
        # default='starter': 默认值是 'starter'（入门版）
        sa.Column('subscription_plan', sa.String(20), default='starter'),
        
        # subscription_status: 订阅状态（active/paused/cancelled 等）
        sa.Column('subscription_status', sa.String(20), default='active'),
        
        # subscription_start: 订阅开始时间
        # sa.DateTime(): 日期时间类型
        sa.Column('subscription_start', sa.DateTime(), nullable=True),
        
        # subscription_end: 订阅结束时间
        sa.Column('subscription_end', sa.DateTime(), nullable=True),
        
        # daily_token_limit: 每日 Token 限额
        # Token 是 AI 模型的计费单位
        # default=1000000: 默认每日 100 万 Token
        sa.Column('daily_token_limit', sa.Integer(), default=1000000),
        
        # monthly_token_limit: 每月 Token 限额
        # default=30000000: 默认每月 3000 万 Token
        sa.Column('monthly_token_limit', sa.Integer(), default=30000000),
        
        # created_at: 创建时间
        # server_default=sa.func.now(): 由数据库服务器自动设置当前时间
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        # updated_at: 更新时间
        # onupdate=sa.func.now(): 当记录更新时自动更新时间
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        # PrimaryKeyConstraint: 定义主键
        # 主键是唯一标识每条记录的字段组合
        sa.PrimaryKeyConstraint('id'),
        
        # UniqueConstraint: 唯一约束，确保字段值不重复
        # uq_company_name: 公司名称不能重复
        sa.UniqueConstraint('name', name='uq_company_name'),
    )

    # 创建 users 表（用户表）
    # 这个表存储所有用户账户信息
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # username: 用户名（登录用）
        # nullable=False: 必填字段
        sa.Column('username', sa.String(50), nullable=False),
        
        # password_hash: 密码哈希
        # 不存储明文密码，只存储密码的"指纹"（哈希值）
        # 这样即使数据库泄露，攻击者也拿不到用户密码
        sa.Column('password_hash', sa.String(255), nullable=False),
        
        # email: 电子邮箱
        sa.Column('email', sa.String(100), nullable=True),
        
        # company_id: 所属公司 ID
        # sa.ForeignKey('companies.id'): 外键，引用 companies 表的 id 字段
        # 表示这个用户属于哪家公司
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=True),
        
        # is_admin: 是否是管理员
        # sa.Boolean(): 布尔类型，True 或 False
        sa.Column('is_admin', sa.Boolean(), default=False),
        
        # disabled: 账户是否被禁用
        sa.Column('disabled', sa.Boolean(), default=False),
        
        # refresh_token_jti: JWT 刷新令牌的 ID
        # 用于实现 token 续期功能
        sa.Column('refresh_token_jti', sa.String(64), nullable=True),
        
        # mfa_secret: 双因素认证（ MFA = Multi-Factor Authentication）的密钥
        sa.Column('mfa_secret', sa.String(32), nullable=True),
        
        # mfa_enabled: 是否启用了双因素认证
        sa.Column('mfa_enabled', sa.Boolean(), default=False),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        # 用户名不能重复
        sa.UniqueConstraint('username', name='uq_user_username'),
        # 邮箱不能重复（但可以为 NULL，因为 nullable=True）
        sa.UniqueConstraint('email', name='uq_user_email'),
    )

    # 创建 agents 表（AI Agent 表）
    # 这个表存储 AI Agent 的配置信息
    op.create_table(
        'agents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 所属公司（每个公司的 Agent 配置是独立的）
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # name: Agent 名称
        sa.Column('name', sa.String(50), nullable=False),
        
        # description: Agent 描述
        sa.Column('description', sa.Text(), nullable=True),
        
        # tools_json: Agent 使用的工具列表
        # sa.Text(): 存储 JSON 格式的字符串，如 '["tool1", "tool2"]'
        # server_default='[]': 默认值是空数组
        sa.Column('tools_json', sa.Text(), nullable=False, server_default='[]'),
        
        # skills_json: Agent 掌握的技能配置
        # server_default='{}': 默认值是空对象
        sa.Column('skills_json', sa.Text(), nullable=True, server_default='{}'),
        
        # system_prompt: 系统提示词
        # 用于定义 Agent 的行为准则和角色设定
        sa.Column('system_prompt', sa.Text(), nullable=True),
        
        # model_provider: 使用的 AI 模型提供商
        # default='deepseek': 默认使用 DeepSeek 模型
        sa.Column('model_provider', sa.String(30), default='deepseek'),
        
        # model_name: 具体使用的模型名称
        sa.Column('model_name', sa.String(100), default='deepseek-chat'),
        
        # is_custom: 是否是自定义 Agent
        sa.Column('is_custom', sa.Boolean(), default=False),
        
        # is_active: Agent 是否启用
        sa.Column('is_active', sa.Boolean(), default=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        # 同一公司下的 Agent 名称不能重复
        sa.UniqueConstraint('company_id', 'name', name='uq_company_agent_name'),
    )

    # 创建 tasks 表（任务表）
    # 这个表存储所有任务记录，包括状态、结果、步骤等
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 所属公司
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # source_agent_id: 发送任务的 Agent ID
        sa.Column('source_agent_id', sa.Integer(), sa.ForeignKey('agents.id'), nullable=True),
        
        # target_agent_name: 目标 Agent 的名称
        # （某些情况下可能只知道名称，不知道具体 ID）
        sa.Column('target_agent_name', sa.String(50), nullable=True),
        
        # task_description: 任务描述（必填）
        sa.Column('task_description', sa.Text(), nullable=False),
        
        # status: 任务状态
        # 常见状态：pending（待处理）、running（执行中）、completed（已完成）、failed（失败）
        sa.Column('status', sa.String(20), default='pending'),
        
        # result: 任务执行结果
        sa.Column('result', sa.Text(), nullable=True),
        
        # steps_json: 任务执行的步骤记录（JSON 格式）
        # 记录任务执行的每个步骤，便于调试和追溯
        sa.Column('steps_json', sa.Text(), nullable=True),
        
        # review_status: 审核状态
        # 用于需要人工审核的任务
        sa.Column('review_status', sa.String(20), nullable=True),
        
        # review_level: 审核级别
        sa.Column('review_level', sa.String(20), nullable=True),
        
        # priority: 优先级（数字越大优先级越高）
        sa.Column('priority', sa.Integer(), default=0),
        
        # retry_count: 当前重试次数
        sa.Column('retry_count', sa.Integer(), default=0),
        
        # max_retries: 最大重试次数
        sa.Column('max_retries', sa.Integer(), default=3),
        
        # scheduled_for: 计划执行时间
        # 用于定时任务的调度
        sa.Column('scheduled_for', sa.DateTime(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        # completed_at: 完成时间
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 feedback 表（反馈表）
    # 这个表存储用户对 Agent 输出结果的反馈，用于改进 Agent 能力
    op.create_table(
        'feedback',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # session_id: 对话会话 ID
        # 用于将反馈与特定对话关联
        sa.Column('session_id', sa.String(100), nullable=False),
        
        # tool_name: 工具名称
        # 记录用户对哪个工具的输出提供了反馈
        sa.Column('tool_name', sa.String(100), nullable=False),
        
        # original_output: Agent 原始输出
        sa.Column('original_output', sa.Text(), nullable=False),
        
        # human_edited_output: 人工修正后的输出
        # 如果用户不满意原始输出，会提供修正版本
        sa.Column('human_edited_output', sa.Text(), nullable=True),
        
        # kol_name: KOL（关键意见领袖）名称
        # KOL 是指在特定领域有影响力的人
        sa.Column('kol_name', sa.String(100), nullable=True),
        
        # product_name: 产品名称
        sa.Column('product_name', sa.String(100), nullable=True),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.String(50), nullable=True),
        
        # agent_id: Agent ID
        sa.Column('agent_id', sa.Integer(), nullable=True),
        
        # rating: 评分（1-5 分）
        sa.Column('rating', sa.Integer(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 a2a_messages 表（Agent-to-Agent 消息表）
    # 这个表存储不同 Agent 之间相互通信的消息
    op.create_table(
        'a2a_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # sender: 发送者名称
        sa.Column('sender', sa.String(50), nullable=False),
        
        # recipients: 接收者列表（JSON 格式）
        # 因为可能有多个接收者，所以用 JSON 数组存储
        sa.Column('recipients', sa.Text(), nullable=False),
        
        # task: 任务描述
        sa.Column('task', sa.Text(), nullable=False),
        
        # task_type: 任务类型
        # 如 "chat"（聊天）、"tool_call"（工具调用）等
        sa.Column('task_type', sa.String(50), nullable=False),
        
        # company_id: 公司 ID（用于多租户隔离）
        sa.Column('company_id', sa.Integer(), nullable=True),
        
        # payload_json: 附加数据（JSON 格式）
        sa.Column('payload_json', sa.Text(), nullable=True),
        
        # status: 消息状态
        sa.Column('status', sa.String(20), default='pending'),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 evolution_logs 表（Agent 进化日志表）
    # 这个表记录 Agent 的"学习"过程
    # 当 Agent 发现可以改进的地方时，会记录下来供后续优化
    op.create_table(
        'evolution_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # agent_id: Agent ID
        sa.Column('agent_id', sa.Integer(), nullable=True),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=True),
        
        # tool_name: 相关的工具名称
        sa.Column('tool_name', sa.String(100), nullable=True),
        
        # change_type: 变更类型
        # 如 "prompt_optimization"（提示词优化）、"knowledge_added"（知识添加）等
        sa.Column('change_type', sa.String(50), nullable=False),
        
        # suggestion_text: 建议文本
        sa.Column('suggestion_text', sa.Text(), nullable=True),
        
        # prompt_changes: 提示词变更内容
        sa.Column('prompt_changes', sa.Text(), nullable=True),
        
        # knowledge_entries: 知识条目
        sa.Column('knowledge_entries', sa.Text(), nullable=True),
        
        # training_data_path: 训练数据路径
        sa.Column('training_data_path', sa.Text(), nullable=True),
        
        # confidence_score: 置信度分数（0-1 之间）
        # 表示这个改进建议的可信程度
        sa.Column('confidence_score', sa.Float(), nullable=True),
        
        # applied: 是否已应用
        # 进化建议需要审核后才能实际应用到 Agent
        sa.Column('applied', sa.Boolean(), default=False),
        
        # applied_at: 应用时间
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 evolution_reviews 表（进化审核表）
    # 这个表存储对 Agent 进化建议的审核记录
    op.create_table(
        'evolution_reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # agent_id: Agent ID
        sa.Column('agent_id', sa.Integer(), nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=True),
        
        # tool_name: 工具名称
        sa.Column('tool_name', sa.String(100), nullable=True),
        
        # suggestion_text: 建议文本
        sa.Column('suggestion_text', sa.Text(), nullable=True),
        
        # knowledge_entries: 知识条目
        sa.Column('knowledge_entries', sa.Text(), nullable=True),
        
        # prompt_changes: 提示词变更
        sa.Column('prompt_changes', sa.Text(), nullable=True),
        
        # status: 审核状态
        # 如 pending（待审核）、approved（已批准）、rejected（已拒绝）
        sa.Column('status', sa.String(20), default='pending'),
        
        # reviewed_by: 审核人 ID
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        
        # reviewed_at: 审核时间
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 workflows 表（工作流表）
    # 这个表存储复杂工作流的定义和执行结果
    op.create_table(
        'workflows',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # name: 工作流名称
        sa.Column('name', sa.String(100), nullable=False),
        
        # status: 工作流状态
        sa.Column('status', sa.String(20), default='pending'),
        
        # definition_json: 工作流定义（JSON 格式）
        # 描述工作流的步骤、条件、分支等
        sa.Column('definition_json', sa.Text(), nullable=False),
        
        # result_json: 执行结果（JSON 格式）
        sa.Column('result_json', sa.Text(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        # completed_at: 完成时间
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 alerts 表（告警表）
    # 这个表存储系统生成的各类告警信息
    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # alert_type: 告警类型
        # 如 "error"（错误）、"warning"（警告）、"info"（信息）
        sa.Column('alert_type', sa.String(50), nullable=False),
        
        # title: 告警标题
        sa.Column('title', sa.String(200), nullable=False),
        
        # message: 告警详情
        sa.Column('message', sa.Text(), nullable=True),
        
        # severity: 严重程度
        sa.Column('severity', sa.String(20), default='warning'),
        
        # is_read: 是否已读
        sa.Column('is_read', sa.Boolean(), default=False),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 company_knowledge 表（公司知识库表）
    # 这个表存储公司特有的知识，用于 RAG（检索增强生成）
    op.create_table(
        'company_knowledge',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # category: 知识分类
        sa.Column('category', sa.String(50), nullable=False),
        
        # title: 知识标题
        sa.Column('title', sa.String(200), nullable=False),
        
        # content: 知识内容
        sa.Column('content', sa.Text(), nullable=False),
        
        # embedding_id: 向量 ID
        # 用于在向量数据库（如 Milvus）中快速检索
        sa.Column('embedding_id', sa.String(64), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 memories 表（Agent 记忆表）
    # 这个表实现 Agent 的三层记忆系统
    op.create_table(
        'memories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), nullable=False),
        
        # agent_key: Agent 标识键
        sa.Column('agent_key', sa.String(50), nullable=False),
        
        # memory_type: 记忆类型
        # 如 "working"（工作记忆）、"short_term"（短期记忆）、"long_term"（长期记忆）
        sa.Column('memory_type', sa.String(20), nullable=False),
        
        # content: 记忆内容
        sa.Column('content', sa.Text(), nullable=False),
        
        # memory_id: 记忆唯一 ID
        sa.Column('memory_id', sa.String(64), nullable=True),
        
        # importance: 重要性分数（0-1 之间）
        # 用于决定哪些记忆应该保留更久
        sa.Column('importance', sa.Float(), default=0.5),
        
        # access_count: 访问次数
        # 经常被访问的记忆更重要
        sa.Column('access_count', sa.Integer(), default=0),
        
        # last_accessed: 最后访问时间
        sa.Column('last_accessed', sa.DateTime(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 cost_records 表（费用记录表）
    # 这个表记录 API 调用产生的费用
    op.create_table(
        'cost_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # agent_key: Agent 标识
        sa.Column('agent_key', sa.String(50), nullable=True),
        
        # model_name: 使用的模型名称
        sa.Column('model_name', sa.String(100), nullable=False),
        
        # provider: AI 服务提供商
        sa.Column('provider', sa.String(30), nullable=False),
        
        # input_tokens: 输入的 Token 数量
        sa.Column('input_tokens', sa.Integer(), default=0),
        
        # output_tokens: 输出的 Token 数量
        sa.Column('output_tokens', sa.Integer(), default=0),
        
        # cost_usd: 费用（美元）
        sa.Column('cost_usd', sa.Float(), default=0.0),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
    )

    # 创建 company_agent_tools 表（公司-Agent-工具关联表）
    # 这个表记录每个公司每个 Agent 启用了哪些工具
    op.create_table(
        'company_agent_tools',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # agent_name: Agent 名称
        sa.Column('agent_name', sa.String(50), nullable=False),
        
        # tool_name: 工具名称
        sa.Column('tool_name', sa.String(100), nullable=False),
        
        # enabled: 是否启用
        sa.Column('enabled', sa.Boolean(), default=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        # 同一公司、同一 Agent、同一工具的组合只能有一条记录
        sa.UniqueConstraint('company_id', 'agent_name', 'tool_name', name='uq_company_agent_tool'),
    )

    # 创建 company_agent_skills 表（公司-Agent-技能关联表）
    # 这个表记录每个公司每个 Agent 启用了哪些技能
    op.create_table(
        'company_agent_skills',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        
        # company_id: 公司 ID
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        
        # agent_name: Agent 名称
        sa.Column('agent_name', sa.String(50), nullable=False),
        
        # skill_name: 技能名称
        sa.Column('skill_name', sa.String(100), nullable=False),
        
        # enabled: 是否启用
        sa.Column('enabled', sa.Boolean(), default=True),
        
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        # 同一公司、同一 Agent、同一技能的组合只能有一条记录
        sa.UniqueConstraint('company_id', 'agent_name', 'skill_name', name='uq_company_agent_skill'),
    )

    # ============================================
    # 创建索引（Index）
    # ============================================
    # 索引类似于书的目录，可以加快查询速度
    # 但索引也会占用存储空间，所以只对常用的查询条件创建索引
    # ============================================

    # idx_tasks_company_status: 任务表的 公司ID+状态 索引
    # 用于查询某个公司的待处理任务
    op.create_index('idx_tasks_company_status', 'tasks', ['company_id', 'status'])

    # idx_tasks_target_agent: 任务表的 目标Agent+状态 索引
    # 用于查询某个 Agent 的待处理任务
    op.create_index('idx_tasks_target_agent', 'tasks', ['target_agent_name', 'status'])

    # idx_agents_company: Agent 表的 公司ID 索引
    # 用于查询某个公司的所有 Agent
    op.create_index('idx_agents_company', 'agents', ['company_id'])

    # idx_users_company: 用户表的 公司ID 索引
    # 用于查询某个公司的所有用户
    op.create_index('idx_users_company', 'users', ['company_id'])

    # idx_memories_company_agent: 记忆表的 公司ID+Agent+类型 索引
    # 用于快速检索某个 Agent 的记忆
    op.create_index('idx_memories_company_agent', 'memories', ['company_id', 'agent_key', 'memory_type'])

    # idx_cost_records_company: 费用记录表的 公司ID+时间 索引
    # 用于查询某个公司的费用记录
    op.create_index('idx_cost_records_company', 'cost_records', ['company_id', 'created_at'])

    # idx_evolution_logs_company: 进化日志表的 公司ID+时间 索引
    # 用于查询某个公司的进化历史
    op.create_index('idx_evolution_logs_company', 'evolution_logs', ['company_id', 'created_at'])


# ============================================
# downgrade() 函数 - 降级数据库结构
# ============================================
# 这个函数会在运行 "alembic downgrade -1" 时被调用
# 函数的作用是"删除"所有创建的表
# 注意：删除顺序很重要，必须先删除有外键依赖的表
# ============================================

def downgrade() -> None:
    # 删除表时需要注意依赖关系：
    # 被其他表引用的表（如 companies）必须最后删除
    # 否则会报错"无法删除，因为有其他表引用它"
    
    # 先删除 company_agent_skills（没有表依赖它）
    op.drop_table('company_agent_skills')
    
    # 再删除 company_agent_tools
    op.drop_table('company_agent_tools')
    
    # 再删除 cost_records
    op.drop_table('cost_records')
    
    # 再删除 memories
    op.drop_table('memories')
    
    # 再删除 company_knowledge
    op.drop_table('company_knowledge')
    
    # 再删除 alerts
    op.drop_table('alerts')
    
    # 再删除 workflows
    op.drop_table('workflows')
    
    # 再删除 evolution_reviews
    op.drop_table('evolution_reviews')
    
    # 再删除 evolution_logs
    op.drop_table('evolution_logs')
    
    # 再删除 a2a_messages
    op.drop_table('a2a_messages')
    
    # 再删除 feedback
    op.drop_table('feedback')
    
    # 再删除 tasks（依赖 agents 表）
    op.drop_table('tasks')
    
    # 再删除 agents（依赖 companies 表）
    op.drop_table('agents')
    
    # 再删除 users（依赖 companies 表）
    op.drop_table('users')
    
    # 最后删除 companies（被其他所有表引用）
    op.drop_table('companies')
