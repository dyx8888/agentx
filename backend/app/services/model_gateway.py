"""
模型网关 - 多提供商支持 + 企业自有 Key + 智能路由 + Token 计费
+ Token预算管理 + 流式输出 + 重试幂等 + 结构化输出校验
+ 流式异常处理 + Prompt Caching

支持的提供商: DeepSeek, OpenAI, 火山引擎(豆包)

文档依据: 2.docx - 大模型API调用工程实践
  - Token预算公式: window >= input_tokens + max_output_tokens
  - 流式输出: SSE协议, TTFT指标
  - 重试幂等: 指数退避+jitter, 幂等key设计
  - 限流分层: 用户级/租户级/模型级/供应商级
  - 结构化输出: JSON Schema校验, 4级兜底机制
  - 流式异常处理: 用户取消/超时/断流/重连
  - Prompt Caching: 稳定前缀缓存, 缓存命中率监控
"""

import asyncio  # 用于异步流式输出和重试延迟
import contextlib
import hashlib  # 用于生成幂等key
import json  # 用于结构化输出JSON Schema校验
import os
import random  # 用于 jitter 随机延迟
import threading
import time
import uuid
from collections import OrderedDict  # SemanticCache 内存降级模式的 LRU 容器
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import date  # CostAttributor 按日聚合查询使用 date
from enum import StrEnum
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from app.core.logging import get_logger

logger = get_logger(__name__)
_JITTER_RANDOM = random.SystemRandom()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None

# ============ Token预算管理常量 ============
# 文档依据: 2.docx - Token预算公式 window >= input_tokens + max_output_tokens
TOKEN_BUDGET_SAFETY_MARGIN = 0.15  # 安全边距15%，给供应商额外开销留空间
DEFAULT_TOKEN_WINDOW = 128000  # 默认上下文窗口128K
MAX_OUTPUT_TOKENS_DEFAULT = 4096  # 默认最大输出Token
# 降级顺序: 删RAG片段 → 压缩历史 → 减工具Schema → 降低输出长度 → 切换模型 → 拒绝
TOKEN_BUDGET_DEGRADE_ORDER = [
    "trim_rag",  # 1. 删除低相关RAG片段
    "compress_history",  # 2. 压缩早期历史消息
    "reduce_tools",  # 3. 减少工具Schema
    "reduce_output",  # 4. 降低最大输出长度
    "switch_model",  # 5. 切换长上下文模型
    "reject",  # 6. 拒绝执行并提示用户缩小范围
]

# ============ 重试幂等常量 ============
# 文档依据: 2.docx - 指数退避 + jitter, 幂等key设计
MAX_RETRIES_DEFAULT = 3  # 最大重试次数
BASE_DELAY_SECONDS = 1.0  # 基础延迟秒数
MAX_DELAY_SECONDS = 60.0  # 最大延迟秒数
JITTER_FACTOR = 0.1  # jitter因子，实际延迟 = base_delay * (1 ± jitter)

# ============ 结构化输出常量 ============
# 文档依据: 2.docx - 4级兜底机制
STRUCTURED_OUTPUT_FALLBACK_LEVELS = {
    "L1": "本地JSON Schema校验 → 不通过则自动修复常见错误",
    "L2": "轻量修复（补全缺失括号、修复引号、截断尾部多余内容）",
    "L3": "降级Schema（去掉复杂嵌套字段，保留核心字段重试）",
    "L4": "人工兜底（返回原始文本 + 标记需人工处理）",
}

# ============ P4 增强：多模型路由 / 语义缓存 / 成本归因 / 审计日志 ============
# Redis URL：与 session_store / token_blacklist 共用，避免重复配置
P4_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 任务类型 → 默认模型 key 的路由规则（被 company_llm_config 中的偏好覆盖）
# 设计依据：分析任务需要思维链 → deepseek-reasoner；代码任务用 deepseek-coder；
# 但当前 model_config.yaml 默认未配置 deepseek_coder，因此 code 任务也回退到 deepseek-chat
DEFAULT_TASK_TYPE_ROUTING: dict[str, str] = {
    "chat": "deepseek",
    "analysis": "deepseek",
    "code": "deepseek",
    "vision": "deepseek",
    "default": "deepseek",
}

MODEL_KEY_ALIASES: dict[str, str] = {
    "deepseek_chat": "deepseek",
    "deepseek-chat": "deepseek",
    "deepseek": "deepseek",
    "deepseek_reasoner": "deepseek",
    "openai_gpt4": "gpt4o",
    "volcano_lite": "deepseek_volc",
}

MODEL_GATEWAY_DEFAULT_ENV = "MODEL_GATEWAY_DEFAULT"
EVAL_PROXY_MODEL_KEY = "eval_proxy"
EVAL_PROXY_BASE_URL_ENV_KEYS = ("AGENT_EVAL_BASE_URL", "EVAL_PROXY_BASE_URL")
EVAL_PROXY_API_KEY_ENV_KEYS = ("AGENT_EVAL_API_KEY", "EVAL_PROXY_API_KEY")
EVAL_PROXY_MODEL_NAME_ENV_KEYS = ("AGENT_EVAL_MODEL_NAME", "EVAL_PROXY_MODEL_NAME")

# 模型健康度阈值：连续失败次数 >= 此值时暂时跳过该模型
MODEL_HEALTH_FAIL_THRESHOLD = 3
# 模型健康度冷却时间（秒）：失败后多长时间内视为不健康
MODEL_HEALTH_COOLDOWN_SECONDS = 300
# 模型健康度 Redis 共享状态的 TTL（秒）：与多 worker 共享，TTL 防止状态无限残留
MODEL_HEALTH_TTL_SECONDS = 3600

# SemanticCache 内存降级 LRU 容量上限
SEMANTIC_CACHE_MEMORY_MAX_SIZE = 1000
# SemanticCache 默认 TTL（秒）
SEMANTIC_CACHE_DEFAULT_TTL = 3600

# AuditLogger 关键操作枚举（与文档约束对齐）
AUDIT_ACTIONS = {
    "model_switch",  # 模型切换
    "fallback_triggered",  # 触发 fallback
    "cache_hit",  # 语义缓存命中
    "cache_miss",  # 语义缓存未命中
    "token_budget_exceeded",  # Token 预算超限
}


class ModelProvider(StrEnum):  # 模型提供商枚举，使用StrEnum便于配置文件中直接引用
    DEEPSEEK = "deepseek"  # DeepSeek：性价比高，适合中文场景
    OPENAI = "openai"  # OpenAI：GPT系列，性能最强但成本最高
    VOLCANO = "volcano"  # 火山引擎：字节跳动豆包模型，国内合规
    CUSTOM = "custom"  # 自定义：允许企业接入自有模型


class TaskComplexity(StrEnum):  # 任务复杂度枚举，用于智能路由选模型
    SIMPLE = "simple"  # 简单任务：如查询、回复，用低成本模型
    STANDARD = "standard"  # 标准任务：默认复杂度
    COMPLEX = "complex"  # 复杂任务：如分析、推理，用高能力模型


@dataclass  # 使用dataclass，因为ModelCapability是纯数据描述
class ModelCapability:  # 描述每个模型的能力和成本，用于路由决策
    provider: str  # 提供商名称
    model_name: str  # 实际模型名称（API调用时使用的名称）
    max_tokens: int = 8192  # 最大输出token数，默认8192适合大多数场景
    supports_function_calling: bool = True  # 是否支持函数调用，默认True
    supports_vision: bool = False  # 是否支持视觉，默认False
    cost_per_1k_input: float = 0.0  # 每千输入token成本（美元）
    cost_per_1k_output: float = 0.0  # 每千输出token成本（美元）
    suitable_for: list[str] = field(
        default_factory=lambda: ["standard"]
    )  # 适合的任务复杂度，使用field避免可变默认值


class EnterpriseKeyManager:  # 企业自有API Key管理器，支持多租户Key隔离
    """企业自有 API Key 管理器"""

    def __init__(self):  # 初始化空字典，Key通过set_keys或_load_from_db填充
        self._company_keys: dict[
            int, dict[str, str]
        ] = {}  # 嵌套字典：company_id → {provider: api_key}

    def set_keys(
        self, company_id: int, provider: str, api_key: str
    ):  # 手动设置企业Key，适用于管理后台操作
        if company_id not in self._company_keys:  # 首次设置时初始化该企业的字典
            self._company_keys[company_id] = {}
        self._company_keys[company_id][provider] = api_key  # 覆盖或添加指定提供商的Key
        logger.info("enterprise_key_set", company_id=company_id, provider=provider)

    def get_key(
        self, company_id: int, provider: str
    ) -> str | None:  # 获取企业Key，缓存未命中时从数据库加载
        keys = self._company_keys.get(company_id, {})
        key = keys.get(provider)
        if not key:  # 缓存未命中，尝试从数据库加载
            self._load_from_db(company_id)  # 懒加载策略，减少数据库查询
            keys = self._company_keys.get(company_id, {})
            key = keys.get(provider)
        return key  # 可能返回None，调用方需处理

    def _load_from_db(self, company_id: int):  # 从数据库加载企业Key，使用延迟导入避免循环依赖
        """从数据库加载企业 API Key"""
        try:  # 数据库加载失败不应影响主流程
            from app.database import db  # 延迟导入，避免启动时数据库未就绪

            company = db.get_company(company_id)
            if not company:  # 企业不存在时静默返回
                return
            credentials = getattr(company, "platform_credentials", None)  # 使用getattr安全获取属性
            if not credentials:  # 无凭证时静默返回
                return
            import json  # 仅在需要时导入json

            creds = (
                json.loads(credentials) if isinstance(credentials, str) else credentials
            )  # 兼容字符串和字典两种格式
            llm_keys = creds.get("llm_api_keys", {})  # 从platform_credentials中提取LLM Key
            self._company_keys[company_id] = llm_keys  # 更新缓存
        except Exception as e:
            logger.warning("enterprise_key_load_failed", company_id=company_id, error=str(e))


class TokenQuotaManager:  # Token配额管理器，按企业ID隔离，支持日配额和月配额
    """Token 配额管理器"""

    def __init__(self):  # 初始化空字典，配额通过set_quota设置
        self._quotas: dict[int, dict[str, Any]] = {}  # 企业配额字典，使用Any因为值类型混合
        self._usage: dict[int, dict[str, int]] = {}  # 使用量字典（当前未在代码中使用，预留扩展）

    def set_quota(
        self, company_id: int, daily_limit: int = 0, monthly_limit: int = 0
    ):  # 设置企业配额，0表示不限制
        self._quotas[company_id] = {  # 直接覆盖，不支持增量更新
            "daily_limit": daily_limit,
            "monthly_limit": monthly_limit,
            "daily_used": 0,  # 初始使用量为0
            "monthly_used": 0,
            "last_reset_day": time.strftime("%Y-%m-%d"),  # 记录最后重置日期，用于跨天重置
            "last_reset_month": time.strftime("%Y-%m"),  # 记录最后重置月份，用于跨月重置
        }

    def check_quota(
        self, company_id: int, tokens: int
    ) -> tuple[bool, str]:  # 检查配额是否足够，返回(是否允许, 原因)
        """检查配额是否足够"""
        quota = self._quotas.get(company_id)
        if not quota:  # 未设置配额则不限制，返回True
            return True, ""

        today = time.strftime("%Y-%m-%d")  # 当前日期
        this_month = time.strftime("%Y-%m")  # 当前月份

        if quota["last_reset_day"] != today:  # 跨天重置日使用量
            quota["daily_used"] = 0
            quota["last_reset_day"] = today
        if quota["last_reset_month"] != this_month:  # 跨月重置月使用量
            quota["monthly_used"] = 0
            quota["last_reset_month"] = this_month

        if (
            quota["daily_limit"] > 0 and quota["daily_used"] + tokens > quota["daily_limit"]
        ):  # 日配额检查，limit>0才限制
            return False, f"Daily token quota exceeded ({quota['daily_limit']})"
        if (
            quota["monthly_limit"] > 0 and quota["monthly_used"] + tokens > quota["monthly_limit"]
        ):  # 月配额检查
            return False, f"Monthly token quota exceeded ({quota['monthly_limit']})"

        return True, ""

    def record_usage(self, company_id: int, tokens: int):  # 记录使用量，仅在已设置配额的企业中记录
        if company_id not in self._quotas:  # 未设置配额则不记录，避免不必要的内存占用
            return
        quota = self._quotas[company_id]
        quota["daily_used"] += tokens  # 累加日使用量
        quota["monthly_used"] += tokens  # 累加月使用量

    def get_usage(self, company_id: int) -> dict:  # 获取当前使用情况，返回0表示无限制
        quota = self._quotas.get(company_id, {})
        return {
            "daily_used": quota.get("daily_used", 0),
            "daily_limit": quota.get("daily_limit", 0),
            "monthly_used": quota.get("monthly_used", 0),
            "monthly_limit": quota.get("monthly_limit", 0),
        }


