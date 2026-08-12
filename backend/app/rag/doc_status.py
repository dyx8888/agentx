"""# DocStatus 模块，文档处理生命周期状态追踪，借鉴 RAG-Anything 的文档状态追踪设计
文档状态追踪模块  # 追踪文档从上传到入库的完整生命周期
借鉴 RAG-Anything 的文档状态追踪设计：READY → HANDLING → PROCESSED → FAILED
同时追踪文本处理和多模态处理两个维度的状态
"""

import enum  # 枚举定义状态常量
import time  # 时间戳用于记录状态变更时间

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


class DocState(enum.StrEnum):  # 文档处理状态枚举
    """文档处理状态，借鉴 RAG-Anything 的状态设计"""

    READY = "ready"  # 就绪，等待处理
    HANDLING = "handling"  # 处理中
    PROCESSED = "processed"  # 已处理完成
    FAILED = "failed"  # 处理失败
    SKIPPED = "skipped"  # 已跳过（不支持的格式或大小超限）


class DocStatus:  # 单个文档的状态追踪器
    """单个文档的状态追踪器，记录文本处理和多模态处理两个维度的状态。

    借鉴 RAG-Anything 的文档状态设计，将文本处理和多模态处理分开追踪。
    """

    def __init__(self, doc_id: str, file_path: str = ""):
        """初始化文档状态追踪器。

        Args:
            doc_id: 文档唯一标识
            file_path: 文件路径
        """
        self.doc_id = doc_id
        self.file_path = file_path

        # 文本处理状态
        self.text_state: DocState = DocState.READY
        self.text_started_at: float = 0.0
        self.text_completed_at: float = 0.0
        self.text_error: str = ""
        self.text_chunk_count: int = 0  # 切分后的切片数

        # 多模态处理状态（图像、表格等）
        self.multimodal_state: DocState = DocState.READY
        self.multimodal_started_at: float = 0.0
        self.multimodal_completed_at: float = 0.0
        self.multimodal_error: str = ""
        self.multimodal_count: int = 0  # 多模态内容数量

        # 元数据
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.metadata: dict = {}

    def start_text_processing(self):  # 开始文本处理
        """标记文本处理开始"""
        self.text_state = DocState.HANDLING
        self.text_started_at = time.time()
        self.updated_at = time.time()
        logger.info("doc_text_processing_started", doc_id=self.doc_id)

    def complete_text_processing(self, chunk_count: int = 0):  # 完成文本处理
        """标记文本处理完成

        Args:
            chunk_count: 切分后的切片数
        """
        self.text_state = DocState.PROCESSED
        self.text_completed_at = time.time()
        self.text_chunk_count = chunk_count
        self.updated_at = time.time()
        logger.info(
            "doc_text_processing_completed",
            doc_id=self.doc_id,
            chunk_count=chunk_count,
            duration_ms=round((self.text_completed_at - self.text_started_at) * 1000),
        )

    def fail_text_processing(self, error: str):  # 文本处理失败
        """标记文本处理失败

        Args:
            error: 错误描述
        """
        self.text_state = DocState.FAILED
        self.text_completed_at = time.time()
        self.text_error = error
        self.updated_at = time.time()
        logger.error("doc_text_processing_failed", doc_id=self.doc_id, error=error)

    def start_multimodal_processing(self):  # 开始多模态处理
        """标记多模态处理开始"""
        self.multimodal_state = DocState.HANDLING
        self.multimodal_started_at = time.time()
        self.updated_at = time.time()
        logger.info("doc_multimodal_processing_started", doc_id=self.doc_id)

    def complete_multimodal_processing(self, count: int = 0):  # 完成多模态处理
        """标记多模态处理完成

        Args:
            count: 多模态内容数量
        """
        self.multimodal_state = DocState.PROCESSED
        self.multimodal_completed_at = time.time()
        self.multimodal_count = count
        self.updated_at = time.time()
        logger.info(
            "doc_multimodal_processing_completed",
            doc_id=self.doc_id,
            count=count,
            duration_ms=round((self.multimodal_completed_at - self.multimodal_started_at) * 1000),
        )

    def fail_multimodal_processing(self, error: str):  # 多模态处理失败
        """标记多模态处理失败

        Args:
            error: 错误描述
        """
        self.multimodal_state = DocState.FAILED
        self.multimodal_completed_at = time.time()
        self.multimodal_error = error
        self.updated_at = time.time()
        logger.error("doc_multimodal_processing_failed", doc_id=self.doc_id, error=error)

    def skip(self, reason: str = ""):  # 跳过文档
        """标记文档被跳过（不支持的格式或大小超限）"""
        self.text_state = DocState.SKIPPED
        self.multimodal_state = DocState.SKIPPED
        self.text_error = reason
        self.updated_at = time.time()
        logger.info("doc_skipped", doc_id=self.doc_id, reason=reason)

    @property
    def is_fully_processed(self) -> bool:  # 是否已完全处理
        """检查文档是否已完全处理完成"""
        text_done = self.text_state in (DocState.PROCESSED, DocState.SKIPPED)
        multimodal_done = self.multimodal_state in (DocState.PROCESSED, DocState.SKIPPED)
        return text_done and multimodal_done

    @property
    def has_failed(self) -> bool:  # 是否有处理失败
        """检查是否有任何处理失败"""
        return self.text_state == DocState.FAILED or self.multimodal_state == DocState.FAILED

    def to_dict(self) -> dict:  # 转为字典
        """将状态转为可序列化的字典"""
        return {
            "doc_id": self.doc_id,
            "file_path": self.file_path,
            "text_state": self.text_state.value,
            "text_started_at": self.text_started_at,
            "text_completed_at": self.text_completed_at,
            "text_error": self.text_error,
            "text_chunk_count": self.text_chunk_count,
            "multimodal_state": self.multimodal_state.value,
            "multimodal_started_at": self.multimodal_started_at,
            "multimodal_completed_at": self.multimodal_completed_at,
            "multimodal_error": self.multimodal_error,
            "multimodal_count": self.multimodal_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_fully_processed": self.is_fully_processed,
            "has_failed": self.has_failed,
        }


