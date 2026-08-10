"""
HTTP Tool Client for AgentX Stage 7
Provides HTTP-based tool calling for Agent-side tool invocation with retry and timeout
"""  # Agent的HTTP工具调用客户端，通过HTTP协议解耦Agent与工具实现，支持重试和超时机制

import time  # 用于指数退避重试的sleep延迟
from typing import Any  # 用于参数schema的类型注解

import httpx  # 使用httpx而非requests，因为httpx原生支持异步且API更现代
from langchain_core.tools import tool  # LangChain的@tool装饰器，将普通函数转换为Agent可调用的工具

from app.core.logging import get_logger  # 统一日志记录

logger = get_logger(__name__)  # 模块级logger

# Simple logger for HTTP tool calls
def log_http_call(tool_name: str, endpoint: str, kwargs: dict, status: str, response: Any = None, error: str = None):  # 独立函数而非类方法，因为日志记录是通用工具函数
    """Log HTTP tool calls for debugging"""
    logger.info("http_tool_call", status=status, tool_name=tool_name, endpoint=endpoint)  # info级别记录调用状态，便于观察正常流程
    if kwargs:  # 仅在有参数时记录，避免空日志
        logger.debug("http_tool_call_params", params=kwargs)  # debug级别记录参数，避免敏感信息泄露到info日志
    if response:  # 仅在有响应时记录
        logger.debug("http_tool_call_response", response=response)
    if error:  # 仅在有错误时记录
        logger.error("http_tool_call_error", error=error)  # error级别记录错误，便于告警

def create_http_tool(name: str, description: str, endpoint: str, parameters: dict[str, Any] = None):  # 工厂函数，动态创建HTTP工具；参数可选，因为简单工具可能不需要参数schema
    """
    Create an HTTP-based tool that can be used by agents
    
    Args:
        name: Tool name
        description: Tool description
        endpoint: HTTP endpoint URL
        parameters: Expected parameters schema
        
    Returns:
        Decorated tool function that makes HTTP calls
    """
    def tool_function(**kwargs):  # 内部函数，使用**kwargs接收任意参数，因为不同工具的参数schema不同
        """The actual tool function that makes HTTP calls with retry"""
        max_retries = 3  # 固定3次重试，平衡可靠性和响应时间
        timeout = 30  # 30秒超时，HTTP请求通常应在此时限内完成

        for attempt in range(max_retries):  # 重试循环，从0开始
            try:
                # Log the HTTP call attempt
                log_http_call(name, endpoint, kwargs, "ATTEMPT", attempt=attempt+1)  # attempt+1用于人类可读

                # Make HTTP request with timeout
                with httpx.Client(timeout=timeout) as client:  # 使用上下文管理器，确保连接正确关闭
                    response = client.post(endpoint, json=kwargs)  # POST请求，JSON格式传输参数
                    response.raise_for_status()  # 非2xx状态码直接抛异常，由外层重试逻辑处理

                    # Log successful response
                    log_http_call(name, endpoint, kwargs, "SUCCESS", response=response.json())
                    return response.json()  # 成功则返回JSON数据

            except httpx.TimeoutException as e:  # 超时异常单独处理，使用指数退避
                log_http_call(name, endpoint, kwargs, "TIMEOUT", error=str(e))
                if attempt < max_retries - 1:  # 非最后一次重试才等待
                    time.sleep(2 ** attempt)  # 指数退避：1s, 2s, 4s，避免连续快速重试
                    continue
                return f"HTTP request timeout after {max_retries} attempts: {str(e)}"  # 最后一次失败返回错误信息

            except httpx.RequestError as e:  # 请求错误（如DNS、连接失败），同样使用指数退避
                log_http_call(name, endpoint, kwargs, "REQUEST_ERROR", error=str(e))
                if attempt < max_retries - 1:  # 非最后一次重试
                    time.sleep(2 ** attempt)  # 指数退避
                    continue
                return f"HTTP request failed after {max_retries} attempts: {str(e)}"

            except Exception as e:  # 其他未知异常，不重试直接返回错误
                log_http_call(name, endpoint, kwargs, "ERROR", error=str(e))
                return f"Error calling tool {name}: {str(e)}"

        return f"Tool {name} failed after {max_retries} attempts"  # 理论上不会走到这里，作为兜底返回

    # Apply the @tool decorator
    return tool(tool_function)(  # 使用LangChain的@tool装饰器包装，使其被Agent识别为可调用工具
        name=name,  # 工具名称，Agent通过名称引用
        description=description,  # 工具描述，帮助LLM理解何时使用
        parameters_schema=parameters  # 参数schema，用于LLM理解参数格式
    )
