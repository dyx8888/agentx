"""
模型网关升级扩展：Token 统计持久化 + 模型健康监控 + 企业配额管理 API
"""  # 从model_gateway中抽离的扩展模块，独立维护以避免model_gateway过于臃肿

import time  # 用于健康检查的延迟测量
from dataclasses import dataclass, field  # 用于TokenUsageRecord数据载体和可变默认值
from datetime import datetime  # 用于记录时间戳和UTC时间

from app.core.logging import get_logger  # 统一日志记录，便于追踪和调试

logger = get_logger(__name__)  # 模块级logger，按模块名分组日志


@dataclass  # 使用dataclass，因为TokenUsageRecord是纯数据载体，不需要方法
class TokenUsageRecord:  # 每次模型调用的用量记录，用于成本核算和配额管理
    company_id: int  # 企业ID，用于多租户成本隔离
    agent_key: str = ""  # Agent标识，默认空字符串表示未指定
    model_name: str = ""  # 模型名称，用于区分不同模型的使用成本
    provider: str = ""  # 提供商，用于区分不同平台的费用
    input_tokens: int = 0  # 输入token数，默认0表示可能未成功获取
    output_tokens: int = 0  # 输出token数
    cost_usd: float = 0.0  # 美元成本，使用float保留精度
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 使用field避免可变默认值，UTC时间便于跨时区比较


class TokenUsagePersistence:  # 全部使用staticmethod，因为持久化操作不依赖实例状态，类似工具类
    """Token 用量持久化到 PostgreSQL cost_records 表"""

    @staticmethod  # 静态方法，写入操作是纯函数式的
    def record(record: TokenUsageRecord):  # 记录单次模型调用的token用量到数据库
        try:  # 外层try包裹，确保数据库写入失败不影响主流程
            from app.database import db  # 延迟导入，避免循环依赖和启动时数据库未就绪
            if hasattr(db, 'execute'):  # 防御性检查：确保db对象有execute方法，兼容不同数据库后端
                db.execute(  # 使用参数化查询，防止SQL注入
                    "INSERT INTO cost_records "
                    "(company_id, agent_key, model_name, provider, input_tokens, "
                    "output_tokens, cost_usd, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        record.company_id,
                        record.agent_key or "",  # 空字符串兜底，防止NULL值导致数据库约束问题
                        record.model_name,
                        record.provider,
                        record.input_tokens,
                        record.output_tokens,
                        record.cost_usd,
                        datetime.utcnow(),  # 使用UTC时间，与数据库时区保持一致
                    ],
                )
                return True  # 成功返回True，供调用方确认
        except Exception as e:  # 宽泛捕获，因为数据库操作可能因多种原因失败
            logger.warning("token_usage_persist_failed", error=str(e))  # warning级别，因为不影响核心业务
        return False  # 失败返回False，调用方可以据此做降级处理

    @staticmethod  # 静态方法，查询操作不依赖实例状态
    def get_company_usage(company_id: int, days: int = 30) -> list[dict]:  # 默认30天，符合常见报表周期
        try:
            from app.database import db  # 延迟导入，避免循环依赖
            if hasattr(db, 'get_session'):  # 防御性检查，兼容不同数据库实现
                return db.get_company_cost_records(company_id, days)  # 委托给数据库层，不做数据转换
        except Exception as e:
            logger.warning("token_usage_query_failed", error=str(e))
        return []  # 查询失败返回空列表，避免上层空指针异常

    @staticmethod  # 静态方法，统计分析不需要实例状态
    def get_usage_summary(company_id: int, days: int = 30) -> dict:  # 汇总统计，返回聚合数据
        records = TokenUsagePersistence.get_company_usage(company_id, days)  # 复用上述查询方法
        total_input = sum(r.get("input_tokens", 0) for r in records)  # 使用get避免KeyError
        total_output = sum(r.get("output_tokens", 0) for r in records)
        total_cost = sum(r.get("cost_usd", 0) for r in records)

        by_agent = {}  # 按Agent分组统计，便于分析各Agent的成本分布
        for r in records:
            agent = r.get("agent_key", "unknown")  # 未知Agent归入unknown
            if agent not in by_agent:
                by_agent[agent] = {"tokens": 0, "cost": 0.0}  # 初始化分组
            by_agent[agent]["tokens"] += r.get("input_tokens", 0) + r.get("output_tokens", 0)  # 总计token
            by_agent[agent]["cost"] += r.get("cost_usd", 0)

        return {  # 返回结构化汇总数据，便于前端展示
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cost_usd": round(total_cost, 4),  # 四舍五入到4位小数，避免浮点精度问题
            "period_days": days,
            "by_agent": by_agent,
            "record_count": len(records),
        }


