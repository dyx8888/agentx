"""
SendStrategyEngine - Three-level message dispatch strategy for customer service

Level 1: Confidence >= 90% -> Fast batch review by default; explicit auto-send only
         when ALLOW_CUSTOMER_SERVICE_AUTO_SEND is explicitly enabled.
Level 2: Confidence 70%-89% -> Batch confirmation (hourly batch review)
Level 3: Confidence < 70% -> Per-message review (immediate human review)

Also handles: sentiment escalation detection, auto-reply safety gating
"""  # 客服消息发送策略引擎：根据置信度和情绪风险分级处理；生产默认只生成待审核草稿

import os
from dataclasses import dataclass, field  # dataclass用于SendDecision，field用于设置可变默认值
from datetime import datetime  # 用于生成决策时间戳和批次分组键
from enum import StrEnum  # 使用StrEnum，因为发送级别和风险等级需要以字符串形式在API中传输


class SendLevel(StrEnum):  # 发送级别枚举，决定了消息是否需要人工介入
    SILENT = "auto_send"  # 显式自动外发：仅在显式启用自动外发开关时使用
    BATCH = "batch"  # 批量确认：中等置信度消息按小时批次集中审核
    REVIEW = "review"  # 逐条审核：低置信度或高风险消息需要立即人工审核
    BLOCKED = "blocked"  # 阻止发送：涉及敏感话题的消息完全禁止发送


class SentimentRisk(StrEnum):  # 客户情绪风险等级，用于触发不同级别的升级处理
    LOW = "low"  # 低风险：正常沟通，无需特殊处理
    MEDIUM = "medium"  # 中风险：轻微不满，需要关注但不紧急
    HIGH = "high"  # 高风险：强烈不满，需要人工介入
    CRITICAL = "critical"  # 严重风险：涉及举报、投诉等，需要立即人工处理


@dataclass  # 使用dataclass，因为SendDecision是纯数据载体，不需要复杂方法
class SendDecision:  # 每次消息发送的决策结果，将策略评估结果与执行指令绑定
    message_id: str  # 消息唯一标识，用于追踪和审计
    level: SendLevel  # 发送级别，决定消息的处理流程
    confidence: float  # 置信度分数，原始值保留完整精度以便后续分析
    reason: str  # 决策原因，帮助审核人员理解决策逻辑
    sentiment_risk: SentimentRisk = SentimentRisk.LOW  # 默认低风险，大多数消息是正常沟通
    requires_escalation: bool = False  # 默认不需要升级，仅高风险消息触发升级
    escalation_note: str = ""  # 升级说明，为空表示不需要升级
    auto_send: bool = False  # 默认不自动发送，仅显式启用自动外发时才会设为True
    batch_group: str = ""  # 批次分组键，为空表示不归入批次
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )  # 使用field避免可变默认值，时间戳用于审计


