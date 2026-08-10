"""
Monitoring and Reminder MCP Server
Provides functionality to check delivery status and generate reminder messages for KOLs.
"""

from fastmcp import FastMCP

from app.core.logging import get_logger
from app.mcp_servers.mock_data import MOCK_DELIVERY_STATUS
from app.services.model_gateway import ModelGateway
from app.tools.result import ToolResult, ErrorCode, ERROR_SUGGESTIONS

logger = get_logger(__name__)

# Create MCP server
mcp = FastMCP("monitor_server")


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
def check_delivery_status(order_id: str) -> str:
    """
    Check delivery status for a given order ID.
    
    Args:
        order_id: The order ID to check (e.g., "ORD001")
    
    Returns:
        Delivery status information including tracking details
    """
    try:
        # Get mock delivery status
        delivery_info = MOCK_DELIVERY_STATUS.get(order_id)

        if not delivery_info:
            return ToolResult.error(
                error_code=ErrorCode.INVALID_PARAMS,
                message=f"订单 {order_id} 未找到，请检查订单号是否正确。",
                suggestion=ERROR_SUGGESTIONS[ErrorCode.INVALID_PARAMS],
            ).to_json()

        # Format response
        response = f"""
📦 订单状态查询结果

🔍 订单号：{order_id}
📋 当前状态：{delivery_info['status']}
🚚 快递单号：{delivery_info['tracking_number']}
📅 预计送达：{delivery_info['estimated_delivery']}

"""

        # Add status-specific information
        if delivery_info['status'] == "已发货":
            response += "✅ 商品已从仓库发出，正在配送途中"
        elif delivery_info['status'] == "运输中":
            response += "🚚 快递正在运输中，请耐心等待"
        elif delivery_info['status'] == "已签收":
            response += "🎉 商品已成功签收，请注意查收"
        elif delivery_info['status'] == "异常":
            response += "⚠️ 配送出现异常，请联系客服处理"

        return ToolResult.ok(data=response, message="Delivery status retrieved.").to_json()

    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"查询配送状态时出错：{str(e)}",
            suggestion=ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR],
        ).to_json()

@mcp.tool()
def generate_arrival_script(kol_name: str, product_name: str, delivery_status: str) -> str:
    """
    Generate reminder message for KOL based on delivery status.
    
    Args:
        kol_name: Name of the KOL
        product_name: Name of the product
        delivery_status: Current delivery status (已发货, 运输中, 已签收, 异常)
    
    Returns:
        Personalized reminder message for the KOL
    """
    try:
        # Initialize ModelGateway and get LLM
        model_gateway = get_model_gateway()
        llm = model_gateway.get_llm("deepseek")

        # Determine message type based on delivery status
        message_type = ""
        if delivery_status == "已发货":
            message_type = "发货通知"
        elif delivery_status == "运输中":
            message_type = "配送提醒"
        elif delivery_status == "已签收":
            message_type = "开箱提醒"
        elif delivery_status == "异常":
            message_type = "异常处理"

        # Create prompt for generating personalized message
        prompt = f"""
        你是品牌商务助手，需要为达人 {kol_name} 生成一条关于产品 {product_name} 的{message_type}私信。
        
        当前配送状态：{delivery_status}
        产品名称：{product_name}
        达人姓名：{kol_name}
        
        请生成一条友好、专业的私信，包含以下要素：
        
        1. 亲切的问候和称呼
        2. 说明当前配送状态
        3. 根据状态给出相应的建议或提醒
        4. 表达感谢和支持
        5. 保持语气友好，不过于正式
        
        要求：
        - 消息长度控制在100-150字
        - 语言自然流畅
        - 体现品牌关怀
        - 根据不同状态调整内容重点
        
        """

        # Generate message using LLM
        response = llm.invoke(prompt)

        return ToolResult.ok(
            data=response.content,
            message=f"Arrival script generated for {kol_name}."
        ).to_json()

    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"生成提醒消息时出错：{str(e)}",
            suggestion=ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR],
        ).to_json()

if __name__ == "__main__":
    import os
    # Check if we should run as HTTP service
    if os.getenv("RUN_AS_HTTP_SERVICE", "false").lower() == "true":
        # Run as independent FastAPI service
        import uvicorn
        from fastapi import FastAPI

        app = FastAPI()

        from pydantic import BaseModel

        class GenerateArrivalScriptRequest(BaseModel):
            kol_name: str
            product_name: str
            delivery_status: str

        class CheckDeliveryStatusRequest(BaseModel):
            order_id: str

        @app.post("/tools/check_delivery_status")
        async def check_delivery_status_endpoint(request: CheckDeliveryStatusRequest):
            return check_delivery_status(request.order_id)

        @app.post("/tools/generate_arrival_script")
        async def generate_arrival_script_endpoint(request: GenerateArrivalScriptRequest):
            return generate_arrival_script(request.kol_name, request.product_name, request.delivery_status)

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "monitor"}

        port = int(os.getenv("PORT", "8106"))
        logger.info("monitor_server_starting", port=port)
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # Run as MCP server
        mcp.run()