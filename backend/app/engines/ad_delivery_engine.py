"""
广告投放执行引擎 - 自动止损/A/B测试/ROI优化
"""  # 广告投放引擎：通过规则判断实现自动止损、A/B测试建议和ROI优化，不依赖LLM

from dataclasses import dataclass, field  # 使用dataclass定义数据模型，减少样板代码
from datetime import datetime  # 记录指标时间戳，用于判断投放时长
from enum import StrEnum  # 字符串枚举，便于序列化和日志输出

from app.core.logging import get_logger  # 结构化日志，便于追踪投放决策过程

logger = get_logger(__name__)  # 模块级日志记录器，使用__name__确保日志来源清晰


class CampaignStatus(StrEnum):  # 广告计划状态枚举，使用StrEnum便于前端直接使用字符串值
    RUNNING = "running"  # 正常运行中
    PAUSED = "paused"  # 已暂停（止损触发）
    BUDGET_REDUCED = "budget_reduced"  # 预算已削减
    PENDING_REVIEW = "pending_review"  # 等待人工审核


@dataclass
class CampaignMetrics:  # 广告计划的核心指标数据载体
    campaign_id: str  # 广告计划唯一标识
    impressions: int  # 曝光量
    clicks: int  # 点击量
    conversions: int  # 转化量
    spend: float  # 消耗金额
    revenue: float  # 收入金额
    cpa: float  # 单次转化成本
    roi: float  # 投资回报率
    ctr: float  # 点击率（小数形式）
    lasting_hours: float = 0  # 计划已运行时长，用于判断是否达到止损触发条件
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())  # 使用UTC时间避免时区问题

    @property
    def ctr_pct(self) -> float:  # 将小数CTR转为百分比，方便人类阅读和日志展示
        return self.ctr * 100


