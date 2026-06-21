import io

import pytest

from app.rag.document_parser import DocumentParser, SUPPORTED_FORMATS
from app.rag.text_splitter import TextChunker


def _make_docx_bytes(text: str) -> bytes:
    """Create a minimal DOCX with text for testing"""
    from docx import Document
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestDocumentParser:
    def test_parse_txt(self):
        content = "Hello, this is a test document.\n它包含中文。"
        result = DocumentParser.parse("test.txt", content.encode("utf-8"))
        assert "Hello" in result
        assert "中文" in result

    def test_parse_docx(self):
        content = _make_docx_bytes("这是Word文档的内容。")
        result = DocumentParser.parse("test.docx", content)
        assert "Word文档" in result

    def test_parse_html(self):
        html = "<html><body><h1>标题</h1><p>段落内容</p></body></html>".encode("utf-8")
        result = DocumentParser.parse("test.html", html)
        assert "标题" in result
        assert "段落内容" in result

    def test_parse_unsupported_format(self):
        with pytest.raises(ValueError, match="Unsupported file format"):
            DocumentParser.parse("test.xlsx", b"fake content")

    def test_parse_exceeds_size_limit(self):
        big_content = b"x" * (50 * 1024 * 1024 + 1)
        with pytest.raises(ValueError, match="File size exceeds"):
            DocumentParser.parse("test.txt", big_content)

    def test_supported_formats_define(self):
        assert "pdf" in SUPPORTED_FORMATS
        assert "docx" in SUPPORTED_FORMATS
        assert "html" in SUPPORTED_FORMATS
        assert "txt" in SUPPORTED_FORMATS


class TestTextChunker:
    def test_chunk_short_text(self):
        chunker = TextChunker(chunk_size=512, chunk_overlap=64)
        text = "这是一段很短的文本。"
        chunks = chunker.chunk(text, source_file="test.txt")
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].source_file == "test.txt"
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1

    def test_chunk_long_text(self):
        chunker = TextChunker(chunk_size=128, chunk_overlap=16)
        text = "这是第一段。" * 30
        chunks = chunker.chunk(text, source_file="long.txt")
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.content) <= 128  # chunk_size is approximate
            assert chunk.source_file == "long.txt"

    def test_chunk_metadata_preserved(self):
        chunker = TextChunker(chunk_size=512, chunk_overlap=64)
        text = "测试文本。"
        metadata = {"category": "test", "author": "tester"}
        chunks = chunker.chunk(text, source_file="meta.txt", metadata=metadata)
        assert chunks[0].metadata == metadata

    def test_chunk_ids_are_unique(self):
        chunker = TextChunker(chunk_size=64, chunk_overlap=8)
        text = "A" * 200
        chunks = chunker.chunk(text, source_file="unique.txt")
        ids = {c.chunk_id for c in chunks}
        assert len(ids) == len(chunks)

    def test_chunk_total_chunks(self):
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        text = "这是一段较长的文本。" * 20
        chunks = chunker.chunk(text)
        total = chunks[0].total_chunks
        for c in chunks:
            assert c.total_chunks == total

    def test_overlap_exists(self):
        chunker = TextChunker(chunk_size=100, chunk_overlap=30)
        text = "A" * 300
        chunks = chunker.chunk(text)
        if len(chunks) >= 2:
            assert chunks[0].content[-10:] == chunks[1].content[:10]