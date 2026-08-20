"""Preview semantic chunker for ecommerce RAG documents.

This module is intentionally not wired into ingestion yet. It provides a small,
dependency-free preview chunker that can be tested before replacing the existing
recursive TextChunker path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.rag.text_splitter import TextChunker

FACT_ID_RE = re.compile(r"\bfact_id\s*=\s*([^|\s]+)", re.IGNORECASE)
MARKER_RE = re.compile(r"\bmarker\s*=\s*([^|\s]+)", re.IGNORECASE)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?|[一二三四五六七八九十百千万]+")
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|【[^】]+】$|第[一二三四五六七八九十\d]+[章节条]|[一二三四五六七八九十\d]+[、.．]\s*[^。！？；]+$)"
)
NUMBERED_RULE_RE = re.compile(r"^\s*(?:\(?\d+\)?[、.．)]|第[一二三四五六七八九十\d]+条)")
FAQ_Q_RE = re.compile(r"^\s*(?:Q[:：]|问[:：]|问题[:：])", re.IGNORECASE)
FAQ_A_RE = re.compile(r"^\s*(?:A[:：]|答[:：]|答案[:：])", re.IGNORECASE)
POLICY_KEYWORDS = (
    "适用条件",
    "不适用条件",
    "例外",
    "限制条件",
    "优先级",
    "生效时间",
    "售后",
    "退货",
    "退款",
    "禁用",
    "违规",
    "替代表达",
)
UPDATE_KEYWORDS = ("公告", "更新", "目标", "库存", "优先级", "生效时间")
TABLE_KEYWORDS = ("SKU", "库存", "价格", "达人", "排期", "销量", "规格")


@dataclass(frozen=True)
class _Line:
    number: int
    text: str
    char_start: int
    char_end: int


class SmartChunker:
    """Preview semantic chunker for Chinese ecommerce knowledge documents."""

    def __init__(
        self,
        max_chunk_chars: int = 800,
        fallback_chunk_size: int | None = None,
        fallback_chunk_overlap: int = 64,
    ) -> None:
        self.max_chunk_chars = max(int(max_chunk_chars), 80)
        self.fallback_chunk_size = int(fallback_chunk_size or self.max_chunk_chars)
        self.fallback_chunk_overlap = max(int(fallback_chunk_overlap), 0)

    def split_text(self, text: str, metadata: dict | None = None) -> list[dict]:
        """Split text into preview chunks with semantic metadata."""
        source_metadata = dict(metadata or {})
        lines = self._scan_lines(text or "")
        chunks: list[dict] = []
        pending_paragraph: list[_Line] = []
        current_section = ""
        i = 0

        def flush_paragraph() -> None:
            nonlocal pending_paragraph
            if pending_paragraph:
                self._append_chunks(
                    chunks,
                    pending_paragraph,
                    "paragraph",
                    current_section,
                    source_metadata,
                )
                pending_paragraph = []

        while i < len(lines):
            line = lines[i]
            stripped = line.text.strip()
            if not stripped:
                flush_paragraph()
                i += 1
                continue

            if self._is_heading(stripped):
                flush_paragraph()
                current_section = stripped.lstrip("#").strip()
                i += 1
                continue

            if self._is_faq_question(stripped):
                flush_paragraph()
                group = [line]
                if i + 1 < len(lines) and self._is_faq_answer(lines[i + 1].text.strip()):
                    group.append(lines[i + 1])
                    i += 1
                self._append_chunks(chunks, group, "faq_pair", current_section, source_metadata)
                i += 1
                continue

            if self._is_fact_line(stripped):
                flush_paragraph()
                self._append_chunks(chunks, [line], "fact_line", current_section, source_metadata)
                i += 1
                continue

            if self._is_table_like(stripped):
                flush_paragraph()
                group = [line]
                i += 1
                while i < len(lines) and self._is_table_like(lines[i].text.strip()):
                    group.append(lines[i])
                    i += 1
                self._append_chunks(chunks, group, "table_like", current_section, source_metadata)
                continue

            if self._is_update_notice(stripped):
                flush_paragraph()
                group, i = self._collect_special_block(lines, i, self._is_update_notice)
                self._append_chunks(
                    chunks,
                    group,
                    "update_notice",
                    current_section,
                    source_metadata,
                )
                continue

            if self._is_policy_or_rule(stripped):
                flush_paragraph()
                group, i = self._collect_special_block(lines, i, self._is_policy_or_rule)
                self._append_chunks(
                    chunks,
                    group,
                    "numbered_rule",
                    current_section,
                    source_metadata,
                )
                continue

            pending_paragraph.append(line)
            i += 1

        flush_paragraph()
        self._renumber_chunks(chunks)
        return chunks

    def chunk(
        self,
        text: str,
        source_file: str = "",
        metadata: dict | None = None,
    ) -> list[dict]:
        """Compatibility wrapper mirroring TextChunker.chunk inputs."""
        merged = dict(metadata or {})
        if source_file:
            merged.setdefault("source_file", source_file)
        return self.split_text(text, metadata=merged)

    def _append_chunks(
        self,
        chunks: list[dict],
        lines: list[_Line],
        chunk_type: str,
        section_title: str,
        source_metadata: dict[str, Any],
    ) -> None:
        if not lines:
            return
        content = "\n".join(line.text.strip() for line in lines if line.text.strip())
        if not content:
            return
        if section_title and chunk_type in {"paragraph", "numbered_rule", "table_like", "faq_pair"}:
            content = f"{section_title}\n{content}"

        line_start = min(line.number for line in lines)
        line_end = max(line.number for line in lines)
        char_start = min(line.char_start for line in lines)
        char_end = max(line.char_end for line in lines)

        if len(content) > self.max_chunk_chars:
            self._append_fallback_chunks(
                chunks,
                content,
                source_metadata,
                line_start=line_start,
                line_end=line_end,
                char_start=char_start,
                section_title=section_title,
                original_chunk_type=chunk_type,
            )
            return

        chunks.append(
            {
                "content": content,
                "metadata": self._build_metadata(
                    source_metadata,
                    content,
                    chunk_type=chunk_type,
                    line_start=line_start,
                    line_end=line_end,
                    char_start=char_start,
                    char_end=char_end,
                    section_title=section_title,
                ),
            }
        )

    def _append_fallback_chunks(
        self,
        chunks: list[dict],
        content: str,
        source_metadata: dict[str, Any],
        *,
        line_start: int,
        line_end: int,
        char_start: int,
        section_title: str,
        original_chunk_type: str,
    ) -> None:
        fallback = TextChunker(
            chunk_size=self.fallback_chunk_size,
            chunk_overlap=min(self.fallback_chunk_overlap, self.fallback_chunk_size - 1),
        )
        offset = 0
        for text_chunk in fallback.chunk(content, metadata=source_metadata):
            chunk_content = text_chunk.content
            local_pos = content.find(chunk_content, offset)
            if local_pos < 0:
                local_pos = offset
            offset = local_pos + max(len(chunk_content), 1)
            chunks.append(
                {
                    "content": chunk_content,
                    "metadata": self._build_metadata(
                        source_metadata,
                        chunk_content,
                        chunk_type="fallback",
                        line_start=line_start,
                        line_end=line_end,
                        char_start=char_start + local_pos,
                        char_end=char_start + local_pos + len(chunk_content),
                        section_title=section_title,
                        original_chunk_type=original_chunk_type,
                    ),
                }
            )

    @staticmethod
    def _scan_lines(text: str) -> list[_Line]:
        lines: list[_Line] = []
        offset = 0
        for number, raw_line in enumerate(text.splitlines(keepends=True), start=1):
            body = raw_line.rstrip("\r\n")
            lines.append(
                _Line(
                    number=number,
                    text=body,
                    char_start=offset,
                    char_end=offset + len(body),
                )
            )
            offset += len(raw_line)
        if text and not text.endswith(("\n", "\r")) and not lines:
            lines.append(_Line(number=1, text=text, char_start=0, char_end=len(text)))
        return lines

    @staticmethod
    def _collect_special_block(
        lines: list[_Line],
        start: int,
        predicate,
    ) -> tuple[list[_Line], int]:
        group = [lines[start]]
        i = start + 1
        while i < len(lines):
            stripped = lines[i].text.strip()
            if not stripped or SmartChunker._is_heading(stripped):
                break
            if predicate(stripped):
                group.append(lines[i])
                i += 1
                continue
            break
        return group, i

    @staticmethod
    def _is_heading(text: str) -> bool:
        if not text:
            return False
        if HEADING_RE.search(text):
            return True
        return len(text) <= 40 and text.endswith((":", "：")) and "|" not in text

    @staticmethod
    def _is_faq_question(text: str) -> bool:
        return bool(FAQ_Q_RE.search(text))

    @staticmethod
    def _is_faq_answer(text: str) -> bool:
        return bool(FAQ_A_RE.search(text))

    @staticmethod
    def _is_fact_line(text: str) -> bool:
        return bool(FACT_ID_RE.search(text) or MARKER_RE.search(text))

    @staticmethod
    def _is_table_like(text: str) -> bool:
        if not text:
            return False
        separator_count = text.count("|") + text.count("\t")
        if separator_count >= 2:
            return True
        has_table_keyword = any(keyword in text for keyword in TABLE_KEYWORDS)
        has_column_spacing = bool(re.search(r"\S\s{2,}\S", text))
        return has_table_keyword and has_column_spacing

    @staticmethod
    def _is_policy_or_rule(text: str) -> bool:
        return bool(NUMBERED_RULE_RE.search(text) or any(keyword in text for keyword in POLICY_KEYWORDS))

    @staticmethod
    def _is_update_notice(text: str) -> bool:
        return any(keyword in text for keyword in UPDATE_KEYWORDS) and any(
            marker in text for marker in ("目标", "库存", "优先级", "生效", "更新", "公告")
        )

    @staticmethod
    def _extract_fact_ids(content: str) -> list[str]:
        return list(dict.fromkeys(match.strip() for match in FACT_ID_RE.findall(content)))

    @staticmethod
    def _extract_markers(content: str) -> list[str]:
        return list(dict.fromkeys(match.strip() for match in MARKER_RE.findall(content)))

    @staticmethod
    def _detect_numbers(content: str) -> list[str]:
        return list(dict.fromkeys(match.group(0) for match in NUMBER_RE.finditer(content)))

    def _build_metadata(
        self,
        source_metadata: dict[str, Any],
        content: str,
        *,
        chunk_type: str,
        line_start: int,
        line_end: int,
        char_start: int,
        char_end: int,
        section_title: str,
        original_chunk_type: str | None = None,
    ) -> dict:
        metadata: dict[str, Any] = {
            "chunk_type": chunk_type,
            "chunk_index": 0,
            "line_start": line_start,
            "line_end": line_end,
            "char_start": char_start,
            "char_end": char_end,
            "section_title": section_title,
            "fact_ids": self._extract_fact_ids(content),
            "markers": self._extract_markers(content),
            "has_table_like_rows": self._is_table_like(content),
            "has_policy_keywords": any(keyword in content for keyword in POLICY_KEYWORDS),
            "has_update_priority": "优先级" in content or "优先" in content,
            "detected_numbers": self._detect_numbers(content),
        }
        if original_chunk_type:
            metadata["original_chunk_type"] = original_chunk_type

        for key in ("source_file", "document_id", "parent_document_id"):
            if source_metadata.get(key):
                metadata[key] = source_metadata[key]

        return metadata

    @staticmethod
    def _renumber_chunks(chunks: list[dict]) -> None:
        total = len(chunks)
        for index, chunk in enumerate(chunks):
            chunk["metadata"]["chunk_index"] = index
            chunk["metadata"]["total_chunks"] = total
