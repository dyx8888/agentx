"""
安全防护模块 (Security Guard Module)
=====================================

基于 4.docx（AI应用系统设计）中定义的安全需求，实现以下核心功能：
1. PII脱敏（PII Desensitization）
2. Prompt注入防护（Prompt Injection Prevention）
3. 敏感内容预处理（Sensitive Content Preprocessing）
4. 上下文分区（Context Partitioning）

参考文档：4.docx - AI应用系统设计 - 安全防护章节
"""

import re
import json
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# 数据类定义
# =============================================================================

@dataclass
class PIIDetectionResult:
    """PII检测结果"""
    has_pii: bool = False
    items: List[Dict[str, Any]] = field(default_factory=list)
    # 每个 item 结构: {"type": "phone"|"id_card"|"bank_card"|"email"|"address",
    #                  "start": int, "end": int, "original": str}


@dataclass
class InjectionDetectionResult:
    """注入检测结果"""
    is_injection: bool = False
    risk_score: float = 0.0  # 0.0 ~ 1.0
    detected_patterns: List[str] = field(default_factory=list)
    # 每个 pattern: 匹配到的注入模式名称


@dataclass
class SensitiveContentResult:
    """敏感内容检测结果"""
    has_sensitive: bool = False
    categories: List[str] = field(default_factory=list)
    # 如: "violence", "hate_speech", "sexual_content", "illegal_info"


@dataclass
class SecurityCheckResult:
    """安全检查综合结果"""
    safe: bool = True
    pii_result: Optional[PIIDetectionResult] = None
    injection_result: Optional[InjectionDetectionResult] = None
    sensitive_result: Optional[SensitiveContentResult] = None
    sanitized_text: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# PII检测器 (PII Detector)
# =============================================================================

