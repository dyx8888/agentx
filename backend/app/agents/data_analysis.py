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
                    diff = "N/A"
                else:
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

        message_lower = message.lower()

        # 根据消息内容决定分析类型
        if any(kw in message_lower for kw in ["roi", "投入产出", "投产比", "投放效果"]):
            # ROI 分析
            roi_result = calculate_roi(gmv=100000, ad_spend=20000)
            return format_analysis_report(roi_data=roi_result)

        elif any(kw in message_lower for kw in ["数据质量", "数据完整性", "数据准确性"]):
            # 数据质量分析
            quality_result = analyze_data_quality(
                {
                    "gmv": 100000,
                    "orders": 500,
                    "roi": 3.0,
                }
            )
            return format_analysis_report(quality_data=quality_result)

        elif any(kw in message_lower for kw in ["竞品", "对标", "竞争分析"]):
            # 竞品分析
            competitor_result = competitor_analysis(
                own_data={"gmv": 100000, "followers": 50000, "engagement_rate": 3.0},
                competitor_data={"gmv": 150000, "followers": 80000, "engagement_rate": 2.5},
            )
            return format_analysis_report(competitor_data=competitor_result)

        else:
            # 综合报告
            roi_result = calculate_roi(gmv=100000, ad_spend=20000)
            quality_result = analyze_data_quality(
                {
                    "gmv": 100000,
                    "orders": 500,
                    "roi": 3.0,
                }
            )
            return format_analysis_report(
                roi_data=roi_result,
                quality_data=quality_result,
            )

    return data_analysis_agent
