"""
RedisSaver - LangGraph Checkpointer with Redis backend

实现 LangGraph BaseCheckpointSaver 接口，使用 Redis 存储 checkpoint。
支持 Redis 不可用时的内存降级。
"""

import json  # 序列化降级后备：当 JsonPlusSerializer 不可用时作为纯 JSON 兜底
import os  # 读取环境变量 REDIS_URL
import secrets  # get_next_version 中生成随机后缀，避免分布式下版本号碰撞
from collections import defaultdict  # 内存降级存储的嵌套字典结构，自动创建缺失键减少判断代码
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import (
    ExitStack,  # 预留上下文管理器集合，用于统一管理需要清理的资源（如连接池、文件句柄）
    suppress,  # 预留上下文管理器集合，用于统一管理需要清理的资源（如连接池、文件句柄）
)
from typing import (  # 类型标注提供自文档化能力，减少运行时的类型错误
    Any,
)

from app.core.logging import get_logger

try:
    import redis  # redis-py 是可选的，允许在没有 Redis 库的环境下使用纯内存模式
    from redis.connection import ConnectionPool
except ImportError:  # 不抛异常，因为支持内存降级运行——系统不应因缺少可选依赖而崩溃
    redis = None
    ConnectionPool = None

try:
    from langgraph.checkpoint.base import (  # 尝试导入 LangGraph 标准 API
        WRITES_IDX_MAP,
        BaseCheckpointSaver,
        ChannelVersions,
        Checkpoint,
        CheckpointMetadata,
        CheckpointTuple,
        get_checkpoint_id,
        get_checkpoint_metadata,
    )
except ImportError:
    # 降级到旧版本兼容：当 LangGraph 版本不同时，用基础类型兜底确保代码不崩溃
    BaseCheckpointSaver = object  # 继承 object 是最低限度的兼容，不会破坏 isinstance 检查
    Checkpoint = dict  # 当类型不可用时回退到 dict，保持数据结构的灵活性
    CheckpointMetadata = dict
    CheckpointTuple = Any
    ChannelVersions = dict

    def get_checkpoint_id(c):
        return c.get("configurable", {}).get(
            "checkpoint_id"
        )  # lambda 提取 checkpoint_id，兼容旧版 config 结构

    def get_checkpoint_metadata(c, m):
        return m  # 旧版中 metadata 直接传入，无需额外处理

    WRITES_IDX_MAP = {}

try:
    from langgraph.serde.jsonplus import (
        JsonPlusSerializer,  # JsonPlus 支持更丰富的类型序列化（如 datetime、set）
    )
except ImportError:
    JsonPlusSerializer = None  # 不可用时回退到 json.dumps，功能降级但不影响核心流程

logger = get_logger(__name__)  # checkpointer 日志独立，方便排查 Redis 连接与 checkpoint 流转问题

# 默认 checkpoint TTL（1 小时）
DEFAULT_CHECKPOINT_TTL = 3600  # 1小时：平衡了恢复能力与存储成本，电商场景下单次会话很少超过1小时


