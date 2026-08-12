"""
上下文组装器 (Context Assembler)
================================

依据 4.docx《AI应用系统设计》中关于上下文分区的设计要求实现。

设计要求：
  - RAG、Memory、Tool 结果不得混入同一个"背景上下文"中，必须清晰分区。
  - Memory 上下文 → "用户背景区" (USER_BACKGROUND)
  - RAG 上下文   → "证据资料区" (EVIDENCE)
  - Tool 结果    → "工具结果区" (TOOL_RESULT)
  - 每个区域使用 XML 风格的边界标记明确分隔。
  - 组装顺序：权限过滤 → Memory → RAG → Tool 结果。
  - 在检索前进行权限范围过滤。

核心流程：
  1. 权限过滤：根据当前用户的权限范围 (active_permissions) 过滤碎片。
  2. 按区域分组：Memory / RAG / Tool 分别归入对应区域。
  3. 去重：在同一区域内，移除内容高度重叠的碎片。
  4. 组装：按 Memory → RAG → Tool 的顺序拼接，每个区域包裹边界标记。
  5. 令牌预算控制：超出预算时，按优先级（置信度）裁剪低优先级碎片。
  6. 返回结构化结果 ContextAssemblyResult。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 枚举 & 数据结构
# ---------------------------------------------------------------------------


class ContextZone(Enum):
    """
    上下文分区枚举。

    依据 4.docx 设计要求，将上下文划分为四个独立区域：
      - USER_BACKGROUND: 用户背景区 —— 存放 Memory 上下文（用户画像、历史偏好、行为记录）。
      - EVIDENCE:       证据资料区 —— 存放 RAG 检索到的知识库片段。
      - TOOL_RESULT:    工具结果区 —— 存放工具调用返回的结果。
      - SYSTEM_INSTRUCTION: 系统指令区 —— 存放系统级提示词。
    """

    USER_BACKGROUND = "user_background"
    EVIDENCE = "evidence"
    TOOL_RESULT = "tool_result"
    SYSTEM_INSTRUCTION = "system_instruction"


# ---------------------------------------------------------------------------
# 每个区域对应的 XML 边界标记
# ---------------------------------------------------------------------------

_ZONE_BOUNDARY_TEMPLATES: dict[ContextZone, str] = {
    ContextZone.USER_BACKGROUND: "<!-- USER_BACKGROUND_START -->\n{content}\n<!-- USER_BACKGROUND_END -->",
    ContextZone.EVIDENCE: "<!-- EVIDENCE_START -->\n{content}\n<!-- EVIDENCE_END -->",
    ContextZone.TOOL_RESULT: "<!-- TOOL_RESULT_START -->\n{content}\n<!-- TOOL_RESULT_END -->",
    ContextZone.SYSTEM_INSTRUCTION: "<!-- SYSTEM_INSTRUCTION_START -->\n{content}\n<!-- SYSTEM_INSTRUCTION_END -->",
}

# 默认令牌预算（字符估算系数：中英文混合场景下约 2.5 字符 / token）
_DEFAULT_TOKEN_BUDGET = 8000
_CHARS_PER_TOKEN = 2.5


@dataclass
class ContextFragment:
    """
    上下文碎片。

    表示一个独立的上下文信息单元，由上游系统（Memory / RAG / Tool）产出。

    Attributes:
        zone:             所属上下文分区。
        content:          碎片文本内容。
        source:           来源标识（如 "memory:user_profile", "rag:doc_123", "tool:weather_api"）。
        timestamp:        碎片产生时间戳。
        confidence:       置信度 (0.0 ~ 1.0)，用于优先级排序和裁剪决策。
        permission_scope: 权限范围标签，用于权限过滤（如 {"basic", "vip", "admin"}）。
    """

    zone: ContextZone
    content: str
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.5
    permission_scope: set[str] = field(default_factory=set)

    def __post_init__(self):
        """合法性校验。"""
        if not isinstance(self.zone, ContextZone):
            raise TypeError(f"zone must be ContextZone, got {type(self.zone)}")
        if not isinstance(self.content, str):
            raise TypeError(f"content must be str, got {type(self.content)}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    def estimated_tokens(self) -> int:
        """估算该碎片占用的 token 数。"""
        if not self.content:
            return 0
        return max(1, int(len(self.content) / _CHARS_PER_TOKEN))


@dataclass
class ZoneStats:
    """
    单个分区的统计信息。

    Attributes:
        zone:            分区名称。
        fragment_count:  原始碎片数量。
        kept_count:      最终保留的碎片数量。
        estimated_tokens: 该分区估算 token 数。
    """

    zone: ContextZone
    fragment_count: int = 0
    kept_count: int = 0
    estimated_tokens: int = 0


@dataclass
class ContextAssemblyResult:
    """
    上下文组装结果。

    依据 4.docx 设计要求，上下文组装完成后返回结构化结果，
    包含组装后的完整文本及各分区的元数据，便于上游 LLM 调用方使用。

    Attributes:
        assembled_text:       组装后的完整上下文文本，各区域已包裹边界标记。
        zone_stats:           各分区统计信息列表。
        total_tokens_estimated: 估算的总 token 数。
        trimmed_fragments:    因超出 token 预算而被裁剪的碎片列表。
    """

    assembled_text: str
    zone_stats: list[ZoneStats] = field(default_factory=list)
    total_tokens_estimated: int = 0
    trimmed_fragments: list[ContextFragment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ContextAssembler
# ---------------------------------------------------------------------------


class ContextAssembler:
    """
    上下文组装器。

    依据 4.docx《AI应用系统设计》中关于上下文分区的设计要求实现。
    负责将 Memory、RAG、Tool 三种来源的上下文碎片按以下流程组装：

      1. 权限过滤 —— 根据 active_permissions 过滤掉无权限访问的碎片。
      2. 按区域分组 —— 将碎片按 zone 分组。
      3. 去重 —— 在同一区域内去除内容高度重叠的碎片。
      4. 有序组装 —— 按 Memory → RAG → Tool 顺序拼接，每区包裹 XML 边界标记。
      5. 令牌预算控制 —— 超出预算时，按置信度优先级裁剪低价值碎片。

    Usage::

        assembler = ContextAssembler(token_budget=8000)
        result = assembler.assemble(
            memory_fragments=memory_list,
            rag_fragments=rag_list,
            tool_fragments=tool_list,
            system_instruction="You are a helpful assistant.",
            active_permissions={"basic", "vip"},
        )
        print(result.assembled_text)
    """

    # ------------------------------------------------------------------
    # 去重阈值：两段文本的 Jaccard 相似度超过此值即视为重复
    # ------------------------------------------------------------------
    _DEDUP_SIMILARITY_THRESHOLD = 0.85

    def __init__(self, token_budget: int = _DEFAULT_TOKEN_BUDGET):
        """
        Args:
            token_budget: 最大 token 预算，超出时将触发裁剪。
        """
        self.token_budget = token_budget
        logger.info("ContextAssembler initialized with token_budget=%d", self.token_budget)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def assemble(
        self,
        memory_fragments: list[ContextFragment] | None = None,
        rag_fragments: list[ContextFragment] | None = None,
        tool_fragments: list[ContextFragment] | None = None,
        system_instruction: str | None = None,
        active_permissions: set[str] | None = None,
    ) -> ContextAssemblyResult:
        """
        执行上下文组装。

        依据 4.docx 设计，组装顺序严格为：权限过滤 → Memory → RAG → Tool。

        Args:
            memory_fragments:   Memory 上下文碎片列表（用户背景区）。
            rag_fragments:      RAG 检索碎片列表（证据资料区）。
            tool_fragments:     Tool 调用结果碎片列表（工具结果区）。
            system_instruction: 系统指令文本（可选，放入系统指令区）。
            active_permissions: 当前用户拥有的权限范围标签集合。

        Returns:
            ContextAssemblyResult: 组装结果。
        """
        memory_fragments = memory_fragments or []
        rag_fragments = rag_fragments or []
        tool_fragments = tool_fragments or []

        logger.info(
            "Starting context assembly | memory=%d rag=%d tool=%d budget=%d",
            len(memory_fragments),
            len(rag_fragments),
            len(tool_fragments),
            self.token_budget,
        )

        # --- 第 1 步：权限过滤 ---
        memory_fragments = self._filter_by_permission(memory_fragments, active_permissions)
        rag_fragments = self._filter_by_permission(rag_fragments, active_permissions)
        tool_fragments = self._filter_by_permission(tool_fragments, active_permissions)

        # --- 第 2 步：按区域分组 ---
        zone_fragments: dict[ContextZone, list[ContextFragment]] = {
            ContextZone.USER_BACKGROUND: memory_fragments,
            ContextZone.EVIDENCE: rag_fragments,
            ContextZone.TOOL_RESULT: tool_fragments,
        }

        # --- 第 3 步：去重 ---
        for zone, fragments in zone_fragments.items():
            zone_fragments[zone] = self._deduplicate(fragments)

        # --- 第 4 步：组装（按 Memory → RAG → Tool 顺序）---
        assembled_parts: list[str] = []
        zone_stats: list[ZoneStats] = []
        trimmed_fragments: list[ContextFragment] = []

        # 系统指令区（可选）
        if system_instruction:
            si_fragment = ContextFragment(
                zone=ContextZone.SYSTEM_INSTRUCTION,
                content=system_instruction,
                source="system",
                confidence=1.0,
            )
            wrapped = self._wrap_zone(ContextZone.SYSTEM_INSTRUCTION, [si_fragment])
            assembled_parts.append(wrapped)
            zone_stats.append(
                ZoneStats(
                    zone=ContextZone.SYSTEM_INSTRUCTION,
                    fragment_count=1,
                    kept_count=1,
                    estimated_tokens=si_fragment.estimated_tokens(),
                )
            )

        # 组装顺序: Memory → RAG → Tool
        assembly_order = [
            ContextZone.USER_BACKGROUND,
            ContextZone.EVIDENCE,
            ContextZone.TOOL_RESULT,
        ]

        for zone in assembly_order:
            fragments = zone_fragments[zone]
            kept, trimmed = self._apply_token_budget(fragments, self.token_budget)
            wrapped = self._wrap_zone(zone, kept)
            assembled_parts.append(wrapped)
            trimmed_fragments.extend(trimmed)

            zone_tokens = sum(f.estimated_tokens() for f in kept)
            zone_stats.append(
                ZoneStats(
                    zone=zone,
                    fragment_count=len(fragments),
                    kept_count=len(kept),
                    estimated_tokens=zone_tokens,
                )
            )

        # --- 第 5 步：全局令牌预算控制 ---
        assembled_text = "\n\n".join(part for part in assembled_parts if part)
        total_tokens = self._estimate_tokens(assembled_text)

        if total_tokens > self.token_budget:
            logger.warning(
                "Assembled context exceeds budget (%d > %d), applying final trim",
                total_tokens,
                self.token_budget,
            )
            assembled_text, final_trimmed = self._trim_text_to_budget(
                assembled_text, self.token_budget
            )
            trimmed_fragments.extend(final_trimmed)
            total_tokens = self._estimate_tokens(assembled_text)

        result = ContextAssemblyResult(
            assembled_text=assembled_text,
            zone_stats=zone_stats,
            total_tokens_estimated=total_tokens,
            trimmed_fragments=trimmed_fragments,
        )

        logger.info(
            "Context assembly complete | total_tokens=%d zones=%d trimmed=%d",
            total_tokens,
            len(zone_stats),
            len(trimmed_fragments),
        )

        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _filter_by_permission(
        self,
        fragments: list[ContextFragment],
        active_permissions: set[str] | None,
    ) -> list[ContextFragment]:
        """
        权限过滤。

        若碎片定义了 permission_scope 且 active_permissions 不为空，
        则只保留权限范围与 active_permissions 有交集的碎片。
        无 permission_scope 的碎片视为公开，始终保留。
        """
        if active_permissions is None:
            # 未指定权限范围时不进行过滤
            return fragments

        kept: list[ContextFragment] = []
        for f in fragments:
            if not f.permission_scope:
                # 无权限限制，公开可访问
                kept.append(f)
            elif f.permission_scope & active_permissions:
                # 权限范围有交集
                kept.append(f)
            else:
                logger.debug(
                    "Fragment filtered by permission | source=%s required=%s available=%s",
                    f.source,
                    f.permission_scope,
                    active_permissions,
                )
        return kept

    def _deduplicate(self, fragments: list[ContextFragment]) -> list[ContextFragment]:
        """
        同一区域内去重。

        使用基于文本指纹的相似度检测：
        1. 对每个碎片计算内容指纹（normalized shingle hash）。
        2. 若两碎片指纹 Jaccard 相似度超过阈值，保留置信度更高的。
        3. 置信度相同时保留先出现的。
        """
        if len(fragments) <= 1:
            return list(fragments)

        # 计算每个碎片的 shingle 指纹集合
        fingerprints: list[set[str]] = [self._compute_shingle_set(f.content) for f in fragments]
        kept_indices: list[int] = []
        removed = set()

        for i in range(len(fragments)):
            if i in removed:
                continue
            for j in range(i + 1, len(fragments)):
                if j in removed:
                    continue
                similarity = self._jaccard_similarity(fingerprints[i], fingerprints[j])
                if similarity >= self._DEDUP_SIMILARITY_THRESHOLD:
                    # 决定保留哪个
                    if fragments[i].confidence >= fragments[j].confidence:
                        removed.add(j)
                    else:
                        removed.add(i)
                        break  # i 被移除，不再与后续比较

        kept_indices = [idx for idx in range(len(fragments)) if idx not in removed]
        deduped = [fragments[idx] for idx in kept_indices]

        if len(removed) > 0:
            logger.debug(
                "Deduplication removed %d fragments from zone",
                len(removed),
            )

        return deduped

    def _apply_token_budget(
        self,
        fragments: list[ContextFragment],
        budget: int,
    ) -> tuple:
        """
        按令牌预算裁剪碎片。

        策略：
        1. 按置信度降序排列（高置信度优先级高）。
        2. 从头开始累加 token，超出预算后停止。
        3. 被裁剪的碎片单独返回，供上层记录。
        """
        if not fragments:
            return [], []

        # 按置信度降序排列
        sorted_fragments = sorted(fragments, key=lambda f: f.confidence, reverse=True)

        kept: list[ContextFragment] = []
        trimmed: list[ContextFragment] = []
        current_tokens = 0

        for f in sorted_fragments:
            frag_tokens = f.estimated_tokens()
            if current_tokens + frag_tokens <= budget:
                kept.append(f)
                current_tokens += frag_tokens
            else:
                trimmed.append(f)

        # 恢复原始顺序
        original_order = {id(f): i for i, f in enumerate(fragments)}
        kept.sort(key=lambda f: original_order[id(f)])

        if trimmed:
            logger.debug(
                "Token budget trim: kept=%d trimmed=%d tokens=%d/%d",
                len(kept),
                len(trimmed),
                current_tokens,
                budget,
            )

        return kept, trimmed

    def _wrap_zone(self, zone: ContextZone, fragments: list[ContextFragment]) -> str:
        """
        用 XML 边界标记包裹一个区域的所有碎片。

        依据 4.docx 设计要求，每个区域必须有清晰的边界标记。
        """
        if not fragments:
            return ""

        # 拼接碎片内容，碎片之间用空行分隔
        content = "\n\n".join(f.content for f in fragments)
        template = _ZONE_BOUNDARY_TEMPLATES.get(
            zone, "<!-- {zone} -->\n{content}\n<!-- /{zone} -->"
        )
        return template.format(content=content)

    def _trim_text_to_budget(self, text: str, budget: int) -> tuple:
        """
        当组装后的完整文本仍超出预算时，做最终裁剪。

        策略：按区域边界标记分段，从工具结果区开始向前裁剪，
        优先保留用户背景区和证据资料区。
        """
        estimated = self._estimate_tokens(text)
        if estimated <= budget:
            return text, []

        trimmed_fragments: list[ContextFragment] = []

        # 按区域边界标记拆分
        zone_pattern = re.compile(
            r"<!-- (USER_BACKGROUND|EVIDENCE|TOOL_RESULT|SYSTEM_INSTRUCTION)_START -->"
            r"(.*?)"
            r"<!-- \1_END -->",
            re.DOTALL,
        )

        parts = []
        # 找出所有区域块及它们之间的分隔符
        matches = list(zone_pattern.finditer(text))
        last_end = 0

        for m in matches:
            # 区域之间的分隔文本
            if m.start() > last_end:
                parts.append(("separator", text[last_end : m.start()]))
            parts.append(("zone", m.group(0), m.group(1), m.group(2)))
            last_end = m.end()

        if last_end < len(text):
            parts.append(("separator", text[last_end:]))

        # 从后往前裁剪：优先丢弃 TOOL_RESULT，再 EVIDENCE，最后 USER_BACKGROUND
        zone_discard_order = ["TOOL_RESULT", "EVIDENCE", "USER_BACKGROUND"]
        current_text = text

        for discard_zone in zone_discard_order:
            if self._estimate_tokens(current_text) <= budget:
                break
            # 查找并移除该区域
            current_text = self._remove_zone_from_text(current_text, discard_zone)
            # 记录被裁剪的碎片
            trimmed_fragments.append(
                ContextFragment(
                    zone=ContextZone(discard_zone.lower()),
                    content=f"[trimmed: {discard_zone} zone exceeded budget]",
                    source="context_assembler",
                    confidence=0.0,
                )
            )

        return current_text, trimmed_fragments

    def _remove_zone_from_text(self, text: str, zone_name: str) -> str:
        """从文本中移除指定区域块。"""
        pattern = re.compile(
            rf"<!-- {zone_name}_START -->.*?<!-- {zone_name}_END -->",
            re.DOTALL,
        )
        # 移除该区域块及其前后的多余空白
        result = pattern.sub("", text)
        # 清理多余的连续空行
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算文本的 token 数（字符数 / 缩放系数）。"""
        if not text:
            return 0
        return max(1, int(len(text) / _CHARS_PER_TOKEN))

    @staticmethod
    def _compute_shingle_set(text: str, shingle_size: int = 3) -> set[str]:
        """
        计算文本的 shingle（字符 n-gram）哈希指纹集合。

        用于去重时的相似度计算。
        """
        if not text:
            return set()
        # 标准化：去除多余空白，统一小写
        normalized = " ".join(text.lower().split())
        if len(normalized) < shingle_size:
            return {hashlib.md5(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()}
        shingles = set()
        for i in range(len(normalized) - shingle_size + 1):
            shingle = normalized[i : i + shingle_size]
            shingles.add(hashlib.md5(shingle.encode("utf-8"), usedforsecurity=False).hexdigest())
        return shingles

    @staticmethod
    def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
        """计算两个集合的 Jaccard 相似度。"""
        if not set_a and not set_b:
            return 1.0
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0
