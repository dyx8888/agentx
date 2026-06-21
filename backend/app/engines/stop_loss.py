"""
StopLossEngine - Deterministic ad delivery stop-loss rule evaluation engine
Zero LLM dependency, pure rule-based evaluation.
"""  # 纯规则驱动的广告止损引擎：通过预定义规则+eval表达式评估广告计划是否需要止损

from dataclasses import dataclass, field  # 数据模型定义
from datetime import datetime, timedelta  # 时间计算：触发时间、历史查询时间窗口
from enum import StrEnum  # 字符串枚举


class StopLossAction(StrEnum):  # 止损动作枚举，定义了所有可能的止损操作类型
    REDUCE_BUDGET_50 = "reduce_budget_50"  # 将日预算减半
    PAUSE_CAMPAIGN = "pause_campaign"  # 暂停计划
    REPLACE_CREATIVE = "replace_creative"  # 替换素材
    NOTIFY_ONLY = "notify_only"  # 仅通知，不自动执行
    HUMAN_CONFIRM = "human_confirm"  # 需要人工确认后才执行


class StopLossSeverity(StrEnum):  # 止损严重等级
    CRITICAL = "critical"  # 严重：需要立即自动执行
    WARNING = "warning"  # 警告：需要关注
    INFO = "info"  # 信息：仅供参考


@dataclass
class StopLossRule:  # 止损规则定义，每条规则包含触发条件和执行动作
    rule_id: str  # 规则唯一ID，如"SL-001"
    description: str  # 规则描述，用于日志和通知
    condition_expr: str  # eval表达式字符串，在受控上下文中执行
    action: StopLossAction  # 触发后执行的动作
    severity: StopLossSeverity  # 严重等级
    auto_execute: bool = False  # 是否自动执行：True=自动止损，False=仅通知
    notify_channels: list[str] = field(default_factory=lambda: ["dashboard", "ad_agent"])  # 通知渠道列表


@dataclass
class StopLossTrigger:  # 止损触发记录，保存每次触发的完整信息
    rule_id: str  # 触发的规则ID
    campaign_id: str  # 触发的广告计划ID
    campaign_name: str  # 计划名称
    triggered_at: str  # 触发时间
    reason: str  # 触发原因（规则描述）
    current_value: float  # 当前指标值
    threshold: float  # 阈值
    action: StopLossAction  # 将执行的动作
    severity: StopLossSeverity  # 严重等级
    auto_executed: bool  # 是否自动执行
    recommended_action: str  # 推荐的操作说明（人类可读）


@dataclass
class CampaignMetrics:  # 广告计划指标（与ad_delivery_engine中的CampaignMetrics不同，此为纯数据模型）
    campaign_id: str
    campaign_name: str
    platform: str  #投放平台
    daily_budget: float  # 日预算
    current_spend: float  # 当前消耗
    cpa: float  # 单次转化成本
    target_cpa: float  # 目标CPA
    roi: float  # 当前ROI
    breakeven_roi: float  # 盈亏平衡ROI
    ctr: float  # 点击率
    industry_avg_ctr: float  # 行业平均点击率
    impressions: int  # 曝光
    clicks: int  # 点击
    conversions: int  # 转化
    running_hours: float  # 已运行时长


