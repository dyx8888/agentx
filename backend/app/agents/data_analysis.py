"""
数据分析 Agent - 数据质量分析、ROI 计算、竞品分析
负责：指标计算、异常检测、趋势预测、复盘报告、竞品对标
"""

import structlog

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "1.0.0"
PROMPT_UPDATED = "2026-06-21"

DATA_ANALYSIS_SYSTEM_PROMPT = """你是数据分析数字员工，负责为品牌方提供电商全链路数据分析与洞察。

## 核心职责
1. **ROI 分析**：计算 GMV、ROI、CPA、CTR、CVR 等核心指标，评估投放效果
2. **数据质量分析**：检查数据完整性、一致性、准确性，发现数据问题
3. **竞品分析**：对标竞品数据，找出差距和机会点
4. **趋势预测**：基于历史数据预测未来趋势
5. **复盘报告**：周报/月报/大促复盘，数据驱动优化建议

## 指标计算标准
- ROI = GMV / 投放费用
- CPA = 投放费用 / 转化数
- 利润 = GMV - 投放费用 - 成本

## 输出规范
- 报告格式：摘要 → 核心指标速览 → 分析发现 → 优化建议
- 所有数据需标注数据来源和时间范围
- 优化建议需有优先级排序和可操作性说明
"""


def calculate_roi(gmv: float, ad_spend: float, cost: float = 0) -> dict:
    """计算 ROI 及相关指标

    Args:
        gmv: 成交总额
        ad_spend: 投放费用
        cost: 其他成本（商品成本等）

    Returns:
        dict: 包含 roi, gmv, ad_spend, profit 等指标
    """
    roi = 0.0 if ad_spend == 0 else round(gmv / ad_spend, 2)

    profit = gmv - ad_spend - cost

    return {
        "roi": roi,
        "gmv": gmv,
        "ad_spend": ad_spend,
        "cost": cost,
        "profit": profit,
    }


NO_REAL_DATA_MESSAGE = (
    "当前企业暂无可用的真实销售/投放数据，未生成指标或预测。"
    "请先接入店铺、广告平台或导入数据后重试。"
)
_METRIC_KEYS = {
    "gmv",
    "payment_amount",
    "refund_amount",
    "ad_spend",
    "impressions",
    "clicks",
    "conversions",
    "orders",
    "unique_buyers",
    "repeat_buyers",
}


def _read_metric_data(kwargs: dict) -> dict:
    """Read caller-provided metrics without inventing a business data source."""
    for key in ("metrics_data", "sales_data", "business_data"):
        value = kwargs.get(key)
        if isinstance(value, dict) and any(name in value for name in _METRIC_KEYS):
            return value
    return {}


def _metric_value(data: dict, *keys: str) -> float:
    for key in keys:
        value = data.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def calculate_sales_summary(
    *,
    orders: float = 0,
    gmv: float = 0,
    ad_spend: float = 0,
    refund_amount: float = 0,
) -> dict[str, float]:
    """Calculate a deterministic summary for explicitly supplied sales metrics.

    This function deliberately does not load tenant or platform data. Callers
    must label the result as user-provided and pass only values extracted from
    the current request.
    """
    orders_value = float(orders or 0)
    gmv_value = round(float(gmv or 0), 2)
    ad_spend_value = round(float(ad_spend or 0), 2)
    refund_value = round(float(refund_amount or 0), 2)
    net_sales = round(gmv_value - refund_value, 2)
    roas = 0.0 if ad_spend_value == 0 else round(gmv_value / ad_spend_value, 2)

    return {
        "orders": int(orders_value) if orders_value.is_integer() else round(orders_value, 2),
        "gmv": gmv_value,
        "ad_spend": ad_spend_value,
        "refund_amount": refund_value,
        "net_sales": net_sales,
        "roas": roas,
    }


def _format_display_number(value: float | int) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def format_sales_analysis_report(
    summary: dict[str, float],
    *,
    source_label: str,
    provided_fields: set[str] | None = None,
) -> str:
    """Format a user-provided sales calculation without presenting it as real data."""
    provided = set(provided_fields or summary.keys())

    orders = (
        _format_display_number(summary["orders"])
        if "orders" in provided
        else "未提供"
    )
    gmv = _format_display_number(summary["gmv"]) if "gmv" in provided else "未提供"
    ad_spend = (
        _format_display_number(summary["ad_spend"])
        if "ad_spend" in provided
        else "未提供"
    )
    refund = (
        _format_display_number(summary["refund_amount"])
        if "refund_amount" in provided
        else "未提供"
    )
    if {"gmv", "refund_amount"}.issubset(provided):
        net_sales = _format_display_number(summary["net_sales"])
    else:
        net_sales = "无法计算（需要销售额和退款）"
    if {"gmv", "ad_spend"}.issubset(provided) and summary["ad_spend"]:
        roas = _format_display_number(summary["roas"])
    else:
        roas = "无法计算（需要销售额和广告费）"

    return "\n".join(
        [
            "## 销售分析报告",
            f"- 数据来源：{source_label}",
            "- 口径：仅计算本条消息明确提供的数值，未查询企业或平台真实数据。",
            f"- 总订单：{orders}",
            f"- 总销售额：{gmv}",
            f"- 总广告费：{ad_spend}",
            f"- 总退款：{refund}",
            f"- 净销售额：{net_sales}",
            f"- ROAS：{roas}",
        ]
    )


