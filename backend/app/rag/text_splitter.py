"""Text chunking utilities for RAG ingestion.

LangChain's RecursiveCharacterTextSplitter is used when available. Production
Docker images should still work without that optional dependency, so this module
includes a small recursive fallback splitter with the same basic behavior.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    total_chunks: int
    source_file: str = ""
    source_page: int = 0
    metadata: dict = field(default_factory=dict)
    chunk_id: str = ""

    def __post_init__(self) -> None:
        if not self.chunk_id:
            seed = f"{self.source_file}:{self.chunk_index}:{self.content[:80]}"
            self.chunk_id = hashlib.md5(
                seed.encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest()


class _FallbackRecursiveSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int, separators: list[str]):
        self.chunk_size = max(int(chunk_size), 1)
        self.chunk_overlap = max(min(int(chunk_overlap), self.chunk_size - 1), 0)
        self.separators = separators

    def split_text(self, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []
        pieces = self._split_recursive(normalized, self.separators)
        chunks: list[str] = []
        current = ""

        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            candidate = piece if not current else f"{current}\n{piece}"
            if len(candidate) <= self.chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = piece

        if current:
            chunks.append(current)

        return self._apply_overlap(chunks)

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text]
        if not separators:
            return [
                text[i : i + self.chunk_size]
                for i in range(0, len(text), self.chunk_size)
            ]

        separator = separators[0]
        if separator and separator in text:
            parts = text.split(separator)
            result: list[str] = []
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if len(part) <= self.chunk_size:
                    result.append(part)
                else:
                    result.extend(self._split_recursive(part, separators[1:]))
            return result

        return self._split_recursive(text, separators[1:])

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        overlapped = [chunks[0]]
        for chunk in chunks[1:]:
            prefix = overlapped[-1][-self.chunk_overlap :]
            combined = f"{prefix}{chunk}"
            if len(combined) > self.chunk_size:
                combined = combined[-self.chunk_size :]
            overlapped.append(combined)
        return overlapped


class TextChunker:
    """Chunk text for vector indexing."""

    DEFAULT_SEPARATORS = [
        "\n\n",
        "\n",
        "\u3002",
        "\uff01",
        "\uff1f",
        "\uff1b",
        ". ",
        "! ",
        "? ",
        "; ",
        " ",
        "",
    ]

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _get_splitter(self):
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=self.DEFAULT_SEPARATORS,
            )
        except ImportError:
            try:
                from langchain.text_splitter import RecursiveCharacterTextSplitter

                return RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                    separators=self.DEFAULT_SEPARATORS,
                )
            except ImportError:
                logger.info("text_splitter_using_builtin_fallback")
                return _FallbackRecursiveSplitter(
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                    separators=self.DEFAULT_SEPARATORS,
                )

    def chunk(
        self,
        text: str,
        source_file: str = "",
        metadata: dict | None = None,
    ) -> list[TextChunk]:
        splitter = self._get_splitter()
        raw_chunks = [chunk.strip() for chunk in splitter.split_text(text or "") if chunk.strip()]
        total = len(raw_chunks)

        return [
            TextChunk(
                content=chunk_text,
                chunk_index=i,
                total_chunks=total,
                source_file=source_file,
                metadata=metadata or {},
            )
            for i, chunk_text in enumerate(raw_chunks)
        ]
