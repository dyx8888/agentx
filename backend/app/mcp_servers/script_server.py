"""
Script Generation MCP Server
Provides functionality to generate complete video scripts for KOLs using RAG knowledge retrieval.
"""

from fastmcp import FastMCP

from app.core.logging import get_logger
from app.mcp_servers.knowledge_retrieval_server import search_knowledge
from app.services.model_gateway import ModelGateway
from app.tools.result import ToolResult, ErrorCode, ERROR_SUGGESTIONS

logger = get_logger(__name__)

# Create MCP server
mcp = FastMCP("script_server")


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
def generate_script(kol_name: str, product_name: str, platform: str = "douyin", style: str = "lively") -> str:
    """
    Generate complete video script for KOL using LLM with RAG knowledge retrieval.
    
    Args:
        kol_name: Name of the KOL to create script for
        product_name: Name of the product to promote
        platform: Target platform for the script (douyin, xiaohongshu, weibo)
        style: Script style (lively, professional, casual, creative)
    
    Returns:
        Generated complete video script with opening, product introduction, interaction, and closing
    """
    try:
        # Phase 1: 从上下文获取 company_id，传给知识检索
        company_id = _resolve_company_id()
        # Step 1: Retrieve relevant knowledge from brand script database
        search_query = f"{product_name} video script {platform} {style}"
        knowledge_results_json = search_knowledge(search_query, n_results=3, company_id=company_id)

        # Parse ToolResult JSON from knowledge retrieval
        knowledge_results = []
        try:
            import json
            parsed = json.loads(knowledge_results_json)
            if parsed.get("status") == "ok":
                knowledge_results = parsed.get("data", [])
            else:
                logger.warning("knowledge_retrieval_failed", error=parsed.get("message"))
        except (json.JSONDecodeError, TypeError):
            logger.warning("knowledge_retrieval_parse_error")

        # Step 2: Initialize ModelGateway and get LLM
        model_gateway = get_model_gateway()
        llm = model_gateway.get_llm("deepseek")

        # Step 3: Format retrieved knowledge for prompt
        knowledge_context = ""
        if knowledge_results:
            knowledge_context = "\n\nReference Brand Script Templates:\n"
            for i, result in enumerate(knowledge_results, 1):
                knowledge_context += f"{i}. {result['content']}\n"
                if result.get('metadata'):
                    metadata = result['metadata']
                    knowledge_context += f"   Category: {metadata.get('category', 'N/A')}, Scenario: {metadata.get('scenario', 'N/A')}\n"
                knowledge_context += "\n"

        # Step 4: Create enhanced prompt for complete script generation
        prompt = f"""
        You are a professional video script writer for {platform}. Generate a complete video script for {kol_name} to promote {product_name}.
        
        Platform: {platform}
        Style: {style}
        Target KOL: {kol_name}
        Product: {product_name}
        
        {knowledge_context}
        
        IMPORTANT: Reference the above brand script templates for style and structure. Create a complete script that includes:
        
        1. Opening Hook (5-10 seconds): Catch viewer attention with engaging opening
        2. Product Introduction (15-20 seconds): Introduce {product_name} naturally and highlight key benefits
        3. Demonstration/Usage (20-30 seconds): Show how to use the product and its effects
        4. Interaction & Engagement (10-15 seconds): Include questions, polls, or call-to-action
        5. Closing & CTA (5-10 seconds): Strong closing with clear call-to-action
        
        Requirements:
        - Script should be {style} in tone
        - Include specific timestamps for each section
        - Add visual cues and camera directions in [brackets]
        - Include natural language that fits {kol_name}'s style
        - Reference the brand templates while making it unique
        - Total script length: 60-90 seconds
        
        Format the output clearly with section headers and timestamps.
        """

        # Step 5: Generate script using LLM
        response = llm.invoke(prompt)

        return ToolResult.ok(
            data=response.content,
            message=f"Video script generated for {kol_name} on {platform}."
        ).to_json()

    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"Error generating script: {str(e)}",
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

        class GenerateScriptRequest(BaseModel):
            kol_name: str
            product_name: str
            platform: str = "douyin"
            style: str = "lively"

        @app.post("/tools/generate_script")
        async def generate_script_endpoint(request: GenerateScriptRequest):
            return generate_script(request.kol_name, request.product_name, request.platform, request.style)

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "script"}

        port = int(os.getenv("PORT", "8103"))
        logger.info("script_server_starting", port=port)
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # Run as MCP server
        mcp.run()