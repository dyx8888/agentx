"""  # MultiModalRetriever 模块，CLIP 多模态检索，支持以图搜图和文本搜图
多模态 RAG 检索引擎  # 多模态 = 文本 + 图像，CLIP 将两者映射到同一向量空间实现跨模态检索
CLIP Embedding + Milvus 以图搜图 + 文本-图像跨模态检索  # CLIP 是 OpenAI 的图文联合模型，核心优势是图文嵌入在同一语义空间
用于视觉设计师 Agent 风格参考检索  # 设计师需要根据风格描述或参考图找到类似的设计素材
"""

import base64  # 用于 base64 编码图像的编解码，支持 API 传输图像
import os  # 读取 Milvus 和 CLIP 模型配置环境变量
from dataclasses import dataclass, field  # dataclass 用于 ImageSearchResult 数据类
from io import BytesIO  # 将字节流转为 PIL 可读的文件对象

import numpy as np  # 向量存储和归一化运算

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

DEFAULT_CLIP_MODEL = os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32")  # 默认 CLIP 模型，ViT-B/32 平衡速度和效果
MILVUS_COLLECTION = os.getenv("MILVUS_IMAGE_COLLECTION", "company_images")  # 图像专用 Collection，与文本向量库分离


@dataclass  # 使用 dataclass 提供类型安全和 IDE 提示
class ImageSearchResult:  # 图像搜索结果
    image_id: str  # 图像唯一标识
    image_path: str | None = None  # 图像路径，可能为空（base64 上传）
    caption: str = ""  # 图像描述/标题
    metadata: dict = field(default_factory=dict)  # 元数据，使用 field 避免共享引用
    similarity: float = 0.0  # 相似度分数
    source: str = "vector"  # 检索来源


