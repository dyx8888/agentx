"""
客服引擎 - 三级发送策略 + 情绪识别 + 自动回复审核
"""  # 客服引擎：关键词情绪识别 + 三级发送决策（自动发/批量审/人工审），高风险自动升级

from dataclasses import dataclass, field  # dataclass定义消息和回复数据模型
from datetime import datetime  # 记录消息和回复的时间戳
from enum import StrEnum  # 字符串枚举，便于序列化

from app.core.logging import get_logger  # 结构化日志记录

logger = get_logger(__name__)


class EmotionLevel(StrEnum):  # 客户情绪风险等级，使用StrEnum便于JSON传输
    LOW_RISK = "low"  # 低风险：普通咨询，可自动回复
    MEDIUM_RISK = "medium"  # 中风险：有投诉倾向，需批量审核
    HIGH_RISK = "high"  # 高风险：严重投诉/法律威胁，必须人工处理


class SendDecision(StrEnum):  # 回复发送的三种决策级别
    AUTO_SEND = "auto_send"  # 自动发送：高置信度+低风险，直接发送
    BATCH_REVIEW = "batch_review"  # 批量审核：中等置信度，积累后批量人工审
    MANUAL_REVIEW = "manual_review"  # 人工审核：低置信度或高风险，必须人工处理


@dataclass
class CustomerMessage:  # 客户消息数据模型
    conv_id: str  # 会话ID，用于关联多轮对话
    customer_id: str  # 客户标识
    content: str  # 消息内容
    platform: str  # 来源平台（淘宝/抖音/拼多多等）
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 使用UTC时间避免时区问题


@dataclass
class ReplyDraft:  # 回复草稿数据模型，包含置信度和发送决策
    conv_id: str  # 关联的会话ID
    content: str  # 回复内容
    confidence: float  # 置信度0-1，越高越可靠
    send_decision: SendDecision  # 发送决策类型
    emotion: EmotionLevel  # 客户情绪等级
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 生成时间