class PIIDetector:
    """
    PII（个人身份信息）检测与脱敏器。

    根据 4.docx 安全设计要求，检测并脱敏以下类型的敏感信息：
    - 中国手机号码（11位）
    - 身份证号码（18位）
    - 银行卡号（16-19位）
    - 电子邮箱地址
    - 中国地址信息

    用法:
        detector = PIIDetector()
        masked_text = detector.mask_pii("我的手机号是13800138000")
        results = detector.detect_pii("我的手机号是13800138000")
    """

    # --- 正则模式定义 ---

    # 中国手机号：1开头，第二位3-9，共11位
    PHONE_PATTERN: re.Pattern = re.compile(
        r'(?<!\d)(1[3-9]\d{9})(?!\d)'
    )

    # 身份证号：18位数字，最后一位可能是X/x
    ID_CARD_PATTERN: re.Pattern = re.compile(
        r'(?<!\d)(\d{17}[\dXx])(?!\d)'
    )

    # 银行卡号：16-19位连续数字
    BANK_CARD_PATTERN: re.Pattern = re.compile(
        r'(?<!\d)(\d{16,19})(?!\d)'
    )

    # 电子邮箱
    EMAIL_PATTERN: re.Pattern = re.compile(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    )

    # 中国地址：省/市/区/路/街/号/栋/单元/室 等关键词组合
    ADDRESS_PATTERN: re.Pattern = re.compile(
        r'(?:'
        r'(?:[\u4e00-\u9fff]{2,}(?:省|自治区|市|特别行政区))'
        r'[\u4e00-\u9fff]{0,}(?:市|区|县|镇|乡|街道|路|街|巷|弄|道|村|里)'
        r'[\u4e00-\u9fff\d\-\号栋楼座单元室层]*'
        r')'
    )

    # 脱敏占位符映射
    MASK_PLACEHOLDERS: Dict[str, str] = {
        "phone": "[PHONE_MASKED]",
        "id_card": "[ID_CARD_MASKED]",
        "bank_card": "[BANK_CARD_MASKED]",
        "email": "[EMAIL_MASKED]",
        "address": "[ADDRESS_MASKED]",
    }

    def __init__(self) -> None:
        logger.info("PIIDetector 初始化完成")

    def detect_pii(self, text: str) -> PIIDetectionResult:
        """
        检测文本中的PII信息，返回检测到的类型和位置。

        Args:
            text: 待检测的文本

        Returns:
            PIIDetectionResult: 包含检测结果的详细信息
        """
        result = PIIDetectionResult()

        if not text:
            return result

        # 按优先级检测：先检测长模式（地址），再检测短模式
        # 使用已检测区域避免重复标记
        covered_ranges: List[Tuple[int, int]] = []

        def _is_covered(start: int, end: int) -> bool:
            for cs, ce in covered_ranges:
                if start >= cs and end <= ce:
                    return True
            return False

        # 1. 检测地址（最长模式优先）
        for match in self.ADDRESS_PATTERN.finditer(text):
            if not _is_covered(match.start(), match.end()):
                result.items.append({
                    "type": "address",
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(),
                })
                covered_ranges.append((match.start(), match.end()))

        # 2. 检测身份证号
        for match in self.ID_CARD_PATTERN.finditer(text):
            if not _is_covered(match.start(), match.end()):
                result.items.append({
                    "type": "id_card",
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(),
                })
                covered_ranges.append((match.start(), match.end()))

        # 3. 检测银行卡号（在身份证号之后检测，避免18位身份证号被误判为银行卡）
        for match in self.BANK_CARD_PATTERN.finditer(text):
            if not _is_covered(match.start(), match.end()):
                result.items.append({
                    "type": "bank_card",
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(),
                })
                covered_ranges.append((match.start(), match.end()))

        # 4. 检测手机号
        for match in self.PHONE_PATTERN.finditer(text):
            if not _is_covered(match.start(), match.end()):
                result.items.append({
                    "type": "phone",
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(),
                })
                covered_ranges.append((match.start(), match.end()))

        # 5. 检测邮箱
        for match in self.EMAIL_PATTERN.finditer(text):
            if not _is_covered(match.start(), match.end()):
                result.items.append({
                    "type": "email",
                    "start": match.start(),
                    "end": match.end(),
                    "original": match.group(),
                })
                covered_ranges.append((match.start(), match.end()))

        result.has_pii = len(result.items) > 0
        if result.has_pii:
            logger.info(
                "PII检测到 %d 处敏感信息: %s",
                len(result.items),
                [item["type"] for item in result.items],
            )

        return result

    def mask_pii(self, text: str) -> str:
        """
        对文本中的PII信息进行脱敏处理，替换为占位符。

        Args:
            text: 待脱敏的文本

        Returns:
            str: 脱敏后的文本
        """
        if not text:
            return text

        detection = self.detect_pii(text)
        if not detection.has_pii:
            return text

        # 按位置从后往前替换，避免索引偏移
        sorted_items = sorted(detection.items, key=lambda x: x["start"], reverse=True)
        masked_text = text

        for item in sorted_items:
            pii_type = item["type"]
            placeholder = self.MASK_PLACEHOLDERS.get(pii_type, "[MASKED]")
            masked_text = (
                masked_text[:item["start"]]
                + placeholder
                + masked_text[item["end"]:]
            )

        logger.debug("PII脱敏完成，共处理 %d 处", len(sorted_items))
        return masked_text

    def mask_pii_partial(self, text: str) -> str:
        """
        部分脱敏：保留部分信息以便识别，中间部分用星号替代。
        例如：138****8000, 3101****1234****

        Args:
            text: 待脱敏的文本

        Returns:
            str: 部分脱敏后的文本
        """
        if not text:
            return text

        detection = self.detect_pii(text)
        if not detection.has_pii:
            return text

        sorted_items = sorted(detection.items, key=lambda x: x["start"], reverse=True)
        masked_text = text

        for item in sorted_items:
            pii_type = item["type"]
            original = item["original"]

            if pii_type == "phone":
                # 手机号：保留前3后4
                partial = original[:3] + "****" + original[-4:]
            elif pii_type == "id_card":
                # 身份证：保留前4后4
                partial = original[:4] + "**********" + original[-4:]
            elif pii_type == "bank_card":
                # 银行卡：保留前4后4
                partial = original[:4] + "****" + ("*" * (len(original) - 12)) + "****" + original[-4:]
            elif pii_type == "email":
                # 邮箱：保留首字符和域名
                at_idx = original.find("@")
                if at_idx > 0:
                    partial = original[0] + "***" + original[at_idx:]
                else:
                    partial = "***@***"
            elif pii_type == "address":
                # 地址：保留前6个字符
                partial = original[:6] + "****"
            else:
                partial = "****"

            masked_text = (
                masked_text[:item["start"]]
                + partial
                + masked_text[item["end"]:]
            )

        logger.debug("PII部分脱敏完成，共处理 %d 处", len(sorted_items))
        return masked_text


