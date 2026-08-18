"""
Data Analysis and Strategy MCP Server
Provides functionality to generate performance reports and strategy suggestions for KOL campaigns.
"""

import os
import sys

# Add the project root to Python path for standalone execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


from fastmcp import FastMCP

from app.core.logging import get_logger
from app.mcp_servers.mock_data import MOCK_PERFORMANCE_DATA, MOCK_STRATEGY_DATA
from app.services.model_gateway import ModelGateway
from app.tools.result import ToolResult, ErrorCode, ERROR_SUGGESTIONS

logger = get_logger(__name__)

# Create MCP server
mcp = FastMCP("report_server")


def _resolve_company_id(fallback: str = "default") -> str:
    """从 MCP 请求上下文中读取 company_id（优先），fallback 到参数值"""
    try:
        from fastmcp.server.context import get_request_context
        ctx = get_request_context()
        if ctx and hasattr(ctx, 'meta') and ctx.meta:
            return ctx.meta.get("company_id", fallback)
    except Exception:
        pass
    return fallback


# Singleton instance for ModelGateway
_model_gateway = None

def get_model_gateway():
    """Get singleton ModelGateway instance"""
    global _model_gateway
    if _model_gateway is None:
        _model_gateway = ModelGateway()
    return _model_gateway

@mcp.tool()
def generate_performance_report(kol_name: str, campaign_id: str) -> str:
    """
    Generate comprehensive performance report for a KOL campaign.
    First tries real platform API, falls back to mock data.
    """
    try:
        # Check if platform adapter is configured
        from app.platforms import get_platform_adapter
        platform_adapter = get_platform_adapter("douyin_star")

        if platform_adapter and platform_adapter.is_available():
            try:
                performance_data = platform_adapter.get_campaign_report(kol_name, campaign_id)
                if performance_data:
                    logger.info("report_platform_api_using", kol=kol_name, campaign=campaign_id)
                    result = _format_real_report(performance_data, kol_name, campaign_id)
                    return ToolResult.ok(data=result, message="Performance report generated from real API.").to_json()
            except Exception as e:
                logger.error("report_platform_error", error=str(e))

        # Fallback to mock data
        logger.warning("report_mock_fallback", kol=kol_name, campaign=campaign_id)
        result = _generate_mock_report(kol_name, campaign_id)
        return ToolResult.ok(data=result, message="Performance report generated from mock data.").to_json()
    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"生成报告时出错：{str(e)}",
            suggestion=ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR],
        ).to_json()


def _format_real_report(performance_data, kol_name, campaign_id):
    """Format real API data into a report"""
    model_gateway = get_model_gateway()
    llm = model_gateway.get_llm("deepseek")
    prompt = f"""
        请基于以下抖音星图平台的活动数据，为达人 {kol_name} 生成专业的表现分析报告：

        活动ID: {campaign_id}
        达人姓名: {performance_data.get('kol_name', kol_name)}
        活动名称: {performance_data.get('campaign_name', f'活动{campaign_id}')}
        活动期间: {performance_data.get('period', '2024-01-01 至 2024-01-31')}

        数据指标：
        - 总曝光量: {performance_data.get('metrics', {}).get('total_views', 0)}
        - 总点赞数: {performance_data.get('metrics', {}).get('total_likes', 0)}
        - 总评论数: {performance_data.get('metrics', {}).get('total_comments', 0)}
        - 总分享数: {performance_data.get('metrics', {}).get('total_shares', 0)}
        - ROI: {performance_data.get('metrics', {}).get('roi', 0)}%
        - CPM: {performance_data.get('metrics', {}).get('cpm', 0)}
        - CPC: {performance_data.get('metrics', {}).get('cpc', 0)}

        内容表现：
        {performance_data.get('content_performance', '')}

        建议：
        {performance_data.get('recommendations', [])}

        请生成结构化的分析报告，包含数据洞察、效果评估和优化建议。
        """
    response = llm.invoke(prompt)
    return response.content


