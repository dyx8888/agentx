"""
MetricsEngine - Deterministic e-commerce metric calculation engine
Zero LLM dependency, pure computation.
"""  # 纯计算指标引擎：所有电商核心指标（GMV/ROI/CPA/CTR/CVR等）通过数学公式计算，无LLM依赖

from dataclasses import dataclass, field  # 数据模型定义
from datetime import date, timedelta  # 日期计算：趋势预测和报告生成


@dataclass
class EcommerceMetrics:  # 电商核心指标聚合模型，所有指标集中在一个对象中便于传递
    gmv: float = 0.0  # 总成交额
    refund_amount: float = 0.0  # 退款金额
    net_gmv: float = 0.0  # 净GMV = GMV - 退款
    ad_spend: float = 0.0  # 广告花费
    impressions: int = 0  # 曝光量
    clicks: int = 0  # 点击量
    conversions: int = 0  # 转化量
    orders: int = 0  # 订单数
    unique_buyers: int = 0  # 独立买家数
    repeat_buyers: int = 0  # 复购买家数
    roi: float = 0.0  # 投资回报率 = GMV / 广告花费
    cpa: float = 0.0  # 单次转化成本 = 广告花费 / 转化数
    ctr: float = 0.0  # 点击率 = 点击 / 曝光
    cvr: float = 0.0  # 转化率 = 转化 / 点击
    gpm: float = 0.0  # 千次曝光成交额
    aov: float = 0.0  # 客单价 = GMV / 订单数
    repurchase_rate: float = 0.0  # 复购率
    refund_rate: float = 0.0  # 退款率


@dataclass
class AnomalyResult:  # 指标异常检测结果
    metric_name: str  # 指标名称
    current_value: float  # 当前值
    baseline_value: float  # 基准值（用于对比）
    deviation_pct: float  # 偏离百分比
    severity: str  # 严重等级：red/orange/yellow
    direction: str  # 偏离方向：up/down
    possible_causes: list[str] = field(default_factory=list)  # 可能原因
    suggested_actions: list[str] = field(default_factory=list)  # 建议操作