class ModelRouter:  # 模型智能路由器
    """模型智能路由器 - 按 Agent 类型 + 任务复杂度选模型，并支持任务类型 + 健康度感知路由

    P4 增强：
    - 新增实例方法 route(task_type, company_id) -> str：按任务类型路由到不同模型
    - 健康度感知：维护 model_health dict，失败次数超阈值的模型暂时跳过
    - 保留原有 classmethod get_model / estimate_complexity，向后兼容 get_llm_for_agent
    """

    ROUTING_RULES = {  # 类级别路由规则表，Agent类型 → 复杂度 → 模型key
        "品牌商务": {  # 品牌商务Agent：简单/标准用deepseek，复杂用deepseek
            TaskComplexity.SIMPLE: "deepseek",
            TaskComplexity.STANDARD: "deepseek",
            TaskComplexity.COMPLEX: "deepseek",  # 复杂任务需要推理能力
        },
        "内容运营": {  # 内容运营Agent：复杂任务用GPT-4，因为内容生成质量要求高
            TaskComplexity.SIMPLE: "deepseek",
            TaskComplexity.STANDARD: "deepseek",
            TaskComplexity.COMPLEX: "deepseek",  # 内容运营的复杂任务对质量要求最高
        },
        "数据分析": {  # 数据分析Agent：复杂任务用deepseek
            TaskComplexity.SIMPLE: "deepseek",
            TaskComplexity.STANDARD: "deepseek",
            TaskComplexity.COMPLEX: "deepseek",
        },
        "客服专员": {  # 客服Agent：简单任务用低成本deepseek，节省成本
            TaskComplexity.SIMPLE: "deepseek",  # 简单回复用最便宜的模型
            TaskComplexity.STANDARD: "deepseek",
            TaskComplexity.COMPLEX: "deepseek",
        },
        "视觉设计": {  # 视觉设计Agent：标准/复杂用GPT-4，因为视觉理解需要多模态能力
            TaskComplexity.SIMPLE: "deepseek",
            TaskComplexity.STANDARD: "deepseek",
            TaskComplexity.COMPLEX: "deepseek",
        },
        "default": {  # 默认路由规则，兜底处理未知Agent类型
            TaskComplexity.SIMPLE: "deepseek",
            TaskComplexity.STANDARD: "deepseek",
            TaskComplexity.COMPLEX: "deepseek",
        },
    }

    # 任务类型 → 默认模型 key 路由表（P4 新增）
    # 与 DEFAULT_TASK_TYPE_ROUTING 模块常量对齐；类级别定义便于子类覆写
    TASK_TYPE_ROUTING = DEFAULT_TASK_TYPE_ROUTING

    # model_health 在 Redis 中的 key 前缀，与多 worker 共享
    HEALTH_KEY_PREFIX = "model_health:"

    def __init__(self):  # P4 新增：实例级健康度状态，避免多个 gateway 共享同一份健康统计
        # model_health[model_key] = {"fail_count": int, "last_fail_at": float_epoch}
        # 内存降级存储：仅在 Redis 不可用时使用，多 worker 部署下各进程独立（已知折中）
        self.model_health: dict[str, dict] = {}
        self._health_lock = threading.Lock()  # 保护 model_health 并发读写
        # P4 共享状态：Redis 客户端，与 SemanticCache / TokenBlacklist 共用 P4_REDIS_URL
        self._redis = None
        self._redis_available = False
        self._init_redis_client()

    def _init_redis_client(self):
        """构造异步 Redis 客户端（仅创建对象，不发起连接）

        与 SemanticCache / TokenBlacklist 保持一致：构造函数中不 await，
        连接验证延迟到 init() 中执行。
        """
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(P4_REDIS_URL, socket_connect_timeout=3)
        except Exception as e:
            logger.warning("model_health_redis_client_init_failed", error=str(e))
            self._redis = None

    async def init(self):
        """异步初始化：ping Redis 验证连通性

        应在 FastAPI lifespan 启动阶段通过 ModelGateway.init_p4_components() 调用。
        失败时降级到内存模式，并记录多 worker 不一致警告。
        """
        if not self._redis:
            return  # 客户端未创建，直接走内存模式
        try:
            await self._redis.ping()
            self._redis_available = True
            logger.info("model_health_redis_connected", url=P4_REDIS_URL)
        except Exception as e:
            self._redis_available = False
            logger.warning(
                "model_health_redis_unavailable_multi_worker_inconsistency", error=str(e)
            )

    async def close(self):
        """关闭 Redis 连接，释放连接池资源"""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning("model_health_redis_close_error", error=str(e))
            finally:
                self._redis = None
                self._redis_available = False

    def _redis_health_key(self, model_key: str) -> str:
        """构造 model_health 在 Redis 中的 key

        Args:
            model_key: 模型标识，如 deepseek

        Returns:
            Redis key，如 "model_health:deepseek"
        """
        return f"{self.HEALTH_KEY_PREFIX}{model_key}"

    @classmethod  # classmethod，路由逻辑基于类级别规则
    def get_model(
        cls, agent_name: str = None, complexity: TaskComplexity = None
    ) -> str:  # 根据Agent名称和复杂度返回模型key
        agent_rules = cls.ROUTING_RULES.get(
            agent_name, cls.ROUTING_RULES["default"]
        )  # 未知Agent使用默认规则
        return agent_rules.get(complexity, "deepseek")  # 未知复杂度默认deepseek

    @classmethod  # classmethod，估算逻辑基于类级别关键词
    def estimate_complexity(
        cls, task_description: str
    ) -> TaskComplexity:  # 基于关键词的简单复杂度估算
        """根据任务描述估算复杂度"""
        complex_keywords = [  # 复杂任务关键词：涉及深层分析
            "分析",
            "预测",
            "优化",
            "策略",
            "全面",
            "综合",
            "评估",
            "规划",
            "报告",
            "多维度",
            "深度",
        ]
        simple_keywords = ["查询", "回复", "检查", "提醒", "通知"]  # 简单任务关键词

        lower = task_description.lower()  # 转小写，不区分大小写
        complex_count = sum(1 for kw in complex_keywords if kw in lower)  # 统计复杂关键词数量
        simple_count = sum(1 for kw in simple_keywords if kw in lower)  # 统计简单关键词数量

        if complex_count >= 2:  # 至少2个复杂关键词才判定为复杂
            return TaskComplexity.COMPLEX
        elif simple_count >= 2 and complex_count == 0:  # 至少2个简单关键词且无复杂关键词
            return TaskComplexity.SIMPLE
        return TaskComplexity.STANDARD  # 默认标准复杂度

    # ============ P4 新增：任务类型路由 + 健康度感知 ============

    async def route(
        self,
        task_type: str,
        company_id: int | None = None,
        available_models: dict[str, dict] | None = None,
    ) -> str:
        """按任务类型路由到最优模型 key

        Args:
            task_type: chat / analysis / code / vision / default
            company_id: 可选，传入时会尝试读取 company_llm_config 中的偏好模型
            available_models: 当前 ModelGateway 已加载的 models_config，
                              用于校验候选模型是否真的可用（避免路由到未配置的模型）

        Returns:
            最优 model_key。所有候选都不健康或未配置时回退到 "default" 任务类型的默认模型。
        """
        # 第一步：确定候选模型优先级列表
        # 优先级：company 偏好 > 任务类型默认 > default 兜底
        candidates: list[str] = []

        # 1.1 读取 company 偏好模型（如果指定 company_id）
        if company_id is not None:
            company_preferred = self._load_company_preferred_model(company_id, task_type)
            if company_preferred:
                candidates.append(company_preferred)

        # 1.2 任务类型默认模型
        task_default = self.TASK_TYPE_ROUTING.get(task_type) or self.TASK_TYPE_ROUTING["default"]
        if task_default not in candidates:
            candidates.append(task_default)

        # 1.3 default 兜底模型
        default_model = self.TASK_TYPE_ROUTING["default"]
        if default_model not in candidates:
            candidates.append(default_model)

        # 第二步：按候选顺序返回第一个"健康且已配置"的模型
        for model_key in candidates:
            if available_models is not None and model_key not in available_models:
                # 模型未在 model_config.yaml 中配置，跳过
                continue
            if await self._is_healthy(model_key):
                return model_key

        # 第三步：所有候选都不健康或未配置时，返回 default 任务类型的默认模型
        # 不抛异常：路由失败不应阻塞业务，让上层用默认模型尝试调用
        # （如果默认模型也不健康，调用层会触发 fallback 或熔断）
        return default_model

    async def mark_failed(self, model_key: str) -> None:
        """记录模型调用失败，累计失败次数超过阈值后该模型被暂时跳过

        多 worker 共享：Redis 可用时状态写 Redis（TTL=MODEL_HEALTH_TTL_SECONDS），
        所有 worker 共享同一份健康度；Redis 不可用时降级到进程内内存（各 worker 独立）。
        """
        if not model_key:
            return
        now = time.time()

        # Redis 优先：多 worker 共享状态
        if self._redis_available and self._redis is not None:
            try:
                key = self._redis_health_key(model_key)
                # 读取现有失败计数（跨 worker 累加）
                raw = await self._redis.get(key)
                if raw is not None:
                    raw_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                    existing = json.loads(raw_str)
                    fail_count = existing.get("fail_count", 0) + 1
                else:
                    fail_count = 1
                health = {"fail_count": fail_count, "last_fail_at": now}
                await self._redis.setex(key, MODEL_HEALTH_TTL_SECONDS, json.dumps(health))
                if fail_count >= MODEL_HEALTH_FAIL_THRESHOLD:
                    logger.warning(
                        "model_marked_unhealthy", model_key=model_key, fail_count=fail_count
                    )
                return
            except Exception as e:
                # Redis 写入失败：降级到内存，保证失败标记不丢失
                logger.warning(
                    "model_health_redis_write_failed_fallback_memory",
                    model_key=model_key,
                    error=str(e),
                )

        # 内存降级路径（多 worker 下各进程独立，已知折中）
        with self._health_lock:
            health = self.model_health.setdefault(model_key, {"fail_count": 0, "last_fail_at": 0.0})
            health["fail_count"] = health.get("fail_count", 0) + 1
            health["last_fail_at"] = now
            if health["fail_count"] >= MODEL_HEALTH_FAIL_THRESHOLD:
                logger.warning(
                    "model_marked_unhealthy", model_key=model_key, fail_count=health["fail_count"]
                )

    async def mark_healthy(self, model_key: str) -> None:
        """记录模型调用成功，重置失败计数

        多 worker 共享：Redis 可用时删除 Redis 中的健康度 key，
        所有 worker 同步感知恢复；Redis 不可用时降级到进程内内存。
        """
        if not model_key:
            return

        # Redis 优先：多 worker 共享状态
        if self._redis_available and self._redis is not None:
            try:
                await self._redis.delete(self._redis_health_key(model_key))
                return
            except Exception as e:
                logger.warning(
                    "model_health_redis_delete_failed_fallback_memory",
                    model_key=model_key,
                    error=str(e),
                )

        # 内存降级路径
        with self._health_lock:
            # 仅在确实有失败记录时才清理，避免无谓的字典操作
            if model_key in self.model_health:
                self.model_health.pop(model_key, None)

    async def _is_healthy(self, model_key: str) -> bool:
        """检查模型是否健康（失败次数 < 阈值，或冷却时间已过）

        多 worker 共享：Redis 可用时从 Redis 读取健康度，所有 worker 感知一致；
        Redis 不可用时降级到进程内内存（各 worker 独立，可能不一致）。
        """
        # Redis 优先：多 worker 共享状态
        if self._redis_available and self._redis is not None:
            try:
                raw = await self._redis.get(self._redis_health_key(model_key))
                if raw is None:
                    return True  # 无失败记录，视为健康
                raw_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                health = json.loads(raw_str)
                fail_count = health.get("fail_count", 0)
                if fail_count < MODEL_HEALTH_FAIL_THRESHOLD:
                    return True  # 失败次数未达阈值，仍可使用
                last_fail_at = health.get("last_fail_at", 0.0)
                # 冷却时间已过，重置失败计数并视为健康
                if time.time() - last_fail_at > MODEL_HEALTH_COOLDOWN_SECONDS:
                    await self._redis.delete(self._redis_health_key(model_key))
                    return True
                return False  # 冷却中，跳过
            except Exception as e:
                logger.warning(
                    "model_health_redis_read_failed_fallback_memory",
                    model_key=model_key,
                    error=str(e),
                )

        # 内存降级路径
        with self._health_lock:
            health = self.model_health.get(model_key)
            if not health:
                return True  # 无失败记录，视为健康
            fail_count = health.get("fail_count", 0)
            if fail_count < MODEL_HEALTH_FAIL_THRESHOLD:
                return True  # 失败次数未达阈值，仍可使用
            last_fail_at = health.get("last_fail_at", 0.0)
            # 冷却时间已过，重置失败计数并视为健康
            if time.time() - last_fail_at > MODEL_HEALTH_COOLDOWN_SECONDS:
                self.model_health.pop(model_key, None)
                return True
            return False  # 冷却中，跳过

    def _load_company_preferred_model(self, company_id: int, task_type: str) -> str | None:
        """从 company_llm_config 读取偏好模型

        存储结构（与 app/api/companies.py 的 LLM 配置管理一致）：
        company.llm_api_key 字段（EncryptedText）反序列化为 JSON，结构形如：
        {
            "deepseek": {"gateway": "...", "apiKey": "...", "preferred_tasks": ["analysis"]},
            ...
        }

        Args:
            company_id: 公司 ID
            task_type: 任务类型，用于匹配 provider 的 preferred_tasks

        Returns:
            匹配到的 model_key，未找到返回 None
        """
        try:
            # 延迟导入避免循环依赖
            from app.database import db

            company = db.get_company(company_id)
            if not company or not getattr(company, "llm_api_key", None):
                return None
            # llm_api_key 字段是 EncryptedText，ORM 读取时已自动解密
            config_json = company.llm_api_key
            config_map = json.loads(config_json) if isinstance(config_json, str) else config_json
            if not isinstance(config_map, dict):
                return None
            # 遍历各 provider，查找其 preferred_tasks 是否包含当前 task_type
            for provider_key, cfg in config_map.items():
                if not isinstance(cfg, dict):
                    continue
                preferred_tasks = cfg.get("preferred_tasks") or []
                if task_type in preferred_tasks:
                    # 将 provider_key 映射为 model_key
                    if provider_key == "deepseek":
                        # 读取 model_key 字段，缺省回退到 deepseek
                        return cfg.get("model_key") or "deepseek"
                    # 其他 provider 直接用 provider_key 作为 model_key（与 model_config.yaml 对齐）
                    return cfg.get("model_key") or provider_key
            return None
        except Exception as e:
            # 数据库读取失败不应阻塞路由，warning 后回退到默认路由
            logger.warning(
                "company_preferred_model_load_failed",
                company_id=company_id,
                task_type=task_type,
                error=str(e),
            )
            return None

    def get_health_status(self) -> dict[str, dict]:
        """返回当前所有模型的健康状态快照（用于监控接口）"""
        with self._health_lock:
            # 深拷贝避免外部修改
            return {k: dict(v) for k, v in self.model_health.items()}