def _generate_mock_report(kol_name: str, campaign_id: str) -> str:
    """Generate mock performance report"""
    performance_data = MOCK_PERFORMANCE_DATA.get(kol_name)
    if not performance_data:
        return f"未找到达人 {kol_name} 的活动数据，请检查达人姓名和活动ID。"

    roi = (performance_data['revenue'] - performance_data['cost']) / performance_data['cost'] * 100
    cpm = performance_data['cost'] / performance_data['exposure'] * 1000
    cpc = performance_data['cost'] / (performance_data['exposure'] * performance_data['click_rate'] / 100)
    cpa = performance_data['cost'] / performance_data['sales_count'] if performance_data['sales_count'] > 0 else 0

    model_gateway = get_model_gateway()
    llm = model_gateway.get_llm("deepseek")

    report_data = f"""📊 {kol_name} 活动表现报告

🎯 活动基本信息
• 活动ID: {campaign_id}
• 平台: {performance_data['platform']}
• 品类: {performance_data['category']}

📈 核心数据指标
• 曝光量: {performance_data['exposure']:,}
• 互动率: {performance_data['engagement_rate']}%
• 点击率: {performance_data['click_rate']}%
• 转化率: {performance_data['conversion_rate']}%

💰 商业表现
• 销售数量: {performance_data['sales_count']} 件
• 销售收入: ¥{performance_data['revenue']:,}
• 投入成本: ¥{performance_data['cost']:,}
• 投资回报率(ROI): {roi:.1f}%

📊 成本分析
• 千次展示成本(CPM): ¥{cpm:.2f}
• 单次点击成本(CPC): ¥{cpc:.2f}
• 获客成本(CPA): ¥{cpa:.2f}

"""
    prompt = f"""基于以下达人活动数据，请生成详细的分析报告和改进建议：

{report_data}

请从以下几个方面进行分析：
1. 整体表现评估（优秀/良好/一般/需改进）
2. 各项指标的行业对比分析
3. 优势和不足分析
4. 具体的优化建议
5. 后续合作建议

要求：
- 分析要客观专业
- 建议要具体可行
- 语言要简洁明了
- 重点突出关键发现"""
    response = llm.invoke(prompt)
    return report_data + "\n" + "="*50 + "\n" + response.content


@mcp.tool()
def generate_strategy_suggestion(platform: str, category: str) -> str:
    """
    Generate strategy suggestions based on platform and category.
    """
    try:
        platform_data = MOCK_STRATEGY_DATA.get(platform, {})
        category_data = platform_data.get(category, {})
        if not category_data:
            category_data = {
                "best_posting_time": "19:00-21:00",
                "optimal_duration": "60-90秒",
                "top_hashtags": ["#热门话题", "#种草推荐"],
                "avg_engagement": 6.5,
                "trending_formats": ["产品展示", "使用教程", "经验分享"]
            }

        model_gateway = get_model_gateway()
        llm = model_gateway.get_llm("deepseek")

        trending_formats_text = "\n".join(
            [f"• {fmt}" for fmt in category_data["trending_formats"]]
        )

        strategy_data = f"""
🎯 {platform}平台 {category}品类策略建议

⏰ 最佳发布时间
• 推荐时段: {category_data['best_posting_time']}
• 用户活跃度: 高峰期流量提升30-50%

📏 内容形式建议
• 最佳时长: {category_data['optimal_duration']}
• 热门标签: {', '.join(category_data['top_hashtags'])}
• 平均互动率: {category_data['avg_engagement']}%

🔥 热门内容形式
{trending_formats_text}

"""
        prompt = f"""
            基于{platform}平台{category}品类的数据洞察，请制定详细的达人营销策略：

            {strategy_data}

            请从以下几个方面制定策略：
            1. 达人选择标准和建议
            2. 内容创作指导原则
            3. 发布时间和频率策略
            4. 互动和用户维护策略
            5. 效果评估和优化建议
            6. 预算分配建议

            要求：
            - 策略要具体可执行
            - 结合平台特点和用户习惯
            - 包含具体的操作建议
            - 考虑成本效益和ROI
            """
        response = llm.invoke(prompt)
        result = strategy_data + "\n" + "="*50 + "\n" + response.content
        return ToolResult.ok(data=result, message="Strategy suggestion generated.").to_json()
    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"生成策略建议时出错：{str(e)}",
            suggestion=ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR],
        ).to_json()


if __name__ == "__main__":
    import os
    if os.getenv("RUN_AS_HTTP_SERVICE", "false").lower() == "true":
        import uvicorn
        from fastapi import FastAPI
        from pydantic import BaseModel

        class PerformanceReportRequest(BaseModel):
            kol_name: str
            campaign_id: str

        class StrategySuggestionRequest(BaseModel):
            platform: str
            category: str

        app = FastAPI()

        @app.post("/tools/generate_performance_report")
        async def generate_performance_report_endpoint(request: PerformanceReportRequest):
            return generate_performance_report(request.kol_name, request.campaign_id)

        @app.post("/tools/generate_strategy_suggestion")
        async def generate_strategy_suggestion_endpoint(request: StrategySuggestionRequest):
            return generate_strategy_suggestion(request.platform, request.category)

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "report"}

        port = int(os.getenv("PORT", "8104"))
        logger.info("report_server_starting", port=port)
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        mcp.run()