class DocStatusManager:  # 文档状态管理器，批量管理多个文档的状态
    """文档状态管理器，管理一批文档的处理状态。

    借鉴 RAG-Anything 的文档生命周期管理设计。
    """

    def __init__(self):
        self._statuses: dict[str, DocStatus] = {}  # doc_id → DocStatus

    def get_or_create(self, doc_id: str, file_path: str = "") -> DocStatus:  # 获取或创建状态
        """获取或创建文档状态

        Args:
            doc_id: 文档唯一标识
            file_path: 文件路径

        Returns:
            DocStatus 实例
        """
        if doc_id not in self._statuses:
            self._statuses[doc_id] = DocStatus(doc_id=doc_id, file_path=file_path)
        return self._statuses[doc_id]

    def get(self, doc_id: str) -> DocStatus | None:  # 获取状态
        """获取文档状态

        Returns:
            DocStatus 实例，不存在时返回 None
        """
        return self._statuses.get(doc_id)

    def remove(self, doc_id: str):  # 移除状态
        """移除文档状态追踪"""
        if doc_id in self._statuses:
            del self._statuses[doc_id]
            logger.info("doc_status_removed", doc_id=doc_id)

    def get_all_states(self) -> dict[str, str]:  # 获取所有文档状态
        """获取所有文档的当前状态概览

        Returns:
            doc_id → 状态字符串 的字典
        """
        return {doc_id: status.text_state.value for doc_id, status in self._statuses.items()}

    def get_pending_docs(self) -> list[str]:  # 获取待处理文档
        """获取所有待处理的文档 ID 列表"""
        return [
            doc_id
            for doc_id, status in self._statuses.items()
            if status.text_state == DocState.READY
        ]

    def get_failed_docs(self) -> list[str]:  # 获取失败文档
        """获取所有处理失败的文档 ID 列表"""
        return [doc_id for doc_id, status in self._statuses.items() if status.has_failed]

    def get_processed_docs(self) -> list[str]:  # 获取已完成文档
        """获取所有已完全处理完成的文档 ID 列表"""
        return [doc_id for doc_id, status in self._statuses.items() if status.is_fully_processed]

    @property
    def stats(self) -> dict:  # 统计信息
        """获取处理统计信息"""
        total = len(self._statuses)
        processed = len(self.get_processed_docs())
        failed = len(self.get_failed_docs())
        pending = len(self.get_pending_docs())
        handling = total - processed - failed - pending

        return {
            "total": total,
            "processed": processed,
            "failed": failed,
            "pending": pending,
            "handling": handling,
        }

    def clear(self):  # 清空所有状态
        """清空所有文档状态追踪"""
        self._statuses.clear()
        logger.info("doc_status_manager_cleared")


# 全局单例
_doc_status_manager: DocStatusManager | None = None


def get_doc_status_manager() -> DocStatusManager:
    """获取全局文档状态管理器单例"""
    global _doc_status_manager
    if _doc_status_manager is None:
        _doc_status_manager = DocStatusManager()
    return _doc_status_manager