# ============ P4 新增：语义缓存 SemanticCache ============


class SemanticCache:
    """语义缓存 - 基于 query 哈希的响应缓存

    设计：
    - 缓存 key = sha256(normalized_query + model_key + temperature)[:16]
      加入 model_key 和 temperature 是因为同一 query 在不同模型/温度下输出不同
    - Redis 优先（key=semcache:{hash}），降级到进程内 OrderedDict + LRU(1000)
    - 内存模式无 TTL 精确过期，靠 LRU 淘汰控制容量
    - 所有方法 async：与 ModelGateway.ainvoke 的调用链一致

    注意：本实现是"简化版"语义缓存——按精确哈希命中，不做向量相似度匹配。
    完整语义缓存需要嵌入模型 + 向量索引，超出 P4 范围。
    """

    CACHE_KEY_PREFIX = "semcache:"

    def __init__(self):
        self._redis = None
        self._redis_available = False
        # OrderedDict 实现 LRU：访问/写入时 move_to_end，容量超限时 popitem(last=False)
        self._memory: OrderedDict[str, str] = OrderedDict()
        self._memory_lock = threading.Lock()
        self._init_redis_client()

    def _init_redis_client(self):
        """构造异步 Redis 客户端（与 TokenBlacklist 同样的延迟连接策略）"""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(P4_REDIS_URL, socket_connect_timeout=3)
        except Exception as e:
            logger.warning("semantic_cache_redis_init_failed", error=str(e))
            self._redis = None

    async def init(self):
        """异步初始化：ping Redis 验证连通性。失败降级到内存模式。"""
        if not self._redis:
            return
        try:
            await self._redis.ping()
            self._redis_available = True
            logger.info("semantic_cache_redis_connected", url=P4_REDIS_URL)
        except Exception as e:
            self._redis_available = False
            logger.warning("semantic_cache_redis_unavailable", error=str(e))
            # 多 worker 部署下内存降级模式各进程独立维护 LRU(1000)，命中率独立、
            # 缓存不同步。此处仅记一次 warning，不阻塞业务。
            logger.warning("semantic_cache_redis_unavailable_multi_worker_independent")

    async def close(self):
        """关闭 Redis 连接"""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as e:
                logger.warning("semantic_cache_redis_close_error", error=str(e))
            finally:
                self._redis = None
                self._redis_available = False

    @staticmethod
    def compute_query_hash(query: str, model_key: str, temperature: float | str = "") -> str:
        """计算 query 哈希：sha256(normalized_query + model_key + temperature)[:16]

        归一化策略：
        - strip 首尾空白
        - 转小写
        - 折叠连续空白为单个空格
        """
        normalized = " ".join((query or "").strip().lower().split())
        raw = f"{normalized}|{model_key}|{temperature}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    async def get(self, query_hash: str) -> str | None:
        """查询缓存。命中返回响应字符串，未命中返回 None。"""
        if not query_hash:
            return None
        key = f"{self.CACHE_KEY_PREFIX}{query_hash}"

        # Redis 优先
        if self._redis_available and self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is not None:
                    # bytes → str
                    return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                return None
            except Exception as e:
                logger.warning(
                    "semantic_cache_redis_read_failed_fallback_memory",
                    hash=query_hash,
                    error=str(e),
                )

        # 内存降级
        with self._memory_lock:
            if query_hash in self._memory:
                # LRU：命中时移到末尾，表示最近访问
                self._memory.move_to_end(query_hash)
                return self._memory[query_hash]
            return None

    async def set(
        self, query_hash: str, response: str, ttl: int = SEMANTIC_CACHE_DEFAULT_TTL
    ) -> None:
        """写入缓存。ttl 仅对 Redis 模式有效；内存模式靠 LRU 淘汰。"""
        if not query_hash or response is None:
            return
        key = f"{self.CACHE_KEY_PREFIX}{query_hash}"

        # Redis 优先
        if self._redis_available and self._redis is not None:
            try:
                await self._redis.setex(key, max(int(ttl), 1), response)
                return
            except Exception as e:
                logger.warning(
                    "semantic_cache_redis_write_failed_fallback_memory",
                    hash=query_hash,
                    error=str(e),
                )

        # 内存降级
        with self._memory_lock:
            # 已存在则先删除，保证 LRU 顺序正确
            if query_hash in self._memory:
                self._memory.pop(query_hash, None)
            self._memory[query_hash] = response
            # 容量保护：超限时淘汰最旧条目
            while len(self._memory) > SEMANTIC_CACHE_MEMORY_MAX_SIZE:
                self._memory.popitem(last=False)  # FIFO 淘汰最旧


# ============ P4 新增：成本归因 CostAttributor ============