# =============================================================================
# Prompt注入检测器 (Prompt Injection Detector)
# =============================================================================

class PromptInjectionDetector:
    """
    Prompt注入攻击检测器。

    根据 4.docx 安全设计要求，检测以下类型的注入攻击：
    - 指令覆盖（Instruction Override）：试图覆盖系统指令
    - 角色操纵（Role Manipulation）：试图改变AI角色设定
    - 分隔符注入（Delimiter Injection）：试图通过注入分隔符破坏上下文结构
    - 越狱尝试（Jailbreak Attempt）：已知的越狱模式

    用法:
        detector = PromptInjectionDetector()
        result = detector.detect("Ignore all previous instructions...")
        print(f"风险分数: {result.risk_score}")
    """

    # --- 注入模式定义 ---
    # 每条规则: (正则模式, 规则名称, 风险权重)

    INJECTION_PATTERNS: List[Tuple[re.Pattern, str, float]] = [
        # 指令覆盖类
        (
            re.compile(
                r'(?:ignore|forget|disregard|override|bypass)\s+'
                r'(?:all\s+)?(?:previous|above|prior|earlier|system)\s+'
                r'(?:instructions?|prompts?|rules?|directives?|commands?)',
                re.IGNORECASE,
            ),
            "instruction_override",
            0.9,
        ),
        (
            re.compile(
                r'(?:you\s+(?:are|must|should|will|need\s+to)\s+now\s+(?:act|behave|play|roleplay|pretend|follow))',
                re.IGNORECASE,
            ),
            "instruction_override_2",
            0.8,
        ),
        (
            re.compile(
                r'(?:new\s+(?:system\s+)?(?:instructions?|prompts?|rules?|directives?))',
                re.IGNORECASE,
            ),
            "new_instruction_injection",
            0.85,
        ),
        # 角色操纵类
        (
            re.compile(
                r'(?:you\s+are\s+(?:now\s+)?(?:DAN|jailbroken|unrestricted|unfiltered|free|no\s+limits?))',
                re.IGNORECASE,
            ),
            "role_manipulation_dan",
            0.95,
        ),
        (
            re.compile(
                r'(?:pretend\s+(?:you\s+are|to\s+be)|act\s+(?:as|like)\s+(?:a|an)|roleplay\s+(?:as|like))',
                re.IGNORECASE,
            ),
            "role_manipulation_pretend",
            0.7,
        ),
        (
            re.compile(
                r'(?:you\s+are\s+(?:not|no\s+longer)\s+(?:an?\s+)?(?:AI|assistant|language\s+model|chatbot))',
                re.IGNORECASE,
            ),
            "role_denial",
            0.85,
        ),
        # 分隔符注入类
        (
            re.compile(
                r'{system_message}|{user_message}|{assistant_message}|'
                r'<system>|<user>|<assistant>|'
                r'\[SYSTEM\]|\[USER\]|\[ASSISTANT\]|'
                r'<\/?system>|<\/?user>|<\/?assistant>',
                re.IGNORECASE,
            ),
            "delimiter_injection_tags",
            0.8,
        ),
        (
            re.compile(
                r'---\s*SYSTEM\s*---|---\s*USER\s*---|---\s*ASSISTANT\s*---',
                re.IGNORECASE,
            ),
            "delimiter_injection_markdown",
            0.8,
        ),
        # 越狱尝试类
        (
            re.compile(
                r'(?:do\s+anything\s+now|developer\s+mode|god\s+mode|'
                r'jailbreak|no\s+restrictions?|no\s+limitations?|'
                r'no\s+ethical?\s+(?:restrictions?|limitations?|guidelines?))',
                re.IGNORECASE,
            ),
            "jailbreak_attempt",
            0.95,
        ),
        (
            re.compile(
                r'(?:respond\s+as\s+(?:if\s+)?(?:you\s+(?:are|have)\s+)?'
                r'(?:evil|malicious|unethical|immoral|dangerous|toxic|racist|sexist))',
                re.IGNORECASE,
            ),
            "jailbreak_unethical_role",
            0.9,
        ),
        # 中文注入模式
        (
            re.compile(
                r'(?:忽略|无视|忘记|覆盖|绕过)\s*'
                r'(?:所有|之前的|上面的|前面的|系统的)?\s*'
                r'(?:指令|提示|规则|命令|要求)',
            ),
            "instruction_override_cn",
            0.9,
        ),
        (
            re.compile(
                r'(?:从现在开始|从现在起|接下来|现在)\s*'
                r'(?:你是|你作为|你扮演|你假装|你充当)',
            ),
            "role_manipulation_cn",
            0.8,
        ),
        # 上下文泄露尝试
        (
            re.compile(
                r'(?:reveal|show|display|print|output|tell\s+me)\s+'
                r'(?:your\s+)?(?:system\s+(?:prompt|message|instructions?)|'
                r'(?:original|initial|base)\s+(?:prompt|instructions?)|'
                r'hidden\s+(?:instructions?|prompt|rules?))',
                re.IGNORECASE,
            ),
            "context_leak_attempt",
            0.85,
        ),
        (
            re.compile(
                r'(?:泄露|透露|显示|输出|告诉我)\s*'
                r'(?:你的|原始的|初始的|系统的|隐藏的)?\s*'
                r'(?:提示词|指令|系统消息|规则)',
            ),
            "context_leak_attempt_cn",
            0.85,
        ),
    ]

    def __init__(self) -> None:
        logger.info("PromptInjectionDetector 初始化完成")

    def detect(self, text: str) -> InjectionDetectionResult:
        """
        检测输入文本中是否存在Prompt注入攻击。

        Args:
            text: 用户输入文本

        Returns:
            InjectionDetectionResult: 包含风险分数和检测到的模式
        """
        result = InjectionDetectionResult()

        if not text:
            return result

        detected_patterns: List[str] = []
        max_score: float = 0.0

        for pattern, pattern_name, weight in self.INJECTION_PATTERNS:
            if pattern.search(text):
                detected_patterns.append(pattern_name)
                max_score = max(max_score, weight)

        if detected_patterns:
            result.is_injection = True
            result.risk_score = max_score
            result.detected_patterns = detected_patterns
            logger.warning(
                "检测到Prompt注入风险: score=%.2f, patterns=%s",
                max_score,
                detected_patterns,
            )

        return result

    def detect_detailed(self, text: str) -> Dict[str, Any]:
        """
        返回详细的注入检测结果，包括每个匹配到的模式及其位置。

        Args:
            text: 用户输入文本

        Returns:
            Dict: 包含详细检测结果
        """
        result = self.detect(text)
        details: Dict[str, Any] = {
            "is_injection": result.is_injection,
            "risk_score": result.risk_score,
            "detected_patterns": result.detected_patterns,
            "matches": [],
        }

        if not text:
            return details

        for pattern, pattern_name, weight in self.INJECTION_PATTERNS:
            for match in pattern.finditer(text):
                details["matches"].append({
                    "pattern": pattern_name,
                    "weight": weight,
                    "start": match.start(),
                    "end": match.end(),
                    "matched_text": match.group(),
                })

        return details