class AdDeliveryEngine:
    """广告投放自动执行引擎"""  # 核心引擎：通过多维度规则评估实现自动止损、A/B测试建议和优化提示

    INDUSTRY_AVG_CTR = 0.02  # 行业平均点击率2%，作为CTR对比基准
    CPA_TOLERANCE = 1.5  # CPA超出目标的容忍倍数，超过此值触发止损
    ROI_BREAKEVEN_THRESHOLD = 1.0  # ROI盈亏平衡线，低于1表示亏损
    BUDGET_EXHAUSTION_THRESHOLD = 0.90  # 预算消耗达90%阈值，防止预算耗尽而无回报

    def __init__(self):
        self._active_campaigns: dict[str, CampaignMetrics] = {}  # 活跃计划字典，使用campaign_id为键实现O(1)查找
        self._stop_loss_log: list[dict] = []  # 止损操作日志，保留历史记录便于审计
        logger.info("ad_delivery_engine_initialized")  # 引擎初始化日志，便于追踪生命周期

    def register_campaign(self, campaign_id: str, metrics: CampaignMetrics):  # 注册广告计划到活跃列表
        self._active_campaigns[campaign_id] = metrics

    async def evaluate_campaign(self, campaign_id: str, target_cpa: float,  # 异步评估广告计划，集成止损+A/B测试+优化建议
                                   target_roi: float, daily_budget: float,
                                   company_id: int) -> list[dict]:
        """评估广告计划并执行自动止损"""
        metrics = self._active_campaigns.get(campaign_id)  # O(1)查找
        if not metrics:
            return []

        actions = []  # 收集所有操作建议，合并返回
        stop_loss_logs = self._analyze_stop_loss(  # 止损分析：CPA/ROI/CTR/预算多维度评估
            campaign_id, metrics, target_cpa, target_roi, daily_budget, company_id
        )
        ab_test_suggestions = self._analyze_ab_test(metrics)  # A/B测试建议：基于CTR和CPA判断是否需要测试
        optimization_tips = self._generate_optimization_tips(metrics)  # 优化建议：CTR异常和ROI优秀的提示

        if stop_loss_logs:
            actions.extend(stop_loss_logs)  # 止损操作优先级最高
            self._stop_loss_log.extend(stop_loss_logs)  # 持久化止损日志

        for suggestion in ab_test_suggestions:
            actions.append(suggestion)

        for tip in optimization_tips:
            actions.append(tip)

        return actions

    def _analyze_stop_loss(self, campaign_id: str, m: CampaignMetrics,  # 多维度止损规则分析，逐条检查是否触发
                             target_cpa: float, target_roi: float,
                             daily_budget: float, company_id: int) -> list[dict]:
        actions = []

        if m.cpa > target_cpa * self.CPA_TOLERANCE and m.lasting_hours >= 2:  # CPA超过目标1.5倍且持续2h，说明出价/人群有问题
            actions.append({
                "type": "stop_loss",
                "campaign_id": campaign_id,
                "action": "reduce_budget",  # 降低预算50%而非直接暂停，给计划一个缓冲期
                "message": f"CPA({m.cpa:.2f})超过目标({target_cpa:.2f})的{self.CPA_TOLERANCE}x，持续{m.lasting_hours}h",
                "auto_execute": True,  # 可自动执行，因为降预算风险可控
                "new_budget_pct": 50,
            })

        if m.roi < self.ROI_BREAKEVEN_THRESHOLD and m.lasting_hours >= 4:  # ROI低于盈亏线持续4h，说明在持续亏钱
            actions.append({
                "type": "stop_loss",
                "campaign_id": campaign_id,
                "action": "pause_campaign",  # 直接暂停，因为每多跑一小时就多亏一小时
                "message": f"ROI({m.roi:.2f})低于盈亏线{self.ROI_BREAKEVEN_THRESHOLD}，持续{m.lasting_hours}h",
                "auto_execute": True,
            })

        if m.ctr < self.INDUSTRY_AVG_CTR * 0.5:  # CTR低于行业均值50%，素材可能已严重疲劳或受众不精准
            actions.append({
                "type": "stop_loss",
                "campaign_id": campaign_id,
                "action": "replace_creative",  # 替换素材而非暂停，因为可能是创意疲劳问题
                "message": f"CTR({m.ctr_pct:.2f}%)低于行业均值50%({self.INDUSTRY_AVG_CTR*100:.1f}%)",
                "auto_execute": False,  # 替换素材需要人工审核新素材质量
                "require_review": True,
            })

        if m.spend > daily_budget * self.BUDGET_EXHAUSTION_THRESHOLD and m.roi < 1:  # 消耗超90%且ROI<1，预算快用完但效果差
            actions.append({
                "type": "stop_loss",
                "campaign_id": campaign_id,
                "action": "pause_campaign",
                "message": f"消耗已达日预算{daily_budget}的{self.BUDGET_EXHAUSTION_THRESHOLD*100}%且ROI({m.roi:.2f})<1",
                "auto_execute": True,
            })

        return actions

    def _analyze_ab_test(self, m: CampaignMetrics) -> list[dict]:  # 当指标异常时建议进行A/B测试而非盲目调整
        suggestions = []
        if m.ctr < self.INDUSTRY_AVG_CTR * 0.7:  # CTR低于行业均值70%，素材可能需要更换方向
            suggestions.append({
                "type": "ab_test",
                "campaign_id": m.campaign_id,
                "test_item": "creative_ab",
                "suggestion": "建议对素材A/B测试，当前CTR偏低，尝试更换主图或标题",
            })
        if m.cpa > 50 and m.roi < 2:  # CPA过高且ROI偏低，可能是人群包不够精准
            suggestions.append({
                "type": "ab_test",
                "campaign_id": m.campaign_id,
                "test_item": "audience_ab",
                "suggestion": "建议对人群包进行A/B测试，尝试扩宽或收窄定向",
            })
        return suggestions

    def _generate_optimization_tips(self, m: CampaignMetrics) -> list[dict]:  # 基于数据异常产生优化提示
        tips = []
        if m.ctr > self.INDUSTRY_AVG_CTR * 2 and m.conversions == 0:  # 点击率高但无转化，说明落地页或商品有问题
            tips.append({
                "type": "optimization_tip",
                "message": "CTR很高但无转化，检查落地页加载速度和购物路径",
            })
        if m.roi > 3:  # ROI优秀，应该放大投放规模
            tips.append({
                "type": "optimization_tip",
                "message": f"ROI({m.roi:.2f})表现优秀，建议适当提升预算放大收益",
            })
        return tips

    async def execute_stop_loss_action(self, campaign_id: str, action_type: str,  # 执行止损动作，通过协作引擎通知相关人员
                                         company_id: int) -> dict:
        logger.info("ad_stop_loss_executing", campaign=campaign_id, action=action_type)  # 记录止损执行
        from app.communication.collaboration import collaboration_engine  # 延迟导入避免循环依赖

        if action_type == "reduce_budget":
            await collaboration_engine.create_alert(  # 创建协作告警，通知相关Agent
                company_id=company_id,
                alert_type="ad_stop_loss",
                title="广告自动止损",
                message=f"广告计划 {campaign_id} CPA过高，已自动降低预算50%",
                severity="warning",  # 降预算用warning级别，因为计划仍在运行
                related_agents=["smart_ad_delivery"],
            )
            return {"campaign_id": campaign_id, "action": "budget_reduced",
                    "new_budget_pct": 50, "status": CampaignStatus.BUDGET_REDUCED.value}
        elif action_type == "pause_campaign":
            self._active_campaigns.pop(campaign_id, None)  # 从活跃列表中移除暂停的计划
            await collaboration_engine.create_alert(
                company_id=company_id,
                alert_type="ad_stop_loss",
                title="广告自动暂停",
                message=f"广告计划 {campaign_id} 已自动暂停（止损规则触发）",
                severity="critical",  # 暂停计划用critical级别，因为涉及损失
                related_agents=["smart_ad_delivery"],
            )
            return {"campaign_id": campaign_id, "action": "paused",
                    "status": CampaignStatus.PAUSED.value}

        return {"campaign_id": campaign_id, "action": action_type, "status": "unknown"}

    def get_active_campaigns(self) -> list[dict]:  # 返回活跃计划摘要列表，方便监控面板展示
        return [
            {"campaign_id": cid, "roi": m.roi, "cpa": m.cpa, "ctr": m.ctr_pct,
             "spend": m.spend, "revenue": m.revenue}
            for cid, m in self._active_campaigns.items()
        ]

    def get_stop_loss_log(self, limit: int = 20) -> list[dict]:  # 返回最近N条止损日志，默认20条
        return self._stop_loss_log[-limit:]  # 切片取尾部，即最新的记录


ad_engine = AdDeliveryEngine()  # 全局单例，确保整个应用使用同一个广告引擎实例