class CostAttributor:
    """成本归因 - 按公司 + 模型 + 任务类型记录 LLM 调用成本

    设计：
    - 复用 PostgreSQL cost_records 表，新增 task_type 列（ALTER TABLE IF NOT EXISTS）
    - 失败时只记 warning，不阻塞主流程
    - 提供 get_daily_cost 异步聚合查询接口

    注意：与 app.tracking.cost_tracker.CostTracker 互补：
    - CostTracker 写 SQLite 的 llm_usage 表（兼容旧部署）
    - CostAttributor 写 PostgreSQL 的 cost_records 表（带 task_type 维度，P4 新增）
    """

    _table_initialized = False  # 类级别标志，避免每次 record 都检查表结构
    _init_lock = threading.Lock()

    def __init__(self):
        # 暂无实例状态，保留 __init__ 以便未来扩展（如内存缓冲批量写入）
        pass

    def _ensure_table_schema(self):
        """首次调用时确保 cost_records 表有 task_type 列（幂等）

        使用 ALTER TABLE ADD COLUMN IF NOT EXISTS 兼容已有部署：
        - 旧库：cost_records 表已存在但无 task_type 列 → ADD COLUMN
        - 新库：cost_records 表已存在且有 task_type 列 → IF NOT EXISTS 跳过
        - 空库：cost_records 表不存在 → 静默失败，record() 时再走异常路径
        """
        if self._table_initialized:
            return
        with self._init_lock:
            if self._table_initialized:
                return
            try:
                from sqlalchemy import text

                from app.database import db

                # 仅在 db 已初始化且支持 engine 时尝试
                engine = getattr(db, "engine", None)
                if engine is None:
                    return
                if engine.dialect.name == "sqlite":
                    with engine.connect() as conn:
                        columns = {
                            row[1]
                            for row in conn.execute(text("PRAGMA table_info(cost_records)"))
                        }
                        if "task_type" not in columns:
                            conn.execute(
                                text("ALTER TABLE cost_records ADD COLUMN task_type VARCHAR(50)")
                            )
                        conn.commit()
                    self._table_initialized = True
                    logger.info("cost_attributor_schema_ready")
                    return
                with engine.connect() as conn:
                    # PostgreSQL 9.6+ 支持 ADD COLUMN IF NOT EXISTS
                    # SQLite 不支持该语法，但 SQLite 模式下不会走 PostgreSQL 路径
                    conn.execute(
                        text(
                            "ALTER TABLE cost_records ADD COLUMN IF NOT EXISTS task_type VARCHAR(50)"
                        )
                    )
                    conn.commit()
                self._table_initialized = True
                logger.info("cost_attributor_schema_ready")
            except Exception as e:
                # 表结构初始化失败：仍标记为已初始化避免重复尝试，后续 record 会捕获写入异常
                logger.warning("cost_attributor_schema_init_failed", error=str(e))
                self._table_initialized = True

    async def record(
        self,
        company_id: int,
        model_key: str,
        input_tokens: int,
        output_tokens: int,
        task_type: str = "",
        provider: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """记录单次模型调用的成本

        失败时仅记 warning，不抛异常（约束 6）。
        """
        if not company_id or not model_key:
            return
        # 确保表结构就绪（同步调用，快路径已通过 _table_initialized 短路）
        with contextlib.suppress(Exception):
            self._ensure_table_schema()

        try:
            from datetime import datetime as _dt

            from sqlalchemy import text

            from app.database import db

            # 复用 db.engine 的 raw connection，与 TokenUsagePersistence 保持一致
            engine = getattr(db, "engine", None)
            if engine is None:
                return
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO cost_records "
                        "(company_id, model_name, provider, input_tokens, output_tokens, "
                        " cost_usd, task_type, created_at) "
                        "VALUES (:cid, :mn, :pv, :it, :ot, :cu, :tt, :ca)"
                    ),
                    {
                        "cid": company_id,
                        "mn": model_key,
                        "pv": provider or "",
                        "it": int(input_tokens or 0),
                        "ot": int(output_tokens or 0),
                        "cu": float(cost_usd or 0.0),
                        "tt": task_type or "",
                        "ca": _dt.utcnow(),
                    },
                )
                conn.commit()
        except Exception as e:
            # 约束 6：失败只记 warning，不阻塞主流程
            logger.warning(
                "cost_attributor_record_failed",
                company_id=company_id,
                model_key=model_key,
                task_type=task_type,
                error=str(e),
            )

    async def get_daily_cost(
        self, company_id: int, query_date: date | None = None
    ) -> dict[str, float]:
        """按 model_key 分组查询指定日期的成本

        Args:
            company_id: 公司 ID
            query_date: 查询日期，默认今天

        Returns:
            {model_key: total_cost_usd} 字典。查询失败返回空字典。
        """
        if query_date is None:
            query_date = date.today()
        try:
            from sqlalchemy import text

            from app.database import db

            engine = getattr(db, "engine", None)
            if engine is None:
                return {}
            with engine.connect() as conn:
                # 按 model_name 分组求和；DATE(created_at) 兼容 PG 和 SQLite
                result = conn.execute(
                    text(
                        "SELECT model_name, SUM(cost_usd) as total "
                        "FROM cost_records "
                        "WHERE company_id = :cid AND DATE(created_at) = :d "
                        "GROUP BY model_name"
                    ),
                    {"cid": company_id, "d": query_date},
                )
                rows = result.fetchall()
                return {row[0]: float(row[1] or 0.0) for row in rows}
        except Exception as e:
            logger.warning(
                "cost_attributor_daily_cost_query_failed",
                company_id=company_id,
                date=str(query_date),
                error=str(e),
            )
            return {}


# ============ P4 新增：审计日志 AuditLogger ============


class AuditLogger:
    """审计日志 - 记录关键操作到 audit_log 表

    表结构（首次调用时自动创建）：
    - id: 自增主键
    - company_id: 公司 ID
    - user_id: 操作者 ID（可空，系统操作无 user）
    - action: 操作类型（见 AUDIT_ACTIONS）
    - resource: 操作的资源标识（如 model_key、cache_key）
    - metadata_json: 附加元数据 JSON
    - created_at: 创建时间

    失败时只记 warning，不阻塞主流程（约束 6）。
    """

    _table_initialized = False
    _init_lock = threading.Lock()

    def __init__(self):
        pass

    def _ensure_table(self):
        """首次调用时创建 audit_log 表（CREATE TABLE IF NOT EXISTS，幂等）"""
        if self._table_initialized:
            return
        with self._init_lock:
            if self._table_initialized:
                return
            try:
                from sqlalchemy import text

                from app.database import db

                engine = getattr(db, "engine", None)
                if engine is None:
                    return
                with engine.connect() as conn:
                    conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS audit_log ("
                            "  id SERIAL PRIMARY KEY,"
                            "  company_id INTEGER NOT NULL,"
                            "  user_id INTEGER,"
                            "  action VARCHAR(100) NOT NULL,"
                            "  resource VARCHAR(255),"
                            "  metadata_json TEXT,"
                            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                            ")"
                        )
                    )
                    # SQLite 不支持 SERIAL，但 SQLite 模式下会自动用 INTEGER PRIMARY KEY 替代
                    # 此处 CREATE TABLE IF NOT EXISTS 已足够幂等
                    conn.commit()
                self._table_initialized = True
                logger.info("audit_logger_table_ready")
            except Exception as e:
                logger.warning("audit_logger_table_init_failed", error=str(e))
                # 即使初始化失败也标记为已初始化，避免每次调用都重试
                self._table_initialized = True

    async def log(
        self,
        company_id: int,
        user_id: int | None,
        action: str,
        resource: str = "",
        metadata: dict | None = None,
    ) -> None:
        """记录一条审计日志

        Args:
            company_id: 公司 ID
            user_id: 操作者 ID，可空
            action: 操作类型（建议使用 AUDIT_ACTIONS 中的值）
            resource: 资源标识（如 model_key、cache_key）
            metadata: 附加元数据，会序列化为 JSON

        失败时仅记 warning，不抛异常（约束 6）。
        """
        if not company_id or not action:
            return
        with contextlib.suppress(Exception):
            self._ensure_table()

        try:
            from datetime import datetime as _dt

            from sqlalchemy import text

            from app.database import db

            engine = getattr(db, "engine", None)
            if engine is None:
                return
            metadata_str = json.dumps(metadata, ensure_ascii=False) if metadata else None
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO audit_log "
                        "(company_id, user_id, action, resource, metadata_json, created_at) "
                        "VALUES (:cid, :uid, :act, :res, :md, :ca)"
                    ),
                    {
                        "cid": company_id,
                        "uid": user_id,
                        "act": action,
                        "res": resource or "",
                        "md": metadata_str,
                        "ca": _dt.utcnow(),
                    },
                )
                conn.commit()
        except Exception as e:
            # 约束 6：审计日志失败不阻塞主流程
            logger.warning(
                "audit_logger_log_failed",
                company_id=company_id,
                action=action,
                resource=resource,
                error=str(e),
            )


class TokenBudgetManager:
    """Token预算管理器 - 文档依据: 2.docx

    核心公式: window >= input_tokens + max_output_tokens
    对于思维链模型: window >= input_tokens + reasoning_tokens + max_output_tokens

    超预算时按降级顺序处理：
    1. 删除低相关RAG片段
    2. 压缩早期历史消息
    3. 减少工具Schema
    4. 降低最大输出长度
    5. 切换长上下文模型
    6. 拒绝执行并提示用户缩小范围
    """

    def __init__(
        self,
        window_size: int = DEFAULT_TOKEN_WINDOW,
        max_output: int = MAX_OUTPUT_TOKENS_DEFAULT,
        safety_margin: float = TOKEN_BUDGET_SAFETY_MARGIN,
    ):
        self.window_size = window_size
        self.max_output_tokens = max_output
        self.safety_margin = safety_margin
        self._budget_history: list[dict] = []  # 预算使用历史，用于监控

    def estimate_input_tokens(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        history_messages: list = None,
        rag_context: str = "",
        tool_schemas: list = None,
    ) -> int:
        """估算输入Token数（粗略估算：中文约1.7字符/Token, 英文约3.3字符/Token）

        文档依据: 2.docx - DeepSeek官方数据: 1个Token约等于3.3个英文字符或1.7个中文字符
        """
        total_chars = 0
        total_chars += len(system_prompt)
        total_chars += len(user_prompt)
        if history_messages:
            for msg in history_messages:
                total_chars += len(str(getattr(msg, "content", "")))
        total_chars += len(rag_context)
        if tool_schemas:
            total_chars += len(json.dumps(tool_schemas, ensure_ascii=False))

        # 混合估算：假设50%中文+50%英文，平均约2.5字符/Token
        estimated = int(total_chars / 2.5)
        return max(estimated, 1)

    def check_budget(self, input_tokens: int, reasoning_tokens: int = 0) -> tuple[bool, dict]:
        """检查Token预算是否足够

        Returns:
            (is_within_budget, budget_info)
        """
        effective_window = int(self.window_size * (1 - self.safety_margin))
        total_estimated = input_tokens + reasoning_tokens + self.max_output_tokens
        is_within = total_estimated <= effective_window

        budget_info = {
            "window_size": self.window_size,
            "effective_window": effective_window,
            "input_tokens": input_tokens,
            "reasoning_tokens": reasoning_tokens,
            "max_output_tokens": self.max_output_tokens,
            "total_estimated": total_estimated,
            "remaining": effective_window - total_estimated,
            "usage_ratio": round(total_estimated / effective_window, 3)
            if effective_window > 0
            else 1.0,
            "is_within_budget": is_within,
        }
        self._budget_history.append(budget_info)
        return is_within, budget_info

    def get_degrade_strategy(self, input_tokens: int, reasoning_tokens: int = 0) -> str:
        """获取超预算时的降级策略"""
        is_within, info = self.check_budget(input_tokens, reasoning_tokens)
        if is_within:
            return "ok"
        excess = info["total_estimated"] - info["effective_window"]
        # 根据超出量选择降级策略
        if excess < info["effective_window"] * 0.1:
            return "trim_rag"
        elif excess < info["effective_window"] * 0.3:
            return "compress_history"
        elif excess < info["effective_window"] * 0.5:
            return "reduce_tools"
        elif excess < info["effective_window"] * 0.8:
            return "reduce_output"
        else:
            return "switch_model"

    def get_budget_history(self, limit: int = 10) -> list[dict]:
        """获取最近的预算使用历史"""
        return self._budget_history[-limit:]


