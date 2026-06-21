"""
IdempotencyManager - Agent 副作用操作幂等性保障

提供幂等键生成、Redis 去重、本地内存降级。
用于防止重复扣款、订票等危险操作。
"""

import hashlib  # SHA256 哈希生成幂等键的不可逆摘要，避免参数明文暴露在 Redis key 中
import json  # 参数序列化，sort_keys 确保相同参数生成相同哈希
import os  # 读取环境变量 REDIS_URL
import threading  # 本地缓存需要线程锁保护，因为多线程并发下 dict 操作不是线程安全的
import time  # 本地缓存的 TTL 过期判断
from typing import Any, Optional

from app.core.logging import get_logger

try:
    import redis  # redis-py 可选依赖，允许纯内存模式运行
    from redis.connection import ConnectionPool
except ImportError:  # 不抛异常：幂等性检查不能因为依赖缺失而阻断业务
    redis = None
    ConnectionPool = None

logger = get_logger(__name__)  # 幂等性日志独立，便于审计哪些操作被重复请求

# 默认幂等 TTL（24 小时）
DEFAULT_IDEMPOTENT_TTL = 86400  # 24小时：电商场景中同一请求的幂等窗口通常不超过一天，过期后自动释放存储
# 本地缓存最大条目数
MAX_LOCAL_CACHE_SIZE = 1000  # 限制内存用量：本地缓存是 Redis 的降级方案，不应无限增长导致 OOM