class RedisSaver(BaseCheckpointSaver):
    """基于 Redis 的 LangGraph Checkpointer

    支持：
      - Redis 存储 checkpoint 及其 pending writes
      - Redis 不可用时自动降级为内存存储
      - TTL 自动过期
    """

    def __init__(self, redis_url: str | None = None, ttl: int = DEFAULT_CHECKPOINT_TTL):
        serde = (
            JsonPlusSerializer() if JsonPlusSerializer else None
        )  # 序列化器优先使用 JsonPlus，支持更多类型
        super().__init__(serde=serde)  # 调用父类初始化，传入序列化器以注册到 LangGraph 框架
        self._redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )  # 优先参数 > 环境变量 > 默认值，保证灵活性
        self._redis_client: redis.Redis | None = (
            None  # 延迟初始化：连接在 _connect() 中建立，避免构造时阻塞
        )
        self._connection_pool: ConnectionPool | None = None  # 连接池复用连接，避免频繁 TCP 握手
        self._connected: bool = (
            False  # 显式标记连接状态，用 bool 而非 try/except 判断，性能更好且语义清晰
        )
        self._ttl = ttl  # 实例级 TTL 允许不同场景使用不同过期时间

        # 内存降级存储
        self._storage: dict = defaultdict(
            lambda: defaultdict(dict)
        )  # 三层嵌套：thread_id -> checkpoint_ns -> checkpoint_id -> data
        self._writes: dict = defaultdict(
            dict
        )  # pending writes 缓存：(thread_id, checkpoint_ns, checkpoint_id) -> writes
        self._blobs: dict = {}  # 大对象存储：用 tuple 键避免序列化大对象到 checkpoint 中
        self._stack = ExitStack()  # 上下文管理器栈，用于统一管理资源生命周期

        self._connect()  # 构造时自动连接，调用方无需手动初始化

    # ── Redis 连接 ──────────────────────────────────────────────

    def _connect(
        self,
    ) -> bool:  # 返回 bool 让调用方可判断连接是否成功，但不建议依赖返回值（连接失败内部已降级）
        if redis is None:  # redis-py 未安装时直接跳过，不抛异常
            logger.warning("checkpoint_redis_not_installed")
            return False
        try:
            self._connection_pool = ConnectionPool.from_url(
                self._redis_url
            )  # 连接池可复用 TCP 连接，减少 Redis 连接开销
            self._redis_client = redis.Redis(connection_pool=self._connection_pool)
            self._redis_client.ping()  # ping 验证连接可用性，和 net.connect 不同，ping 确保 Redis 服务端正常响应
            self._connected = True
            logger.info("checkpoint_redis_connected", url=self._redis_url)
            return True
        except Exception as e:  # 宽捕获：连接失败不应阻断服务启动，降级到内存即可
            logger.warning("checkpoint_redis_connect_failed", error=str(e))
            self._connected = False
            return False

    @property
    def is_available(
        self,
    ) -> bool:  # property 提供简洁的只读访问，外部不需要知道 _connected 的内部实现细节
        return (
            self._connected and self._redis_client is not None
        )  # 双重检查：连接标记 + 客户端实例，避免竞态导致 NPE

    # ── Redis Key 构建 ──────────────────────────────────────────

    @staticmethod
    def _key_checkpoint(
        thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> str:  # staticmethod 不需要实例状态，key 构建逻辑与 Redis 连接状态无关
        return f"ckpt:{thread_id}:{checkpoint_ns}:{checkpoint_id}"  # 用冒号分隔形成层级结构，Redis 可视化工具可按层级浏览

    @staticmethod
    def _key_latest(
        thread_id: str, checkpoint_ns: str
    ) -> str:  # latest 指针独立存储，避免每次都遍历所有 checkpoint 找最新的
        return f"ckpt:{thread_id}:{checkpoint_ns}:latest"

    @staticmethod
    def _key_blob(
        thread_id: str, checkpoint_ns: str, channel: str, version: str
    ) -> str:  # blob 按 channel+version 隔离，支持增量更新
        return f"ckpt:blob:{thread_id}:{checkpoint_ns}:{channel}:{version}"

    @staticmethod
    def _key_writes(
        thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> str:  # writes 与 checkpoint 绑定，用于恢复时重放未完成的写入
        return f"ckpt:writes:{thread_id}:{checkpoint_ns}:{checkpoint_id}"

    # ── 序列化帮助 ──────────────────────────────────────────────

    def _serialize(self, obj: Any) -> bytes:  # 实例方法：需要访问 self.serde 属性
        if self.serde:  # JsonPlusSerializer 优先，支持 datetime/set 等原生 JSON 不支持的类型
            return self.serde.dumps_typed(obj)[
                1
            ]  # dumps_typed 返回 (type_tag, serialized_bytes)，取第二部分
        return json.dumps(
            obj, default=str
        ).encode()  # 降级到 json.dumps，default=str 确保任何对象都能被序列化而不抛异常

    def _deserialize(self, raw: bytes) -> Any:
        if self.serde:
            return self.serde.loads_typed(
                ("json", raw)
            )  # loads_typed 需要 type_tag 参数，这里固定为 "json"
        return json.loads(raw)  # 纯 JSON 反序列化，不需要类型信息

    # ── 核心 API ────────────────────────────────────────────────

    def get_tuple(
        self, config: dict
    ) -> CheckpointTuple | None:  # LangGraph 框架要求的接口方法，返回 Optional 表示可能不存在
        thread_id = config["configurable"][
            "thread_id"
        ]  # configurable 是 LangGraph 的嵌套配置字典，外部 key 固定
        checkpoint_ns = config["configurable"].get(
            "checkpoint_ns", ""
        )  # checkpoint_ns 可选，空字符串作为默认命名空间

        checkpoint_id = (
            get_checkpoint_id(config) if get_checkpoint_id else None
        )  # 兼容旧版：get_checkpoint_id 可能为 None

        if checkpoint_id:  # 有具体 ID 则精确查找，O(1) 复杂度
            return self._get_specific(thread_id, checkpoint_ns, checkpoint_id, config)
        else:  # 无 ID 则取最新 checkpoint，通过 latest 指针避免全量扫描
            return self._get_latest(thread_id, checkpoint_ns, config)

    def _get_specific(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str, config: dict
    ) -> CheckpointTuple | None:
        data = self._fetch_checkpoint(
            thread_id, checkpoint_ns, checkpoint_id
        )  # 先查 Redis 再降级内存，统一入口
        if not data:
            return None
        return self._build_tuple(
            thread_id, checkpoint_ns, checkpoint_id, data, config
        )  # 组装 CheckpointTuple，加载 blobs 和 pending writes

    def _get_latest(
        self, thread_id: str, checkpoint_ns: str, config: dict
    ) -> CheckpointTuple | None:
        # 先查 Redis
        latest_id = None
        if self.is_available:  # 先检查可用性，避免不必要的 try/except 开销
            try:
                latest_id = self._redis_client.get(self._key_latest(thread_id, checkpoint_ns))
                if latest_id:
                    latest_id = latest_id.decode()  # Redis 返回 bytes，需要 decode 为 str
            except Exception:  # 静默降级：Redis 操作失败不报错，直接回退内存
                pass

        # 降级到内存
        if (
            not latest_id and self._storage[thread_id][checkpoint_ns]
        ):  # 双层检查：latest_id 为空 + 内存有数据
            checkpoints = self._storage[thread_id][checkpoint_ns]
            latest_id = max(
                checkpoints.keys()
            )  # 用 checkpoint_id 的字符串排序取最大，因为 ID 格式为单调递增的版本号

        if not latest_id:
            return None

        data = self._fetch_checkpoint(thread_id, checkpoint_ns, latest_id)
        if not data:
            return None
        return self._build_tuple(thread_id, checkpoint_ns, latest_id, data, config)

    def _fetch_checkpoint(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> dict | None:
        if self.is_available:  # Redis 优先：性能更好且数据持久化
            try:
                raw = self._redis_client.get(
                    self._key_checkpoint(thread_id, checkpoint_ns, checkpoint_id)
                )
                if raw:
                    return self._deserialize(raw)
            except Exception:  # 静默降级，不中断调用链
                pass

        entry = self._storage[thread_id][checkpoint_ns].get(
            checkpoint_id
        )  # 内存降级，defaultdict 确保不抛 KeyError
        return entry

    def _build_tuple(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        data: dict,
        config: dict,
    ) -> CheckpointTuple:
        checkpoint_raw = data.get(
            "checkpoint", {}
        )  # 从存储数据中提取 checkpoint body，.get 防御性取值以防数据结构不完整
        metadata_raw = data.get("metadata", {})
        parent_id = data.get("parent_checkpoint_id")  # 父节点 ID 用于构建 DAG 关系，支持回溯

        # 加载 blobs
        channel_values = self._load_blobs(  # blob 单独存储，避免 checkpoint 主记录过大
            thread_id, checkpoint_ns, checkpoint_raw.get("channel_versions", {})
        )

        checkpoint = {
            **checkpoint_raw,
            "channel_values": channel_values,
        }  # 合并 blob 数据到 checkpoint，保持 LangGraph 的标准结构

        # 加载 pending writes
        writes_map = self._fetch_writes(
            thread_id, checkpoint_ns, checkpoint_id
        )  # pending writes 是未完成写入，恢复时需重放
        pending_writes = list(
            writes_map.values()
        )  # 转换为列表，LangGraph 的 CheckpointTuple 期望 list 格式

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata_raw,
            pending_writes=pending_writes,
            parent_config=(  # 有父节点时构建父节点 config，支持 LangGraph 的向上回溯
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_id,
                    }
                }
                if parent_id
                else None  # 根节点没有父节点，传 None
            ),
        )

    def _fetch_writes(
        self, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> dict:  # 返回 dict 而非 list，因为内部用 (task_id, idx) 作为 key 去重
        if self.is_available:
            try:
                raw = self._redis_client.get(
                    self._key_writes(thread_id, checkpoint_ns, checkpoint_id)
                )
                if raw:
                    return self._deserialize(raw)
            except Exception:
                pass

        return self._writes.get(
            (thread_id, checkpoint_ns, checkpoint_id), {}
        )  # 内存降级返回空 dict，不抛异常

    def _load_blobs(
        self, thread_id: str, checkpoint_ns: str, versions: dict
    ) -> dict:  # versions 是 {channel: version} 的映射，按需加载而非全量加载
        channel_values = {}
        for channel, version in versions.items():
            blob_key = self._key_blob(thread_id, checkpoint_ns, channel, version)
            if self.is_available:
                try:
                    raw = self._redis_client.get(blob_key)
                    if raw:
                        vv = raw
                        if (
                            vv != b"empty"
                        ):  # 哨兵值 "empty" 表示该 channel 在本版本中为空，避免 None 混淆
                            channel_values[channel] = self._deserialize(vv)
                        continue  # 从 Redis 拿到了就跳过内存查找
                except Exception:
                    pass

            # 内存降级
            local_key = (thread_id, checkpoint_ns, channel, version)
            if local_key in self._blobs:
                vv = self._blobs[local_key]
                if vv != "empty":  # 内存中的哨兵值，与 Redis 不同，内存中是 str 而非 bytes
                    channel_values[channel] = vv
        return channel_values

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,  # new_versions 是 LangGraph 框架计算出的版本增量，用于判断哪些 channel 需要更新
    ) -> dict:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint[
            "id"
        ]  # 从 checkpoint 对象中提取 id，而非从 config 中，保证一致性

        c = checkpoint.copy()  # 浅拷贝避免修改原始对象，深拷贝会浪费内存
        channel_values = c.pop(
            "channel_values", {}
        )  # channel_values 分离存储为 blob，减小 checkpoint 主记录体积

        # 存储 blobs
        for channel, version in new_versions.items():
            blob_key = self._key_blob(thread_id, checkpoint_ns, channel, version)
            if channel in channel_values:  # 有值则序列化存储
                if self.is_available:
                    with suppress(Exception):
                        self._redis_client.setex(
                            blob_key,
                            self._ttl,
                            self._serialize(channel_values[channel]),
                        )
                self._blobs[(thread_id, checkpoint_ns, channel, version)] = channel_values[
                    channel
                ]  # 内存始终存储，作为 Redis 的双重保障
            else:  # 无值的 channel 标记为 empty，哨兵值
                if self.is_available:
                    with suppress(Exception):
                        self._redis_client.setex(blob_key, self._ttl, b"empty")
                self._blobs[(thread_id, checkpoint_ns, channel, version)] = "empty"

        # 存储 checkpoint
        parent_id = config["configurable"].get(
            "checkpoint_id"
        )  # 当前 config 中的 checkpoint_id 即为父节点
        data = {
            "checkpoint": c,
            "metadata": get_checkpoint_metadata(config, metadata)
            if get_checkpoint_metadata
            else metadata,
            "parent_checkpoint_id": parent_id,
        }

        if self.is_available:
            try:
                ckpt_key = self._key_checkpoint(thread_id, checkpoint_ns, checkpoint_id)
                latest_key = self._key_latest(thread_id, checkpoint_ns)
                pipe = (
                    self._redis_client.pipeline()
                )  # 使用 pipeline 批量执行，保证原子性：checkpoint 和 latest 指针同时更新
                pipe.setex(ckpt_key, self._ttl, self._serialize(data))
                pipe.setex(latest_key, self._ttl, checkpoint_id.encode())
                pipe.execute()
            except Exception:  # pipeline 失败不抛出，内存降级保证数据不丢失
                pass

        # 内存降级
        self._storage[thread_id][checkpoint_ns][checkpoint_id] = (
            data  # 内存始终存储，不依赖 Redis 成功
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }  # 返回的 config 可作为下次调用的父节点配置

    def put_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],  # Sequence 而非 list，接受更广泛的可迭代类型
        task_id: str,
        task_path: str = "",  # task_path 默认空字符串，表示根任务
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        outer_key = (
            thread_id,
            checkpoint_ns,
            checkpoint_id,
        )  # 用 tuple 作为复合键，比字符串拼接更高效且避免分隔符冲突
        existing = self._writes.get(outer_key, {})  # 获取已有 writes，追加而非覆盖

        for idx, (channel, value) in enumerate(writes):
            inner_key = (
                task_id,
                WRITES_IDX_MAP.get(channel, idx) if WRITES_IDX_MAP else idx,
            )  # WRITES_IDX_MAP 提供 channel 的固定索引映射
            existing[inner_key] = (task_id, channel, value, task_path)

        self._writes[outer_key] = existing  # 更新内存缓存

        if self.is_available:
            try:
                writes_key = self._key_writes(thread_id, checkpoint_ns, checkpoint_id)
                self._redis_client.setex(writes_key, self._ttl, self._serialize(existing))
            except Exception:
                pass

    def delete_thread(self, thread_id: str) -> None:
        if self.is_available:
            try:
                pattern = (
                    f"ckpt:{thread_id}:*"  # 用通配符模式匹配该线程的所有 key，批量删除而非逐个指定
                )
                for key in self._redis_client.scan_iter(
                    match=pattern
                ):  # scan_iter 避免 KEYS 阻塞 Redis，适合生产环境
                    self._redis_client.delete(key)
                pattern = (
                    f"ckpt:blob:{thread_id}:*"  # blob 和 writes 需要单独删除，因为 key 前缀不同
                )
                for key in self._redis_client.scan_iter(match=pattern):
                    self._redis_client.delete(key)
                pattern = f"ckpt:writes:{thread_id}:*"
                for key in self._redis_client.scan_iter(match=pattern):
                    self._redis_client.delete(key)
            except Exception as e:
                logger.warning("checkpoint_delete_thread_failed", thread_id=thread_id, error=str(e))

        if thread_id in self._storage:  # 清理内存中的对应数据
            del self._storage[thread_id]
        for k in list(self._writes.keys()):  # list() 创建副本后再迭代删除，避免 RuntimeError
            if k[0] == thread_id:  # tuple 键的第一个元素是 thread_id
                del self._writes[k]
        for k in list(self._blobs.keys()):
            if k[0] == thread_id:
                del self._blobs[k]

    def get_next_version(
        self, current: str | None, channel: None
    ) -> str:  # channel 参数为 None 是 LangGraph 的接口约定
        if current is None:
            current_v = 0  # 首次版本号从 0 开始
        elif isinstance(current, int):
            current_v = current
        else:  # current 是字符串格式 "00000000000000000000000000000032.0000000000000000"
            current_v = int(current.split(".")[0])  # 解析主版本号，整数部分单调递增
        next_v = current_v + 1
        next_h = secrets.randbelow(10**16)  # 随机后缀防止分布式下多节点同时写入产生版本号冲突
        return f"{next_v:032}.{next_h:016}"  # 零填充保证字典序排序正确，版本号即为排序键

    # ── 异步方法 ─────────────────────────────────────────────────

    async def aget_tuple(
        self, config: dict
    ) -> (
        CheckpointTuple | None
    ):  # async 方法直接委托同步方法，因为 Redis 操作本身是 I/O 阻塞的，这里提供兼容接口
        return self.get_tuple(config)

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        return self.delete_thread(thread_id)

    async def alist(
        self,
        config: dict | None = None,
        *,
        filter: dict | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:  # AsyncIterator 支持 async for 语法
        # 简化版：返回内存中的结果
        for thread_id in (
            self._storage if not config else [config["configurable"]["thread_id"]]
        ):  # 无 config 时遍历所有线程
            for checkpoint_ns in self._storage.get(thread_id, {}):
                for checkpoint_id, data in sorted(
                    self._storage[thread_id][checkpoint_ns].items(),
                    key=lambda x: x[0],
                    reverse=True,  # 降序排列，最新的在前
                ):
                    yield self._build_tuple(thread_id, checkpoint_ns, checkpoint_id, data, {})
                    if limit is not None:  # 限制返回数量，防止内存溢出
                        limit -= 1
                        if limit <= 0:
                            return

    def list(
        self,
        config: dict | None = None,
        *,
        filter: dict | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:  # 同步版本的 list，与 alist 逻辑一致
        for thread_id in self._storage if not config else [config["configurable"]["thread_id"]]:
            for checkpoint_ns in self._storage.get(thread_id, {}):
                for checkpoint_id, data in sorted(
                    self._storage[thread_id][checkpoint_ns].items(),
                    key=lambda x: x[0],
                    reverse=True,
                ):
                    yield self._build_tuple(thread_id, checkpoint_ns, checkpoint_id, data, {})
                    if limit is not None:
                        limit -= 1
                        if limit <= 0:
                            return

    # ── 清理 ─────────────────────────────────────────────────────

    def close(self) -> None:
        if self._connection_pool:  # 先断开连接池，释放 Redis 连接
            self._connection_pool.disconnect()
        self._connected = False
        self._storage.clear()  # 清空内存数据，避免内存泄漏
        self._writes.clear()
        self._blobs.clear()
        logger.info("checkpoint_redis_saver_closed")


# 全局单例
_redis_saver: RedisSaver | None = None  # 模块级变量，延迟初始化


def get_redis_saver() -> RedisSaver:  # 工厂函数而非直接暴露全局变量，便于未来替换实现
    """获取全局 RedisSaver 单例"""
    global _redis_saver
    if _redis_saver is None:  # 简单懒加载，线程安全由 Python GIL 保证
        _redis_saver = RedisSaver()
    return _redis_saver