class MetricsEngine:
    """Deterministic calculation engine for e-commerce core metrics."""  # 指标计算引擎：全部静态方法，无状态

    ALERT_THRESHOLDS: dict[str, dict[str, float]] = {  # 各指标的异常阈值配置（red/orange/yellow三级）
        "gmv": {"red": 0.20, "orange": 0.10, "yellow": 0.05},  # GMV下降20%/10%/5%
        "roi": {"red": 0.30, "orange": 0.15, "yellow": 0.05},  # ROI下降30%/15%/5%
        "ctr": {"red": 0.50, "orange": 0.30, "yellow": 0.15},  # CTR下降50%/30%/15%
        "refund_rate": {"red": 0.05, "orange": 0.03, "yellow": 0.01},  # 退款率绝对值阈值：5%/3%/1%
        "cpa": {"red": 0.50, "orange": 0.30, "yellow": 0.15},  # CPA上升50%/30%/15%
    }

    ANOMALY_CAUSES: dict[str, list[str]] = {  # 各指标异常的常见原因库，用于生成诊断建议
        "gmv": [
            "\u6295\u653e\u8d39\u7528\u51cf\u5c11\u5bfc\u81f4\u6d41\u91cf\u4e0b\u964d",
            "\u7ade\u54c1\u4fc3\u9500\u6d3b\u52a8\u62a2\u5360\u4efd\u989d",
            "\u5b63\u8282\u6027\u6d88\u8d39\u6de1\u5b63\u6765\u4e34",
            "\u5546\u54c1\u8f6c\u5316\u7387\u5f02\u5e38\u4e0b\u964d",
            "\u5e73\u53f0\u6d41\u91cf\u5206\u914d\u7b56\u7565\u53d8\u5316",
        ],
        "roi": [
            "\u7d20\u6750\u52b3\u5316\u5bfc\u81f4CTR\u4e0b\u964d",
            "\u7ade\u54c1\u52a0\u5927\u6295\u653e\u62ac\u9ad8\u6210\u672c",
            "\u4eba\u7fa4\u5305\u7cbe\u51c6\u5ea6\u4e0b\u964d",
            "\u5546\u54c1\u5b9a\u4ef7\u7b56\u7565\u5931\u6548",
        ],
        "ctr": [
            "\u7d20\u6750\u521b\u610f\u8870\u9000\u9700\u66f4\u65b0",
            "\u76ee\u6807\u4eba\u7fa4\u5ba1\u7f8e\u75b2\u52b3",
            "\u5e73\u53f0\u7b97\u6cd5\u8c03\u6574\u5bfc\u81f4\u5c55\u793a\u4e0b\u964d",
        ],
        "refund_rate": [
            "\u5546\u54c1\u8d28\u91cf\u95ee\u9898",
            "\u5b9e\u7269\u4e0e\u63cf\u8ff0\u4e0d\u7b26",
            "\u7269\u6d41\u635f\u574f\u5bfc\u81f4\u9000\u8d27",
            "\u7ade\u54c1\u964d\u4ef7\u5bfc\u81f4\u4e70\u5bb6\u53cd\u6094",
        ],
        "cpa": [
            "\u7d20\u6750\u8f6c\u5316\u7387\u4e0b\u964d",
            "\u7ade\u54c1\u62ac\u4ef7",
            "\u4eba\u7fa4\u7ade\u4e89\u52a0\u5267",
            "\u843d\u5730\u9875\u8f6c\u5316\u7387\u4f4e",
        ],
    }

    @staticmethod
    def calculate_metrics(  # 从原始数据计算所有衍生电商指标
        payment_amount: float = 0.0,
        refund_amount: float = 0.0,
        ad_spend: float = 0.0,
        impressions: int = 0,
        clicks: int = 0,
        conversions: int = 0,
        orders: int = 0,
        unique_buyers: int = 0,
        repeat_buyers: int = 0,
    ) -> EcommerceMetrics:
        metrics = EcommerceMetrics(  # 先填充直接传入的基础指标
            gmv=payment_amount,
            refund_amount=refund_amount,
            net_gmv=payment_amount - refund_amount,  # 净GMV自动计算
            ad_spend=ad_spend,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            orders=orders,
            unique_buyers=unique_buyers,
            repeat_buyers=repeat_buyers,
        )

        if impressions > 0:  # 有曝光时才计算CTR和GPM，避免除零
            metrics.ctr = round(clicks / impressions * 100, 2)  # 百分比，保留2位小数
            metrics.gpm = round(payment_amount / impressions * 1000, 2)  # 千次曝光GMV

        if clicks > 0:  # 有点击时才计算CVR
            metrics.cvr = round(conversions / clicks * 100, 2)

        if conversions > 0:  # 有转化时才计算CPA
            metrics.cpa = round(ad_spend / conversions, 2)

        if ad_spend > 0:  # 有花费时才计算ROI
            metrics.roi = round(payment_amount / ad_spend, 2)

        if orders > 0:  # 有订单时才计算AOV和退款率
            metrics.aov = round(payment_amount / orders, 2)
            metrics.refund_rate = round(refund_amount / payment_amount * 100, 2) if payment_amount > 0 else 0.0

        if unique_buyers > 0:  # 有买家时才计算复购率
            metrics.repurchase_rate = round(repeat_buyers / unique_buyers * 100, 2)

        return metrics

    @staticmethod
    def detect_anomaly(  # 检测指标异常：计算偏离度→匹配阈值等级→生成原因和建议
        metric_name: str,
        current_value: float,
        baseline_value: float,
    ) -> AnomalyResult | None:
        if baseline_value <= 0:  # 基准值为0或负数时无法计算偏离度
            return None

        deviation = (current_value - baseline_value) / baseline_value  # 偏离度 = (当前-基准) / 基准
        abs_deviation = abs(deviation)  # 取绝对值判断严重程度

        thresholds = MetricsEngine.ALERT_THRESHOLDS.get(metric_name, {})  # 获取该指标的阈值配置
        if not thresholds or abs_deviation < thresholds.get("yellow", 0.05):  # 低于最低阈值则不告警
            return None

        if abs_deviation >= thresholds.get("red", 0.20):  # 逐级匹配严重等级
            severity = "red"
        elif abs_deviation >= thresholds.get("orange", 0.10):
            severity = "orange"
        else:
            severity = "yellow"

        direction = "up" if deviation > 0 else "down"  # 偏离方向
        causes = MetricsEngine.ANOMALY_CAUSES.get(metric_name, ["\u672a\u77e5\u539f\u56e0"])  # 获取可能原因
        actions = MetricsEngine._get_suggested_actions(metric_name, severity, direction)  # 获取建议操作

        return AnomalyResult(
            metric_name=metric_name,
            current_value=current_value,
            baseline_value=baseline_value,
            deviation_pct=round(deviation * 100, 2),  # 转为百分比
            severity=severity,
            direction=direction,
            possible_causes=causes,
            suggested_actions=actions,
        )

    @staticmethod
    def _get_suggested_actions(metric_name: str, severity: str, direction: str) -> list[str]:  # 根据指标+方向+严重等级生成操作建议
        actions_map: dict[str, dict[str, list[str]]] = {  # 三级映射：指标→方向(up/down)→建议列表
            "gmv": {
                "down": [
                    "\u68c0\u67e5\u6295\u653e\u8ba1\u5212\u662f\u5426\u88ab\u6682\u505c\u6216\u964d\u9884\u7b97",
                    "\u5206\u6790\u7ade\u54c1\u8fd1\u671f\u4fc3\u9500\u7b56\u7565",
                    "\u67e5\u770b\u5546\u54c1\u8f6c\u5316\u6f0f\u6597\u662f\u5426\u51fa\u73b0\u95ee\u9898",
                    "\u786e\u8ba4\u5e73\u53f0\u6d41\u91cf\u5206\u914d\u662f\u5426\u6b63\u5e38",
                ],
                "up": ["\u5206\u6790\u589e\u957f\u9a71\u52a8\u56e0\u7d20\uff0c\u590d\u5236\u6210\u529f\u7b56\u7565"],
            },
            "roi": {
                "down": [
                    "\u7d27\u6025\u6682\u505c\u4f4e\u6548\u8ba1\u5212\uff0c\u907f\u514d\u4e8f\u635f\u6269\u5927",
                    "\u66f4\u6362\u4f4eCTR\u7d20\u6750\uff0c\u4f7f\u7528\u5386\u53f2\u9ad8\u6548\u7d20\u6750",
                    "\u8c03\u6574\u4eba\u7fa4\u5305\uff0c\u6536\u7a84\u5b9a\u5411\u81f3\u9ad8\u8f6c\u5316\u4eba\u7fa4",
                    "\u68c0\u67e5\u5546\u54c1\u5b9a\u4ef7\u662f\u5426\u9700\u8981\u8c03\u6574",
                ],
                "up": ["\u9002\u5f53\u52a0\u5927\u9884\u7b97\u6295\u653e\uff0c\u6269\u5927\u76c8\u5229\u89c4\u6a21"],
            },
            "ctr": {
                "down": [
                    "\u66f4\u6362\u7d20\u6750\u521b\u610f\u65b9\u5411",
                    "\u8f6e\u6362\u65b0\u7d20\u6750\uff0c\u907f\u514d\u4eba\u7fa4\u5ba1\u7f8e\u75b2\u52b3",
                    "\u8c03\u6574\u6807\u9898/\u5c01\u9762\u7b56\u7565",
                ],
                "up": ["\u8bb0\u5f55\u9ad8\u6548\u7d20\u6750\u7279\u5f81\uff0c\u5f62\u6210\u7d20\u6750\u6a21\u677f"],
            },
            "refund_rate": {
                "up": [
                    "\u7acb\u5373\u68c0\u67e5\u8fd1\u671f\u8d28\u91cf\u53cd\u9988\u548c\u5dee\u8bc4",
                    "\u6838\u5b9e\u4ed3\u50a8\u53d1\u8d27\u662f\u5426\u51fa\u73b0\u95ee\u9898",
                    "\u901a\u77e5\u5ba2\u670d\u52a0\u5f3a\u552e\u540e\u5904\u7406",
                    "\u6682\u505c\u95ee\u9898SKU\u7684\u6295\u653e\u63a8\u5e7f",
                ],
                "down": [],  # 退款率下降是好事，无建议
            },
            "cpa": {
                "up": [
                    "\u964d\u4f4e\u51fa\u4ef7\u81f3\u53ef\u63a5\u53d7\u8303\u56f4",
                    "\u4f18\u5316\u4eba\u7fa4\u5b9a\u5411\u7cbe\u51c6\u5ea6",
                    "\u68c0\u67e5\u843d\u5730\u9875\u8f6c\u5316\u7387\u662f\u5426\u4e0b\u964d",
                ],
                "down": ["\u4fdd\u6301\u5f53\u524d\u7b56\u7565\uff0c\u53ef\u9002\u5f53\u52a0\u5927\u9884\u7b97"],
            },
        }

        metric_actions = actions_map.get(metric_name, {})
        direction_actions = metric_actions.get(direction, ["\u8fdb\u4e00\u6b65\u5206\u6790\u786e\u8ba4\u539f\u56e0"])

        if severity == "red":  # 红色等级的建议前加【紧急】标记
            direction_actions = ["\u3010\u7d27\u6025\u3011" + action for action in direction_actions]

        return direction_actions

    @staticmethod
    def trend_forecast(historical_data: list[float], days_ahead: int = 7) -> list[dict]:  # 使用简单线性回归预测未来趋势
        if len(historical_data) < 3:  # 样本量不足3天时无法做有意义的回归，返回全零预测
            return [{"day": i + 1, "forecast": 0.0, "confidence": "low"} for i in range(days_ahead)]

        n = len(historical_data)
        x_mean = (n - 1) / 2.0  # x的均值（天数索引的中心）
        y_mean = sum(historical_data) / n  # y的均值（指标均值）

        numerator = sum((i - x_mean) * (historical_data[i] - y_mean) for i in range(n))  # 协方差分子
        denominator = sum((i - x_mean) ** 2 for i in range(n))  # x的方差分母

        slope = numerator / denominator if denominator != 0 else 0.0  # 线性回归斜率（趋势方向）
        intercept = y_mean - slope * x_mean  # 截距

        variance = sum(  # 计算拟合方差用于置信区间
            (historical_data[i] - (slope * i + intercept)) ** 2 for i in range(n)
        ) / n
        std_dev = variance ** 0.5  # 标准差

        forecasts = []
        for i in range(1, days_ahead + 1):
            day_idx = n + i - 1  # 未来的索引位置
            forecast_value = max(0.0, slope * day_idx + intercept)  # 预测值不低于0

            if i <= 3:  # 短期预测置信度高
                confidence = "high"
            elif i <= 7:  # 中期预测置信度中
                confidence = "medium"
            else:  # 长期预测置信度低
                confidence = "low"

            forecasts.append({
                "day": i,
                "date": str(date.today() + timedelta(days=i)),  # 对应日历日期
                "forecast": round(forecast_value, 2),
                "lower_bound": round(max(0.0, forecast_value - std_dev * 1.96), 2),  # 95%置信区间下界
                "upper_bound": round(forecast_value + std_dev * 1.96, 2),  # 95%置信区间上界
                "confidence": confidence,
            })

        return forecasts

    @staticmethod
    def generate_comprehensive_report(  # 生成综合分析报告：指标汇总+异常检测+趋势预测+优化建议
        metrics: EcommerceMetrics,
        historical_gmv: list[float] = None,
        platform: str = "",
    ) -> dict:
        report = {
            "summary": {},
            "core_metrics": {  # 核心指标明细
                "gmv": metrics.gmv,
                "net_gmv": metrics.net_gmv,
                "roi": metrics.roi,
                "cpa": metrics.cpa,
                "ctr": metrics.ctr,
                "cvr": metrics.cvr,
                "gpm": metrics.gpm,
                "aov": metrics.aov,
                "repurchase_rate": metrics.repurchase_rate,
                "refund_rate": metrics.refund_rate,
            },
            "anomalies": [],
            "forecast": [],
            "optimization_suggestions": [],
        }

        if metrics.roi < 1.0:  # ROI低于盈亏线→高优先级告警
            report["optimization_suggestions"].append({
                "priority": "high",
                "area": "\u6295\u653eROI",
                "issue": f"ROI={metrics.roi}\uff0c\u4f4e\u4e8e\u76c8\u4e8f\u5e73\u8861\u7ebf",
                "suggestion": "\u7acb\u5373\u6682\u505c\u4f4e\u6548\u8ba1\u5212\uff0c\u4f18\u5316\u7d20\u6750\u548c\u4eba\u7fa4\u540e\u91cd\u65b0\u6295\u653e",
            })

        if metrics.refund_rate > 5.0:  # 退款率超过5%→高优先级
            report["optimization_suggestions"].append({
                "priority": "high",
                "area": "\u9000\u8d27\u7387",
                "issue": f"\u9000\u8d27\u7387={metrics.refund_rate}%\uff0c\u8d85\u8fc7\u6b63\u5e38\u8303\u56f4",
                "suggestion": "\u68c0\u67e5\u5546\u54c1\u8d28\u91cf\u548c\u7269\u6d41\u73af\u8282\uff0c\u901a\u77e5\u5ba2\u670d\u52a0\u5f3a\u552e\u540e",
            })

        if metrics.ctr < 1.0:  # CTR低于1%→中优先级
            report["optimization_suggestions"].append({
                "priority": "medium",
                "area": "\u70b9\u51fb\u7387",
                "issue": f"CTR={metrics.ctr}%\uff0c\u4f4e\u4e8e\u884c\u4e1a\u5747\u503c",
                "suggestion": "\u66f4\u6362\u7d20\u6750\u521b\u610f\uff0c\u4f18\u5316\u6807\u9898\u548c\u5c01\u9762",
            })

        if historical_gmv and len(historical_gmv) >= 7:  # 有足够历史数据时才做趋势预测
            report["forecast"] = MetricsEngine.trend_forecast(historical_gmv, 7)

        if platform:  # 附加平台信息
            report["platform"] = platform

        return report