class IdempotencyManager:
    """幂等性管理器

    职责：
      - 生成幂等键：idem:{company_id}:{agent_name}:{tool_name}:{hash(params)}
      - 检查 Redis：已执行过则返回缓存结果
      - 存储结果：执行后写入 Redis + 本地缓存
      - 降级：Redis 不可用时回退到本地内存缓存
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")  # 优先级：参数 > 环境变量 > 默认值
        self._redis_client: Optional[redis.Redis] = None  # 延迟初始化连接
        self._connection_pool: Optional[ConnectionPool] = None
        self._connected: bool = False
        self._local_cache: dict[str, dict[str, Any]] = {}  # 本地缓存 value 包含 data 和 expires_at，支持 TTL 淘汰
        self._lock = threading.Lock()  # 线程锁保护本地缓存的读写，因为幂等性检查可能被多线程并发调用

        self._connect()  # 构造时自动连接

    # ── Redis 连接 ──────────────────────────────────────────────

    def _connect(self) -> bool:  # 返回 bool 供调用方判断，但幂等检查内部会降级处理
        if redis is None:
            logger.warning("idempotency_redis_not_installed")
            return False
        try:
            self._connection_pool = ConnectionPool.from_url(self._redis_url)  # 连接池复用连接
            self._redis_client = redis.Redis(connection_pool=self._connection_pool)
            self._redis_client.ping()  # 验证连接可用性
            self._connected = True
            logger.info("idempotency_redis_connected", url=self._redis_url)
            return True
        except Exception as e:  # 连接失败不阻断，降级到本地缓存
            logger.warning("idempotency_redis_connect_failed", error=str(e))
            self._connected = False
            return False

    @property
    def is_available(self) -> bool:  # 外部只读属性，隐藏内部实现
        return self._connected and self._redis_client is not None

    # ── 幂等键生成 ──────────────────────────────────────────────

    @staticmethod
    def generate_key(
        company_id: str,
        agent_name: str,
        tool_name: str,
        params: dict,
    ) -> str:  # staticmethod 不需要实例状态，纯函数式计算
        """生成幂等键

        格式: idem:{company_id}:{agent_name}:{tool_name}:{hash(params)}
        """
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)  # sort_keys 保证相同参数生成相同哈希；ensure_ascii=False 保留中文；default=str 处理不可序列化对象
        params_hash = hashlib.sha256(params_str.encode()).hexdigest()[:16]  # 取前16位：碰撞概率足够低（2^64），且 key 长度可控
        return f"idem:{company_id}:{agent_name}:{tool_name}:{params_hash}"  # 层级前缀便于 Redis 可视化管理和按租户批量清理

    # ── 核心 API ────────────────────────────────────────────────

    def check_or_execute(
        self,
        key: str,
        executor: callable,  # callable 而非具体函数签名：幂等管理器不关心执行逻辑，将控制权交给调用方
        ttl: int = DEFAULT_IDEMPOTENT_TTL,
    ) -> tuple[Any, bool]:  # 返回 (result, is_cached) 让调用方区分是首次执行还是缓存命中，便于日志和业务判断
        """幂等检查并执行

        如果 key 已存在，返回缓存结果 + is_cached=True。
        否则执行 executor()，存储结果，返回 result + is_cached=False。

        Args:
            key: 幂等键
            executor: 实际执行函数，无参数
            ttl: 结果 TTL（秒）

        Returns:
            (result, is_cached): 结果 + 是否来自缓存
        """
        # 1. 检查 Redis
        cached = self._get_from_redis(key)
        if cached is not None:  # 用 is not None 而非 if cached，因为缓存结果可能是 falsy 值（如空列表、0、False）
            logger.info("idempotency_cache_hit_redis", key=key)
            return cached, True

        # 2. 检查本地缓存
        with self._lock:  # 线程锁保护本地缓存读写，防止并发下重复执行
            if key in self._local_cache:  # 先检查再判断过期：即使过期也不删除，留给 _evict_local_cache 统一清理
                logger.info("idempotency_cache_hit_local", key=key)
                return self._local_cache[key]["data"], True

        # 3. 执行实际操作
        try:
            result = executor()  # 调用方闭包捕获了实际参数，幂等管理器不关心具体执行逻辑
        except Exception as e:  # 执行失败不缓存结果，让调用方决定重试策略
            logger.error("idempotency_executor_failed", key=key, error=str(e))
            raise  # 重新抛出，不做包装，保持原始异常栈

        # 4. 存储结果
        self._store(key, result, ttl)  # 执行成功后存储，失败不存储
        return result, False

    def check_only(self, key: str) -> Optional[Any]:  # 只读检查，不执行，用于幂等性预检场景
        """仅检查幂等键，不执行

        Returns:
            None 如果 key 不存在，否则返回缓存结果
        """
        cached = self._get_from_redis(key)
        if cached is not None:
            return cached
        with self._lock:  # 本地缓存读取也需要锁，防止与其他线程的写入产生竞态
            entry = self._local_cache.get(key)
            if entry:
                return entry["data"]
        return None

    def store(self, key: str, data: Any, ttl: int = DEFAULT_IDEMPOTENT_TTL) -> None:  # 手动存储，用于外部已执行操作的结果登记
        """手动存储幂等结果"""
        self._store(key, data, ttl)

    # ── 内部存储 ─────────────────────────────────────────────────

    def _get_from_redis(self, key: str) -> Optional[Any]:
        if not self.is_available:  # Redis 不可用时直接返回 None，不阻塞
            return None
        try:
            raw = self._redis_client.get(key)
            if raw:
                return json.loads(raw)  # json.loads 而非自定义序列化，因为缓存数据是纯 JSON 对象
        except Exception as e:  # 读取失败不影响业务，降级到本地缓存
            logger.warning("idempotency_redis_get_failed", key=key, error=str(e))
        return None

    def _store(self, key: str, data: Any, ttl: int) -> None:
        # Redis 存储
        if self.is_available:
            try:
                self._redis_client.setex(key, ttl, json.dumps(data, default=str))  # setex 原子操作：设置值 + TTL，保证原子性
                logger.debug("idempotency_stored_redis", key=key, ttl=ttl)
            except Exception as e:  # Redis 写入失败不抛异常，本地缓存兜底
                logger.warning("idempotency_redis_store_failed", key=key, error=str(e))

        # 本地缓存（始终存储作为降级后备）
        with self._lock:  # 线程安全写入
            self._local_cache[key] = {
                "data": data,
                "expires_at": time.time() + ttl,  # 记录过期时间戳，而非存储 TTL 值，避免每次读取都要计算
            }
            # 本地缓存淘汰
            if len(self._local_cache) > MAX_LOCAL_CACHE_SIZE:  # 超过阈值触发淘汰，在写入路径上执行（而非独立线程），简化实现
                self._evict_local_cache()

    def _evict_local_cache(self) -> None:  # 调用方已持有 _lock，此方法不需要再加锁
        """淘汰过期条目（LRU 简化版：按过期时间清理）"""
        now = time.time()
        expired = [k for k, v in self._local_cache.items() if v["expires_at"] < now]  # 先清理已过期的条目
        for k in expired:
            del self._local_cache[k]
        # 如果淘汰后仍超标，删除最旧的条目
        if len(self._local_cache) > MAX_LOCAL_CACHE_SIZE:
            sorted_keys = sorted(
                self._local_cache.keys(),
                key=lambda k: self._local_cache[k]["expires_at"],  # 按过期时间升序，最早过期的排前面
            )
            remove_count = len(self._local_cache) - MAX_LOCAL_CACHE_SIZE
            for k in sorted_keys[:remove_count]:  # 删除最旧的 N 条，确保缓存大小回到阈值以内
                del self._local_cache[k]

    # ── 清理 ─────────────────────────────────────────────────────

    def clear_key(self, key: str) -> bool:  # 返回 bool 表示是否成功从 Redis 清除，本地缓存清除始终成功
        """手动清除幂等键"""
        cleared = False
        if self.is_available:
            try:
                self._redis_client.delete(key)  # Redis 删除单个 key，不关心是否存在
                cleared = True
            except Exception as e:
                logger.warning("idempotency_redis_delete_failed", key=key, error=str(e))
        with self._lock:  # 锁保护本地缓存操作
            self._local_cache.pop(key, None)  # pop 而非 del：key 不存在时不抛异常
        return cleared

    def close(self) -> None:
        if self._connection_pool:  # 释放连接池资源
            self._connection_pool.disconnect()
        self._connected = False
        with self._lock:  # 清空本地缓存时加锁，防止并发读写
            self._local_cache.clear()
        logger.info("idempotency_manager_closed")


# 全局单例
_idempotency_manager: Optional[IdempotencyManager] = None  # 模块级变量，延迟初始化


def get_idempotency_manager() -> IdempotencyManager:  # 工厂函数提供统一访问入口
    """获取全局 IdempotencyManager 单例"""
    global _idempotency_manager
    if _idempotency_manager is None:  # 懒加载，首次调用时才创建实例
        _idempotency_manager = IdempotencyManager()
    return _idempotency_manager