class CLIPEmbeddingService:  # CLIP 图像-文本联合 Embedding，单例模式
    """CLIP 图像-文本联合 Embedding"""  # CLIP 将图像和文本映射到同一 512 维向量空间

    _instance = None  # 单例存储

    def __new__(cls):  # 使用 __new__ 实现单例，确保全局只有一个 CLIP 模型实例
        if cls._instance is None:  # 首次创建
            cls._instance = super().__new__(cls)  # 调用父类 __new__ 创建实例
            cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回单例

    def __init__(self):  # __init__ 在每次 CLIPEmbeddingService() 时都会调用，需要 _initialized 保护
        if self._initialized:  # 已初始化则跳过，防止重复加载模型
            return
        self._initialized = True  # 标记已初始化
        self._model = None  # CLIP 模型，懒加载
        self._processor = None  # CLIP 处理器（tokenizer + 图像预处理）
        self._model_name = DEFAULT_CLIP_MODEL  # 模型名称
        self._cache: dict[str, np.ndarray] = {}  # 文本 embedding 缓存

    def _load_model(self):  # 加载 CLIP 模型
        if self._model is not None:  # 已加载则跳过
            return
        try:  # transformers 可能未安装
            import torch  # 延迟导入
            from transformers import CLIPModel, CLIPProcessor  # 延迟导入
            self._model = CLIPModel.from_pretrained(self._model_name)  # 加载 CLIP 模型
            self._processor = CLIPProcessor.from_pretrained(self._model_name)  # 加载处理器
            logger.info("clip_model_loaded", model=self._model_name)  # 记录成功
        except ImportError:  # transformers 未安装
            logger.warning("transformers_not_installed_clip_disabled")  # 降级
            self._model = None  # 标记不可用
        except Exception as e:  # 其他加载异常
            logger.error("clip_load_error", error=str(e))  # 记录错误
            self._model = None  # 降级

    def encode_text(self, texts: list[str]) -> np.ndarray:  # 文本编码为 CLIP 向量
        self._load_model()  # 确保模型加载
        if self._model is None:  # 模型不可用时返回随机向量（降级）
            return np.random.randn(len(texts), 512).astype(np.float32)  # 512 维随机向量，保持接口一致

        import torch  # 延迟导入
        cached = []  # 缓存命中的向量
        to_encode = []  # 需要编码的文本
        for t in texts:  # 逐条检查缓存
            key = f"txt:{t}"[:128]  # 截断 key 到 128 字符，防止过长文本导致 key 异常
            if key in self._cache:  # 缓存命中
                cached.append(self._cache[key])  # 使用缓存向量
            else:  # 缓存未命中
                to_encode.append(t)  # 加入待编码列表

        if to_encode:  # 有待编码文本
            inputs = self._processor(  # 使用 CLIP processor 处理文本
                text=to_encode, return_tensors="pt", padding=True, truncation=True  # 填充和截断确保统一长度
            )
            with torch.no_grad():  # 关闭梯度计算，节省显存
                embeddings = self._model.get_text_features(**inputs).cpu().numpy()  # 获取文本特征并转为 numpy
            for t, emb in zip(to_encode, embeddings, strict=False):  # 写入缓存
                self._cache[f"txt:{t}"[:128]] = emb  # 缓存的 key 与查询时一致
                cached.append(emb)  # 添加到结果

        result = np.array(cached)  # 转为 numpy 数组
        result = result / np.linalg.norm(result, axis=1, keepdims=True)  # L2 归一化，方便内积计算余弦相似度
        return result  # 返回归一化后的文本向量

    def encode_image(self, image_paths: list[str] | None = None,  # 图像编码：支持路径或字节流
                     image_bytes: list[bytes] | None = None) -> np.ndarray:  # 两者至少提供一个
        self._load_model()  # 确保模型加载
        if self._model is None:  # 模型不可用时返回随机向量
            n = len(image_paths) if image_paths else len(image_bytes)  # 确定数量
            return np.random.randn(n, 512).astype(np.float32)  # 随机向量降级

        import torch  # 延迟导入
        from PIL import Image  # 延迟导入 PIL

        images = []  # PIL Image 列表
        if image_paths:  # 从路径加载
            for path in image_paths:
                images.append(Image.open(path).convert("RGB"))  # 转为 RGB，确保三通道
        elif image_bytes:  # 从字节流加载
            for b in image_bytes:
                images.append(Image.open(BytesIO(b)).convert("RGB"))  # BytesIO 包装字节流

        inputs = self._processor(images=images, return_tensors="pt")  # CLIP processor 预处理图像
        with torch.no_grad():  # 关闭梯度
            embeddings = self._model.get_image_features(**inputs).cpu().numpy()  # 获取图像特征

        result = np.array(embeddings)  # 转为 numpy
        result = result / np.linalg.norm(result, axis=1, keepdims=True)  # L2 归一化
        return result  # 返回归一化后的图像向量

    def encode_image_base64(self, images_base64: list[str]) -> np.ndarray:  # base64 图像编码
        raw_bytes = [base64.b64decode(img) for img in images_base64]  # 解码 base64 为字节流
        return self.encode_image(image_bytes=raw_bytes)  # 复用字节流编码方法

    @property
    def dimension(self) -> int:  # 向量维度
        self._load_model()  # 确保模型加载
        return 512 if self._model is None else self._model.config.projection_dim  # 降级时返回 512


