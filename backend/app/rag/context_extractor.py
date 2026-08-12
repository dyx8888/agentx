"""# ContextExtractor 模块，多模态内容上下文提取器，借鉴 RAG-Anything 的 ContextExtractor 设计
上下文提取器模块  # 从文档内容列表中提取多模态内容的周围文本上下文
借鉴 RAG-Anything 的 ContextExtractor 和 utils.py 中的 extract_section_path / extract_neighbor_text 设计
"""

from dataclasses import dataclass  # dataclass 用于 ContextConfig 配置类

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


@dataclass
class ContextConfig:  # 上下文提取配置
    """上下文提取配置，借鉴 RAG-Anything 的 ContextConfig 设计"""

    context_window: int = 1  # 上下文窗口大小：前后各取 N 个元素
    context_mode: str = "page"  # 上下文模式：page（同页）/ section（同章节）/ neighbor（相邻）
    max_context_tokens: int = 2000  # 最大上下文 token 数，避免 Prompt 过长


class ContextExtractor:  # 多模态内容上下文提取器
    """多模态内容上下文提取器，从文档内容列表中提取周围文本作为上下文。

    借鉴 RAG-Anything 的 ContextExtractor 设计，解决多模态内容（图片、表格等）
    脱离上下文后难以理解的问题。
    """

    def __init__(self, config: ContextConfig = None):
        """初始化上下文提取器

        Args:
            config: 上下文提取配置
        """
        self.config = config or ContextConfig()

    def extract_context(  # 核心方法：提取上下文
        self,
        content_list: list[dict],  # 文档内容列表，每个元素含 type/content/page 等字段
        current_item_index: int,  # 当前多模态内容在列表中的位置
    ) -> str:
        """提取当前多模态内容周围的文本上下文。

        Args:
            content_list: 文档解析后的内容列表
            current_item_index: 当前多模态内容的索引位置

        Returns:
            提取到的上下文字符串
        """
        if not content_list or current_item_index >= len(content_list):
            return ""

        mode = self.config.context_mode
        window = self.config.context_window

        if mode == "page":
            return self._extract_page_context(content_list, current_item_index)
        elif mode == "section":
            return self._extract_section_context(content_list, current_item_index)
        else:
            return self._extract_neighbor_context(content_list, current_item_index, window)

    def _extract_page_context(self, content_list: list[dict], index: int) -> str:  # 提取同页上下文
        """提取当前元素所在页面的所有文本内容作为上下文。

        Args:
            content_list: 文档内容列表
            index: 当前元素索引

        Returns:
            同页上下文字符串
        """
        current_item = content_list[index]
        current_page = current_item.get("page", 0)
        if not current_page:
            return ""

        context_parts = []
        for item in content_list:
            if item.get("page") == current_page and item.get("type") == "text":
                text = item.get("content", "")
                if text:
                    context_parts.append(text)

        context = "\n".join(context_parts)
        return self._truncate_if_needed(context)

    def _extract_section_context(
        self, content_list: list[dict], index: int
    ) -> str:  # 提取章节上下文
        """提取当前元素所在章节的上下文。
        章节由标题（type='heading'）界定，取最近两个标题之间的文本内容。

        Args:
            content_list: 文档内容列表
            index: 当前元素索引

        Returns:
            章节上下文字符串
        """
        # 向前查找最近的标题
        section_start = 0
        for i in range(index, -1, -1):
            if content_list[i].get("type") == "heading":
                section_start = i
                break

        # 向后查找下一个标题（或列表末尾）
        section_end = len(content_list)
        for i in range(index + 1, len(content_list)):
            if content_list[i].get("type") == "heading":
                section_end = i
                break

        context_parts = []
        for i in range(section_start, section_end):
            item = content_list[i]
            if item.get("type") in ("text", "heading"):
                text = item.get("content", "")
                if text:
                    prefix = "## " if item.get("type") == "heading" else ""
                    context_parts.append(prefix + text)

        context = "\n".join(context_parts)
        return self._truncate_if_needed(context)

    def _extract_neighbor_context(  # 提取相邻上下文
        self, content_list: list[dict], index: int, window: int
    ) -> str:
        """提取当前元素前后各 window 个文本元素的上下文。

        Args:
            content_list: 文档内容列表
            index: 当前元素索引
            window: 前后窗口大小

        Returns:
            相邻上下文字符串
        """
        start = max(0, index - window)
        end = min(len(content_list), index + window + 1)

        context_parts = []
        for i in range(start, end):
            if i == index:
                continue  # 跳过当前元素本身
            item = content_list[i]
            if item.get("type") in ("text", "heading"):
                text = item.get("content", "")
                if text:
                    context_parts.append(text)

        context = "\n".join(context_parts)
        return self._truncate_if_needed(context)

    def _truncate_if_needed(self, text: str) -> str:  # 按最大 token 数截断
        """如果文本超过最大 token 限制，则截断。
        使用简单的字符数估算：中文约 1.5 字符/token，英文约 4 字符/token。

        Args:
            text: 原始文本

        Returns:
            截断后的文本
        """
        max_chars = self.config.max_context_tokens * 2  # 粗略估算：1 token ≈ 2 字符
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...(上下文已截断)"

    def extract_section_path(  # 提取章节路径（借鉴 RAG-Anything utils.py 设计）
        self, content_list: list[dict], index: int
    ) -> str:
        """提取当前元素在文档中的章节路径。
        借鉴 RAG-Anything 的 extract_section_path_from_content_list() 设计。

        Args:
            content_list: 文档内容列表
            index: 当前元素索引

        Returns:
            章节路径，如 "第一章 > 1.1 概述 > 1.1.1 背景"
        """
        headings = []
        for i in range(index + 1):  # 当前元素之前的所有标题
            item = content_list[i]
            if item.get("type") == "heading":
                heading_text = item.get("content", "")
                if heading_text:
                    headings.append(heading_text)

        if not headings:
            return ""

        return " > ".join(headings)


# 全局单例
_context_extractor: ContextExtractor | None = None


def get_context_extractor(window: int = 1, mode: str = "page") -> ContextExtractor:
    """获取全局上下文提取器单例。

    Args:
        window: 上下文窗口大小
        mode: 上下文模式

    Returns:
        ContextExtractor 实例
    """
    global _context_extractor
    if _context_extractor is None:
        config = ContextConfig(context_window=window, context_mode=mode)
        _context_extractor = ContextExtractor(config)
    return _context_extractor
