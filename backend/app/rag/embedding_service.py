"""  # EmbeddingService 模块，文本向量化服务，Sentencetransformers 封装 + 缓存 + fallback
文本 Embedding 服务  # 将文本转为稠密向量，是 RAG 检索的核心基础设施
基于 BGE/M3E 中文 Embedding 模型，提供文本向量化和缓存功能  # BGE 系列在中文语义任务上表现优异，small 版本平衡了速度和效果
"""

import hashlib  # MD5 哈希用于生成缓存 key，避免用原始文本做 key 导致内存占用过大
import os  # 读取环境变量 EMBEDDING_MODEL，支持不同环境使用不同模型

import numpy as np  # 向量存储和运算，Embedding 结果统一为 numpy 数组

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

MODEL_CACHE: dict = {}  # 进程级模型缓存，避免多次加载同一模型浪费 GPU 显存和内存
DEFAULT_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")  # 环境变量 > 默认值，支持部署时灵活切换模型


class EmbeddingService:  # 文本向量化服务，单例模式
    """文本 Embedding 服务"""  # 封装模型加载、向量化、缓存、fallback 全套逻辑

    def __init__(self, model_name: str = None):  # 可选自定义模型名
        self.model_name = model_name or DEFAULT_MODEL_NAME  # 未指定时使用环境变量或默认模型
        self._model = None  # 懒加载，首次 encode 时才加载模型
        self._cache: dict = {}  # 文本 → 向量的本地缓存，用 MD5 key 节省内存
        self._cache_hits = 0  # 缓存命中计数，用于监控缓存效果
        self._cache_misses = 0  # 缓存未命中计数

    def _load_model(self):  # 加载 Embedding 模型，支持进程级缓存
        if self._model is not None:  # 已加载则直接返回，避免重复加载
            return self._model

        if self.model_name in MODEL_CACHE:  # 进程级缓存检查，同一模型只加载一次
            self._model = MODEL_CACHE[self.model_name]  # 复用已有模型
            return self._model

        try:  # 尝试加载 SentenceTransformer
            from sentence_transformers import SentenceTransformer  # 延迟导入，避免未安装时 import 即崩溃
            self._model = SentenceTransformer(self.model_name)  # 加载模型，首次会自动下载
            MODEL_CACHE[self.model_name] = self._model  # 写入进程级缓存
            logger.info("embedding_model_loaded", model=self.model_name)  # 记录成功加载
        except ImportError:  # sentence-transformers 未安装
            logger.warning("sentence_transformers_not_installed_fallback")  # 降级提示
            self._model = None  # 设为 None，后续使用 fallback
        except Exception as e:  # 其他加载异常（网络问题、显存不足等）
            logger.error("embedding_model_load_error", error=str(e))  # 记录错误
            self._model = None  # 降级

        return self._model  # 可能为 None（降级模式）

    def _cache_key(self, text: str) -> str:  # 生成缓存 key
        return hashlib.md5(text.encode("utf-8")).hexdigest()  # MD5 比原始文本短且固定长度，内存友好

    @property
    def dimension(self) -> int:  # 向量维度，用于创建 Milvus Collection 时的 schema 定义
        model = self._load_model()  # 触发加载
        if model:  # 正常加载时获取模型维度
            return model.get_sentence_embedding_dimension()  # SentenceTransformer 的方法
        return 512  # 降级模式下默认 512 维，与 fallback_embedding 一致

    def encode(self, texts: list[str]) -> np.ndarray:  # 批量向量化，核心方法
        if not texts:  # 空列表直接返回空数组，避免后续逻辑出错
            return np.array([])

        cached = []  # 存储 (原始索引, 向量) 对
        indices_to_encode = []  # 需要编码的文本索引
        texts_to_encode = []  # 需要编码的文本

        for i, text in enumerate(texts):  # 逐条检查缓存
            key = self._cache_key(text)  # 生成 MD5 key
            if key in self._cache:  # 缓存命中
                cached.append((i, self._cache[key]))  # 记录原始索引和缓存向量
                self._cache_hits += 1  # 命中计数
            else:  # 缓存未命中
                indices_to_encode.append(i)  # 记录原始索引
                texts_to_encode.append(text)  # 记录待编码文本
                self._cache_misses += 1  # 未命中计数

        if texts_to_encode:  # 有待编码的文本
            model = self._load_model()  # 加载模型
            if model:  # 正常模式
                encoded = model.encode(texts_to_encode, normalize_embeddings=True)  # 归一化方便后续余弦相似度计算
            else:  # 降级模式
                encoded = np.array([self._fallback_embedding(t) for t in texts_to_encode])  # 使用字符级 fallback

            for idx, emb in zip(indices_to_encode, encoded, strict=False):  # 将新编码结果写入缓存
                key = self._cache_key(texts[idx])  # 用原始文本生成 key
                self._cache[key] = emb  # 写入缓存
                cached.append((idx, emb))  # 添加到结果列表

        cached.sort(key=lambda x: x[0])  # 按原始索引排序，恢复输入顺序
        result = np.array([emb for _, emb in cached])  # 提取向量并转为 numpy 数组
        return result  # 返回与输入顺序一致的向量矩阵

    def encode_single(self, text: str) -> np.ndarray:  # 单条文本向量化的便捷方法
        return self.encode([text])[0]  # 复用批量方法，取第一个结果

    def _fallback_embedding(self, text: str, dim: int = 512) -> np.ndarray:  # 降级向量化：基于字符的简单哈希
        chars = list(text.lower())  # 转小写，减少大小写差异
        vec = np.zeros(dim)  # 初始化全零向量
        for i, ch in enumerate(chars[:dim]):  # 最多处理 dim 个字符
            vec[i % dim] += ord(ch) / 255.0  # 字符 ASCII 值归一化后叠加到向量对应位置
        norm = np.linalg.norm(vec)  # 计算 L2 范数
        if norm > 0:  # 非零向量才归一化
            vec /= norm  # L2 归一化，与模型输出格式一致
        return vec  # 返回降级向量

    @property
    def cache_stats(self) -> dict:  # 缓存统计，用于监控
        total = self._cache_hits + self._cache_misses  # 总请求数
        hit_rate = self._cache_hits / total if total > 0 else 0  # 命中率，避免除零
        return {
            "hits": self._cache_hits,  # 命中次数
            "misses": self._cache_misses,  # 未命中次数
            "hit_rate": round(hit_rate, 3),  # 命中率，保留 3 位小数
            "cache_size": len(self._cache),  # 缓存条目数
        }


_embedding_service: EmbeddingService | None = None  # 模块级单例，全局共享


def get_embedding_service() -> EmbeddingService:  # 工厂函数，保证全局单例
    global _embedding_service  # 声明修改全局变量
    if _embedding_service is None:  # 首次调用时创建
        _embedding_service = EmbeddingService()  # 使用默认模型创建
    return _embedding_service  # 返回单例
