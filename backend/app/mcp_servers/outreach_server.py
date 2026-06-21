"""
Outreach Composer MCP Server
Provides functionality to generate outreach messages for KOLs using LLM with RAG knowledge retrieval.
"""

from fastmcp import FastMCP

from app.core.logging import get_logger
from app.mcp_servers.knowledge_retrieval_server import search_knowledge
from app.services.model_gateway import ModelGateway
from app.tools.result import ToolResult, ErrorCode, ERROR_SUGGESTIONS

logger = get_logger(__name__)

# Create MCP server
mcp = FastMCP("outreach_server")


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
def generate_outreach(kol_name: str, product_name: str, style: str = "professional") -> str:
    """
    Generate outreach messages for a KOL using LLM with RAG knowledge retrieval.
    
    Args:
        kol_name: Name of the KOL to create outreach for
        product_name: Name of the product to promote
        style: Style of the outreach message (professional, casual, creative)
    
    Returns:
        Generated outreach message content
    """
    try:
        # Phase 1: 从上下文获取 company_id，传给知识检索
        company_id = _resolve_company_id()
        # Step 1: Retrieve relevant knowledge from brand script database
        search_query = f"{product_name} collaboration outreach {style}"
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

        # Step 4: Create enhanced prompt with RAG knowledge
        prompt = f"""
        You are a professional marketing assistant. Generate 3 different outreach messages for {kol_name} to promote {product_name}.
        
        Style: {style}
        
        {knowledge_context}
        
        IMPORTANT: Reference the above brand script templates for style and structure. Customize the messages for {kol_name} while maintaining our brand voice and key elements from the templates.
        
        Requirements:
        1. Each message should be personalized and mention the KOL's name
        2. Each message should highlight the product benefits
        3. Each message should have a clear call-to-action
        4. Messages should be concise but persuasive
        5. Follow the style and structure of the reference templates
        6. Format as a numbered list with clear separation between messages
        
        Example format:
        1. [First personalized message here]
        
        2. [Second personalized message here]
        
        3. [Third personalized message here]
        """

        # Step 5: Generate outreach content with RAG-enhanced prompt
        response = llm.invoke(prompt)

        return ToolResult.ok(
            data=response.content,
            message=f"Outreach messages generated for {kol_name}."
        ).to_json()

    except Exception as e:
        return ToolResult.error(
            error_code=ErrorCode.UNKNOWN_ERROR,
            message=f"Error generating outreach message: {str(e)}",
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
        from typing import Optional

        class GenerateOutreachRequest(BaseModel):
            kol_name: str
            product_name: str
            style: str = "professional"
            brand_name: Optional[str] = None
            company_name: Optional[str] = None

        @app.post("/tools/generate_outreach")
        async def generate_outreach_endpoint(request: GenerateOutreachRequest):
            return generate_outreach(request.kol_name, request.product_name, request.style)

        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "service": "outreach"}

        port = int(os.getenv("PORT", "8105"))
        logger.info("outreach_server_starting", port=port)
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # Run as MCP server
        mcp.run()