# =============================================================================
# 敏感内容检测器 (Sensitive Content Detector)
# =============================================================================

class SensitiveContentDetector:
    """
    敏感内容检测器。

    根据 4.docx 安全设计要求，检测以下类型的敏感内容：
    - 暴力内容
    - 仇恨言论
    - 色情/不当内容
    - 违法违规信息
    - 自残/自杀相关内容

    用法:
        detector = SensitiveContentDetector()
        result = detector.detect("某些敏感文本...")
    """

    # 敏感内容关键词分类
    SENSITIVE_KEYWORDS: Dict[str, List[str]] = {
        "violence": [
            "杀人", "杀死", "谋杀", "屠杀", "绑架", "爆炸", "恐怖袭击",
            "kill", "murder", "bomb", "terrorist", "massacre",
        ],
        "hate_speech": [
            "种族歧视", "种族主义", "纳粹", "法西斯",
            "racist", "racism", "nazi", "fascist",
        ],
        "sexual_content": [
            "色情", "淫秽", "裸体", "成人内容",
            "porn", "pornography", "nude", "explicit",
        ],
        "illegal_info": [
            "毒品", "贩毒", "走私", "洗钱", "诈骗", "黑客",
            "drug", "trafficking", "smuggling", "hacking", "fraud",
        ],
        "self_harm": [
            "自杀", "自残", "割腕", "跳楼", "上吊",
            "suicide", "self-harm", "self-harm", "kill myself",
        ],
    }

    def __init__(self) -> None:
        logger.info("SensitiveContentDetector 初始化完成")

    def detect(self, text: str) -> SensitiveContentResult:
        """
        检测文本中的敏感内容。

        Args:
            text: 待检测的文本

        Returns:
            SensitiveContentResult: 包含检测到的敏感内容类别
        """
        result = SensitiveContentResult()

        if not text:
            return result

        text_lower = text.lower()

        for category, keywords in self.SENSITIVE_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    if category not in result.categories:
                        result.categories.append(category)
                    break  # 已匹配到该类别，继续下一个类别

        result.has_sensitive = len(result.categories) > 0
        if result.has_sensitive:
            logger.warning("检测到敏感内容: categories=%s", result.categories)

        return result


