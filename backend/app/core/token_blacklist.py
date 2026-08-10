"""Token 黑名单 - 支持 refresh token 撤销与轮换

设计原则：
1. 所有 IO 异步化：使用 redis.asyncio，避免阻塞 FastAPI 事件循环
2. 优雅降级：Redis 不可用时不阻塞业务，降级到进程内内存字典
3. 自清理：Redis 通过 SETEX 的 TTL 自动过期；内存模式通过 cleanup_expired() 定期清理
4. 幂等：重复 revoke 同一 jti 不会报错，仅覆盖 TTL
5. 单例：通过 get_token_blacklist() 工厂返回全局唯一实例，避免重复初始化连接池

key 命名规范：blacklist:jti:{jti}  value=1  TTL=expires_at - now（秒）
当 TTL <= 0 表示 token 已自然过期，可直接忽略（仍写入以保持幂等语义）
"""

import os  # 从环境变量读取 REDIS_URL，与 session_store 保持一致
import threading  # 单例双检锁，避免并发场景下创建多个实例
import time  # 内存模式 expires_at 用 epoch 秒比较

from app.core.logging import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # 与 session_store 共用默认值
BLACKLIST_KEY_PREFIX = "blacklist:jti:"  # 前缀命名空间，便于 Redis 端 KEYS/SCAN 排查与统计
# 内存降级模式下，单实例最多保留多少条黑名单条目，防止极端场景下内存膨胀
MEMORY_BLACKLIST_MAX_SIZE = 10000