def analyze_data_quality(data: dict) -> dict:
    """分析数据质量

    Args:
        data: 待检查的数据字典

    Returns:
        dict: 包含 completeness（完整度 0-1）和 issues（问题列表）
    """
    if not data:
        return {"completeness": 0.0, "issues": ["数据为空"]}

    total_fields = len(data)
    missing_fields = []

    for key, value in data.items():
        if value is None or value == "":
            missing_fields.append(key)

    completeness = round((total_fields - len(missing_fields)) / total_fields, 2)

    issues = []
    if missing_fields:
        issues.append(f"缺少字段: {', '.join(missing_fields)}")

    return {
        "completeness": completeness,
        "issues": issues,
    }


def competitor_analysis(own_data: dict, competitor_data: dict) -> dict:
    """竞品对比分析

    Args:
        own_data: 自身数据
        competitor_data: 竞品数据

    Returns:
        dict: 包含 comparison, advantage, disadvantage
    """
    comparison = {}
    advantage = []
    disadvantage = []

    for key in own_data:
        if key in competitor_data:
            own_val = own_data[key]
            comp_val = competitor_data[key]

            if isinstance(own_val, (int, float)) and isinstance(comp_val, (int, float)):
                if comp_val == 0:
                    comparison[key] = "N/A"
                    continue

                diff_pct = round((own_val - comp_val) / comp_val * 100, 1)
                diff = f"{diff_pct:+}%"
                comparison[key] = diff

                if diff_pct > 0:
                    advantage.append(f"{key} 领先 {abs(diff_pct)}%")
                elif diff_pct < 0:
                    disadvantage.append(f"{key} 落后 {abs(diff_pct)}%")

    return {
        "comparison": comparison,
        "advantage": advantage,
        "disadvantage": disadvantage,
    }


def format_analysis_report(
    roi_data: dict | None = None,
    quality_data: dict | None = None,
    competitor_data: dict | None = None,
) -> str:
    """格式化分析报告

    Args:
        roi_data: ROI 计算数据
        quality_data: 数据质量分析数据
        competitor_data: 竞品分析数据

    Returns:
        str: 格式化后的分析报告
    """
    lines = ["## 数据分析报告\n"]
    has_content = False

    if roi_data:
        has_content = True
        lines.append("### ROI 分析")
        lines.append(f"- GMV: {roi_data.get('gmv', 'N/A')}")
        lines.append(f"- 投放费用: {roi_data.get('ad_spend', 'N/A')}")
        lines.append(f"- ROI: {roi_data.get('roi', 'N/A')}")
        if roi_data.get("profit") is not None:
            lines.append(f"- 利润: {roi_data.get('profit')}")
        lines.append("")

    if quality_data:
        has_content = True
        lines.append("### 数据质量")
        lines.append(f"- 完整度: {quality_data.get('completeness', 'N/A')}")
        issues = quality_data.get("issues", [])
        if issues:
            for issue in issues:
                lines.append(f"- 问题: {issue}")
        lines.append("")

    if competitor_data:
        has_content = True
        lines.append("### 竞品分析")
        comparison = competitor_data.get("comparison", {})
        for key, val in comparison.items():
            lines.append(f"- {key}: {val}")
        advantage = competitor_data.get("advantage", [])
        if advantage:
            lines.append("\n**优势**:")
            for adv in advantage:
                lines.append(f"- {adv}")
        disadvantage = competitor_data.get("disadvantage", [])
        if disadvantage:
            lines.append("\n**劣势**:")
            for dis in disadvantage:
                lines.append(f"- {dis}")
        lines.append("")

    if not has_content:
        lines.append("暂无数据可供分析。")

    return "\n".join(lines)


async def get_agent_function():
    """返回数据分析 Agent 的可调用函数"""

    async def data_analysis_agent(message: str, **kwargs) -> str:
        """数据分析 Agent 主入口

        Args:
            message: 用户消息
            **kwargs: 额外参数（session, company_id 等）

        Returns:
            str: 分析结果
        """
        logger.info(
            "data_analysis_agent_called",
            message=message[:100],
        )

        metrics_data = _read_metric_data(kwargs)
        if not metrics_data:
            return NO_REAL_DATA_MESSAGE

        message_lower = message.lower()
        gmv = _metric_value(metrics_data, "gmv", "payment_amount")
        ad_spend = _metric_value(metrics_data, "ad_spend")
        cost = _metric_value(metrics_data, "cost")

        # 根据消息内容决定分析类型
        if any(kw in message_lower for kw in ["roi", "投入产出", "投产比", "投放效果"]):
            # ROI 分析
            roi_result = calculate_roi(gmv=gmv, ad_spend=ad_spend, cost=cost)
            return format_analysis_report(roi_data=roi_result)

        elif any(kw in message_lower for kw in ["数据质量", "数据完整性", "数据准确性"]):
            # 数据质量分析
            quality_result = analyze_data_quality(metrics_data)
            return format_analysis_report(quality_data=quality_result)

        elif any(kw in message_lower for kw in ["竞品", "对标", "竞争分析"]):
            # 竞品分析
            competitor_data = kwargs.get("competitor_data")
            if not isinstance(competitor_data, dict):
                return NO_REAL_DATA_MESSAGE
            competitor_result = competitor_analysis(metrics_data, competitor_data)
            return format_analysis_report(competitor_data=competitor_result)

        else:
            # 综合报告
            roi_result = calculate_roi(gmv=gmv, ad_spend=ad_spend, cost=cost)
            quality_result = analyze_data_quality(metrics_data)
            return format_analysis_report(
                roi_data=roi_result,
                quality_data=quality_result,
            )

    return data_analysis_agent