# =============================================================================
# 上下文分区器 (Context Partitioner)
# =============================================================================

class ContextPartitioner:
    """
    上下文分区器。

    根据 4.docx 安全设计要求，将不同类型的上下文信息用明确的XML风格边界标记
    进行分区，防止上下文混合/污染。三大分区：

    1. 用户背景区 (user_background) - 包含用户角色、权限、历史行为等
    2. 证据资料区 (rag_evidence) - 包含RAG检索到的外部知识库证据
    3. 工具结果区 (tool_results) - 包含工具调用返回的结果

    参考 4.docx 上下文分区规范。

    用法:
        partitioner = ContextPartitioner()
        user_ctx = partitioner.wrap_user_background("用户是VIP会员")
        evidence_ctx = partitioner.wrap_rag_evidence("检索到的产品信息...")
        tool_ctx = partitioner.wrap_tool_results("工具返回结果...")
    """

    # 分区边界标记
    USER_BACKGROUND_START = '<user_background>'
    USER_BACKGROUND_END = '</user_background>'

    RAG_EVIDENCE_START = '<rag_evidence>'
    RAG_EVIDENCE_END = '</rag_evidence>'

    TOOL_RESULTS_START = '<tool_results>'
    TOOL_RESULTS_END = '</tool_results>'

    # 分区标记（声明性分隔符，不被解析）
    SECTION_BOUNDARY = '---CONTEXT_BOUNDARY---'

    # 允许的分区名称
    VALID_PARTITIONS = {"user_background", "rag_evidence", "tool_results"}

    def __init__(self) -> None:
        logger.info("ContextPartitioner 初始化完成")

    def wrap_user_background(self, content: str) -> str:
        """
        将用户背景信息包装在用户背景区标记中。

        包括：用户角色、权限级别、历史行为摘要、偏好设置等。

        Args:
            content: 用户背景信息内容

        Returns:
            str: 包装后的内容
        """
        return self._wrap(content, self.USER_BACKGROUND_START, self.USER_BACKGROUND_END)

    def wrap_rag_evidence(self, content: str) -> str:
        """
        将RAG检索证据包装在证据资料区标记中。

        包括：从知识库检索到的文档片段、引用来源、相关性评分等。

        Args:
            content: RAG检索到的证据内容

        Returns:
            str: 包装后的内容
        """
        return self._wrap(content, self.RAG_EVIDENCE_START, self.RAG_EVIDENCE_END)

    def wrap_tool_results(self, content: str) -> str:
        """
        将工具调用结果包装在工具结果区标记中。

        包括：API调用返回、数据库查询结果、计算工具输出等。

        Args:
            content: 工具返回的结果内容

        Returns:
            str: 包装后的内容
        """
        return self._wrap(content, self.TOOL_RESULTS_START, self.TOOL_RESULTS_END)

    def build_context(
        self,
        user_background: Optional[str] = None,
        rag_evidence: Optional[str] = None,
        tool_results: Optional[str] = None,
        user_query: Optional[str] = None,
    ) -> str:
        """
        构建完整的分区上下文，将所有上下文组件按正确顺序组装。

        分区顺序：
        1. 用户背景区
        2. 证据资料区
        3. 工具结果区
        4. 用户查询

        Args:
            user_background: 用户背景信息
            rag_evidence: RAG检索证据
            tool_results: 工具调用结果
            user_query: 用户当前查询

        Returns:
            str: 组装后的完整上下文
        """
        parts: List[str] = []

        if user_background:
            parts.append(self.wrap_user_background(user_background))

        if rag_evidence:
            parts.append(self.wrap_rag_evidence(rag_evidence))

        if tool_results:
            parts.append(self.wrap_tool_results(tool_results))

        if user_query:
            parts.append(f"<user_query>{user_query}</user_query>")

        result = "\n\n".join(parts)
        logger.debug("构建上下文分区完成，共 %d 个分区", len(parts))
        return result

    def extract_partition(self, text: str, partition_name: str) -> Optional[str]:
        """
        从已分区的文本中提取指定分区的内容。

        Args:
            text: 已分区的文本
            partition_name: 分区名称，可选 "user_background", "rag_evidence", "tool_results"

        Returns:
            Optional[str]: 提取到的分区内容，如果未找到返回 None
        """
        if partition_name not in self.VALID_PARTITIONS:
            logger.warning("无效的分区名称: %s", partition_name)
            return None

        start_tag = f"<{partition_name}>"
        end_tag = f"</{partition_name}>"

        start_idx = text.find(start_tag)
        end_idx = text.find(end_tag)

        if start_idx == -1 or end_idx == -1:
            return None

        content_start = start_idx + len(start_tag)
        return text[content_start:end_idx].strip()

    def validate_partition_integrity(self, text: str) -> bool:
        """
        验证分区完整性：检查是否存在跨分区内容泄露或标记不匹配。

        Args:
            text: 待验证的文本

        Returns:
            bool: 分区是否完整有效
        """
        # 检查所有开始标记和结束标记是否成对出现
        tags = [
            (self.USER_BACKGROUND_START, self.USER_BACKGROUND_END),
            (self.RAG_EVIDENCE_START, self.RAG_EVIDENCE_END),
            (self.TOOL_RESULTS_START, self.TOOL_RESULTS_END),
        ]

        for start_tag, end_tag in tags:
            start_count = text.count(start_tag)
            end_count = text.count(end_tag)
            if start_count != end_count:
                logger.warning(
                    "分区标记不匹配: %s 出现 %d 次, %s 出现 %d 次",
                    start_tag, start_count, end_tag, end_count,
                )
                return False

        return True

    def _wrap(self, content: str, start_tag: str, end_tag: str) -> str:
        """内部方法：用指定标记包裹内容。"""
        return f"{start_tag}\n{content}\n{end_tag}"