class TokenBlacklist:
    """Refresh token 黑名单（基于 jti）

    生命周期：
    - revoke(jti, expires_at)：撤销一个 jti，TTL=expires_at - now
    - is_revoked(jti)：检查是否在黑名单
    - cleanup_expired()：仅内存模式有效，扫描并删除已过期条目

    Redis 不可用时自动降级到内存字典（进程内），多实例部署下内存模式仅对当前进程有效，
    这是已知折中：完整的跨实例撤销需要 Redis 或共享存储支撑。

    多 worker 风险（重要）：
        当 Redis 不可用降级到内存模式时，各 worker 进程独立维护自己的内存黑名单。
        worker A 执行 revoke(jti) 后，worker B 的 is_revoked(jti) 仍返回 False，
        导致已撤销的 refresh token 在其他 worker 上仍被认为有效。
        生产环境务必确保 Redis 可用，否则 token 撤销语义无法跨 worker 保证。
    """

    def __init__(self):
        self._redis = None  # redis.asyncio 客户端，None 表示未初始化或不可用
        self._redis_available = (
            False  # 标记 Redis 当前是否可用，初始为 False，await init() 成功后置 True
        )
        # 内存降级存储：{jti: expires_at_epoch_seconds}
        # 仅在 Redis 不可用时使用；value 存原始 token 的 expires_at，便于 cleanup_expired 比对
        self._memory: dict[str, int] = {}
        self._memory_lock = threading.Lock()  # 保护 _memory 字典的并发读写
        # is_revoked 内存降级多 worker 风险 warning 是否已记过（首次记一次，避免每次调用刷屏）
        self._memory_warning_logged = False
        self._init_redis_client()

    def _init_redis_client(self):
        """构造异步 Redis 客户端（仅创建对象，不发起连接）

        与 SessionStore 保持一致：构造函数中不 await，避免同步上下文中阻塞事件循环。
        连接验证延迟到 init() 中执行。
        """
        try:
            import redis.asyncio as aioredis  # 延迟导入，未安装 redis 包时不影响模块加载

            self._redis = aioredis.from_url(REDIS_URL, socket_connect_timeout=3)
            # 注意：_redis_available 保持 False，等 await init() 中 ping 成功后再置 True
        except Exception as e:
            # redis 包未安装或 URL 非法时进入此分支，后续操作全部走内存降级
            logger.warning("token_blacklist_redis_client_init_failed", error=str(e))
            self._redis = None

    async def init(self):
        """异步初始化：ping Redis 验证连通性

        应在 FastAPI lifespan 启动阶段调用：
            await get_token_blacklist().init()
        失败时降级到内存模式，不抛异常。
        """
        if not self._redis:
            return  # 客户端未创建，直接走内存模式
        try:
            await self._redis.ping()
            self._redis_available = True
            logger.info("token_blacklist_redis_connected", url=REDIS_URL)
        except Exception as e:
            # ping 失败：置为不可用，后续操作走内存降级
            self._redis_available = False
            logger.warning("token_blacklist_redis_unavailable", error=str(e))
            # 多 worker 部署下内存降级模式各进程独立，撤销操作无法跨 worker 同步：
            # worker A 撤销的 token 在 worker B 仍被认为有效。生产环境务必确保 Redis 可用。
            logger.warning("token_blacklist_redis_unavailable_multi_worker_inconsistency")

    async def close(self):
        """关闭 Redis 连接，释放连接池资源

        应在 FastAPI lifespan 关闭阶段调用：
            await get_token_blacklist().close()
        """
        if self._redis is not None:
            try:
                await self._redis.aclose()  # redis.asyncio 使用 aclose() 而非 close()
            except Exception as e:
                logger.warning("token_blacklist_redis_close_error", error=str(e))
            finally:
                self._redis = None
                self._redis_available = False

    async def revoke(self, jti: str, expires_at: int) -> bool:
        """撤销一个 jti，将其加入黑名单直到 token 自然过期

        Args:
            jti: JWT ID，由 create_refresh_token 注入 payload 的 uuid4
            expires_at: token 的过期时间（epoch 秒）

        Returns:
            bool: 是否成功写入。Redis 不可用时写内存返回 True，异常时返回 False
        """
        if not jti:
            # 空 jti 直接拒绝，避免误把空值写入黑名单导致后续所有空 jti 校验都返回已撤销
            return False

        now = int(time.time())
        ttl = max(int(expires_at) - now, 1)  # TTL 至少 1 秒，避免 Redis 拒绝 TTL<=0
        key = f"{BLACKLIST_KEY_PREFIX}{jti}"

        # Redis 可用优先写 Redis
        if self._redis_available and self._redis is not None:
            try:
                # SETEX 原子写入并设置 TTL，过期后 Redis 自动清理，无需人工干预
                await self._redis.setex(key, ttl, "1")
                logger.info("token_blacklist_revoke_redis", jti=jti, ttl=ttl)
                return True
            except Exception as e:
                # Redis 写入失败：降级到内存，保证撤销语义不丢失
                logger.warning(
                    "token_blacklist_redis_write_failed_fallback_memory", jti=jti, error=str(e)
                )
                # 落入内存分支继续执行

        # 内存降级路径
        with self._memory_lock:
            # 容量保护：超限时淘汰最早过期的一批条目，避免无界增长
            if len(self._memory) >= MEMORY_BLACKLIST_MAX_SIZE:
                self._evict_oldest_locked()
            self._memory[jti] = int(expires_at)
        logger.info("token_blacklist_revoke_memory", jti=jti, expires_at=expires_at)
        return True

    async def is_revoked(self, jti: str) -> bool:
        """检查 jti 是否已被撤销

        Args:
            jti: JWT ID

        Returns:
            bool: True 表示已撤销（或在 Redis 异常时保守返回 False，避免阻塞登录主流程）

        多 worker 风险：
            Redis 不可用降级到内存模式时，各 worker 独立维护内存黑名单。
            worker A 执行 revoke(jti) 后，worker B 的 is_revoked(jti) 仍返回 False，
            导致已撤销 token 在其他 worker 上仍被认为有效。首次降级查询时记一次 warning。
        """
        if not jti:
            return False  # 空 jti 视为未撤销，由 decode_refresh_token 的其他校验兜底

        # Redis 可用优先查 Redis
        if self._redis_available and self._redis is not None:
            try:
                # EXISTS 返回 1 表示存在
                result = await self._redis.exists(f"{BLACKLIST_KEY_PREFIX}{jti}")
                return bool(result)
            except Exception as e:
                # Redis 查询异常：降级到内存查询，保证语义一致
                logger.warning(
                    "token_blacklist_redis_read_failed_fallback_memory", jti=jti, error=str(e)
                )

        # 内存降级路径：首次调用时记一次多 worker 不一致 warning（避免每次调用刷屏）
        if not self._memory_warning_logged:
            self._memory_warning_logged = True
            logger.warning("token_blacklist_redis_unavailable_multi_worker_inconsistency")

        # 检查 jti 是否在内存中且未过期
        with self._memory_lock:
            expires_at = self._memory.get(jti)
            if expires_at is None:
                return False
            if int(time.time()) >= expires_at:
                # 已自然过期，顺手清理避免下次重复查
                self._memory.pop(jti, None)
                return False
            return True

    async def cleanup_expired(self) -> int:
        """清理已过期的黑名单条目（仅内存模式有效）

        Redis 模式下由 SETEX 的 TTL 自动清理，调用此方法为 no-op。
        建议由定时任务（periodic_tasks.py）每小时调用一次。

        Returns:
            int: 本次清理掉的条目数
        """
        # Redis 模式无需清理
        if self._redis_available and self._redis is not None:
            return 0

        now = int(time.time())
        removed = 0
        with self._memory_lock:
            # 一次性扫描并删除已过期条目，避免迭代中修改字典
            expired_jtis = [jti for jti, exp in self._memory.items() if now >= exp]
            for jti in expired_jtis:
                self._memory.pop(jti, None)
                removed += 1
        if removed > 0:
            logger.info(
                "token_blacklist_cleanup_memory", removed=removed, remaining=len(self._memory)
            )
        return removed

    def _evict_oldest_locked(self):
        """内存模式下容量超限时淘汰最早过期的一批条目（调用方需持锁）

        策略：删除最早过期的 10% 条目，分摊清理成本
        """
        if not self._memory:
            return
        # 按 expires_at 升序排序，取最早的 10%
        sorted_items = sorted(self._memory.items(), key=lambda kv: kv[1])
        evict_count = max(len(sorted_items) // 10, 1)
        for jti, _ in sorted_items[:evict_count]:
            self._memory.pop(jti, None)


# ============ 单例工厂 ============

_token_blacklist_instance: TokenBlacklist | None = None
_blacklist_lock = threading.Lock()


def get_token_blacklist() -> TokenBlacklist:
    """获取全局 TokenBlacklist 单例（双检锁）

    与 get_session_store / get_global_model_gateway 保持一致的单例模式，
    确保整个进程共享同一份 Redis 连接池和内存降级字典。
    """
    global _token_blacklist_instance
    if _token_blacklist_instance is None:
        with _blacklist_lock:
            if _token_blacklist_instance is None:
                _token_blacklist_instance = TokenBlacklist()
    return _token_blacklist_instance