# ============ 结构化输出校验器 ============
class StructuredOutputValidator:
    """结构化输出校验器 - 4级兜底机制

    文档依据: 2.docx - 结构化输出4级兜底
    L1: 本地JSON Schema校验
    L2: 轻量修复（补全括号、修复引号、截断尾部）
    L3: 降级Schema（去掉复杂嵌套，保留核心字段）
    L4: 人工兜底（返回原始文本+标记）
    """

    @staticmethod
    def validate_json_schema(content: str, schema: dict) -> tuple[bool, str, dict]:
        """L1: JSON Schema校验

        Returns:
            (is_valid, error_message, parsed_data)
        """
        try:
            # 尝试提取JSON（处理LLM可能包装在markdown代码块中的情况）
            json_str = StructuredOutputValidator._extract_json(content)
            data = json.loads(json_str)

            # 使用jsonschema校验（如果可用）
            try:
                import jsonschema

                jsonschema.validate(instance=data, schema=schema)
            except ImportError:
                # jsonschema不可用时，做基本结构校验
                StructuredOutputValidator._basic_schema_check(data, schema)

            return True, "", data
        except (json.JSONDecodeError, Exception) as e:
            return False, str(e), {}

    @staticmethod
    def lightweight_repair(content: str, schema: dict) -> tuple[bool, str, str]:
        """L2: 轻量修复

        修复常见问题：
        - 补全缺失的括号/引号
        - 修复尾部多余内容
        - 处理markdown代码块包裹
        """
        repaired = StructuredOutputValidator._extract_json(content)
        # 尝试补全缺失的括号
        open_braces = repaired.count("{") - repaired.count("}")
        open_brackets = repaired.count("[") - repaired.count("]")
        if open_braces > 0:
            repaired += "}" * open_braces
        if open_brackets > 0:
            repaired += "]" * open_brackets
        # 修复常见引号问题
        repaired = repaired.replace('"', '"').replace('"', '"')
        repaired = repaired.replace(""", "'").replace(""", "'")
        try:
            json.loads(repaired)
            return True, "repaired", repaired
        except json.JSONDecodeError:
            return False, "repair_failed", content

    @staticmethod
    def degrade_schema(schema: dict) -> dict:
        """L3: 降级Schema - 去掉复杂嵌套字段，保留核心字段"""
        degraded = {"type": "object"}
        if "properties" in schema:
            degraded["properties"] = {}
            for key, prop in schema["properties"].items():
                prop_type = prop.get("type", "string")
                if prop_type in ("object", "array"):
                    # 降级为string类型
                    degraded["properties"][key] = {
                        "type": "string",
                        "description": prop.get("description", f"降级后的{key}字段"),
                    }
                else:
                    degraded["properties"][key] = {
                        "type": prop_type,
                        "description": prop.get("description", ""),
                    }
        if "required" in schema:
            degraded["required"] = schema["required"]
        return degraded

    @staticmethod
    def human_fallback(content: str, original_error: str) -> dict:
        """L4: 人工兜底 - 返回原始文本+标记"""
        return {
            "fallback": True,
            "level": "L4",
            "raw_content": content,
            "error": original_error,
            "message": "结构化输出校验失败，请人工审核以下原始内容",
        }

    @staticmethod
    def _extract_json(content: str) -> str:
        """从内容中提取JSON字符串（处理markdown代码块包裹）"""
        import re

        # 尝试匹配 ```json ... ``` 代码块
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if match:
            return match.group(1).strip()
        # 尝试匹配第一个 { 到最后一个 } 之间的内容
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            return content[first_brace : last_brace + 1]
        return content.strip()

    @staticmethod
    def _basic_schema_check(data: dict, schema: dict):
        """基本Schema结构校验（jsonschema不可用时的降级方案）"""
        if "required" in schema:
            for field in schema["required"]:
                if field not in data:
                    raise ValueError(f"缺少必填字段: {field}")


# ============ 重试与幂等工具 ============
class RetryWithIdempotency:
    """重试与幂等机制 - 文档依据: 2.docx

    指数退避公式: delay = min(base * 2^retry, max_delay) * (1 ± jitter)
    幂等key: MD5(company_id + agent_key + message_hash + timestamp_hour)
    """

    @staticmethod
    def generate_idempotent_key(
        company_id: str, agent_key: str, message: str, window_minutes: int = 60
    ) -> str:
        """生成幂等key - 同一小时窗口内的相同请求产生相同key

        文档依据: 2.docx - 幂等key设计: 基于业务标识+时间窗口
        """
        time_window = int(time.time() / (window_minutes * 60))
        raw = f"{company_id}:{agent_key}:{message}:{time_window}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    @staticmethod
    async def retry_with_backoff(
        func,
        max_retries: int = MAX_RETRIES_DEFAULT,
        base_delay: float = BASE_DELAY_SECONDS,
        max_delay: float = MAX_DELAY_SECONDS,
        jitter: float = JITTER_FACTOR,
        retryable_exceptions: tuple = (Exception,),
    ) -> Any:
        """指数退避重试 + jitter

        文档依据: 2.docx - 指数退避 with jitter:
        delay = min(base * 2^retry, max_delay) * (1 + random(-jitter, +jitter))
        """
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func()
                else:
                    return func()
            except retryable_exceptions as e:
                last_exception = e
                if attempt == max_retries:
                    logger.error(
                        "retry_exhausted", attempt=attempt, max_retries=max_retries, error=str(e)
                    )
                    raise
                delay = min(base_delay * (2**attempt), max_delay)
                jitter_amount = delay * jitter * (2 * _JITTER_RANDOM.random() - 1)
                actual_delay = delay + jitter_amount
                logger.warning(
                    "retry_scheduled",
                    attempt=attempt + 1,
                    delay_seconds=round(actual_delay, 2),
                    error=str(e),
                )
                await asyncio.sleep(actual_delay)
        raise last_exception


