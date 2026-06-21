-- ============================================================
-- AgentX Platform 数据库设计
-- 版本: v1.0
-- 日期: 2026-06-20
-- 数据库: PostgreSQL 14+
-- 说明: 兼容 SQLAlchemy 2.0 ORM
-- ============================================================

-- ============================================================
-- 第一部分：现有表（本期保留不变，此处列出以展示完整关系）
-- 这些表已在 backend/app/database/models.py 中定义，
-- 通过 SQLAlchemy ORM 自动创建，此处不重复 CREATE TABLE
-- ============================================================
-- users, companies, agents, tasks, feedback, evolution_log,
-- subscription_plans, company_subscriptions, company_agent_tools,
-- company_agent_skills, task_board, result_cache, decision_log,
-- feedback_log, skill_evolution_log, user_behavior, user_lora,
-- a2a_messages, workflows
-- 详见: backend/app/database/models.py

-- ============================================================
-- 第二部分：本期新增表（MVP 阶段）
-- 这些表需要新增到 SQLAlchemy models.py 中
-- ============================================================

-- ============================================================
-- 2.1 对话会话表 (conversations)
-- 用途: 管理用户的多轮对话会话
-- 优先级: P0 Must Have
-- 关联: users (user_id), companies (company_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS conversations (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title           VARCHAR(200) NOT NULL DEFAULT '新对话',
    -- 对话标题，默认"新对话"，首条消息后自动生成为消息摘要
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    -- active: 活跃中, archived: 已归档, deleted: 已删除（软删除）
    message_count   INTEGER NOT NULL DEFAULT 0,
    -- 消息总数，冗余字段避免 COUNT 查询
    last_message    TEXT,
    -- 最后一条消息摘要，用于历史列表预览
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引：按用户 + 更新时间排序（历史列表最常用查询）
CREATE INDEX idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
-- 索引：按公司隔离（多租户）
CREATE INDEX idx_conversations_company ON conversations(company_id);


-- ============================================================
-- 2.2 对话消息表 (messages)
-- 用途: 存储每条对话消息的完整内容
-- 优先级: P0 Must Have
-- 关联: conversations (conversation_id), users (user_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id                SERIAL PRIMARY KEY,
    conversation_id   INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- 用户消息关联 user_id，Master 消息为 NULL
    role              VARCHAR(20) NOT NULL,
    -- user: 用户消息, master: Master 回复, system: 系统消息
    content           TEXT NOT NULL,
    -- 消息文本内容（Markdown 格式）
    content_type      VARCHAR(30) NOT NULL DEFAULT 'text',
    -- text: 纯文本, kol_list: 达人列表卡片, analysis_report: 分析报告,
    -- script: 内容脚本, logistics: 物流状态, plan: 执行计划
    metadata_json     JSONB,
    -- 结构化元数据，不同 content_type 对应不同 JSON 结构:
    --   kol_list:     { "kols": [...], "search_id": "xxx" }
    --   analysis_report: { "report_type": "roi", "data": {...} }
    --   script:       { "segments": [...], "products": [...], "status": "pending_review" }
    --   logistics:    { "tracking_number": "...", "carrier": "..." }
    --   plan:         { "steps": [...], "goal": "..." }
    references_json   JSONB,
    -- RAG 检索引用来源列表: [{"source_file": "品牌手册.pdf", "source_page": 3, "score": 0.95, "content": "..."}]
    trace_id          VARCHAR(64),
    -- 链路追踪 ID，关联 AgentRuntime 的执行 trace
    token_count       INTEGER,
    -- 该消息消耗的 Token 数量（用于成本统计）
    sequence_num      INTEGER NOT NULL DEFAULT 0,
    -- 消息在对话中的序号，保证顺序
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引：按对话 + 序号排序（加载对话历史）
CREATE INDEX idx_messages_conversation_seq ON messages(conversation_id, sequence_num);
-- 索引：按 trace_id 追踪（问题排查）
CREATE INDEX idx_messages_trace ON messages(trace_id);
-- 索引：按创建时间（数据归档）
CREATE INDEX idx_messages_created ON messages(created_at);


-- ============================================================
-- 2.3 达人档案表 (kol_profiles)
-- 用途: 存储达人基础信息与数据指标
-- 优先级: P0 Must Have
-- 关联: companies (company_id) - 达人数据按公司隔离
-- ============================================================
CREATE TABLE IF NOT EXISTS kol_profiles (
    id                SERIAL PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name              VARCHAR(100) NOT NULL,
    -- 达人名称
    platform          VARCHAR(20) NOT NULL,
    -- 平台: douyin / xiaohongshu / kuaishou / bilibili / weibo
    platform_uid      VARCHAR(100),
    -- 平台唯一 ID，用于去重和更新
    followers         INTEGER NOT NULL DEFAULT 0,
    -- 粉丝数
    engagement_rate   DECIMAL(5,2) NOT NULL DEFAULT 0,
    -- 互动率 (百分比)，如 3.50 表示 3.5%
    category          VARCHAR(50) NOT NULL DEFAULT '其他',
    -- 内容分类: 美妆 / 穿搭 / 美食 / 母婴 / 数码 / 其他
    sub_category      VARCHAR(50),
    -- 二级分类，更精细的标签
    avg_views         INTEGER NOT NULL DEFAULT 0,
    -- 近 30 天平均播放量
    avg_likes         INTEGER NOT NULL DEFAULT 0,
    -- 近 30 天平均点赞数
    avg_comments      INTEGER NOT NULL DEFAULT 0,
    -- 近 30 天平均评论数
    avg_shares        INTEGER NOT NULL DEFAULT 0,
    -- 近 30 天平均分享数
    price_range_low   INTEGER,
    -- 报价区间下限（元/条）
    price_range_high  INTEGER,
    -- 报价区间上限（元/条）
    location          VARCHAR(100),
    -- 所在城市
    verified          BOOLEAN NOT NULL DEFAULT FALSE,
    -- 是否认证
    bio               TEXT,
    -- 个人简介
    avatar_url        VARCHAR(500),
    -- 头像 URL
    contact_info      TEXT,
    -- 联系方式（加密存储）
    data_source       VARCHAR(50) NOT NULL DEFAULT 'manual',
    -- 数据来源: manual / api_crawl / agent_search
    last_synced_at    TIMESTAMP,
    -- 数据最后同步时间
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    -- 软删除标记
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),

    -- 同一公司 + 同一平台 + 同一平台 UID 唯一
    CONSTRAINT uq_kol_platform_uid UNIQUE (company_id, platform, platform_uid)
);

-- 索引：按公司 + 分类（达人搜索最常用）
CREATE INDEX idx_kol_company_category ON kol_profiles(company_id, category);
-- 索引：按粉丝数排序（达人排序）
CREATE INDEX idx_kol_followers ON kol_profiles(company_id, followers DESC);
-- 索引：按互动率排序（达人排序）
CREATE INDEX idx_kol_engagement ON kol_profiles(company_id, engagement_rate DESC);
-- 索引：全文搜索（达人名称）
CREATE INDEX idx_kol_name_trgm ON kol_profiles USING gin (name gin_trgm_ops);
-- 索引：按平台筛选
CREATE INDEX idx_kol_platform ON kol_profiles(company_id, platform);


-- ============================================================
-- 2.4 达人搜索历史表 (kol_search_history)
-- 用途: 记录用户的达人搜索历史，用于经验积累和推荐优化
-- 优先级: P1 Should Have
-- 关联: users (user_id), companies (company_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS kol_search_history (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    query           VARCHAR(500) NOT NULL,
    -- 原始搜索词
    rewritten_query VARCHAR(500),
    -- Query Rewriter 改写后的查询
    platform_filter VARCHAR(20),
    -- 平台筛选条件
    category_filter VARCHAR(50),
    -- 分类筛选条件
    result_count    INTEGER NOT NULL DEFAULT 0,
    -- 搜索结果数量
    clicked_kol_ids INTEGER[],
    -- 用户点击查看的达人 ID 列表（PostgreSQL 数组类型）
    search_duration_ms INTEGER,
    -- 搜索耗时（毫秒）
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引：按用户 + 时间（查询搜索历史）
CREATE INDEX idx_kol_search_user_time ON kol_search_history(user_id, created_at DESC);
-- 索引：按公司（多租户隔离）
CREATE INDEX idx_kol_search_company ON kol_search_history(company_id);


-- ============================================================
-- 2.5 内容脚本表 (content_scripts)
-- 用途: 存储 Agent 产出的内容脚本（直播脚本、种草文案等）
-- 优先级: P1 Should Have
-- 关联: conversations (conversation_id), messages (message_id), users (user_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS content_scripts (
    id                SERIAL PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id   INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    message_id        INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    -- 关联到产生该脚本的消息
    title             VARCHAR(200) NOT NULL,
    -- 脚本标题
    script_type       VARCHAR(30) NOT NULL DEFAULT 'livestream',
    -- livestream: 直播脚本, social_post: 种草文案, short_video: 短视频脚本
    platform          VARCHAR(20),
    -- 目标平台
    content           TEXT NOT NULL,
    -- 脚本完整内容（Markdown）
    segments_json     JSONB,
    -- 脚本分段: [{"segment": "开场", "duration": 120, "script": "..."}, ...]
    products_json     JSONB,
    -- 涉及产品: [{"name": "XX精华液", "usp": "..."}, ...]
    kol_name          VARCHAR(100),
    -- 关联达人名称
    status            VARCHAR(20) NOT NULL DEFAULT 'draft',
    -- draft: 草稿, pending_review: 待审核, approved: 已通过, rejected: 已驳回
    review_comment    TEXT,
    -- 审核意见（驳回时填写）
    reviewed_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- 审核人
    reviewed_at       TIMESTAMP,
    -- 审核时间
    version           INTEGER NOT NULL DEFAULT 1,
    -- 修改版本号
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引：按状态 + 公司（审核列表查询）
CREATE INDEX idx_scripts_status_company ON content_scripts(company_id, status);
-- 索引：按对话（从对话中查看脚本）
CREATE INDEX idx_scripts_conversation ON content_scripts(conversation_id);


-- ============================================================
-- 2.6 物流跟踪表 (logistics_tracking)
-- 用途: 记录样品物流跟踪信息
-- 优先级: P1 Should Have
-- 关联: companies (company_id), users (user_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS logistics_tracking (
    id                SERIAL PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tracking_number   VARCHAR(100) NOT NULL,
    -- 快递单号
    carrier           VARCHAR(50) NOT NULL,
    -- 快递公司: SF / YTO / ZTO / EMS / JD
    status            VARCHAR(30) NOT NULL DEFAULT 'pending',
    -- pending: 待发货, in_transit: 运输中, delivered: 已签收, exception: 异常
    status_detail     VARCHAR(200),
    -- 详细状态描述
    origin            VARCHAR(200),
    -- 发件地
    destination       VARCHAR(200),
    -- 收件地
    estimated_delivery TIMESTAMP,
    -- 预计送达时间
    actual_delivery   TIMESTAMP,
    -- 实际签收时间
    kol_name          VARCHAR(100),
    -- 关联达人名称
    sample_name       VARCHAR(200),
    -- 样品名称
    tracking_history  JSONB,
    -- 物流轨迹: [{"time": "...", "status": "...", "location": "..."}, ...]
    last_checked_at   TIMESTAMP,
    -- 最后查询时间
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引：按快递单号（唯一查询）
CREATE INDEX idx_logistics_tracking_number ON logistics_tracking(tracking_number);
-- 索引：按公司 + 状态（筛选待处理物流）
CREATE INDEX idx_logistics_company_status ON logistics_tracking(company_id, status);


-- ============================================================
-- 2.7 审核确认记录表 (review_approvals)
-- 用途: 记录所有审核确认操作，用于审计追溯
-- 优先级: P1 Should Have
-- 关联: companies (company_id), users (user_id)
-- ============================================================
CREATE TABLE IF NOT EXISTS review_approvals (
    id                SERIAL PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_type      VARCHAR(30) NOT NULL,
    -- 审核内容类型: script / report / plan / outreach_message
    content_id        INTEGER NOT NULL,
    -- 被审核内容的 ID（根据 content_type 关联不同表）
    action            VARCHAR(20) NOT NULL,
    -- approve: 通过, reject: 驳回, request_changes: 要求修改
    comment           TEXT,
    -- 审核意见
    previous_status   VARCHAR(30),
    -- 审核前状态
    new_status        VARCHAR(30) NOT NULL,
    -- 审核后状态
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引：按内容类型 + 内容 ID（查询某内容的审核历史）
CREATE INDEX idx_review_content ON review_approvals(content_type, content_id);
-- 索引：按公司 + 时间（审计日志）
CREATE INDEX idx_review_company_time ON review_approvals(company_id, created_at DESC);


-- ============================================================
-- 第三部分：关系说明
-- ============================================================

-- ┌──────────┐       ┌──────────────┐       ┌──────────┐
-- │  users   │──1:N──│conversations │──1:N──│ messages │
-- └──────────┘       └──────────────┘       └──────────┘
--       │                                            │
--       │                                     ┌──────┴──────┐
--       │                                     │  1:N        │
--       │                              ┌──────┴──────┐      │
--       │                              │   messages  │      │
--       │                              │ metadata_json│     │
--       │                              └──────┬──────┘      │
--       │                                     │ 引用        │
--       │                              ┌──────┴──────┐      │
--       │                              │content_scripts│    │
--       │                              └──────────────┘      │
--       │                                                    │
--       │──1:N──→ kol_search_history                         │
--       │──1:N──→ logistics_tracking                         │
--       │──1:N──→ review_approvals                           │
--                                                             │
-- ┌──────────┐                                               │
-- │companies │──1:N──→ kol_profiles                          │
-- └──────────┘                                               │
--       │                                                     │
--       │──1:N──→ conversations                               │
--       │──1:N──→ content_scripts                             │
--       │──1:N──→ logistics_tracking                          │
--       │──1:N──→ review_approvals                            │
--       │──1:N──→ kol_search_history                          │
--       │──1:N──→ kol_profiles (多租户隔离)                    │

-- ============================================================
-- 第四部分：触发器与自动维护
-- ============================================================

-- 4.1 自动更新 conversations.message_count
CREATE OR REPLACE FUNCTION update_conversation_message_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE conversations
        SET message_count = message_count + 1,
            last_message = LEFT(NEW.content, 100),
            updated_at = NOW()
        WHERE id = NEW.conversation_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE conversations
        SET message_count = message_count - 1,
            updated_at = NOW()
        WHERE id = OLD.conversation_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_messages_count
    AFTER INSERT OR DELETE ON messages
    FOR EACH ROW EXECUTE FUNCTION update_conversation_message_count();


-- 4.2 自动更新 updated_at 时间戳
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为所有含 updated_at 的表创建触发器
CREATE TRIGGER trg_conversations_updated
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_kol_profiles_updated
    BEFORE UPDATE ON kol_profiles
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_content_scripts_updated
    BEFORE UPDATE ON content_scripts
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_logistics_updated
    BEFORE UPDATE ON logistics_tracking
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();


-- ============================================================
-- 第五部分：初始种子数据
-- ============================================================

-- 5.1 演示公司（用于 Demo 体验）
-- INSERT INTO companies (name, brand_name, category, platforms_json, subscription_status)
-- VALUES ('演示公司', 'DemoBrand', '美妆', '["douyin","xiaohongshu"]', 'active');

-- 5.2 示例达人数据（用于演示达人搜索功能）
-- INSERT INTO kol_profiles (company_id, name, platform, platform_uid, followers, engagement_rate, category, price_range_low, price_range_high, location, verified, data_source)
-- VALUES
--   (1, '李佳琦Austin', 'douyin', 'uid_ljq_001', 48500000, 3.50, '美妆', 50000, 150000, '上海', TRUE, 'manual'),
--   (1, '美妆小天才', 'xiaohongshu', 'uid_mz_002', 3210000, 5.20, '美妆', 8000, 20000, '杭州', TRUE, 'manual'),
--   (1, '时尚达人Lily', 'douyin', 'uid_ss_003', 12500000, 2.80, '穿搭', 15000, 40000, '广州', TRUE, 'manual'),
--   (1, '美食探店王', 'kuaishou', 'uid_ms_004', 8500000, 4.10, '美食', 10000, 30000, '成都', FALSE, 'manual'),
--   (1, '数码评测君', 'bilibili', 'uid_sm_005', 2100000, 6.50, '数码', 20000, 50000, '深圳', TRUE, 'manual');