class ModelHealthChecker:  # 模型健康检查器，全部使用classmethod，因为健康状态缓存是类级别的共享数据
    """模型健康监控"""

    @dataclass  # 内嵌dataclass，因为HealthStatus仅在ModelHealthChecker中使用，不需要独立文件
    class HealthStatus:  # 封装单个模型的健康状态数据
        provider: str  # 提供商名称
        model_key: str  # 模型标识键
        healthy: bool = True  # 默认健康，仅当检查失败时设为False
        latency_ms: float = 0.0  # 延迟毫秒，用于性能监控
        last_check: str = ""  # 最后检查时间，ISO格式
        error_message: str = ""  # 错误信息，仅在不健康时有值

    _status_cache: dict[str, 'ModelHealthChecker.HealthStatus'] = {}  # 类级别缓存，键为model_key；所有实例共享，避免重复检查

    @classmethod  # classmethod，需要使用gateway的配置信息
    async def check_model(cls, gateway, model_key: str) -> HealthStatus:  # 异步方法，因为需要发送HTTP请求进行ping
        cfg = gateway.models_config.get(model_key, {})  # 获取模型配置，空字典兜底
        if not cfg:  # 模型未配置时直接返回不健康状态
            return cls.HealthStatus(
                provider="unknown", model_key=model_key,
                healthy=False, error_message="Model not configured",
            )

        try:  # 尝试发送ping请求，验证模型可达性
            start = time.time()  # 记录开始时间，用于计算延迟
            model = gateway.get_llm(model_key)  # 获取模型实例
            from langchain_core.messages import HumanMessage  # 延迟导入，避免循环依赖
            await model.ainvoke([HumanMessage(content="ping")])  # 发送最小请求，验证连通性
            latency = (time.time() - start) * 1000  # 转换为毫秒
            status = cls.HealthStatus(
                provider=cfg.get("provider", ""),
                model_key=model_key,
                healthy=True,
                latency_ms=round(latency, 2),  # 保留两位小数，避免浮点精度
                last_check=datetime.utcnow().isoformat(),
            )
        except Exception as e:  # 任何异常都视为不健康
            status = cls.HealthStatus(
                provider=cfg.get("provider", ""),
                model_key=model_key,
                healthy=False,
                error_message=str(e),
                last_check=datetime.utcnow().isoformat(),
            )

        cls._status_cache[model_key] = status  # 更新缓存，供后续快速查询
        return status

    @classmethod  # classmethod，批量检查所有模型
    async def check_all(cls, gateway) -> dict:  # 异步遍历所有模型，并发检查
        gateway._load_config()  # 确保配置已加载
        results = {}
        for model_key in gateway.models_config:  # 遍历所有配置的模型
            results[model_key] = await cls.check_model(gateway, model_key)  # 逐个检查，注意：这里没有并发优化
        return {k: {  # 转换为字典格式，便于JSON序列化
            "healthy": v.healthy,
            "latency_ms": v.latency_ms,
            "error": v.error_message if not v.healthy else None,  # 仅在不健康时返回错误信息
        } for k, v in results.items()}

    @classmethod  # classmethod，获取缓存的健康状态
    def get_cached_status(cls) -> dict:  # 同步方法，直接返回缓存数据，无需网络请求
        return {k: {  # 返回简化的缓存数据
            "healthy": v.healthy,
            "latency_ms": v.latency_ms,
            "last_check": v.last_check,
        } for k, v in cls._status_cache.items()}


class QuotaAlertService:  # 配额告警服务，全部使用classmethod，因为告警逻辑基于类级别阈值
    """配额告警服务"""

    THRESHOLD_WARNING = 0.8  # 80%时触发警告，给用户留出缓冲时间
    THRESHOLD_CRITICAL = 0.95  # 95%时触发严重告警，几乎耗尽

    @classmethod  # classmethod，告警检查基于类级别阈值
    def check_and_alert(cls, company_id: int, quota_manager) -> list[dict]:  # 检查配额使用率并生成告警
        alerts = []
        usage = quota_manager.get_usage(company_id)  # 获取当前使用情况

        daily_ratio = usage["daily_used"] / max(usage["daily_limit"], 1)  # max(...,1)防止除零错误
        monthly_ratio = usage["monthly_used"] / max(usage["monthly_limit"], 1)

        if daily_ratio >= cls.THRESHOLD_CRITICAL:  # 先检查严重告警，因为优先级更高
            alerts.append({
                "level": "critical",
                "type": "daily_quota",
                "message": f"Token 日配额即将耗尽 ({usage['daily_used']}/{usage['daily_limit']})",
                "usage_ratio": round(daily_ratio, 2),
            })
        elif daily_ratio >= cls.THRESHOLD_WARNING:  # 再检查警告，elif确保不会同时触发两个级别
            alerts.append({
                "level": "warning",
                "type": "daily_quota",
                "message": f"Token 日配额已使用 {round(daily_ratio * 100)}%",
                "usage_ratio": round(daily_ratio, 2),
            })

        if monthly_ratio >= cls.THRESHOLD_CRITICAL:  # 月配额严重告警
            alerts.append({
                "level": "critical",
                "type": "monthly_quota",
                "message": f"Token 月配额即将耗尽 ({usage['monthly_used']}/{usage['monthly_limit']})",
                "usage_ratio": round(monthly_ratio, 2),
            })
        elif monthly_ratio >= cls.THRESHOLD_WARNING:  # 月配额警告
            alerts.append({
                "level": "warning",
                "type": "monthly_quota",
                "message": f"Token 月配额已使用 {round(monthly_ratio * 100)}%",
                "usage_ratio": round(monthly_ratio, 2),
            })

        return alerts  # 返回告警列表，可能为空表示一切正常
