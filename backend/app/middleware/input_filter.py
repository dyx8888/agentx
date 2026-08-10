"""
用户输入安全过滤器
按照提示词防注入最佳实践，实现前置网关级关键词过滤

设计原则：
1. 精准匹配，宁可漏报不可误杀
2. 两级过滤：硬拒绝 vs 可疑日志
3. 作为 Pydantic field_validator 嵌入 Request 模型
4. 所有拦截行为可审计
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class FilterResult(StrEnum):
    PASSED = "passed"
    REJECTED = "rejected"
    SUSPICIOUS = "suspicious"


@dataclass
class FilterDecision:
    result: FilterResult
    reason: str = ""
    matched_pattern: str = ""


def _match_any(text_lower: str, patterns: list[tuple[str, str]]) -> str | None:
    for name, pattern in patterns:
        if re.search(pattern, text_lower):
            return name
    return None


class InputFilter:
    HARD_REJECT_PATTERNS: list[tuple[str, str]] = [
        (
            "role_switch_legal",
            r"(你|从现在起|现在|立刻).{0,10}(扮演|假装|充当|成|是|就是|假扮|伪装|变身为|变成了)\s*(一个|一名|一位)?\s*(律师|医生|法官|警察|黑客|罪犯|骗子|特工|军人|老师|教授)",
        ),
        (
            "role_switch_other_ai",
            r"(你)?(立刻|现在|从现在起)(扮演|假装|充当|成|是)\s*(ChatGPT|Claude|Gemini|GPT|其他\s*AI|另一个\s*(AI|模型|助手))",
        ),
        (
            "role_switch_generic",
            r"(你)?(立刻|现在|从现在起)(扮演|假装|充当)(一个|非受限的|不受限的|另一个|其他)\s*角色",
        ),
        (
            "prompt_leak_direct",
            r"(显示|输出|告诉|说出|打印|返回|公布|泄露|公开).{0,15}(隐藏的|你的|这个的)?\s*(系统\s*)?(提示词|提示|指令|prompt\s*|system\s*prompt)",
        ),
        (
            "prompt_leak_indirect",
            r"(用|通过|以).{0,20}(重复|复述|打印|输出)(你的|刚才的)?\s*(系统\s*)?(提示词|指令|规则)",
        ),
        (
            "jailbreak_dan",
            r"(DAN\s*模式|developer\s*mode|开发者\s*模式|jailbreak|越狱\s*(模式|指令)?)",
        ),
        (
            "jailbreak_forget",
            r"(忘记|忘掉|忽略|无视|清除|删除|放弃|不要管|别管|别再管).{0,15}(所有|一切|全部)?\s*(你的|系统|之前的)?\s*(规则|指令|限制|约束|提示词|身份|角色|设定|对话)",
        ),
        (
            "jailbreak_unrestricted",
            r"(从现在起|从现在开始).{0,30}(你不再受限|你不受限制|你被释放|你自由了|没有规则|解除限制|最高权限)",
        ),
        (
            "harmful_code",
            r"(帮我\s*(写|生成|开发|制作))?\s*(木马|病毒|恶意|钓鱼|勒索|诈骗|攻击)\s*(程序|代码|脚本|软件)",
        ),
    ]

    SUSPICIOUS_PATTERNS: list[tuple[str, str]] = [
        (
            "generic_role_play",
            r"(你现在|你来)扮演",
        ),
        (
            "ignore_partial",
            r"(忽略|忘记|不用).{0,10}(上面|前面|刚才|之前)的.{0,10}(话|要求|指令)",
        ),
        (
            "prompt_curiosity",
            r"(你的)\s*(提示词|指令|规则)\s*(是什么|是什么样|能看吗|能说吗|写.*什么)",
        ),
        (
            "hypothetical_role",
            r"(如果|假设|假如).{0,20}(你不是|你换了|你变成).{0,20}(角色|身份)",
        ),
        (
            "prompt_prefix_leak",
            r"(重复|复述|原样).{0,10}(上面|前面|最开始|第一句|开头|最开始).{0,20}(话|内容|句子)",
        ),
        (
            "task_hijack",
            r"(从现在起|从现在开始|接下来|现在).{0,10}(任务|目标|角色|指令)\s*(是|就是|变为|变成|改为)",
        ),
        (
            "system_bypass",
            r"(假装|假设|就当你|你就当|想象一下|当成)\s*(你|自己是).{0,8}(一个|没有|不受)\s*(限制|约束|规则|管控)",
        ),
    ]

    WHITELIST_PATTERNS: list[tuple[str, str]] = [
        (
            "script_content",
            r"脚本|剧本|台词|表演|出演|拍摄|视频|广告|文案|创意|策划",
        ),
        (
            "positive_role",
            r"扮演.{0,10}(达人|博主|用户|消费者|客户|妈妈|上班族|学生|网红)",
        ),
        (
            "self_describe",
            r"(你|你是一个|你的角色是).{0,10}(助手|数字员工|AI|客服|运营|商务|设计|分析)",
        ),
    ]

    @classmethod
    def check(cls, text: str) -> FilterDecision:
        if not text or not isinstance(text, str):
            return FilterDecision(FilterResult.PASSED)

        text_lower = text.lower()

        whitelist_match = _match_any(text_lower, cls.WHITELIST_PATTERNS)
        if whitelist_match:
            hard_match = _match_any(text_lower, cls.HARD_REJECT_PATTERNS)
            if hard_match:
                return FilterDecision(
                    FilterResult.PASSED,
                    reason=f"whitelist_override:{whitelist_match}",
                )
            return FilterDecision(FilterResult.PASSED)

        hard_match = _match_any(text_lower, cls.HARD_REJECT_PATTERNS)
        if hard_match:
            return FilterDecision(
                FilterResult.REJECTED,
                reason=f"hard_reject:{hard_match}",
                matched_pattern=hard_match,
            )

        suspicious_match = _match_any(text_lower, cls.SUSPICIOUS_PATTERNS)
        if suspicious_match:
            return FilterDecision(
                FilterResult.SUSPICIOUS,
                reason=f"suspicious:{suspicious_match}",
                matched_pattern=suspicious_match,
            )

        return FilterDecision(FilterResult.PASSED)

    @classmethod
    def validate_message(cls, v: str) -> str:
        decision = cls.check(v)

        if decision.result == FilterResult.REJECTED:
            logger.warning(
                "input_filter_rejected",
                pattern=decision.matched_pattern,
                reason=decision.reason,
                preview=v[:100],
            )
            raise ValueError("请求包含不支持的指令，请重新描述您的需求")

        if decision.result == FilterResult.SUSPICIOUS:
            logger.info(
                "input_filter_suspicious",
                pattern=decision.matched_pattern,
                reason=decision.reason,
                preview=v[:100],
            )

        return v
