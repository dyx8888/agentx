import hashlib  # MD5 哈希生成唯一 chunk_id，用于检索时的去重和溯源
from dataclasses import dataclass, field  # dataclass 用于 TextChunk 数据类，field 用于可变默认值

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


@dataclass  # 使用 dataclass 而非 dict，提供类型安全
class TextChunk:  # 文本切片数据结构
    content: str  # 切片文本内容
    chunk_index: int  # 切片序号，从 0 开始
    total_chunks: int  # 总切片数
    source_file: str = ""  # 源文件名
    source_page: int = 0  # 源页码
    metadata: dict = field(default_factory=dict)  # 额外元数据，使用 field 避免共享引用
    chunk_id: str = ""  # 切片唯一 ID，由 __post_init__ 自动生成

    def __post_init__(self):  # dataclass 初始化后自动调用，生成唯一 chunk_id
        if not self.chunk_id:  # 外部未指定 ID 时自动生成
            self.chunk_id = hashlib.md5(  # MD5 哈希确保 ID 唯一且可重现
                f"{self.source_file}:{self.chunk_index}:{self.content[:50]}".encode()  # 组合源文件+序号+内容前50字符，确保唯一性
            ).hexdigest()  # 32 位十六进制字符串


class TextChunker:  # 文本切片器，基于 LangChain 的 RecursiveCharacterTextSplitter
    """文本切片器，基于 LangChain RecursiveCharacterTextSplitter"""  # 递归语义切片优于固定长度切片

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):  # 512 是中英文 Embedding 模型的推荐窗口大小
        self.chunk_size = chunk_size  # 切片最大长度
        self.chunk_overlap = chunk_overlap  # 相邻切片重叠字符数，保证语义连续性

    def _get_splitter(self):  # 获取 LangChain 切片器实例
        try:  # LangChain 版本兼容：先用新路径尝试
            from langchain_text_splitters import RecursiveCharacterTextSplitter  # langchain >= 0.1.0 的新路径
        except ImportError:  # 新路径不可用
            try:  # 回退到旧路径
                from langchain.text_splitter import RecursiveCharacterTextSplitter  # langchain < 0.1.0 的旧路径
            except ImportError:  # 都不可用
                raise ImportError(  # 抛出明确错误，告知用户如何安装
                    "langchain is required for text chunking. Install with: pip install langchain"
                )
        return RecursiveCharacterTextSplitter(  # 创建递归字符切片器
            chunk_size=self.chunk_size,  # 切片大小
            chunk_overlap=self.chunk_overlap,  # 重叠大小
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],  # 分隔符优先级：段落 → 换行 → 句号 → 叹号 → 问号 → 分号 → 空格 → 字符
        )  # 递归尝试：优先在自然断句处切分，实在不行才按字符切分，保证语义完整性

    def chunk(  # 执行切片
        self, text: str, source_file: str = "", metadata: dict = None  # source_file 和 metadata 会传递给每个切片
    ) -> list[TextChunk]:  # 返回 TextChunk 列表
        splitter = self._get_splitter()  # 获取切片器
        raw_chunks = splitter.split_text(text)  # 执行切片，返回字符串列表
        total = len(raw_chunks)  # 总切片数

        chunks = []  # 构建 TextChunk 列表
        for i, chunk_text in enumerate(raw_chunks):  # 遍历每个切片
            chunks.append(  # 创建 TextChunk 对象
                TextChunk(
                    content=chunk_text,  # 切片文本
                    chunk_index=i,  # 切片序号
                    total_chunks=total,  # 总切片数
                    source_file=source_file,  # 源文件
                    metadata=metadata or {},  # 元数据
                )
            )

        return chunks  # 返回切片列表