class FailoverChatModel:  # 故障转移聊天模型：主模型失败时自动切换到fallback模型，确保高可用
    """带故障转移的聊天模型"""

    def __init__(
        self,
        gateway: "ModelGateway",
        model_key: str,
        company_api_key: str | None = None,
        company_id: int | None = None,
        agent_key: str = "",
    ):
        self.gateway = gateway
        self.model_key = model_key
        self.company_api_key = company_api_key
        self._company_id = company_id
        self._agent_key = agent_key
        self.models = []
        self.fallback_models = []
        self._init_models()
        # Token预算管理器
        cfg = gateway.models_config.get(model_key, {})
        window = cfg.get("context_window", DEFAULT_TOKEN_WINDOW)
        max_out = cfg.get("max_tokens", MAX_OUTPUT_TOKENS_DEFAULT)
        self._token_budget = TokenBudgetManager(window_size=window, max_output=max_out)
        # 结构化输出校验器
        self._output_validator = StructuredOutputValidator()
        # T3.3: LLM 熔断器（按 model_key 隔离，全局单例）
        self._breaker = get_circuit_breaker(f"llm_{model_key}", 5, 30)

    def _init_models(self):  # 初始化模型实例列表，主模型+fallback按顺序排列
        self.gateway._load_config()  # 确保配置已加载
        self.models = [
            self.gateway._create_model_instance(self.model_key, self.company_api_key)
        ]  # 主模型放在第一位
        config = self.gateway.models_config.get(self.model_key, {})  # 获取主模型配置
        self.fallback_models = config.get("fallback_models", [])  # 获取fallback模型列表
        for fb in self.fallback_models:  # 遍历fallback模型
            if fb in self.gateway.models_config:  # 仅创建已配置的fallback模型
                try:
                    self.models.append(
                        self.gateway._create_model_instance(fb, self.company_api_key)
                    )
                except ValueError as e:
                    logger.warning(
                        "fallback_model_unavailable_skipped",
                        model_key=fb,
                        error=str(e),
                    )

    @staticmethod
    def _attach_model_fallback_metadata(
        response,
        *,
        from_model: str,
        to_model: str,
        error: str,
    ) -> None:
        metadata = getattr(response, "response_metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["model_fallback"] = {
            "from_model": from_model,
            "to_model": to_model,
            "error": str(error)[:200],
        }
        with contextlib.suppress(Exception):
            response.response_metadata = metadata

    async def ainvoke(self, messages: list[BaseMessage], **kwargs):  # 异步调用，自动故障转移
        # P4 新增：从 kwargs 中弹出缓存相关参数，避免传给底层 LLM
        # cache_key 由调用方传入（一般通过 SemanticCache.compute_query_hash 生成）；
        # 不传 cache_key 时禁用缓存，行为与原版一致，保证向后兼容
        cache_key = kwargs.pop("cache_key", None)
        task_type = kwargs.pop("task_type", "") or getattr(self, "_agent_key", "")
        # company_id 优先用 kwargs 中的，其次用构造时绑定的 _company_id
        company_id = kwargs.pop("company_id", None) or getattr(self, "_company_id", None)

        # P4 新增：语义缓存命中检查
        # 仅在显式传入 cache_key 时启用，避免对工具调用/流式等场景误缓存
        if cache_key:
            try:
                cached = await self.gateway.semantic_cache.get(cache_key)
                if cached is not None:
                    logger.info("semantic_cache_hit", cache_key=cache_key, model=self.model_key)
                    # 记录审计日志（fire-and-forget，不阻塞返回）
                    if company_id:
                        asyncio.ensure_future(
                            self.gateway.audit_logger.log(
                                company_id=company_id,
                                user_id=None,
                                action="cache_hit",
                                resource=self.model_key,
                                metadata={"cache_key": cache_key},
                            )
                        )
                    # 用缓存的文本构造 AIMessage 返回，保持响应类型一致
                    from langchain_core.messages import AIMessage

                    return AIMessage(content=cached)
            except Exception as e:
                # 缓存查询失败不阻塞主流程，继续走 LLM 调用路径
                logger.warning("semantic_cache_get_failed", cache_key=cache_key, error=str(e))

        last_exc = None  # 保存最后一个异常，用于最终异常信息
        for i, model in enumerate(self.models):  # 按顺序尝试模型，先主后fallback
            try:
                name = self.model_key if i == 0 else self.fallback_models[i - 1]  # 确定当前模型名称
                logger.info("model_invoke", model_name=name)
                if hasattr(model, "ainvoke"):  # 优先使用异步调用
                    resp = await self._breaker.call(model.ainvoke, messages, **kwargs)
                else:  # 降级为同步调用
                    resp = self._breaker.call_sync(model.invoke, messages, **kwargs)
                if company_id:
                    self._company_id = company_id
                self._record_usage(name, resp, messages)  # 记录用量和成本

                # P4 新增：调用成功后标记模型健康
                await self.gateway.router.mark_healthy(name)

                # P4 新增：写入语义缓存 + 记录 cache_miss 审计日志 + 成本归因
                # 这些操作失败都不应阻塞返回，分别 try/except
                response_content = getattr(resp, "content", None)
                if cache_key and response_content is not None:
                    try:
                        await self.gateway.semantic_cache.set(cache_key, str(response_content))
                    except Exception as e:
                        logger.warning(
                            "semantic_cache_set_failed", cache_key=cache_key, error=str(e)
                        )

                if cache_key and company_id:
                    # 记录 cache_miss 审计日志（命中时上面已记 cache_hit，此处只在 miss 时记）
                    with contextlib.suppress(Exception):
                        asyncio.ensure_future(
                            self.gateway.audit_logger.log(
                                company_id=company_id,
                                user_id=None,
                                action="cache_miss",
                                resource=self.model_key,
                                metadata={"cache_key": cache_key},
                            )
                        )

                # P4 新增：成本归因（写 cost_records 表，含 task_type 维度）
                if company_id:
                    self._record_cost_attribution(
                        company_id=company_id,
                        model_key=name,
                        response=resp,
                        messages=messages,
                        task_type=task_type,
                    )

                if i > 0 and last_exc is not None:
                    self._attach_model_fallback_metadata(
                        resp,
                        from_model=self.model_key,
                        to_model=name,
                        error=str(last_exc),
                    )

                return resp  # 成功则立即返回
            except CircuitBreakerOpenError:
                # P4 新增：熔断触发时标记模型失败（便于路由层后续跳过）
                await self.gateway.router.mark_failed(self.model_key)
                raise  # 熔断器开启时直接抛出，不再尝试 fallback
            except Exception as e:  # 捕获所有异常，尝试下一个模型
                last_exc = e
                # P4 新增：触发 fallback 时标记主模型失败 + 记录审计日志
                await self.gateway.router.mark_failed(name)
                if i < len(self.models) - 1 and company_id:  # 还有 fallback 可试
                    with contextlib.suppress(Exception):
                        asyncio.ensure_future(
                            self.gateway.audit_logger.log(
                                company_id=company_id,
                                user_id=None,
                                action="fallback_triggered",
                                resource=name,
                                metadata={
                                    "error": str(e)[:200],
                                    "fallback_to": self.fallback_models[i]
                                    if i < len(self.fallback_models)
                                    else None,
                                },
                            )
                        )
                logger.warning("model_fallback", model_name=name, error=str(e))  # 记录fallback事件
        # 所有模型都失败：抛出异常前记录 token_budget_exceeded 审计日志（仅当 company_id 可用时）
        if company_id:
            with contextlib.suppress(Exception):
                asyncio.ensure_future(
                    self.gateway.audit_logger.log(
                        company_id=company_id,
                        user_id=None,
                        action="token_budget_exceeded",
                        resource=self.model_key,
                        metadata={"error": str(last_exc)[:200] if last_exc else "unknown"},
                    )
                )
        raise Exception(f"All models failed. Last error: {last_exc}")  # 所有模型都失败，抛出异常

    def _record_cost_attribution(
        self,
        company_id: int,
        model_key: str,
        response,
        messages: list[BaseMessage],
        task_type: str = "",
    ) -> None:
        """P4 新增：异步派发成本归因记录（fire-and-forget）

        从 response.usage 提取 token 数，从 models_config 提取单价计算 cost_usd，
        委托给 CostAttributor.record 异步写入 cost_records 表。
        失败不阻塞主流程（约束 6）。
        """
        try:
            # 提取 token 用量（与 _record_usage 同样的逻辑）
            input_tokens = getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0
            output_tokens = getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0
            if not input_tokens and not output_tokens:
                # API 未返回 token 数时粗略估算
                input_tokens = sum(len(getattr(m, "content", "") or "") for m in messages) // 2
                output_tokens = len(getattr(response, "content", "") or "") // 2

            cfg = self.gateway.models_config.get(model_key, {})
            cost_usd = (input_tokens / 1000) * cfg.get("cost_per_1k_input", 0) + (
                output_tokens / 1000
            ) * cfg.get("cost_per_1k_output", 0)
            provider = cfg.get("provider", "")

            # fire-and-forget：成本归因不阻塞返回
            asyncio.ensure_future(
                self.gateway.cost_attributor.record(
                    company_id=company_id,
                    model_key=model_key,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    task_type=task_type,
                    provider=provider,
                    cost_usd=cost_usd,
                )
            )
        except Exception as e:
            logger.warning(
                "cost_attribution_dispatch_failed",
                company_id=company_id,
                model_key=model_key,
                error=str(e),
            )

    def invoke(self, messages: list[BaseMessage], **kwargs):  # 同步调用包装器，内部调用 ainvoke
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ainvoke(messages, **kwargs))
        # 在已有事件循环中创建新的事件循环运行
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, self.ainvoke(messages, **kwargs))
            return future.result()

    def bind_tools(self, tools: list):  # 绑定工具，仅主模型支持
        if not self.models:
            raise RuntimeError("No models to bind tools")
        if hasattr(self.models[0], "bind_tools"):  # 检查主模型是否支持bind_tools
            import copy

            bound = copy.copy(self)
            bound.models = list(self.models)
            bound.models[0] = self.models[0].bind_tools(tools)
            return bound
        raise AttributeError("Primary model doesn't support bind_tools")

    def _record_usage(
        self, model_name: str, response, messages: list[BaseMessage]
    ):  # 记录每次调用的token用量和成本
        try:  # 成本追踪失败不应影响主流程
            input_tokens = getattr(
                getattr(response, "usage", None), "prompt_tokens", 0
            )  # 安全获取输入token，默认0
            output_tokens = getattr(
                getattr(response, "usage", None), "completion_tokens", 0
            )  # 安全获取输出token
            if not input_tokens and not output_tokens:  # 如果API未返回token数，则估算
                input_tokens = (
                    sum(len(getattr(m, "content", "") or "") for m in messages) // 2
                )  # getattr 防 content 为 None,与 _record_cost_attribution 一致
                output_tokens = len(getattr(response, "content", "") or "") // 2
            cfg = self.gateway.models_config.get(model_name, {})  # 获取模型配置中的价格
            # 计算成本：输入成本 + 输出成本
            cost = (input_tokens / 1000) * cfg.get("cost_per_1k_input", 0) + (
                output_tokens / 1000
            ) * cfg.get("cost_per_1k_output", 0)

            from app.tracking.cost_tracker import CostTracker  # 延迟导入，避免循环依赖

            CostTracker.record_usage(
                model_name, input_tokens, output_tokens, cost, str(uuid.uuid4())
            )  # 记录到成本追踪器

            try:  # 嵌套try，持久化失败不影响追踪
                from app.services.model_gateway_extensions import (  # 延迟导入
                    TokenUsagePersistence,
                    TokenUsageRecord,
                )

                company_id = getattr(self, "_company_id", None)  # 使用getattr安全获取
                if not company_id:  # 无法确定租户时不可降级到 1，否则会造成计费/数据越权
                    logger.warning("cost_record_skipped_no_company_id", model=model_name)
                    return
                TokenUsagePersistence.record(
                    TokenUsageRecord(  # 持久化到数据库
                        company_id=company_id,
                        agent_key=getattr(self, "_agent_key", ""),
                        model_name=model_name,
                        provider=cfg.get("provider", ""),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost,
                    )
                )
            except Exception as persist_err:  # 持久化失败不影响主流程，但必须可诊断
                logger.warning(
                    "token_usage_persistence_failed",
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error=str(persist_err),
                )
        except Exception as e:  # 成本追踪异常不影响主流程
            logger.error("cost_tracker_error", error=str(e))

    def check_budget_before_call(
        self, messages: list[BaseMessage], rag_context: str = "", tool_schemas: list = None
    ) -> dict:
        """调用前Token预算检查 - 文档依据: 2.docx

        公式: window >= input_tokens + max_output_tokens
        返回预算信息，超预算时调用方应执行降级策略
        """
        system_content = ""
        user_content = ""
        history = []
        for msg in messages:
            role = getattr(msg, "type", "")
            if role == "system":
                system_content = getattr(msg, "content", "")
            elif role == "human":
                user_content = getattr(msg, "content", "")
            else:
                history.append(msg)

        input_tokens = self._token_budget.estimate_input_tokens(
            system_prompt=system_content,
            user_prompt=user_content,
            history_messages=history,
            rag_context=rag_context,
            tool_schemas=tool_schemas,
        )
        is_within, budget_info = self._token_budget.check_budget(input_tokens)
        if not is_within:
            strategy = self._token_budget.get_degrade_strategy(input_tokens)
            budget_info["degrade_strategy"] = strategy
            logger.warning(
                "token_budget_exceeded",
                input_tokens=input_tokens,
                max_output=self._token_budget.max_output_tokens,
                strategy=strategy,
            )
        return budget_info

    async def ainvoke_with_budget(
        self,
        messages: list[BaseMessage],
        rag_context: str = "",
        tool_schemas: list = None,
        **kwargs,
    ) -> tuple:
        """带预算检查的调用 - 超预算时自动降级

        Returns:
            (response, budget_info)
        """
        budget_info = self.check_budget_before_call(messages, rag_context, tool_schemas)
        if not budget_info.get("is_within_budget", True):
            strategy = budget_info.get("degrade_strategy", "reject")
            if strategy == "reject":
                raise ValueError(
                    f"Token预算严重超限: input={budget_info['input_tokens']}, "
                    f"max_output={budget_info['max_output_tokens']}, "
                    f"window={budget_info['effective_window']}"
                )
            logger.info("token_budget_degrading", strategy=strategy)
        resp = await self.ainvoke(messages, **kwargs)
        return resp, budget_info

    async def astream(self, messages: list[BaseMessage], **kwargs) -> AsyncGenerator[str, None]:
        """流式输出 - 文档依据: 2.docx

        SSE协议流式输出，追踪TTFT（首字延迟）指标
        使用astream_events获取token级别的流式事件
        """
        model = self.models[0]  # 流式输出仅使用主模型
        name = self.model_key
        ttft_start = time.time()
        first_token_sent = False

        try:
            if hasattr(model, "astream"):
                async for chunk in model.astream(messages, **kwargs):
                    if not first_token_sent:
                        ttft_ms = (time.time() - ttft_start) * 1000
                        first_token_sent = True
                        logger.info("streaming_ttft", model_name=name, ttft_ms=round(ttft_ms, 2))
                    yield chunk
            else:
                # 降级：非流式模型直接返回完整响应
                resp = await self.ainvoke(messages, **kwargs)
                yield resp
        except Exception as e:
            logger.error("streaming_error", model_name=name, error=str(e))
            raise

    async def ainvoke_structured(
        self, messages: list[BaseMessage], output_schema: dict, **kwargs
    ) -> dict:
        """结构化输出调用 - 4级兜底机制

        文档依据: 2.docx - 结构化输出4级兜底:
        L1: 本地JSON Schema校验
        L2: 轻量修复
        L3: 降级Schema重试
        L4: 人工兜底

        Returns:
            {
                "success": bool,
                "data": dict,
                "fallback_level": str | None,
                "raw_content": str,
            }
        """
        raw_content = ""

        # L1: 直接调用 + JSON Schema校验
        try:
            resp = await self.ainvoke(messages, **kwargs)
            raw_content = getattr(resp, "content", str(resp))
            is_valid, error, data = self._output_validator.validate_json_schema(
                raw_content, output_schema
            )
            if is_valid:
                return {
                    "success": True,
                    "data": data,
                    "fallback_level": None,
                    "raw_content": raw_content,
                }
            logger.warning("structured_output_l1_failed", error=error)
        except Exception as e:
            raw_content = str(e)
            logger.warning("structured_output_l1_error", error=str(e))

        # L2: 轻量修复
        repaired_ok, repair_status, repaired_content = self._output_validator.lightweight_repair(
            raw_content, output_schema
        )
        if repaired_ok:
            try:
                data = json.loads(repaired_content)
                is_valid, error, _ = self._output_validator.validate_json_schema(
                    repaired_content, output_schema
                )
                if is_valid:
                    return {
                        "success": True,
                        "data": data,
                        "fallback_level": "L2",
                        "raw_content": raw_content,
                    }
            except Exception as repair_err:
                logger.warning(
                    "structured_output_l2_repair_exception",
                    repair_status=repair_status,
                    error=str(repair_err),
                )
        logger.warning("structured_output_l2_failed")

        # L3: 降级Schema重试
        try:
            degraded_schema = self._output_validator.degrade_schema(output_schema)
            # 添加降级指令到消息
            from langchain_core.messages import SystemMessage

            degrade_instruction = SystemMessage(
                content="请以简化JSON格式输出，只包含核心字段，不要嵌套复杂对象。"
            )
            retry_messages = [degrade_instruction] + list(messages)
            resp = await self.ainvoke(retry_messages, **kwargs)
            raw_content = getattr(resp, "content", str(resp))
            is_valid, error, data = self._output_validator.validate_json_schema(
                raw_content, degraded_schema
            )
            if is_valid:
                return {
                    "success": True,
                    "data": data,
                    "fallback_level": "L3",
                    "raw_content": raw_content,
                }
        except Exception as e:
            logger.warning("structured_output_l3_failed", error=str(e))

        # L4: 人工兜底
        fallback = self._output_validator.human_fallback(
            raw_content, "All fallback levels exhausted"
        )
        return {
            "success": False,
            "data": fallback,
            "fallback_level": "L4",
            "raw_content": raw_content,
        }