class StopLossEngine:
    """Automatic stop-loss rule evaluation engine for ad delivery."""  # 自动止损引擎：预定义8条规则覆盖CPA/ROI/CTR/预算/转化等核心维度

    DEFAULT_RULES: list[StopLossRule] = [  # 默认规则集，涵盖电商广告最常见的止损场景
        StopLossRule(
            rule_id="SL-001",
            description="CPA \u8d85\u6807 1.5\u500d\u6301\u7eed2\u5c0f\u65f6 \u2192 \u964d\u9884\u7b9750%",  # 出价过高，降预算控制成本
            condition_expr="cpa > target_cpa * 1.5 and running_hours >= 2",
            action=StopLossAction.REDUCE_BUDGET_50,
            severity=StopLossSeverity.CRITICAL,
            auto_execute=True,  # 降预算风险可控，可自动执行
        ),
        StopLossRule(
            rule_id="SL-002",
            description="ROI \u4f4e\u4e8e\u76c8\u4e8f\u7ebf\u6301\u7eed4\u5c0f\u65f6 \u2192 \u6682\u505c\u8ba1\u5212",  # 持续亏损，必须暂停
            condition_expr="roi < breakeven_roi and running_hours >= 4",
            action=StopLossAction.PAUSE_CAMPAIGN,
            severity=StopLossSeverity.CRITICAL,
            auto_execute=True,
        ),
        StopLossRule(
            rule_id="SL-003",
            description="CTR \u4f4e\u4e8e\u884c\u4e1a\u5747\u503c50% \u2192 \u66ff\u6362\u7d20\u6750",  # 素材疲劳或定向不精准
            condition_expr="ctr < industry_avg_ctr * 0.5",
            action=StopLossAction.REPLACE_CREATIVE,
            severity=StopLossSeverity.WARNING,
            auto_execute=False,  # 替换素材需要人工审核
            notify_channels=["dashboard", "ad_agent", "content_operation"],
        ),
        StopLossRule(
            rule_id="SL-004",
            description="\u6d88\u8017 > \u65e5\u9884\u7b9790% \u4e14 ROI < 1 \u2192 \u6682\u505c\u8ba1\u5212",  # 避免预算耗尽但效果差
            condition_expr="current_spend > daily_budget * 0.9 and roi < 1.0",
            action=StopLossAction.PAUSE_CAMPAIGN,
            severity=StopLossSeverity.CRITICAL,
            auto_execute=True,
        ),
        StopLossRule(
            rule_id="SL-005",
            description="\u8fde\u7eed3\u5929 ROI < \u76c8\u4e8f\u7ebf \u2192 \u9700\u4eba\u5de5\u786e\u8ba4\u6682\u505c",  # 跨天趋势恶化，需人工确认
            condition_expr="consecutive_low_roi_days >= 3",
            action=StopLossAction.HUMAN_CONFIRM,
            severity=StopLossSeverity.WARNING,
            auto_execute=False,  # 涉及长期趋势判断
        ),
        StopLossRule(
            rule_id="SL-006",
            description="\u5355\u6b21\u8f6c\u5316\u6210\u672c > \u76ee\u6807CPA 3\u500d \u2192 \u7acb\u5373\u6682\u505c",  # 极端异常，必须立即止损
            condition_expr="cpa > target_cpa * 3",
            action=StopLossAction.PAUSE_CAMPAIGN,
            severity=StopLossSeverity.CRITICAL,
            auto_execute=True,
        ),
        StopLossRule(
            rule_id="SL-007",
            description="\u8f6c\u5316\u7387\u4e3a0\u6301\u7eed4\u5c0f\u65f6 \u2192 \u6682\u505c\u8ba1\u5212",  # 完全无转化但有花费
            condition_expr="conversions == 0 and running_hours >= 4 and current_spend > 0",
            action=StopLossAction.PAUSE_CAMPAIGN,
            severity=StopLossSeverity.CRITICAL,
            auto_execute=True,
        ),
        StopLossRule(
            rule_id="SL-008",
            description="\u70b9\u51fb\u7387\u4e3a0\u6301\u7eed1\u5c0f\u65f6 \u2192 \u66ff\u6362\u7d20\u6750+\u901a\u77e5",  # 素材完全没有吸引力
            condition_expr="clicks == 0 and running_hours >= 1 and impressions > 1000",
            action=StopLossAction.REPLACE_CREATIVE,
            severity=StopLossSeverity.WARNING,
            auto_execute=False,
            notify_channels=["dashboard", "ad_agent", "visual_designer", "content_operation"],  # 通知设计师和运营
        ),
    ]

    def __init__(self):
        self.rules = list(self.DEFAULT_RULES)  # 复制默认规则列表，支持后续增删
        self.trigger_history: dict[str, list[StopLossTrigger]] = {}  # 触发历史：按campaign_id分组

    def add_rule(self, rule: StopLossRule) -> None:  # 添加自定义止损规则
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:  # 删除止损规则，返回是否成功
        initial_len = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]  # 列表推导过滤
        return len(self.rules) < initial_len

    def evaluate(self, metrics: CampaignMetrics, consecutive_low_roi_days: int = 0) -> list[StopLossTrigger]:  # 遍历规则评估
        triggers = []

        for rule in self.rules:
            condition_met = self._evaluate_condition(rule, metrics, consecutive_low_roi_days)  # 使用eval检查条件
            if not condition_met:
                continue

            trigger = StopLossTrigger(  # 构建触发记录
                rule_id=rule.rule_id,
                campaign_id=metrics.campaign_id,
                campaign_name=metrics.campaign_name,
                triggered_at=datetime.now().isoformat(),
                reason=rule.description,
                current_value=self._get_current_value(rule, metrics),  # 当前指标值
                threshold=self._get_threshold(rule, metrics),  # 阈值
                action=rule.action,
                severity=rule.severity,
                auto_executed=rule.auto_execute,
                recommended_action=self._format_action(rule, metrics),
            )
            triggers.append(trigger)

            campaign_key = metrics.campaign_id
            if campaign_key not in self.trigger_history:
                self.trigger_history[campaign_key] = []
            self.trigger_history[campaign_key].append(trigger)

        return triggers

    def _evaluate_condition(self, rule: StopLossRule, m: CampaignMetrics, consecutive_low_roi_days: int) -> bool:  # 使用eval评估规则表达式
        try:
            ctx = {  # 构建受控的eval上下文，只暴露必要的变量
                "cpa": m.cpa,
                "target_cpa": m.target_cpa,
                "roi": m.roi,
                "breakeven_roi": m.breakeven_roi,
                "ctr": m.ctr,
                "industry_avg_ctr": m.industry_avg_ctr,
                "current_spend": m.current_spend,
                "daily_budget": m.daily_budget,
                "running_hours": m.running_hours,
                "conversions": m.conversions,
                "clicks": m.clicks,
                "impressions": m.impressions,
                "consecutive_low_roi_days": consecutive_low_roi_days,  # 跨天指标
            }
            return bool(eval(rule.condition_expr, {"__builtins__": {}}, ctx))  # 禁用builtins防止代码注入，只允许简单的逻辑表达式
        except Exception:  # eval异常时默认不触发，安全第一
            return False

    @staticmethod
    def _get_current_value(rule: StopLossRule, m: CampaignMetrics) -> float:  # 根据规则ID返回对应的当前指标值
        mapping = {  # 硬编码映射表，因为不同规则关注不同指标
            "SL-001": m.cpa,
            "SL-002": m.roi,
            "SL-003": m.ctr,
            "SL-004": m.current_spend,
            "SL-005": m.roi,
            "SL-006": m.cpa,
            "SL-007": float(m.conversions),  # 转float统一类型
            "SL-008": float(m.clicks),
        }
        return mapping.get(rule.rule_id, 0.0)

    @staticmethod
    def _get_threshold(rule: StopLossRule, m: CampaignMetrics) -> float:  # 根据规则ID返回对应的阈值
        mapping = {
            "SL-001": m.target_cpa * 1.5,  # CPA容忍1.5倍
            "SL-002": m.breakeven_roi,  # ROI盈亏线
            "SL-003": m.industry_avg_ctr * 0.5,  # CTR低于行业一半
            "SL-004": m.daily_budget * 0.9,  # 预算90%
            "SL-005": m.breakeven_roi,
            "SL-006": m.target_cpa * 3,  # CPA 3倍极端情况
            "SL-007": 1.0,  # 转化至少1个
            "SL-008": 1.0,  # 点击至少1次
        }
        return mapping.get(rule.rule_id, 0.0)

    @staticmethod
    def _format_action(rule: StopLossRule, m: CampaignMetrics) -> str:  # 格式化为人类可读的操作建议
        actions = {
            StopLossAction.REDUCE_BUDGET_50: f"\u3010\u81ea\u52a8\u6267\u884c\u3011\u5c06\u8ba1\u5212{m.campaign_name}\u65e5\u9884\u7b97\u4ece{m.daily_budget}\u964d\u81f3{m.daily_budget/2}",
            StopLossAction.PAUSE_CAMPAIGN: f"\u3010\u81ea\u52a8\u6267\u884c\u3011\u6682\u505c\u8ba1\u5212{m.campaign_name}\uff0c\u907f\u514d\u7ee7\u7eed\u4e8f\u635f",
            StopLossAction.REPLACE_CREATIVE: f"\u3010\u5f85\u786e\u8ba4\u3011\u5efa\u8bae\u66ff\u6362\u8ba1\u5212{m.campaign_name}\u7684\u6295\u653e\u7d20\u6750",
            StopLossAction.NOTIFY_ONLY: f"\u3010\u901a\u77e5\u3011\u8ba1\u5212{m.campaign_name}\u5b58\u5728\u98ce\u9669\uff0c\u8bf7\u5173\u6ce8",
            StopLossAction.HUMAN_CONFIRM: f"\u3010\u9700\u786e\u8ba4\u3011\u8ba1\u5212{m.campaign_name}\u8fde\u7eed\u4f4eROI\uff0c\u5efa\u8bae\u6682\u505c\uff0c\u8bf7\u4eba\u5de5\u786e\u8ba4",
        }
        return actions.get(rule.action, str(rule.action))  # 未知动作类型回退到字符串表示

    def get_trigger_history(self, campaign_id: str, hours: int = 24) -> list[StopLossTrigger]:  # 获取指定时间窗口内的触发历史
        all_triggers = self.trigger_history.get(campaign_id, [])
        cutoff = datetime.now() - timedelta(hours=hours)  # 计算截止时间
        return [t for t in all_triggers if datetime.fromisoformat(t.triggered_at) > cutoff]  # 过滤出在窗口内的记录