class CustomerServiceEngine:
    """客服执行引擎"""  # 核心引擎：关键词匹配 → 情绪识别 → 三级发送决策

    HIGH_RISK_KEYWORDS = [  # 高风险关键词：一旦命中直接升级为人工处理
        "投诉", "差评", "曝光", "315", "退款不退货", "12315",
        "工商", "媒体", "律师", "起诉", "法院", "举报",
    ]

    MEDIUM_RISK_KEYWORDS = [  # 中风险关键词：需要关注但不紧急
        "太差", "坑人", "骗人", "质量不行", "发错", "破损",
        "退货", "退款", "补偿", "投诉无门",
    ]

    def __init__(self):
        self._pending_reviews: dict[str, list[ReplyDraft]] = {}  # 按公司ID分组的待审核回复池
        logger.info("customer_service_engine_initialized")

    async def process_message(self, message: CustomerMessage, company_id: int) -> ReplyDraft:  # 核心处理方法：情绪识别→生成回复→计算置信度→决定发送策略
        emotion = self._detect_emotion(message.content)  # 先做情绪识别，因为高风险消息的回复策略完全不同

        try:
            reply_content = await self._generate_reply(message, company_id)  # 调用LLM生成回复，失败时回退到规则回复
            confidence = self._calculate_confidence(reply_content, emotion)  # 综合回复质量和情绪计算置信度

            send_decision = self._determine_send_decision(confidence, emotion)  # 根据置信度和情绪决定三级发送策略

            draft = ReplyDraft(
                conv_id=message.conv_id,
                content=reply_content,
                confidence=confidence,
                send_decision=send_decision,
                emotion=emotion,
            )

            if send_decision == SendDecision.BATCH_REVIEW:  # 中风险回复加入批量审核队列
                self._add_to_batch_review(draft, company_id)

            await self._handle_emotion_escalation(message, emotion, company_id)  # 高风险消息触发升级告警

            logger.info("cs_message_processed", conv=message.conv_id,
                        emotion=emotion.value, decision=send_decision.value)  # 结构化日志便于追踪
            return draft
        except Exception as e:  # 异常兜底：任何错误都转为人工处理，安全第一
            logger.error("cs_process_error", error=str(e))
            return ReplyDraft(
                conv_id=message.conv_id,
                content="系统处理异常，已转人工",  # 固定回复模板，不暴露系统细节
                confidence=0.0,  # 置信度为0，确保走人工审核
                send_decision=SendDecision.MANUAL_REVIEW,
                emotion=EmotionLevel.HIGH_RISK,  # 异常情况按高风险处理
            )

    def _detect_emotion(self, content: str) -> EmotionLevel:  # 基于关键词的情绪检测，先匹配高风险再匹配中风险
        for keyword in self.HIGH_RISK_KEYWORDS:  # 高风险优先检查，因为命中高风险应跳过中风险判断
            if keyword in content:
                return EmotionLevel.HIGH_RISK

        for keyword in self.MEDIUM_RISK_KEYWORDS:  # 中风险关键词检查
            if keyword in content:
                return EmotionLevel.MEDIUM_RISK

        return EmotionLevel.LOW_RISK  # 都不命中默认低风险

    async def _generate_reply(self, message: CustomerMessage, company_id: int) -> str:  # 优先使用LLM生成回复，失败时回退到规则回复
        try:
            from langchain_core.messages import HumanMessage, SystemMessage  # LangChain消息类型，用于LLM调用

            from app.agents.customer_service import get_system_prompt  # 获取客服系统提示词
            from app.core.agent_robustness import enrich_system_prompt  # 增强系统提示词的安全性
            from app.core.instruction_boundary import wrap_system_instructions  # 包装系统指令，防止注入
            from app.services.model_gateway import get_global_model_gateway  # 全局模型网关

            gateway = get_global_model_gateway()  # 获取单例模型网关
            llm = gateway.get_llm()  # 获取LLM实例
            system_prompt = enrich_system_prompt(get_system_prompt())  # 增强提示词：添加安全性和鲁棒性指令

            response = llm.invoke([  # 同步调用LLM（与fastapi异步配合使用）
                SystemMessage(content=wrap_system_instructions(system_prompt)),  # 系统消息包装后发送
                HumanMessage(content=(  # 人类消息包含完整的上下文信息
                    f"请为以下客服消息生成回复:\n"
                    f"客户: {message.customer_id}\n"
                    f"平台: {message.platform}\n"
                    f"消息: {message.content}\n\n"
                    f"要求: 简洁、专业、有温度。如果涉及售后问题，按标准流程处理。"  # 明确的回复要求
                )),
            ])
            return response.content.strip()  # 去除首尾空白
        except Exception:
            return self._rule_based_reply(message.content)  # LLM调用失败时回退到规则回复，保证服务可用性

    def _rule_based_reply(self, content: str) -> str:  # 基于关键词的规则回复，作为LLM失败时的兜底策略
        reply_map = {  # 关键词→回复模板映射，覆盖最常见的客服场景
            "发货": "亲，您的订单已进入发货流程，预计24-48小时内发出，请耐心等待~",
            "物流": "亲，正在为您查询物流状态，请稍候~",
            "退款": "亲，退款申请已收到，我们将在1-3个工作日内为您处理。",
            "退换": "亲，很抱歉给您带来不便。请提供订单号和商品照片，我们马上为您处理退换货。",
            "优惠": "亲，我们目前有满299减50的活动哦，您可以看看有没有需要凑单的~",
        }
        for keyword, reply in reply_map.items():  # 遍历关键词，返回第一个匹配的回复
            if keyword in content:
                return reply
        return "亲，感谢您的咨询，正在为您处理中，请稍候~"  # 完全不匹配时的通用兜底回复

    def _calculate_confidence(self, reply: str, emotion: EmotionLevel) -> float:  # 综合回复质量和情绪计算置信度
        base_confidence = 0.85  # 基准置信度0.85，假设LLM回复质量一般较好
        if len(reply) < 10:  # 回复太短可能不够完整
            base_confidence -= 0.15
        if len(reply) > 500:  # 回复太长可能包含冗余或幻觉内容
            base_confidence -= 0.1
        if emotion == EmotionLevel.HIGH_RISK:  # 高风险消息LLM可能不够敏感，大幅降低置信度
            base_confidence -= 0.3
        elif emotion == EmotionLevel.MEDIUM_RISK:  # 中风险消息略微降低置信度
            base_confidence -= 0.1
        return max(0.1, min(0.99, base_confidence))  # 限制在[0.1, 0.99]区间，避免绝对0和绝对1

    def _determine_send_decision(self, confidence: float,  # 基于置信度和情绪决定三个发送级别
                                   emotion: EmotionLevel) -> SendDecision:
        if emotion == EmotionLevel.HIGH_RISK:  # 高风险消息无论置信度如何都必须人工审核
            return SendDecision.MANUAL_REVIEW
        if confidence >= 0.90:  # 置信度≥90%可直接发送
            return SendDecision.AUTO_SEND
        if confidence >= 0.70:  # 置信度70-90%进入批量审核队列
            return SendDecision.BATCH_REVIEW
        return SendDecision.MANUAL_REVIEW  # 置信度<70%需要人工审核

    def _add_to_batch_review(self, draft: ReplyDraft, company_id: int):  # 将回复草稿加入批量审核队列
        key = str(company_id)  # 将company_id转为字符串，避免整数键和字符串键混用
        if key not in self._pending_reviews:
            self._pending_reviews[key] = []  # 初始化该公司的审核队列
        self._pending_reviews[key].append(draft)

    async def _handle_emotion_escalation(self, message: CustomerMessage,  # 高风险消息触发升级告警
                                           emotion: EmotionLevel, company_id: int):
        if emotion == EmotionLevel.HIGH_RISK:  # 只有高风险才触发升级
            from app.communication.collaboration import collaboration_engine  # 延迟导入避免循环依赖
            await collaboration_engine.create_alert(
                company_id=company_id,
                alert_type="customer_escalation",
                title="客户情绪升级 - 高风险",
                message=f"客户 {message.customer_id} 的消息触发高风险关键词: {message.content[:100]}",  # 截断到100字符避免过长
                severity="critical",  # 高风险用critical级别
                related_agents=["customer_service"],  # 通知客服Agent
            )

    def get_batch_reviews(self, company_id: int) -> list[dict]:  # 获取并清空指定公司的批量审核队列
        drafts = self._pending_reviews.get(str(company_id), [])
        result = []
        for d in drafts:  # 转换为字典格式便于JSON输出
            result.append({
                "conv_id": d.conv_id,
                "content": d.content,
                "confidence": d.confidence,
                "emotion": d.emotion.value,
                "generated_at": d.generated_at,
            })
        self._pending_reviews[str(company_id)] = []  # 清空队列，防止重复处理
        return result

    async def execute_send(self, draft: ReplyDraft) -> dict:  # 执行发送操作，仅AUTO_SEND决策才会实际发送
        if draft.send_decision != SendDecision.AUTO_SEND:  # 非自动发送的请求拒绝执行
            return {"status": "pending_review", "conv_id": draft.conv_id}

        try:
            from app.integrations.enterprise_systems import cs_integration  # 延迟导入避免循环依赖
            result = cs_integration.send_reply(draft.conv_id, draft.content, auto_send=True)  # 调用企业系统接口发送
            return result
        except Exception as e:
            logger.error("cs_send_failed", error=str(e))
            return {"status": "failed", "conv_id": draft.conv_id, "error": str(e)}


cs_engine = CustomerServiceEngine()  # 全局单例，确保客服状态一致