# ============ 流式异常处理 ============
# 文档依据: 2.docx - 流式异常4类场景: 用户取消/超时/断流/重连


class StreamErrorType(StrEnum):
    """流式异常类型"""

    USER_CANCELLED = "user_cancelled"
    TTFT_TIMEOUT = "ttft_timeout"
    TOTAL_TIMEOUT = "total_timeout"
    STREAM_BROKEN = "stream_broken"
    SUPPLIER_ERROR = "supplier_error"


class StreamState:
    """流式状态管理器 - 文档依据: 2.docx

    追踪流式输出的完整生命周期:
    - message_id: 业务消息ID
    - sequence: 增量片段序号
    - finish_reason: 结束原因
    - is_interrupted: 是否被中断
    """

    def __init__(self, message_id: str):
        self.message_id = message_id
        self.sequence = 0
        self.buffer: list[str] = []
        self.finish_reason: str | None = None
        self.is_interrupted = False
        self.error: str | None = None
        self.start_time = time.time()
        self.first_token_time: float | None = None

    def append(self, delta: str) -> int:
        """追加增量片段，返回当前序号"""
        self.sequence += 1
        self.buffer.append(delta)
        if self.first_token_time is None:
            self.first_token_time = time.time()
        return self.sequence

    def full_text(self) -> str:
        return "".join(self.buffer)

    def mark_complete(self, finish_reason: str):
        self.finish_reason = finish_reason

    def mark_interrupted(self, error: str):
        self.is_interrupted = True
        self.error = error

    def get_ttft_ms(self) -> float | None:
        if self.first_token_time:
            return (self.first_token_time - self.start_time) * 1000
        return None

    def get_elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000


# ============ Prompt Caching ============
# 文档依据: 2.docx - Prompt Caching省钱逻辑
# 稳定内容放前面(System Prompt, 工具定义, RAG Context)
# 变化内容放后面(User Prompt)
# 监控 cache_read_tokens 和 cache_creation_tokens 指标


class PromptCacheManager:
    """Prompt缓存管理器 - 文档依据: 2.docx

    原理: 供应商会缓存请求中"可复用的前缀部分"。
    下次请求如果前缀相同，这部分就不重新计费，只收"缓存读取"的费用。

    典型适用场景:
    - 多轮对话 (System Prompt + 历史Message不变)
    - RAG应用 (检索片段重复率高)
    - 批量评估 (同一份System Prompt, 不同的输入)

    工程建议:
    - 把不变的内容放前面 (System Prompt, 工具定义, RAG Context)
    - 把变化的内容放后面 (User Prompt)
    - 监控 cache_read_tokens 和 cache_creation_tokens 指标
    - 批量任务尽量在缓存时间窗口内完成
    """

    def __init__(self):
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_creation_tokens = 0
        self._cache_read_tokens = 0

    def record_cache_hit(self, read_tokens: int = 0):
        """记录缓存命中"""
        self._cache_hits += 1
        self._cache_read_tokens += read_tokens

    def record_cache_miss(self, creation_tokens: int = 0):
        """记录缓存未命中"""
        self._cache_misses += 1
        self._cache_creation_tokens += creation_tokens

    def get_hit_rate(self) -> float:
        """获取缓存命中率"""
        total = self._cache_hits + self._cache_misses
        if total == 0:
            return 0.0
        return self._cache_hits / total

    def get_stats(self) -> dict:
        """获取缓存统计"""
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": round(self.get_hit_rate(), 3),
            "creation_tokens": self._cache_creation_tokens,
            "read_tokens": self._cache_read_tokens,
            "estimated_savings": round(
                self._cache_read_tokens * 0.0001,
                4,  # 粗略估算节省成本
            ),
        }

    @staticmethod
    def optimize_prompt_order(
        system_prompt: str, tool_definitions: str, rag_context: str, user_prompt: str
    ) -> str:
        """优化Prompt顺序以最大化缓存命中率 - 文档依据: 2.docx

        稳定内容放前面，变化内容放后面
        """
        parts = []
        if system_prompt:
            parts.append(system_prompt)
        if tool_definitions:
            parts.append(tool_definitions)
        if rag_context:
            parts.append(rag_context)
        if user_prompt:
            parts.append(user_prompt)
        return "\n\n".join(parts)


# ============ 流式异常处理增强 ============


class StreamErrorHandler:
    """流式异常处理器 - 文档依据: 2.docx

    处理4类流式异常:
    1. 用户取消 (User Cancelled): 关闭页面/点击停止/切换会话
    2. 超时 (Timeout): 连接超时/TTFT超时/总时长超时
    3. 断流 (Stream Broken): 供应商流中断, 没有正常结束标记
    4. 重连 (Reconnect): SSE自动重连, 从断点续传

    核心原则:
    - 用户取消时同时取消供应商请求和后续任务
    - 断流时不把半截内容当成成功
    - 记录finish_reason或最后事件状态
    """

    # 默认超时配置(秒)
    DEFAULT_CONNECT_TIMEOUT = 10.0
    DEFAULT_TTFT_TIMEOUT = 15.0
    DEFAULT_TOTAL_TIMEOUT = 120.0

    def __init__(
        self, connect_timeout: float = None, ttft_timeout: float = None, total_timeout: float = None
    ):
        self.connect_timeout = connect_timeout or self.DEFAULT_CONNECT_TIMEOUT
        self.ttft_timeout = ttft_timeout or self.DEFAULT_TTFT_TIMEOUT
        self.total_timeout = total_timeout or self.DEFAULT_TOTAL_TIMEOUT

    def check_ttft(self, stream_state: StreamState) -> bool:
        """检查TTFT是否超时"""
        if stream_state.first_token_time is not None:
            return True  # 已经收到首个token
        elapsed = stream_state.get_elapsed_ms() / 1000
        return elapsed < self.ttft_timeout

    def check_total_timeout(self, stream_state: StreamState) -> bool:
        """检查总时长是否超时"""
        elapsed = stream_state.get_elapsed_ms() / 1000
        return elapsed < self.total_timeout

    def should_retry_stream(self, error_type: StreamErrorType) -> bool:
        """判断流式异常是否应该重试"""
        # 用户取消和断流通常不重试
        non_retryable = {
            StreamErrorType.USER_CANCELLED,
            StreamErrorType.STREAM_BROKEN,
        }
        return error_type not in non_retryable

    def handle_user_cancelled(self, stream_state: StreamState):
        """处理用户取消 - 文档依据: 2.docx

        用户关闭页面、点击停止生成、切换会话时触发。
        需要同时取消:
        - 到供应商API的请求
        - 正在解析的响应流
        - 后续TTS、工具调用、落库任务
        - 还没提交的增量缓存
        """
        stream_state.mark_interrupted("User cancelled the request")
        logger.info(
            "stream_user_cancelled",
            message_id=stream_state.message_id,
            tokens_generated=stream_state.sequence,
        )

    def handle_broken_stream(self, stream_state: StreamState):
        """处理断流 - 文档依据: 2.docx

        断流时不要轻易把半截内容当成成功。
        正确做法是记录finish_reason或最后事件状态，
        如果没有正常结束标记，就把本次调用标记为INTERRUPTED。
        """
        if stream_state.finish_reason is None:
            stream_state.mark_interrupted("Stream broken without finish_reason")
            logger.warning(
                "stream_broken",
                message_id=stream_state.message_id,
                tokens_received=stream_state.sequence,
            )


