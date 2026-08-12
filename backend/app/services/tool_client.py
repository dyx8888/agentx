"""
HTTP Tool Client for AgentX Stage 7
Provides HTTP-based tool calling for Agent-side tool invocation with retry and timeout
"""  # Agent鐨凥TTP宸ュ叿璋冪敤瀹㈡埛绔紝閫氳繃HTTP鍗忚瑙ｈ€gent涓庡伐鍏峰疄鐜帮紝鏀寔閲嶈瘯鍜岃秴鏃舵満鍒?

import time  # 鐢ㄤ簬鎸囨暟閫€閬块噸璇曠殑sleep寤惰繜
from typing import Any  # 鐢ㄤ簬鍙傛暟schema鐨勭被鍨嬫敞瑙?

import httpx  # 浣跨敤httpx鑰岄潪requests锛屽洜涓篽ttpx鍘熺敓鏀寔寮傛涓擜PI鏇寸幇浠?
from langchain_core.tools import (
    tool,  # LangChain鐨凘tool瑁呴グ鍣紝灏嗘櫘閫氬嚱鏁拌浆鎹负Agent鍙皟鐢ㄧ殑宸ュ叿
)

from app.core.logging import get_logger  # 缁熶竴鏃ュ織璁板綍

logger = get_logger(__name__)  # 妯″潡绾ogger


# Simple logger for HTTP tool calls
def log_http_call(
    tool_name: str,
    endpoint: str,
    kwargs: dict,
    status: str,
    response: Any = None,
    error: str = None,
    **extra: Any,
):  # 鐙珛鍑芥暟鑰岄潪绫绘柟娉曪紝鍥犱负鏃ュ織璁板綍鏄€氱敤宸ュ叿鍑芥暟
    """Log HTTP tool calls for debugging"""
    logger.info(
        "http_tool_call", status=status, tool_name=tool_name, endpoint=endpoint, **extra
    )  # info绾у埆璁板綍璋冪敤鐘舵€侊紝渚夸簬瑙傚療姝ｅ父娴佺▼
    if kwargs:  # 浠呭湪鏈夊弬鏁版椂璁板綍锛岄伩鍏嶇┖鏃ュ織
        logger.debug(
            "http_tool_call_params", params=kwargs
        )  # debug绾у埆璁板綍鍙傛暟锛岄伩鍏嶆晱鎰熶俊鎭硠闇插埌info鏃ュ織
    if response:  # 浠呭湪鏈夊搷搴旀椂璁板綍
        logger.debug("http_tool_call_response", response=response)
    if error:  # 浠呭湪鏈夐敊璇椂璁板綍
        logger.error("http_tool_call_error", error=error)  # error绾у埆璁板綍閿欒锛屼究浜庡憡璀?


def create_http_tool(
    name: str,
    description: str,
    endpoint: str,
    parameters: dict[str, Any] = None,
    default_params: dict[str, Any] | None = None,
):  # 宸ュ巶鍑芥暟锛屽姩鎬佸垱寤篐TTP宸ュ叿锛涘弬鏁板彲閫夛紝鍥犱负绠€鍗曞伐鍏峰彲鑳戒笉闇€瑕佸弬鏁皊chema
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

    bound_defaults = dict(default_params or {})

    def tool_function(**kwargs):  # 鍐呴儴鍑芥暟锛屼娇鐢?*kwargs鎺ユ敹浠绘剰鍙傛暟锛屽洜涓轰笉鍚屽伐鍏风殑鍙傛暟schema涓嶅悓
        """The actual tool function that makes HTTP calls with retry"""
        max_retries = 3  # 鍥哄畾3娆￠噸璇曪紝骞宠　鍙潬鎬у拰鍝嶅簲鏃堕棿
        timeout = 30  # 30绉掕秴鏃讹紝HTTP璇锋眰閫氬父搴斿湪姝ゆ椂闄愬唴瀹屾垚
        payload = {**kwargs, **bound_defaults}

        for attempt in range(max_retries):  # 閲嶈瘯寰幆锛屼粠0寮€濮?
            try:
                # Log the HTTP call attempt
                log_http_call(
                    name, endpoint, payload, "ATTEMPT", attempt=attempt + 1
                )  # attempt+1鐢ㄤ簬浜虹被鍙

                # Make HTTP request with timeout
                with httpx.Client(timeout=timeout) as client:  # 浣跨敤涓婁笅鏂囩鐞嗗櫒锛岀‘淇濊繛鎺ユ纭叧闂?
                    response = client.post(endpoint, json=payload)  # POST璇锋眰锛孞SON鏍煎紡浼犺緭鍙傛暟
                    response.raise_for_status()  # 闈?xx鐘舵€佺爜鐩存帴鎶涘紓甯革紝鐢卞灞傞噸璇曢€昏緫澶勭悊

                    # Log successful response
                    log_http_call(name, endpoint, payload, "SUCCESS", response=response.json())
                    return response.json()  # 鎴愬姛鍒欒繑鍥濲SON鏁版嵁

            except httpx.TimeoutException as e:  # 瓒呮椂寮傚父鍗曠嫭澶勭悊锛屼娇鐢ㄦ寚鏁伴€€閬?
                log_http_call(name, endpoint, payload, "TIMEOUT", error=str(e))
                if attempt < max_retries - 1:  # 闈炴渶鍚庝竴娆￠噸璇曟墠绛夊緟
                    time.sleep(2**attempt)  # 鎸囨暟閫€閬匡細1s, 2s, 4s锛岄伩鍏嶈繛缁揩閫熼噸璇?
                    continue
                return f"HTTP request timeout after {max_retries} attempts: {str(e)}"  # 鏈€鍚庝竴娆″け璐ヨ繑鍥為敊璇俊鎭?

            except httpx.RequestError as e:  # 璇锋眰閿欒锛堝DNS銆佽繛鎺ュけ璐ワ級锛屽悓鏍蜂娇鐢ㄦ寚鏁伴€€閬?
                log_http_call(name, endpoint, payload, "REQUEST_ERROR", error=str(e))
                if attempt < max_retries - 1:  # 闈炴渶鍚庝竴娆￠噸璇?
                    time.sleep(2**attempt)  # 鎸囨暟閫€閬?
                    continue
                return f"HTTP request failed after {max_retries} attempts: {str(e)}"

            except Exception as e:  # 鍏朵粬鏈煡寮傚父锛屼笉閲嶈瘯鐩存帴杩斿洖閿欒
                log_http_call(name, endpoint, payload, "ERROR", error=str(e))
                return f"Error calling tool {name}: {str(e)}"

        return (
            f"Tool {name} failed after {max_retries} attempts"  # 鐞嗚涓婁笉浼氳蛋鍒拌繖閲岋紝浣滀负鍏滃簳杩斿洖
        )

    # Apply the @tool decorator
    # Apply the @tool decorator. LangChain expects metadata first, then the function.
    return tool(name, description=description)(tool_function)