class MultiModalRetriever:  # 多模态检索引擎，支持文本搜图和以图搜图
    """多模态检索引擎"""  # 每个公司独立实例

    def __init__(self, company_id: str = "default"):  # 按公司隔离
        self.company_id = company_id  # 公司 ID
        self._clip = None  # CLIP 单例，懒加载
        self._milvus_initialized = False  # Milvus 是否已初始化
        self._collection = None  # Milvus Collection

    def _get_clip(self):  # 获取 CLIP 单例
        if self._clip is None:  # 首次使用
            self._clip = CLIPEmbeddingService()  # 获取单例
        return self._clip

    def _ensure_milvus(self):  # 确保 Milvus 已连接并创建 Collection
        if self._milvus_initialized:  # 已初始化
            return
        try:  # Milvus 连接可能失败
            from pymilvus import (  # 延迟导入
                Collection,  # Collection 对象
                CollectionSchema,  # Schema 定义
                DataType,  # 数据类型
                FieldSchema,  # 字段定义
                connections,  # 连接管理
                utility,  # 工具函数
            )

            host = os.getenv("MILVUS_HOST", "localhost")  # 环境变量读取
            port = int(os.getenv("MILVUS_PORT", "19530"))
            connections.connect(host=host, port=port, timeout=3)  # 3 秒超时

            fields = [  # 定义 Collection Schema
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),  # 主键 ID
                FieldSchema(name="company_id", dtype=DataType.VARCHAR, max_length=32),  # 公司 ID 用于过滤
                FieldSchema(name="image_path", dtype=DataType.VARCHAR, max_length=500),  # 图像路径
                FieldSchema(name="caption", dtype=DataType.VARCHAR, max_length=500),  # 图像描述
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self._get_clip().dimension),  # CLIP 向量
                FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=2000),  # JSON 元数据
            ]
            schema = CollectionSchema(fields, "image_embeddings")  # 创建 Schema
            if utility.has_collection(MILVUS_COLLECTION):  # Collection 已存在
                self._collection = Collection(MILVUS_COLLECTION)  # 直接使用
            else:  # 不存在则创建
                self._collection = Collection(MILVUS_COLLECTION, schema)  # 创建 Collection
                self._collection.create_index(  # 创建向量索引
                    field_name="embedding",
                    index_params={
                        "metric_type": "IP",  # 内积 = 余弦相似度（向量已归一化）
                        "index_type": "IVF_FLAT",  # IVF 索引，平衡速度和精度
                        "params": {"nlist": 128},  # 聚类中心数
                    },
                )

            self._collection.load()  # 加载到内存
            self._milvus_initialized = True  # 标记已初始化
            logger.info("multimodal_milvus_ready", collection=MILVUS_COLLECTION)  # 记录成功
        except ImportError:  # pymilvus 未安装
            logger.warning("pymilvus_not_installed_multimodal_disabled")  # 降级
        except Exception as e:  # 其他异常
            logger.warning("multimodal_milvus_error", error=str(e))  # 记录错误

    def index_image(self, image_id: str, caption: str,  # 索引单张图像
                    image_path: str = None, image_bytes: bytes = None,  # 路径或字节流二选一
                    metadata: dict = None) -> bool:  # 返回是否成功
        self._ensure_milvus()  # 确保 Milvus 可用
        clip = self._get_clip()  # 获取 CLIP

        embedding = None  # 图像向量
        if image_path:  # 从路径编码
            embedding = clip.encode_image(image_paths=[image_path])
        elif image_bytes:  # 从字节流编码
            embedding = clip.encode_image(image_bytes=[image_bytes])

        if embedding is None:  # 无有效图像数据
            logger.error("no_image_data", image_id=image_id)  # 记录错误
            return False

        if self._collection:  # Milvus 可用
            try:  # 插入可能失败
                import json  # 延迟导入
                self._collection.insert([{  # 插入单条数据
                    "id": image_id,
                    "company_id": self.company_id,  # 公司隔离
                    "image_path": image_path or "",  # 空字符串占位
                    "caption": caption,  # 图像描述
                    "embedding": embedding[0].tolist(),  # 向量转 list
                    "metadata": json.dumps(metadata or {}, ensure_ascii=False),  # JSON 序列化，保留中文
                }])
                self._collection.flush()  # 持久化
                logger.info("image_indexed", image_id=image_id, company=self.company_id)  # 记录成功
                return True
            except Exception as e:  # 插入失败
                logger.error("image_index_error", image_id=image_id, error=str(e))  # 记录错误
                return False
        return False  # Milvus 不可用

    def search_by_text(self, query: str, top_k: int = 10) -> list[ImageSearchResult]:  # 文本搜图
        """文本搜图"""  # 用文本描述搜索相似图像
        return self._search(query, top_k, mode="text")  # 委托给 _search

    def search_by_image(self, image_path: str = None, image_bytes: bytes = None,  # 以图搜图
                        image_base64: str = None, top_k: int = 10) -> list[ImageSearchResult]:  # 支持三种输入方式
        """以图搜图"""  # 用图像搜索相似图像
        if image_base64:  # base64 优先处理
            image_bytes = base64.b64decode(image_base64)  # 解码为字节流
        return self._search(  # 委托给 _search
            image_path=image_path, image_bytes=image_bytes,
            top_k=top_k, mode="image",
        )

    def _search(self, query_text: str = None, image_path: str = None,  # 核心检索方法
                image_bytes: bytes = None, top_k: int = 10,  # 文本和图像参数至少一个非空
                mode: str = "text") -> list[ImageSearchResult]:  # mode 区分检索模式
        self._ensure_milvus()  # 确保 Milvus 可用
        clip = self._get_clip()  # 获取 CLIP

        embedding = None  # 查询向量
        if mode == "text" and query_text:  # 文本模式
            embedding = clip.encode_text([query_text])  # 文本编码
        elif mode == "image":  # 图像模式
            if image_path:  # 路径编码
                embedding = clip.encode_image(image_paths=[image_path])
            elif image_bytes:  # 字节流编码
                embedding = clip.encode_image(image_bytes=[image_bytes])

        if embedding is None:  # 无有效查询向量
            return []

        if self._collection is None:  # Milvus 不可用
            return []

        try:  # 执行检索
            search_params = {"metric_type": "IP", "params": {"nprobe": 10}}  # 内积相似度
            expr = f'company_id == "{self.company_id}"'  # 按公司 ID 过滤，多租户隔离
            results = self._collection.search(  # ANN 搜索
                data=[embedding[0].tolist()],  # 查询向量
                anns_field="embedding",  # 向量字段
                param=search_params,  # 搜索参数
                limit=top_k,  # 返回数量
                expr=expr,  # 过滤表达式
                output_fields=["id", "image_path", "caption", "metadata"],  # 额外返回字段
            )
            formatted = []  # 格式化结果
            import json  # 延迟导入
            for hits in results:  # 遍历命中
                for hit in hits:  # 每个命中
                    formatted.append(ImageSearchResult(  # 构建结果对象
                        image_id=hit.entity.get("id", ""),
                        image_path=hit.entity.get("image_path"),
                        caption=hit.entity.get("caption", ""),
                        metadata=json.loads(hit.entity.get("metadata", "{}")),  # 解析 JSON 元数据
                        similarity=hit.score,  # 相似度分数
                    ))
            return formatted  # 返回结果
        except Exception as e:  # 检索异常
            logger.error("multimodal_search_error", error=str(e))  # 记录错误
            return []  # 降级返回空

    def search_cross_modal(self, query: str, image_path: str = None,  # 跨模态检索：文本+图像联合
                           top_k: int = 10) -> list[ImageSearchResult]:
        """跨模态检索：文本+图像联合检索"""  # 同时用文本和图像检索，融合结果
        text_results = self.search_by_text(query, top_k=top_k)  # 文本检索
        if image_path:  # 有图像时也做图像检索
            img_results = self.search_by_image(image_path=image_path, top_k=top_k)
        else:  # 无图像时只返回文本结果
            img_results = []

        merged = {}  # 合并结果，按 image_id 去重
        for r in text_results:  # 先加入文本结果
            merged[r.image_id] = r
        for r in img_results:  # 再合并图像结果
            if r.image_id in merged:  # 已存在
                merged[r.image_id].similarity = max(merged[r.image_id].similarity, r.similarity)  # 取最大相似度
            else:  # 新结果
                merged[r.image_id] = r

        results = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)  # 按相似度降序
        return results[:top_k]  # 返回 top_k

    def delete_image(self, image_id: str) -> bool:  # 删除图像
        self._ensure_milvus()  # 确保 Milvus 可用
        if self._collection:  # Collection 存在
            try:  # 删除可能失败
                self._collection.delete(f'id == "{image_id}"')  # 按 ID 删除
                return True  # 成功
            except Exception as e:  # 删除失败
                logger.error("image_delete_error", error=str(e))  # 记录错误
        return False  # 失败


_retriever_cache: dict[str, MultiModalRetriever] = {}  # 模块级缓存，按 company_id 存储单例


def get_multimodal_retriever(company_id: str = "default") -> MultiModalRetriever:  # 工厂函数
    if company_id not in _retriever_cache:  # 缓存未命中
        _retriever_cache[company_id] = MultiModalRetriever(company_id)  # 创建并缓存
    return _retriever_cache[company_id]  # 返回单例