class SendStrategyEngine:  # 发送策略引擎，全部使用classmethod，因为策略评估是纯函数式的，不需要实例状态
    """Three-level message dispatch strategy engine."""

    CONFIDENCE_THRESHOLDS: dict[
        str, float
    ] = {  # 类级别阈值，统一管理；使用float而非int，因为置信度是连续值
        "fast_review": 0.90,  # 90%以上置信度进入快速审核；生产默认仍需人工确认
        "batch": 0.70,  # 70%以上进入批量审核，低于70%必须逐条审核
    }

    SENTIMENT_KEYWORDS: dict[
        SentimentRisk, list[str]
    ] = {  # 按风险等级分组的情绪关键词，从高到低优先级匹配
        SentimentRisk.CRITICAL: [  # 严重级关键词：涉及法律、监管、媒体曝光的词汇
            "\u4e3e\u62a5",
            "\u66dd\u5149",
            "315",
            "\u6d88\u534f",
            "\u5de5\u5546\u5c40",
            "\u8d54\u507f3\u500d",
            "\u5047\u4e00\u8d54\u5341",
            "\u6295\u8bc9\u90e8\u95e8",
            "\u5f8b\u5e08\u51fd",
            "\u5a92\u4f53\u66dd\u5149",
            "\u7f51\u7edc\u8206\u8bba",
        ],
        SentimentRisk.HIGH: [  # 高风险关键词：涉及投诉、退款纠纷、质量问题的词汇
            "\u4e0d\u5904\u7406\u5c31",
            "\u6295\u8bc9",
            "\u5dee\u8bc4",
            "\u6c14\u6124",
            "\u9a97\u5b50",
            "\u5b98\u65b9\u6295\u8bc9",
            "\u9000\u6b3e\u4e0d\u9000\u8d27",
            "\u8d5a\u9ed1\u5fc3\u94b1",
            "\u8d28\u91cf\u592a\u5dee",
            "\u6ca1\u4eba\u7ba1",
        ],
        SentimentRisk.MEDIUM: [  # 中风险关键词：涉及不满、失望、效率问题的词汇
            "\u4e0d\u6ee1",
            "\u5931\u671b",
            "\u4ee5\u540e\u4e0d\u4e70\u4e86",
            "\u8fd8\u6ca1\u53d1\u8d27",
            "\u529e\u4e8b\u6548\u7387\u592a\u4f4e",
            "\u6001\u5ea6\u4e0d\u597d",
            "\u53d1\u9519\u8d27\u4e86",
        ],
    }

    SENSITIVE_TOPICS: list[str] = [  # 敏感话题列表，触发后直接BLOCKED，无论置信度如何
        "\u8d28\u91cf\u95ee\u9898",
        "\u5b89\u5168\u95ee\u9898",
        "\u6cd5\u5f8b\u95ee\u9898",
        "\u98df\u54c1\u5b89\u5168",
        "\u4f24\u5bb3\u5065\u5eb7",
        "\u8fc7\u654f\u53cd\u5e94",
        "\u4fb5\u6743",
        "\u6b3a\u8bc8",
        "\u8fdd\u6cd5",
    ]

    SINGLE_SEND_LIMIT = 20.0  # 单次发送赔付上限（元），作为高风险客户自动赔付的硬性上限

    @staticmethod
    def auto_send_enabled() -> bool:
        return os.getenv("ALLOW_CUSTOMER_SERVICE_AUTO_SEND", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @classmethod  # classmethod，因为策略评估基于类级别阈值，不依赖实例状态
    def evaluate(
        cls,
        message_id: str,
        customer_message: str,
        confidence: float,
        agent_reply: str = "",
        context: dict = None,
    ) -> SendDecision:  # context可选，为未来扩展预留
        sentiment_risk = cls.detect_sentiment(
            customer_message
        )  # 先检测情绪风险，因为敏感话题检查优先级最高

        if cls._contains_sensitive_topic(customer_message) or cls._contains_sensitive_topic(
            agent_reply
        ):  # 同时检查客户消息和回复，防止AI回复中无意涉及敏感话题
            return SendDecision(  # 敏感话题直接BLOCKED，不论置信度，安全第一
                message_id=message_id,
                level=SendLevel.BLOCKED,
                confidence=confidence,
                reason="消息涉及敏感话题，已阻止自动发送",
                sentiment_risk=sentiment_risk,
                requires_escalation=True,  # 敏感话题必须升级给人工处理
                escalation_note="涉及敏感话题，需人工审核后再决定是否发送",
            )

        if sentiment_risk in (
            SentimentRisk.CRITICAL,
            SentimentRisk.HIGH,
        ):  # 高/严重风险走REVIEW流程，不信任自动回复
            return SendDecision(
                message_id=message_id,
                level=SendLevel.REVIEW,
                confidence=confidence,
                reason=f"客户情绪风险等级为{sentiment_risk}，需要逐条审核",
                sentiment_risk=sentiment_risk,
                requires_escalation=sentiment_risk == SentimentRisk.CRITICAL,  # 仅CRITICAL需要升级
                escalation_note="高风险客户，建议暂停自动回复并交由人工处理"
                if sentiment_risk == SentimentRisk.CRITICAL
                else "不满客户，需人工审核回复内容",
            )

        if confidence >= cls.CONFIDENCE_THRESHOLDS["fast_review"]:  # 高置信度 + 低风险
            if not cls.auto_send_enabled():
                hour_key = datetime.now().strftime("%Y%m%d%H")
                return SendDecision(
                    message_id=message_id,
                    level=SendLevel.BATCH,
                    confidence=confidence,
                    reason=f"置信度{confidence * 100:.0f}%，生产默认需人工批量确认后发送",
                    sentiment_risk=sentiment_risk,
                    batch_group=hour_key,
                )
            return SendDecision(
                message_id=message_id,
                level=SendLevel.SILENT,
                confidence=confidence,
                reason=f"置信度{confidence * 100:.0f}%，显式开启自动外发，进入外发执行",
                sentiment_risk=sentiment_risk,
                auto_send=True,  # 显式启用自动外发后，调度器据此跳过人工审核
            )

        if confidence >= cls.CONFIDENCE_THRESHOLDS["batch"]:  # 中等置信度 → 批量确认
            hour_key = datetime.now().strftime("%Y%m%d%H")  # 按小时分组，同批次的消息一起审核
            return SendDecision(
                message_id=message_id,
                level=SendLevel.BATCH,
                confidence=confidence,
                reason=f"置信度{confidence * 100:.0f}%，归入批量确认组{hour_key}",
                sentiment_risk=sentiment_risk,
                batch_group=hour_key,
            )

        return SendDecision(  # 低置信度 → 逐条审核，最后的兜底
            message_id=message_id,
            level=SendLevel.REVIEW,
            confidence=confidence,
            reason=f"置信度{confidence * 100:.0f}%，需逐条人工审核",
            sentiment_risk=sentiment_risk,
        )

    @classmethod  # classmethod，检测逻辑基于类级别关键词字典
    def detect_sentiment(
        cls, message: str
    ) -> SentimentRisk:  # 基于关键词的情绪检测，从高到低优先级匹配
        message_lower = message.lower()  # 转小写进行不区分大小写的匹配

        for keyword in cls.SENTIMENT_KEYWORDS[
            SentimentRisk.CRITICAL
        ]:  # 先检查严重风险，因为优先级最高
            if keyword in message_lower:
                return SentimentRisk.CRITICAL  # 立即返回，不继续检查更低级别

        for keyword in cls.SENTIMENT_KEYWORDS[SentimentRisk.HIGH]:  # 再检查高风险
            if keyword in message_lower:
                return SentimentRisk.HIGH

        for keyword in cls.SENTIMENT_KEYWORDS[SentimentRisk.MEDIUM]:  # 最后检查中风险
            if keyword in message_lower:
                return SentimentRisk.MEDIUM

        return SentimentRisk.LOW  # 没有匹配到任何关键词，默认低风险

    @classmethod  # classmethod，工具方法不需要实例状态
    def _contains_sensitive_topic(cls, text: str) -> bool:  # 下划线前缀表示内部方法，不对外暴露
        return any(
            topic in text.lower() for topic in [t.lower() for t in cls.SENSITIVE_TOPICS]
        )  # 同时对话题和文本做lower，确保不区分大小写

    @classmethod  # classmethod，动作映射基于类级别配置
    def get_escalation_action(
        cls, risk: SentimentRisk
    ) -> dict:  # 根据风险等级返回对应的升级动作配置
        actions = {  # 字典映射，O(1)查找，比if-elif链更高效且易于扩展
            SentimentRisk.LOW: {  # 低风险：正常自动回复，无任何限制
                "action": "normal_reply",
                "compensation_limit": 0,  # 无赔付上限，因为不需要赔付
                "notify_dashboard": False,  # 不需要通知仪表盘
                "notify_agents": [],  # 不需要通知任何Agent
            },
            SentimentRisk.MEDIUM: {  # 中风险：升级回复，但不触发通知
                "action": "upgraded_reply",
                "compensation_limit": 0,
                "notify_dashboard": False,
                "notify_agents": [],
            },
            SentimentRisk.HIGH: {  # 高风险：人工接管，通知仪表盘和客服
                "action": "human_takeover",
                "compensation_limit": cls.SINGLE_SEND_LIMIT,  # 使用类级别上限，确保一致性
                "notify_dashboard": True,  # 通知仪表盘，让管理人员知晓
                "notify_agents": ["customer_service"],  # 通知客服Agent
            },
            SentimentRisk.CRITICAL: {  # 严重风险：仅人工处理，通知更多角色
                "action": "immediate_human_only",
                "compensation_limit": 50.0,  # 严重风险的赔付上限更高，灵活性更大
                "notify_dashboard": True,
                "notify_agents": [
                    "customer_service",
                    "brand_bd",
                ],  # 同时通知BD，因为可能涉及品牌危机
            },
        }
        return actions.get(
            risk, actions[SentimentRisk.LOW]
        )  # 兜底返回LOW级别的动作，防止未知风险等级导致错误
