import io  # BytesIO 用于将字节流转为文件对象，PyPDF2 和 python-docx 都需要文件对象而非字节流

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

SUPPORTED_FORMATS = {"pdf", "docx", "html", "htm", "txt"}  # 使用 set 而非 list，O(1) 查找效率，避免循环遍历
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB 上限，防止超大文件导致内存溢出或解析超时


class DocumentParser:  # 静态方法类，无需实例化，所有解析逻辑都是无状态的
    """多格式文档解析器，支持 PDF / Word(.docx) / HTML / TXT"""  # 统一入口，调用方不需要关心文件格式

    @staticmethod
    def parse(filename: str, content: bytes) -> str:  # 静态方法，无需实例化直接调用
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""  # 从右分割取最后一个点，支持多点的文件名；lower() 统一大小写
        if suffix not in SUPPORTED_FORMATS:  # 格式校验前置，避免错误的格式传入解析器导致异常
            raise ValueError(  # 抛出明确异常，让调用方知道不支持该格式
                f"Unsupported file format: .{suffix}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )  # sorted 确保输出顺序一致，便于可读性

        if len(content) > MAX_FILE_SIZE:  # 大小校验前置，防止解析超时或内存溢出
            raise ValueError(f"File size exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit")  # 整数除法转为 MB 显示

        if suffix == "pdf":  # 按后缀分发到不同解析器
            return DocumentParser._parse_pdf(content)
        elif suffix == "docx":  # docx 是 Office Open XML 格式，需要 python-docx
            return DocumentParser._parse_docx(content)
        elif suffix in ("html", "htm"):  # html 和 htm 是同一格式，合并处理
            return DocumentParser._parse_html(content)
        elif suffix == "txt":  # TXT 最简单，直接解码 UTF-8
            return content.decode("utf-8", errors="replace")  # errors="replace" 防止非法字节导致解码崩溃

    @staticmethod
    def _parse_pdf(content: bytes) -> str:  # PDF 解析，使用 PyPDF2
        try:  # PyPDF2 可能未安装，需要友好提示
            from PyPDF2 import PdfReader  # 延迟导入，只在需要时加载
            reader = PdfReader(io.BytesIO(content))  # PyPDF2 需要文件对象，用 BytesIO 包装字节流
            pages = []  # 逐页收集文本
            for page in reader.pages:  # 每页独立提取
                text = page.extract_text()  # 提取页面文本
                if text:  # 图片页或空页返回 None 或空字符串，需要过滤
                    pages.append(text)
            return "\n\n".join(pages)  # 两换行分隔不同页面，保持页面边界
        except ImportError:  # PyPDF2 未安装时给出明确提示
            raise ImportError("PyPDF2 is required for PDF parsing. Install with: pip install PyPDF2")

    @staticmethod
    def _parse_docx(content: bytes) -> str:  # Word 文档解析
        try:  # python-docx 可能未安装
            from docx import Document  # 延迟导入
            doc = Document(io.BytesIO(content))  # python-docx 同样需要文件对象
            paragraphs = []  # 收集段落
            for para in doc.paragraphs:  # 遍历所有段落
                if para.text.strip():  # 跳过空段落，减少噪音
                    style = para.style.name if para.style else ""  # 获取段落样式名，用于判断标题
                    if style and "heading" in style.lower():  # 标题样式转为 Markdown 标题格式
                        paragraphs.append(f"\n## {para.text}\n")  # ## 二级标题，前后加换行分隔
                    else:  # 普通段落
                        paragraphs.append(para.text)
            return "\n".join(paragraphs)  # 单换行连接段落
        except ImportError:  # python-docx 未安装
            raise ImportError(
                "python-docx is required for Word parsing. Install with: pip install python-docx"
            )

    @staticmethod
    def _parse_html(content: bytes) -> str:  # HTML 解析，使用 BeautifulSoup
        try:  # beautifulsoup4 可能未安装
            from bs4 import BeautifulSoup  # 延迟导入
            soup = BeautifulSoup(content, "html.parser")  # 使用内置 html.parser，无需额外安装 lxml
            for tag in soup(["script", "style", "nav", "footer", "header"]):  # 移除无意义标签
                tag.decompose()  # decompose() 彻底删除标签及其内容，比 extract() 更彻底
            text = soup.get_text(separator="\n")  # 用换行分隔不同标签的文本
            lines = [line.strip() for line in text.splitlines() if line.strip()]  # 去除空白行和首尾空格
            return "\n".join(lines)  # 拼接为干净文本
        except ImportError:  # beautifulsoup4 未安装
            raise ImportError(
                "beautifulsoup4 is required for HTML parsing. Install with: pip install beautifulsoup4"
            )