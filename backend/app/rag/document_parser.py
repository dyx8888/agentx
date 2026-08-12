"""# DocumentParser 模块，多格式文档解析器，支持解析器注册表 + 热插拔
多格式文档解析器  # 基于注册表模式，支持运行时切换解析器后端
借鉴 RAG-Anything 的解析器注册表设计，实现 Parser 基类 + 多实现 + 注册表的策略模式
"""

import io  # BytesIO 用于将字节流转为文件对象，PyPDF2 和 python-docx 都需要文件对象而非字节流
from abc import ABC, abstractmethod  # 抽象基类，定义解析器接口规范

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

SUPPORTED_FORMATS = {"pdf", "docx", "html", "htm", "txt"}  # 使用 set 而非 list，O(1) 查找效率
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB 上限，防止超大文件导致内存溢出或解析超时


class BaseParser(ABC):  # 解析器抽象基类，定义统一接口
    """文档解析器抽象基类，所有解析器实现必须继承此类"""  # 借鉴 RAG-Anything 的 Parser 基类设计

    @abstractmethod
    def parse_pdf(self, content: bytes) -> str:  # PDF 解析
        """解析 PDF 文档内容"""

    @abstractmethod
    def parse_docx(self, content: bytes) -> str:  # Word 文档解析
        """解析 DOCX 文档内容"""

    @abstractmethod
    def parse_html(self, content: bytes) -> str:  # HTML 解析
        """解析 HTML 文档内容"""

    @abstractmethod
    def parse_txt(self, content: bytes) -> str:  # 纯文本解析
        """解析 TXT 文档内容"""

    def check_installation(self) -> bool:  # 检查解析器依赖是否安装
        """检查解析器所需的依赖是否已安装，返回 True 表示可用"""
        return True

    @property
    @abstractmethod
    def name(self) -> str:  # 解析器名称，用于注册表标识
        """解析器名称"""


class PyPDF2Parser(BaseParser):  # 基于 PyPDF2 的 PDF 解析器
    """PyPDF2 PDF 解析器"""  # 轻量级 PDF 解析，适合简单文本提取场景

    @property
    def name(self) -> str:
        return "pypdf2"

    def check_installation(self) -> bool:
        try:
            import PyPDF2  # noqa: F401

            return True
        except ImportError:
            return False

    def parse_pdf(self, content: bytes) -> str:
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
        except ImportError:
            raise ImportError(
                "PyPDF2 is required for PDF parsing. Install with: pip install PyPDF2"
            )

    def parse_docx(self, content: bytes) -> str:
        raise NotImplementedError("PyPDF2Parser does not support DOCX parsing")

    def parse_html(self, content: bytes) -> str:
        raise NotImplementedError("PyPDF2Parser does not support HTML parsing")

    def parse_txt(self, content: bytes) -> str:
        return content.decode("utf-8", errors="replace")


class StandardDocxParser(BaseParser):  # 基于 python-docx 的 Word 解析器
    """python-docx Word 解析器"""

    @property
    def name(self) -> str:
        return "python-docx"

    def check_installation(self) -> bool:
        try:
            import docx  # noqa: F401

            return True
        except ImportError:
            return False

    def parse_pdf(self, content: bytes) -> str:
        raise NotImplementedError("StandardDocxParser does not support PDF parsing")

    def parse_docx(self, content: bytes) -> str:
        try:
            from docx import Document

            doc = Document(io.BytesIO(content))
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    style = para.style.name if para.style else ""
                    if style and "heading" in style.lower():
                        paragraphs.append(f"\n## {para.text}\n")
                    else:
                        paragraphs.append(para.text)
            return "\n".join(paragraphs)
        except ImportError:
            raise ImportError(
                "python-docx is required for Word parsing. Install with: pip install python-docx"
            )

    def parse_html(self, content: bytes) -> str:
        raise NotImplementedError("StandardDocxParser does not support HTML parsing")

    def parse_txt(self, content: bytes) -> str:
        return content.decode("utf-8", errors="replace")


class BS4HTMLParser(BaseParser):  # 基于 BeautifulSoup4 的 HTML 解析器
    """BeautifulSoup4 HTML 解析器"""

    @property
    def name(self) -> str:
        return "bs4"

    def check_installation(self) -> bool:
        try:
            import bs4  # noqa: F401

            return True
        except ImportError:
            return False

    def parse_pdf(self, content: bytes) -> str:
        raise NotImplementedError("BS4HTMLParser does not support PDF parsing")

    def parse_docx(self, content: bytes) -> str:
        raise NotImplementedError("BS4HTMLParser does not support DOCX parsing")

    def parse_html(self, content: bytes) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)
        except ImportError:
            raise ImportError(
                "beautifulsoup4 is required for HTML parsing. Install with: pip install beautifulsoup4"
            )

    def parse_txt(self, content: bytes) -> str:
        return content.decode("utf-8", errors="replace")


