"""Deterministic guardrails for high-risk ecommerce actions.

These checks run before the LLM/tool loop so unsafe side-effect requests are
refused or routed to human review without giving the model a chance to call a
write tool.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HighRiskActionDecision:
    """Safe handling decision for a high-risk user request."""

    risk_level: str
    risk_domain: str
    response: str
    requires_human_review: bool = True
    tool_calls: tuple[str, ...] = ()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def detect_high_risk_action(
    message: str, agent_name: str = ""
) -> HighRiskActionDecision | None:
    """Return a safe decision when the request asks for risky side effects."""

    text = (message or "").strip()
    if not text:
        return None

    agent = (agent_name or "").strip()
    customer_scope = agent in {"", "master", "customer_service", "cc"} or _has_any(
        text, ("客户", "订单", "售后", "退款", "赔付", "补偿", "发券")
    )
    logistics_scope = agent in {"", "master", "warehouse_logistics", "logistics"} or _has_any(
        text, ("发货", "补发", "快递单", "仓库", "物流", "改地址", "收货地址", "寄样", "样品")
    )
    brand_scope = agent in {"", "master", "brand_bd"} or _has_any(
        text, ("达人", "邀约", "私信", "ROI", "合同", "佣金", "保底", "寄样")
    )
    direct_terms = ("直接", "立刻", "马上", "不用", "不要审核", "别走审核", "不需要")
    privacy_terms = (
        "手机号",
        "身份证",
        "银行卡",
        "收货地址",
        "微信号",
        "联系方式",
        "私下处理",
    )
    export_terms = ("导出", "发给我", "给我", "提供", "转发")

    if _has_any(text, privacy_terms) and _has_any(text, export_terms):
        subject = "客户" if agent == "customer_service" else "达人/客户"
        return HighRiskActionDecision(
            risk_level="L3",
            risk_domain="privacy_export",
            response=(
                f"不能导出或转发{subject}敏感资料。该请求涉及隐私与合规风险，"
                "需要先确认授权、用途、最小必要范围，并提交人工合规审核。"
            ),
        )

    if customer_scope:
        health_or_claim = _has_any(
            text, ("过敏", "红肿", "皮炎", "治疗", "医学", "痘痘", "疗效", "12315", "投诉")
        )
        refund_or_comp = _has_any(text, ("退款", "赔付", "补偿", "发券", "无门槛券"))

        if health_or_claim and refund_or_comp:
            return HighRiskActionDecision(
                risk_level="L3",
                risk_domain="refund",
                response=(
                    "不能直接退款、赔付或承诺医疗功效。该问题涉及健康、投诉和售后资金动作，"
                    "已转人工客服审核处理；自动回复只能先安抚、建议暂停使用并收集订单与症状信息。"
                ),
            )

        if _has_any(text, ("治疗", "医学保证", "疗效", "保证治好")):
            return HighRiskActionDecision(
                risk_level="L3",
                risk_domain="medical_claim",
                response=(
                    "不能做医疗功效承诺或给出诊疗类保证。请按商品合规话术回复，"
                    "涉及健康不适时建议用户停止使用并咨询专业人员，必要时转人工审核。"
                ),
            )

        if refund_or_comp and _has_any(text, direct_terms):
            return HighRiskActionDecision(
                risk_level="L2",
                risk_domain="compensation",
                response=(
                    "补偿、优惠券或退款都需要按售后政策审核，不能绕过流程自动发放。"
                    "我可以先整理客户情况和建议方案，提交人工审核后再执行。"
                ),
            )

    if logistics_scope:
        if _has_any(text, ("改成", "改地址", "收货地址", "新地址")):
            return HighRiskActionDecision(
                risk_level="L3",
                risk_domain="address_change",
                response=(
                    "高价值订单地址变更必须先做客户身份核验和订单风险核验，"
                    "不能直接修改或同步系统。"
                ),
            )

        if _has_any(text, ("补发", "再发", "快递单", "批量同步", "标记仓库已处理")) or ("发货" in text and _has_any(text, direct_terms)):
            return HighRiskActionDecision(
                risk_level="L3",
                risk_domain="shipment",
                response=(
                    "发货、补发或批量同步属于有副作用动作，必须先审核订单、物流证据和库存影响，"
                    "不能直接创建发货单。"
                ),
            )

        if _has_any(text, ("寄样", "样品")):
            return HighRiskActionDecision(
                risk_level="L2",
                risk_domain="sample_shipping",
                response=(
                    "寄样需要品牌商务确认达人、样品价值、地址和预算归属，"
                    "确认完成前不能安排寄出。"
                ),
            )

    if brand_scope:
        if _has_any(text, ("合同", "保底", "佣金", "违约金", "独家合作")):
            return HighRiskActionDecision(
                risk_level="L3",
                risk_domain="contract",
                response=(
                    "合同、保底佣金和违约责任承诺必须经过法务与负责人审核，"
                    "不能自动承诺或外发。"
                ),
            )

        if _has_any(text, ("群发", "私信", "邀约")) or ("ROI" in text and "保证" in text):
            return HighRiskActionDecision(
                risk_level="L3",
                risk_domain="external_outreach",
                response=(
                    "外发邀约、批量私信和 ROI 承诺必须先审核名单、话术和合规边界，"
                    "不能自动发送或保证收益。"
                ),
            )

        if _has_any(text, ("寄样", "通知仓库", "已确认合作")):
            return HighRiskActionDecision(
                risk_level="L2",
                risk_domain="sample_shipping",
                response=(
                    "寄样和合作确认需要先确认达人资质、合作条款、样品预算和收件信息，"
                    "确认完成前不能通知仓库执行。"
                ),
            )

    return None
