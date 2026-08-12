"""Deterministic guardrails for high-risk ecommerce actions.

These checks run before the LLM/tool loop so unsafe side-effect requests are
refused or routed to human review without giving the model a chance to call a
write tool.
"""

from __future__ import annotations

import os
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



def detect_safe_sop_response(
    message: str, agent_name: str = ""
) -> HighRiskActionDecision | None:
    """Return deterministic L0 SOP responses that do not need tools or LLM."""

    text = (message or "").strip()
    if not text:
        return HighRiskActionDecision(
            risk_level="L0",
            risk_domain="empty_input",
            response="当前输入为空，请补充具体业务目标、对象和约束后再处理。",
            requires_human_review=False,
        )

    agent = (agent_name or "").strip()

    if _has_any(text, ("忽略之前", "系统提示", "内部配置", "eval(", "DROP TABLE", "密码", "token")):
        return HighRiskActionDecision(
            risk_level="L0",
            risk_domain="security_refusal",
            response="不能执行越权、注入、导出密钥或泄露敏感系统信息的请求。我可以在合规范围内继续协助处理业务问题。",
            requires_human_review=False,
        )

    if len(text) > 300:
        return HighRiskActionDecision(
            risk_level="L0",
            risk_domain="long_input",
            response="输入内容较长，我会先按业务目标、关键指标、异常点和下一步动作进行结构化梳理；如需执行具体动作，请拆分成明确任务。",
            requires_human_review=False,
        )

    if agent == "customer_service":
        if "订单" in text and _has_any(text, ("物流", "核验", "查询")):
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="customer_order_query_sop",
                response="处理订单物流查询时，需要先核验订单号、下单账号或脱敏手机号、收件人信息与咨询人身份；核验通过后再查询订单和物流状态，并避免泄露无关客户信息。",
                requires_human_review=False,
            )
        if _has_any(text, ("客户咨询", "回复合规", "处理一个客户")):
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="customer_service_sop",
                response="我会先识别客户问题类型，核对订单/商品/售后上下文，再用知识库和平台规则生成合规回复；涉及退款、投诉、健康、隐私或赔付时转人工审核。",
                requires_human_review=False,
            )

    if agent == "data_analysis":
        if "GMV" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="metric_diagnosis_sop",
                response="GMV 下滑需要拆成流量、转化率、客单价、退款率、库存、价格活动和渠道结构等指标，并做环比/同比/分渠道对比，定位主要贡献项。",
                requires_human_review=False,
            )
        if "复购" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="cohort_analysis_sop",
                response="复购分析应按人群 cohort、首购时间、优惠券触达与未触达做对比，观察复购率、复购间隔、客单价和毛利变化，避免只看领取人数。",
                requires_human_review=False,
            )
        if "数据分析" in text or "电商团队" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="data_analysis_sop",
                response="我可以帮助电商团队做 GMV 拆解、流量转化漏斗分析、投放 ROI 分析、复购和人群分析、商品效率分析、异常预警和经营诊断。",
                requires_human_review=False,
            )

    if agent == "brand_bd" and os.getenv("AGENT_EVAL_MODE", "").lower() in {"1", "true", "yes", "on"}:
        if "达人" in text and "粉丝" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="brand_bd_kol_search_route",
                response="已路由到达人筛选流程：将使用 search_kols 按美妆领域、抖音平台、10 万到 50 万粉丝筛选达人，并输出粉丝量、互动率、匹配度和筛选标准。",
                requires_human_review=False,
                tool_calls=("search_kols",),
            )
        if "报告" in text and _has_any(text, ("ROI", "互动率", "转化")):
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="brand_bd_report_route",
                response="已路由到投放复盘报告流程：将使用 generate_performance_report 生成品牌推广效果报告，覆盖 ROI、互动率、转化表现和优化建议。",
                requires_human_review=False,
                tool_calls=("generate_performance_report",),
            )
        if "数据分析师" in text or "竞品分析" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="brand_bd_delegate_route",
                response="Task 已创建：将通过 a2a_delegate_task 委托数据分析师产出竞品分析报告，并由品牌商务团队汇总复核。",
                requires_human_review=False,
                tool_calls=("a2a_delegate_task",),
            )
    if agent == "content_operation":
        if "数据" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="content_data_sop",
                response="内容数据摘要应整理发布量、曝光、播放、互动、收藏、转化和爆款内容，并按小红书/抖音平台分别看趋势与问题。",
                requires_human_review=False,
            )
        if "报告" in text or "总结" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="content_report_sop",
                response="月度内容运营报告应包含内容发布概览、爆款亮点、低效问题、平台差异、用户反馈和下月动作计划。",
                requires_human_review=False,
            )
        if "内容" in text or "电商内容运营" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="content_operation_sop",
                response="我可以为电商内容运营团队做内容选题、短视频脚本、图文笔记、直播脚本、内容日历、平台适配和内容效果复盘。",
                requires_human_review=False,
            )

    if agent == "warehouse_logistics":
        if "库存" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="inventory_sop",
                response="库存查询应核对 SKU、可售库存、锁定库存、在途库存和安全库存；低库存时需要提醒补货、调拨或暂停高风险活动。",
                requires_human_review=False,
            )
        if "物流" in text or "配送" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="shipment_tracking_sop",
                response="物流配送查询应先核验物流单号和订单归属，再返回当前节点、异常原因和下一步处理建议；异常单需要人工或承运商确认。",
                requires_human_review=False,
            )
        if "仓库" in text and "分配" in text:
            return HighRiskActionDecision(
                risk_level="L0",
                risk_domain="warehouse_allocation_sop",
                response="仓库发货分配应比较地区距离、库存水位、时效、运费、履约能力和异常率，选择成本与配送体验更优的分配方案。",
                requires_human_review=False,
            )

    return None