class ModelGateway:  # 模型网关核心类，集成配置管理、Key管理、配额管理、路由和模型创建
    """模型网关 - 多提供商 + 智能路由 + 企业 Key"""

    def __init__(
        self, config_path: str = None
    ):  # 配置文件路径可选，默认使用项目config目录下的model_config.yaml
        if not config_path:  # 构建默认配置路径
            config_path = os.path.join(BASE_DIR, "config", "model_config.yaml")
        self.config_path = config_path  # 保存配置文件路径
        self.models_config: dict[str, dict] = {}  # 模型配置字典，键为模型key
        self.default_model = "deepseek"  # 默认模型，在配置加载失败时使用
        self._config_loaded = False  # 配置加载标志，用于懒加载
        self.key_manager = EnterpriseKeyManager()  # 企业Key管理器
        self.quota_manager = TokenQuotaManager()  # Token配额管理器
        self.router = ModelRouter()  # 模型路由器（P4 增强：含任务类型路由 + 健康度感知）
        # P4 新增：语义缓存、成本归因、审计日志
        # 均为延迟初始化的组件，构造时不阻塞，Redis 连接在首次 await init() 时验证
        self.semantic_cache = SemanticCache()
        self.cost_attributor = CostAttributor()
        self.audit_logger = AuditLogger()
        load_dotenv()  # 加载.env文件，确保API Key等环境变量可用

    async def init_p4_components(self):
        """P4 新增：异步初始化所有依赖 Redis 的组件

        应在 FastAPI lifespan 启动阶段调用：
            await get_global_model_gateway().init_p4_components()

        与 token_blacklist.init() / session_store.init() 并列。
        失败时各自降级，不抛异常。
        """
        try:
            await self.semantic_cache.init()
        except Exception as e:
            logger.warning("model_gateway_semantic_cache_init_failed", error=str(e))
        try:
            await self.router.init()
        except Exception as e:
            logger.warning("model_gateway_router_init_failed", error=str(e))

    async def close_p4_components(self):
        """P4 新增：关闭所有依赖 Redis 的组件，释放连接池"""
        try:
            await self.semantic_cache.close()
        except Exception as e:
            logger.warning("model_gateway_semantic_cache_close_failed", error=str(e))
        try:
            await self.router.close()
        except Exception as e:
            logger.warning("model_gateway_router_close_failed", error=str(e))

    def _load_config(self):  # 懒加载配置，仅在首次使用时加载
        if self._config_loaded:  # 已加载则跳过
            return
        try:  # 配置文件加载失败使用默认配置
            with open(self.config_path, encoding="utf-8") as f:  # 指定utf-8编码，支持中文
                data = (
                    yaml.safe_load(f) or {}
                )  # 空文件返回 None,用 {} 兜底避免 None.get() 的 AttributeError
            self.models_config = data.get("models", {})  # 提取模型配置
            self.default_model = (
                os.getenv(MODEL_GATEWAY_DEFAULT_ENV)
                or data.get("default_model", "deepseek")
            )  # 评估环境可显式覆盖默认模型，避免误走未配置供应商
            self._inject_eval_proxy_model_from_env()
            self._config_loaded = True
        except FileNotFoundError:  # 配置文件不存在时使用硬编码默认配置
            logger.warning("model_config_not_found_defaults")
            self.models_config = self._default_config()  # 使用硬编码的默认配置
            self._inject_eval_proxy_model_from_env()
            self._config_loaded = True
        except yaml.YAMLError as e:  # 配置文件格式错误时降级到默认配置,避免阻塞启动
            logger.warning("model_config_parse_error_defaults", error=str(e))
            self.models_config = self._default_config()
            self._inject_eval_proxy_model_from_env()
            self._config_loaded = True

    def _inject_eval_proxy_model_from_env(self) -> None:
        base_url = _first_env_value(EVAL_PROXY_BASE_URL_ENV_KEYS)
        if not base_url:
            return

        model_key = os.getenv("AGENT_EVAL_PROXY_MODEL_KEY", EVAL_PROXY_MODEL_KEY).strip()
        model_key = model_key or EVAL_PROXY_MODEL_KEY
        model_name = _first_env_value(EVAL_PROXY_MODEL_NAME_ENV_KEYS) or "default"

        self.models_config[model_key] = {
            "provider": EVAL_PROXY_MODEL_KEY,
            "model_name": model_name,
            "base_url": base_url,
            "temperature": float(os.getenv("AGENT_EVAL_TEMPERATURE", "0.7")),
            "max_tokens": int(os.getenv("AGENT_EVAL_MAX_TOKENS", "2048")),
            "fallback_models": [],
        }

    def _resolve_model_key(self, model_key: str | None) -> str:
        # Resolve legacy model keys to keys that exist in the loaded config.
        candidate = model_key or self.default_model
        if candidate in self.models_config:
            return candidate

        alias = MODEL_KEY_ALIASES.get(candidate)
        if alias and alias in self.models_config:
            return alias

        if self.default_model in self.models_config:
            return self.default_model

        alias = MODEL_KEY_ALIASES.get(self.default_model)
        if alias and alias in self.models_config:
            return alias

        return candidate

    def _configured_model_exists(self, model_key: str | None) -> bool:
        if not model_key:
            return False
        if model_key in self.models_config:
            return True
        alias = MODEL_KEY_ALIASES.get(model_key)
        return bool(alias and alias in self.models_config)

    def validate_startup_config(self, require_api_key: bool | None = None) -> dict[str, Any]:
        """Validate static model routing config before serving traffic.

        This intentionally does not make live model API calls. It catches local
        configuration errors early: missing default model, dangling fallback
        references, and missing production API key for the default provider.
        """
        self._load_config()
        require_key = os.getenv("ENV") == "prod" if require_api_key is None else require_api_key
        errors: list[str] = []
        resolved_default = self._resolve_model_key(self.default_model)

        if not self.models_config:
            errors.append("model_config.yaml has no configured models")
        elif not self._configured_model_exists(resolved_default):
            errors.append(f"default model '{self.default_model}' is not configured")

        for model_key, cfg in self.models_config.items():
            for fallback_key in cfg.get("fallback_models") or []:
                if not self._configured_model_exists(fallback_key):
                    errors.append(
                        f"model '{model_key}' references missing fallback model '{fallback_key}'"
                    )

        if require_key and self._configured_model_exists(resolved_default):
            provider = self.models_config[resolved_default].get("provider", resolved_default)
            if not self._get_env_api_key(provider):
                errors.append(
                    f"default model '{resolved_default}' provider '{provider}' has no API key"
                )

        if errors:
            raise RuntimeError("Model gateway startup config invalid: " + "; ".join(errors))

        return {
            "default_model": resolved_default,
            "model_count": len(self.models_config),
            "require_api_key": require_key,
        }

    def _default_config(self) -> dict:  # 硬编码的默认配置，确保在配置文件缺失时系统仍可运行
        return {
            "deepseek": {  # DeepSeek聊天模型：性价比高，适合大多数场景
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "temperature": 0.7,
                "max_tokens": 8192,
                "cost_per_1k_input": 0.002,
                "cost_per_1k_output": 0.006,
                "suitable_for": ["simple", "standard"],
                "fallback_models": [],  # 无fallback
            },
            "deepseek_reasoner": {  # DeepSeek推理模型：适合复杂推理任务，温度低以保证一致性
                "provider": "deepseek",
                "model_name": "deepseek-reasoner",
                "base_url": "https://api.deepseek.com/v1",
                "temperature": 0.3,  # 较低温度，推理任务需要确定性
                "max_tokens": 65536,  # 大输出窗口，支持长推理链
                "cost_per_1k_input": 0.004,
                "cost_per_1k_output": 0.016,
                "suitable_for": ["complex"],
                "fallback_models": ["deepseek"],  # 失败时降级为chat模型
            },
            "volcano_lite": {  # 火山引擎豆包Lite模型：成本最低，适合简单任务
                "provider": "volcano",
                "model_name": "doubao-lite-32k",
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "temperature": 0.7,
                "max_tokens": 4096,
                "cost_per_1k_input": 0.0003,  # 极低价格
                "cost_per_1k_output": 0.0006,
                "suitable_for": ["simple"],
                "fallback_models": ["deepseek"],  # 失败时降级为deepseek
            },
        }

    def _get_env_api_key(
        self, provider: str
    ) -> str | None:  # 从环境变量获取API Key，映射规则可配置
        env_map = {  # provider -> accepted environment variable names
            "deepseek": ("DEEPSEEK_API_KEY",),
            "openai": ("OPENAI_API_KEY",),
            "volcano": ("VOLCANO_API_KEY", "DEEPSEEK_VOLC_API_KEY"),
            "tokenrhythm": ("TOKENRHYTHM_API_KEY",),
            EVAL_PROXY_MODEL_KEY: ("AGENT_EVAL_API_KEY",),
        }
        env_keys = env_map.get(provider, (f"{provider.upper()}_API_KEY",))
        for env_key in env_keys:
            value = os.getenv(env_key)
            if value:
                return value
        return None

    def _create_model_instance(
        self, model_key: str, company_api_key: str | None = None
    ) -> ChatOpenAI:  # 创建ChatOpenAI实例，企业Key优先于环境变量
        cfg = self.models_config.get(model_key, {})  # 获取模型配置
        if not cfg:  # 未知模型key抛出异常
            raise ValueError(f"Unknown model key: {model_key}")

        provider = cfg.get("provider", "deepseek")  # 默认deepseek

        api_key = company_api_key  # 优先使用企业Key
        if not api_key:  # 企业Key为空时使用环境变量
            api_key = self._get_env_api_key(provider)

        if not api_key:  # 仍然没有Key则抛出异常
            raise ValueError(
                f"No API key available for {model_key}. "
                f"Set {provider.upper()}_API_KEY environment variable or provide company API key."
            )

        params = {  # 构建ChatOpenAI参数
            "model": cfg["model_name"],  # 实际模型名称
            "api_key": api_key,
            "temperature": cfg.get("temperature", 0.7),  # 默认温度0.7
        }
        if "base_url" in cfg:  # 仅在有base_url时设置，OpenAI默认不需要
            params["base_url"] = cfg["base_url"]
        if cfg.get("max_tokens"):  # 仅在有值时设置
            params["max_tokens"] = cfg["max_tokens"]
        if cfg.get("top_p"):  # top_p通过model_kwargs传递
            params["model_kwargs"] = {"top_p": cfg["top_p"]}

        return ChatOpenAI(**params)  # 创建实例

    def get_llm(
        self,
        model_key: str = None,
        company_api_key: str = None,
        company_id: int = None,
        agent_key: str = "",
    ) -> FailoverChatModel:  # 获取LLM实例，默认使用default_model
        self._load_config()  # 确保配置已加载
        resolved_model_key = self._resolve_model_key(model_key)

        if company_id and company_api_key is None:  # 指定了企业ID但未提供Key时自动获取
            company_api_key = self.key_manager.get_key(
                company_id,
                self.models_config.get(resolved_model_key, {}).get(
                    "provider", "deepseek"
                ),
            )

        return FailoverChatModel(
            self,
            resolved_model_key,  # 使用默认模型作为兜底
            company_api_key,
            company_id,
            agent_key,
        )

    def get_llm_for_agent(
        self,
        agent_name: str,
        task_description: str = "",
        company_id: int = None,
        company_api_key: str = None,
    ) -> FailoverChatModel:  # 为Agent自动选择模型
        self._load_config()  # 确保配置已加载

        complexity = self.router.estimate_complexity(task_description)  # 估算任务复杂度
        model_key = self.router.get_model(agent_name, complexity)  # 根据Agent和复杂度选择模型
        model_key = self._resolve_model_key(model_key)

        if company_id and not company_api_key:  # 自动获取企业Key
            provider = self.models_config.get(model_key, {}).get("provider", "deepseek")
            company_api_key = self.key_manager.get_key(company_id, provider)

        logger.info(  # 记录路由决策，便于后续分析
            "model_routed",
            agent=agent_name,
            complexity=complexity.value,
            model=model_key,
        )

        return FailoverChatModel(self, model_key, company_api_key, company_id, agent_name)

    async def get_llm_for_task(
        self,
        task_type: str,
        company_id: int | None = None,
        company_api_key: str | None = None,
        task_description: str = "",
    ) -> FailoverChatModel:
        """P4 新增：按任务类型获取 LLM 实例

        与 get_llm_for_agent 互补：
        - get_llm_for_agent：按 Agent 名 + 任务复杂度路由（沿用原有路由规则）
        - get_llm_for_task：按任务类型（chat/analysis/code/vision）路由 + 健康度感知

        Args:
            task_type: 任务类型，见 DEFAULT_TASK_TYPE_ROUTING 的 key
            company_id: 公司 ID，传入时会读取 company_llm_config 偏好模型
            company_api_key: 企业 API Key，未传入时自动从 key_manager 获取
            task_description: 任务描述（仅用于日志，不影响路由决策）

        Returns:
            FailoverChatModel 实例，已绑定路由后的 model_key
        """
        self._load_config()  # 确保配置已加载

        # 通过 ModelRouter.route 选择最优模型（含健康度感知 + 公司偏好）
        model_key = await self.router.route(
            task_type=task_type,
            company_id=company_id,
            available_models=self.models_config,
        )
        model_key = self._resolve_model_key(model_key)

        if company_id and not company_api_key:
            provider = self.models_config.get(model_key, {}).get("provider", "deepseek")
            company_api_key = self.key_manager.get_key(company_id, provider)

        logger.info(  # 记录任务类型路由决策
            "model_routed_by_task",
            task_type=task_type,
            model=model_key,
            company_id=company_id,
        )

        # 记录审计日志（model_switch）——失败不阻塞主流程
        if company_id:
            with contextlib.suppress(Exception):
                # fire-and-forget：审计日志不阻塞返回
                asyncio.ensure_future(
                    self.audit_logger.log(
                        company_id=company_id,
                        user_id=None,
                        action="model_switch",
                        resource=model_key,
                        metadata={
                            "task_type": task_type,
                            "task_description": task_description[:200],
                        },
                    )
                )

        return FailoverChatModel(self, model_key, company_api_key, company_id, task_type)

    def get_default_model(self) -> str:  # 获取默认模型名称
        return self.default_model

    def list_models(self) -> list[dict]:  # 列出所有可用模型及其配置摘要
        self._load_config()  # 确保配置已加载
        return [  # 返回简化的模型列表，隐藏敏感信息
            {
                "key": k,
                "provider": v.get("provider", ""),
                "model_name": v.get("model_name", ""),
                "suitable_for": v.get("suitable_for", []),
                "cost_per_1k_input": v.get("cost_per_1k_input", 0),
                "cost_per_1k_output": v.get("cost_per_1k_output", 0),
            }
            for k, v in self.models_config.items()
        ]


_global_model_gateway: ModelGateway | None = None  # 全局单例变量，类型注解表明可为None
_gateway_lock = threading.Lock()  # 线程锁，确保单例的线程安全


def get_global_model_gateway() -> ModelGateway:  # 双检锁单例模式，获取全局ModelGateway
    global _global_model_gateway
    if _global_model_gateway is None:  # 第一次检查，避免不必要的锁竞争
        with _gateway_lock:  # 获取锁
            if _global_model_gateway is None:  # 第二次检查，防止并发创建
                _global_model_gateway = ModelGateway()  # 创建单例
    return _global_model_gateway