class CompositeParser(BaseParser):  # 组合解析器，按格式分派给不同子解析器
    """组合解析器，将不同格式的解析委托给各自的子解析器。
    这是默认使用的解析器，内部组合了 PyPDF2Parser、StandardDocxParser、BS4HTMLParser。
    """

    @property
    def name(self) -> str:
        return "composite"

    def __init__(self):
        self._pdf_parser = PyPDF2Parser()
        self._docx_parser = StandardDocxParser()
        self._html_parser = BS4HTMLParser()

    def check_installation(self) -> bool:
        return True  # 组合解析器始终可用，具体格式解析时由子解析器自行检查

    def parse_pdf(self, content: bytes) -> str:
        if not self._pdf_parser.check_installation():
            raise ImportError(
                "PyPDF2 is required for PDF parsing. Install with: pip install PyPDF2"
            )
        return self._pdf_parser.parse_pdf(content)

    def parse_docx(self, content: bytes) -> str:
        if not self._docx_parser.check_installation():
            raise ImportError(
                "python-docx is required for Word parsing. Install with: pip install python-docx"
            )
        return self._docx_parser.parse_docx(content)

    def parse_html(self, content: bytes) -> str:
        if not self._html_parser.check_installation():
            raise ImportError(
                "beautifulsoup4 is required for HTML parsing. Install with: pip install beautifulsoup4"
            )
        return self._html_parser.parse_html(content)

    def parse_txt(self, content: bytes) -> str:
        return content.decode("utf-8", errors="replace")


# 解析器注册表：借鉴 RAG-Anything 的 SUPPORTED_PARSERS 字典设计
# 注册表模式支持运行时切换解析器后端，便于未来扩展 MinerU、Docling 等高级解析器
PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "composite": CompositeParser,  # 默认组合解析器，支持所有格式
    "pypdf2": PyPDF2Parser,  # 纯 PDF 解析器
    "python-docx": StandardDocxParser,  # 纯 Word 解析器
    "bs4": BS4HTMLParser,  # 纯 HTML 解析器
}

# 当前激活的解析器实例，可通过 set_parser() 切换
_active_parser: BaseParser | None = None


def get_parser(name: str = "composite") -> BaseParser:  # 工厂函数：从注册表获取解析器实例
    """获取解析器实例。借鉴 RAG-Anything 的 get_parser() 工厂函数设计。

    Args:
        name: 解析器名称，默认 "composite"

    Returns:
        BaseParser 实例

    Raises:
        ValueError: 当解析器名称不在注册表中时
    """
    if name not in PARSER_REGISTRY:
        available = ", ".join(PARSER_REGISTRY.keys())
        raise ValueError(f"Unknown parser: '{name}'. Available: {available}")
    return PARSER_REGISTRY[name]()


def set_parser(name: str):  # 设置全局激活的解析器
    """设置全局解析器实例"""
    global _active_parser
    _active_parser = get_parser(name)
    logger.info("parser_switched", parser=name)


def get_active_parser() -> BaseParser:
    """获取当前激活的解析器实例，懒加载"""
    global _active_parser
    if _active_parser is None:
        _active_parser = get_parser("composite")
    return _active_parser


def register_parser(name: str, parser_cls: type[BaseParser]):  # 注册自定义解析器到注册表
    """注册自定义解析器，支持运行时热插拔扩展。

    Args:
        name: 解析器名称
        parser_cls: 解析器类，必须继承 BaseParser
    """
    if not issubclass(parser_cls, BaseParser):
        raise TypeError(f"Parser class must inherit from BaseParser, got {parser_cls}")
    PARSER_REGISTRY[name] = parser_cls
    logger.info("parser_registered", name=name)


class DocumentParser:  # 向后兼容的静态门面类，内部委托给解析器注册表
    """多格式文档解析器，支持 PDF / Word(.docx) / HTML / TXT
    兼容旧 API，内部委托给解析器注册表。
    """

    @staticmethod
    def parse(filename: str, content: bytes) -> str:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported file format: .{suffix}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit")

        parser = get_active_parser()

        if suffix == "pdf":
            return parser.parse_pdf(content)
        elif suffix == "docx":
            return parser.parse_docx(content)
        elif suffix in ("html", "htm"):
            return parser.parse_html(content)
        elif suffix == "txt":
            return parser.parse_txt(content)