# =============================================================================
# 安全守卫 (Security Guard) - 统一编排
# =============================================================================

class SecurityGuard:
    """
    安全守卫 - 统一编排所有安全检查。

    根据 4.docx 安全设计要求，对AI应用的输入和输出进行全面的安全防护：
    1. PII检测与脱敏
    2. Prompt注入检测
    3. 敏感内容检测
    4. 上下文分区管理

    提供统一的入口方法，简化安全防护的集成。

    用法:
        guard = SecurityGuard()
        # 检查用户输入
        result = guard.check_input("用户输入文本", user_background="VIP用户")
        if result.safe:
            safe_text = result.sanitized_text
            # 使用 safe_text 进行后续处理
        else:
            # 处理安全风险
            print(result.warnings)
    """

    def __init__(
        self,
        pii_detector: Optional[PIIDetector] = None,
        injection_detector: Optional[PromptInjectionDetector] = None,
        sensitive_detector: Optional[SensitiveContentDetector] = None,
        context_partitioner: Optional[ContextPartitioner] = None,
    ) -> None:
        """
        初始化安全守卫，可选注入自定义检测器实例。

        Args:
            pii_detector: PII检测器实例
            injection_detector: 注入检测器实例
            sensitive_detector: 敏感内容检测器实例
            context_partitioner: 上下文分区器实例
        """
        self.pii_detector = pii_detector or PIIDetector()
        self.injection_detector = injection_detector or PromptInjectionDetector()
        self.sensitive_detector = sensitive_detector or SensitiveContentDetector()
        self.context_partitioner = context_partitioner or ContextPartitioner()
        logger.info("SecurityGuard 初始化完成")

    def check_input(
        self,
        text: str,
        *,
        check_pii: bool = True,
        check_injection: bool = True,
        check_sensitive: bool = True,
        mask_pii: bool = True,
        injection_threshold: float = 0.7,
        user_background: Optional[str] = None,
    ) -> SecurityCheckResult:
        """
        对用户输入进行全面的安全检查。

        检查流程：
        1. PII检测（可选脱敏）
        2. Prompt注入检测
        3. 敏感内容检测

        Args:
            text: 用户输入文本
            check_pii: 是否检查PII
            check_injection: 是否检查注入
            check_sensitive: 是否检查敏感内容
            mask_pii: 是否对PII进行脱敏
            injection_threshold: 注入风险阈值，超过此值视为不安全
            user_background: 用户背景信息（用于记录，不参与检测）

        Returns:
            SecurityCheckResult: 综合安全检查结果
        """
        result = SecurityCheckResult()
        processed_text = text

        if not text:
            result.warnings.append("输入为空")
            result.safe = True  # 空输入是安全的
            return result

        # 1. PII检测与脱敏
        if check_pii:
            pii_result = self.pii_detector.detect_pii(text)
            result.pii_result = pii_result
            if pii_result.has_pii:
                result.warnings.append(
                    f"检测到PII信息: {[item['type'] for item in pii_result.items]}"
                )
                if mask_pii:
                    processed_text = self.pii_detector.mask_pii(text)
                    result.sanitized_text = processed_text

        # 2. Prompt注入检测
        if check_injection:
            injection_result = self.injection_detector.detect(text)
            result.injection_result = injection_result
            if injection_result.is_injection:
                result.warnings.append(
                    f"检测到Prompt注入风险: score={injection_result.risk_score:.2f}, "
                    f"patterns={injection_result.detected_patterns}"
                )
                if injection_result.risk_score >= injection_threshold:
                    result.safe = False

        # 3. 敏感内容检测
        if check_sensitive:
            sensitive_result = self.sensitive_detector.detect(text)
            result.sensitive_result = sensitive_result
            if sensitive_result.has_sensitive:
                result.warnings.append(
                    f"检测到敏感内容: {sensitive_result.categories}"
                )
                result.safe = False

        # 如果未设置 sanitized_text，使用原始文本
        if result.sanitized_text is None:
            result.sanitized_text = processed_text

        if result.warnings:
            logger.warning("安全检查发现问题: %s", result.warnings)
        else:
            logger.debug("安全检查通过，输入安全")

        return result

    def check_output(
        self,
        text: str,
        *,
        check_pii: bool = True,
        check_sensitive: bool = True,
        mask_pii: bool = True,
    ) -> SecurityCheckResult:
        """
        对AI输出进行安全检查（输出侧通常不需要注入检测）。

        Args:
            text: AI输出文本
            check_pii: 是否检查PII（防止模型输出泄露训练数据中的PII）
            check_sensitive: 是否检查敏感内容
            mask_pii: 是否对PII进行脱敏

        Returns:
            SecurityCheckResult: 综合安全检查结果
        """
        return self.check_input(
            text,
            check_pii=check_pii,
            check_injection=False,  # 输出侧不需要注入检测
            check_sensitive=check_sensitive,
            mask_pii=mask_pii,
        )

    def build_safe_context(
        self,
        user_background: str,
        rag_evidence: Optional[str] = None,
        tool_results: Optional[str] = None,
        user_query: Optional[str] = None,
    ) -> Tuple[str, SecurityCheckResult]:
        """
        构建安全的上下文分区，并对用户查询进行安全检查。

        Args:
            user_background: 用户背景信息
            rag_evidence: RAG检索证据
            tool_results: 工具调用结果
            user_query: 用户查询

        Returns:
            Tuple[str, SecurityCheckResult]: (分区后的上下文, 安全检查结果)
        """
        check_result = SecurityCheckResult()

        # 对用户查询进行安全检查
        if user_query:
            check_result = self.check_input(user_query)
            if not check_result.safe:
                logger.warning("用户查询未通过安全检查，但仍构建上下文")
            # 使用脱敏后的文本
            safe_query = check_result.sanitized_text or user_query
        else:
            safe_query = None

        context = self.context_partitioner.build_context(
            user_background=user_background,
            rag_evidence=rag_evidence,
            tool_results=tool_results,
            user_query=safe_query,
        )

        return context, check_result

    def validate_context(self, context: str) -> bool:
        """
        验证上下文分区的完整性。

        Args:
            context: 已构建的上下文

        Returns:
            bool: 分区是否有效
        """
        return self.context_partitioner.validate_partition_integrity(context)

    def get_summary(self) -> Dict[str, Any]:
        """
        获取安全守卫的配置摘要。

        Returns:
            Dict: 配置信息
        """
        return {
            "version": "1.0.0",
            "reference": "4.docx - AI应用系统设计 - 安全防护",
            "capabilities": [
                "PII检测与脱敏",
                "Prompt注入防护",
                "敏感内容检测",
                "上下文分区",
            ],
            "pii_types": list(PIIDetector.MASK_PLACEHOLDERS.keys()),
            "injection_patterns_count": len(PromptInjectionDetector.INJECTION_PATTERNS),
            "sensitive_categories": list(SensitiveContentDetector.SENSITIVE_KEYWORDS.keys()),
            "context_partitions": ["user_background", "rag_evidence", "tool_results"],
        }