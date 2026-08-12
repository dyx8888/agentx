"""# ParseCache 模块，文档解析缓存，借鉴 RAG-Anything 的 parse_cache 设计
解析缓存模块  # 避免重复解析相同文档，提升性能
借鉴 RAG-Anything 的 parse_cache 设计：基于文件路径 + 配置哈希的缓存，通过 mtime 检测失效
"""

import hashlib  # 用于生成缓存 key
import json  # 序列化缓存数据
import os  # 获取文件 mtime 和操作文件系统
import time  # 时间戳用于缓存过期检测

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

DEFAULT_CACHE_TTL = 3600  # 默认缓存有效期（秒），1 小时


class ParseCache:  # 解析缓存管理器
    """解析缓存管理器，用于缓存文档解析结果。

    借鉴 RAG-Anything 的 parse_cache 设计：
    - 基于文件路径 + 配置哈希生成缓存 key
    - 通过文件 mtime 检测缓存是否失效
    - 支持 TTL 过期机制
    """

    def __init__(self, cache_dir: str = None, ttl: int = DEFAULT_CACHE_TTL):
        """初始化解析缓存。

        Args:
            cache_dir: 缓存目录路径，默认使用工作目录下的 .parse_cache
            ttl: 缓存有效期（秒），默认 3600 秒
        """
        self.ttl = ttl
        self._cache: dict[str, dict] = {}  # 内存缓存：key → {result, timestamp, mtime}

        if cache_dir:
            self._cache_dir = cache_dir
        else:
            self._cache_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                ".parse_cache",
            )
        os.makedirs(self._cache_dir, exist_ok=True)

    def _make_key(self, file_path: str, config_hash: str = "") -> str:  # 生成缓存 key
        """基于文件路径和配置哈希生成缓存 key。

        Args:
            file_path: 文件路径
            config_hash: 配置哈希（可选），用于区分不同解析配置的结果

        Returns:
            MD5 缓存 key
        """
        raw = f"{file_path}:{config_hash}"
        return hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()

    def _get_file_mtime(self, file_path: str) -> float:  # 获取文件修改时间
        """获取文件的最后修改时间。

        Returns:
            文件 mtime 时间戳，文件不存在时返回 0
        """
        try:
            return os.path.getmtime(file_path)
        except OSError:
            return 0.0

    def get(self, file_path: str, config_hash: str = "") -> str | None:  # 获取缓存
        """获取缓存中的解析结果。

        Args:
            file_path: 文件路径
            config_hash: 配置哈希

        Returns:
            缓存的解析结果，缓存失效或不存在时返回 None
        """
        key = self._make_key(file_path, config_hash)

        # 先查内存缓存
        if key in self._cache:
            entry = self._cache[key]
            current_mtime = self._get_file_mtime(file_path)

            # 检查 mtime 是否变化
            if entry.get("mtime") != current_mtime:
                logger.info("parse_cache_invalidated_mtime", file=file_path)
                del self._cache[key]
                return None

            # 检查 TTL 是否过期
            if time.time() - entry.get("timestamp", 0) > self.ttl:
                logger.info("parse_cache_invalidated_ttl", file=file_path)
                del self._cache[key]
                return None

            logger.info("parse_cache_hit", file=file_path)
            return entry["result"]

        # 再查磁盘缓存
        disk_path = os.path.join(self._cache_dir, key)
        if os.path.exists(disk_path):
            try:
                with open(disk_path, encoding="utf-8") as f:
                    entry = json.load(f)
                current_mtime = self._get_file_mtime(file_path)

                if entry.get("mtime") != current_mtime:
                    os.remove(disk_path)
                    return None

                if time.time() - entry.get("timestamp", 0) > self.ttl:
                    os.remove(disk_path)
                    return None

                # 加载到内存缓存
                self._cache[key] = entry
                logger.info("parse_cache_hit_disk", file=file_path)
                return entry["result"]
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("parse_cache_disk_read_error", error=str(e))
                return None

        return None

    def set(self, file_path: str, result: str, config_hash: str = ""):  # 设置缓存
        """缓存解析结果。

        Args:
            file_path: 文件路径
            result: 解析结果
            config_hash: 配置哈希
        """
        key = self._make_key(file_path, config_hash)
        entry = {
            "result": result,
            "timestamp": time.time(),
            "mtime": self._get_file_mtime(file_path),
            "file_path": file_path,
        }

        # 写入内存缓存
        self._cache[key] = entry

        # 写入磁盘缓存
        try:
            disk_path = os.path.join(self._cache_dir, key)
            with open(disk_path, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
            logger.info("parse_cache_set", file=file_path)
        except OSError as e:
            logger.warning("parse_cache_disk_write_error", error=str(e))

    def invalidate(self, file_path: str, config_hash: str = ""):  # 使缓存失效
        """使指定文件的缓存失效。

        Args:
            file_path: 文件路径
            config_hash: 配置哈希
        """
        key = self._make_key(file_path, config_hash)

        if key in self._cache:
            del self._cache[key]

        disk_path = os.path.join(self._cache_dir, key)
        if os.path.exists(disk_path):
            os.remove(disk_path)

        logger.info("parse_cache_invalidated", file=file_path)

    def clear(self):  # 清空所有缓存
        """清空所有缓存"""
        self._cache.clear()
        for f in os.listdir(self._cache_dir):
            fpath = os.path.join(self._cache_dir, f)
            if os.path.isfile(fpath):
                os.remove(fpath)
        logger.info("parse_cache_cleared")

    @property
    def stats(self) -> dict:  # 缓存统计
        """获取缓存统计信息"""
        disk_count = len(
            [
                f
                for f in os.listdir(self._cache_dir)
                if os.path.isfile(os.path.join(self._cache_dir, f))
            ]
        )
        return {
            "memory_entries": len(self._cache),
            "disk_entries": disk_count,
            "cache_dir": self._cache_dir,
            "ttl": self.ttl,
        }


# 全局单例缓存实例
_parse_cache: ParseCache | None = None


def get_parse_cache(ttl: int = DEFAULT_CACHE_TTL) -> ParseCache:
    """获取全局解析缓存单例。

    Args:
        ttl: 缓存有效期（秒），仅在首次创建时生效

    Returns:
        ParseCache 实例
    """
    global _parse_cache
    if _parse_cache is None:
        _parse_cache = ParseCache(ttl=ttl)
    return _parse_cache
