"""
Executor Node - 任务执行节点
按计划逐步执行，内部用 ReAct 循环调用 MCP 工具。
支持结构化错误包装、审批门、幂等性、循环检测、超时重试、降级、调用次数上限。
"""

# asyncio 用于异步超时控制和重试等待，避免同步阻塞导致整个 Agent 卡死
import asyncio

# hashlib 用于生成工具调用指纹，检测 Agent 是否陷入执行循环
import hashlib

# json 用于序列化步骤参数生成指纹，以及解析 MCP 工具返回的 ToolResult JSON
import json

# time 用于记录工具调用耗时，便于性能监控和超时分析
import time

# Any 和 Optional 类型注解，标记灵活返回值和可选参数类型
from typing import Any

# HumanMessage/SystemMessage 用于构造 LLM 输入消息，区分用户指令和系统指令
from langchain_core.messages import HumanMessage, SystemMessage

# State 是全局状态类型定义，确保各节点对状态字段的读写一致
State = dict[str, Any]

# enrich_system_prompt 为系统 prompt 注入防护栏规则，防止 LLM 越权执行
from app.core.agent_robustness import enrich_system_prompt

# 幂等管理器：对有副作用的工具调用生成唯一键，执行前检查缓存、执行后存储结果，防止重复执行
from app.core.idempotency import get_idempotency_manager

# wrap_system_instructions/wrap_user_input 包裹边界标记，防止用户输入污染系统指令
from app.core.instruction_boundary import wrap_system_instructions, wrap_user_input

# 结构化日志记录器，所有日志使用结构化字段便于检索
from app.core.logging import get_logger

# ToolResult 封装工具调用的三种结果（ok/error/pending_approval），ErrorCode 统一错误码，ERROR_SUGGESTIONS 映射错误码到修复建议
from app.tools.result import ERROR_SUGGESTIONS, ErrorCode, ToolResult

# 模块级日志实例，__name__ 确保日志前缀为此文件路径
logger = get_logger(__name__)

# 单次 executor 执行的工具调用最大次数：防止 LLM 陷入无限调用循环，设为 20 是在"足够完成任务"和"防止资源耗尽"之间的平衡值
MAX_TOOL_CALLS = 20


def _check_approval_gate(tool_name: str, available_tools: list) -> tuple[bool, str]:
    """
    检查工具是否需要审批。

    Returns:
        (needs_approval, message): 是否需要审批 + 状态信息
    """
    for t in available_tools:
        if t.name == tool_name:
            # 从工具 metadata 中读取 requires_approval 标记，| {} 防止 metadata 为 None 时 get 报错
            metadata = getattr(t, "metadata", {}) or {}
            if metadata.get("requires_approval", False):
                return True, f"Tool '{tool_name}' requires approval."
    # 未找到对应工具或工具不需要审批，返回默认值，空字符串表示无审批消息
    return False, ""


def _is_side_effect_tool(tool_name: str, available_tools: list) -> bool:
    """检查工具是否有副作用（需要幂等保护）"""
    for t in available_tools:
        if t.name == tool_name:
            # 从 metadata 中取 side_effect 标记，| {} 兜底防止 None 值
            metadata = getattr(t, "metadata", {}) or {}
            return metadata.get("side_effect", False)
    # 未找到工具默认视为无副作用，保守策略：不阻止执行
    return False


def _get_tool_metadata(tool_name: str, available_tools: list) -> dict:
    """获取工具 metadata"""
    for t in available_tools:
        if t.name == tool_name:
            # 返回完整 metadata 字典，供调用方自行读取 timeout_ms/retry/degradation 等字段
            return getattr(t, "metadata", {}) or {}
    # 未找到工具返回空字典，调用方用 .get() 取默认值不会报错
    return {}


def _build_step_result(
    current_step: int,
    step_description: str,
    tool_name: str,
    tool_result: ToolResult,
) -> dict:
    """构建统一的 step_result 字典"""
    # 基础字段：所有结果类型共享
    step_result = {
        "step": current_step + 1,  # +1 转换为人类可读的 1-based 序号
        "description": step_description,
        "tool_used": tool_name,
        "status": tool_result.status,
    }
    if tool_result.is_ok():
        # 成功结果：写入 data 字段，下游节点可直接使用
        step_result["result"] = tool_result.data
    elif tool_result.needs_approval():
        # 待审批结果：写入 pending_tool 和 proposed_params，供审批流程使用
        step_result["pending_tool"] = tool_result.tool_name
        step_result["proposed_params"] = tool_result.proposed_params
        step_result["message"] = tool_result.message
    else:
        # 错误结果：写入错误码、错误消息和修复建议，供后续自愈逻辑分析
        step_result["error_code"] = tool_result.error_code
        step_result["error_message"] = tool_result.message
        step_result["suggestion"] = tool_result.suggestion
    return step_result


# ── 循环检测 ────────────────────────────────────────────────────


def _detect_loop(
    fingerprint_window: list,
    current_tool_name: str,
    current_step_data: dict,
    window_size: int = 5,
    repeat_threshold: int = 3,
) -> tuple[list, bool, str | None]:
    """检测 Agent 是否陷入执行循环"""
    # 提取步骤参数，生成指纹时考虑参数变化（同一工具不同参数不算循环）
    step_params = current_step_data.get("params", {})
    # 用 SHA256 对 (工具名 + 参数) 做哈希，取前 16 位作为指纹，避免全哈希太长浪费内存
    # sort_keys=True 确保相同参数不同顺序产生相同指纹，default=str 处理非 JSON 可序列化类型
    fingerprint = hashlib.sha256(
        f"{current_tool_name}:{json.dumps(step_params, sort_keys=True, default=str)}".encode()
    ).hexdigest()[:16]

    # 滑动窗口：保留最近 window_size-1 个指纹 + 当前指纹，保持窗口大小稳定
    new_window = fingerprint_window[-(window_size - 1) :] + [fingerprint]

    # 统计当前指纹在窗口内出现的次数，如果在窗口内重复超过阈值说明陷入循环
    count = new_window.count(fingerprint)
    if count >= repeat_threshold:
        # 返回更新后的窗口 + 循环标记 + 人类可读的循环描述
        return (
            new_window,
            True,
            (
                f"检测到执行循环：工具 '{current_tool_name}' 在最近 {window_size} 步中重复调用了 "
                f"{count} 次。建议停止当前任务并告知用户。"
            ),
        )

    # 未检测到循环：返回更新后的窗口供下一次检测使用
    return new_window, False, None


def _wrap_tool_result(
    response,
    tool_call_count: int,
    available_tools: list,
) -> ToolResult:
    """
    包装 LLM 的工具调用结果为结构化 ToolResult。
    处理三种路径: ok, error, pending_approval。
    同时检测 MCP 工具返回的 ToolResult JSON 并解析。
    """
    # 检查是否有工具调用：response.tool_calls 是 LangChain 的 tool_call 响应格式
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            # 审批门检查：在工具实际执行前先判断是否需要审批，避免绕过审批直接执行敏感操作
            needs_approval, msg = _check_approval_gate(tc["name"], available_tools)
            if needs_approval:
                # 返回 pending_approval 状态，携带工具名和参数，等待审批通过后再执行
                return ToolResult.pending_approval(
                    tool_name=tc["name"],
                    proposed_params=tc.get("args", {}),
                    message=msg,
                )

    # 检查调用次数：在审批门之后检查，因为审批中的调用也应该计入次数
    if tool_call_count >= MAX_TOOL_CALLS:
        return ToolResult.error(
            error_code=ErrorCode.MAX_CALLS_EXCEEDED,
            message=f"Exceeded max tool calls ({MAX_TOOL_CALLS}) for this executor session.",
            # 从全局映射取建议文案，统一错误码 → 建议的管理
            suggestion=ERROR_SUGGESTIONS[ErrorCode.MAX_CALLS_EXCEEDED],
        )

    # 尝试解析 MCP 工具返回的 ToolResult JSON：有些 MCP 工具直接返回 ToolResult 格式的 JSON 字符串
    # 这样可以跳过 LLM 的二次解析，直接使用工具端产出的结构化结果
    content = response.content if hasattr(response, "content") else str(response)
    try:
        parsed = json.loads(content)
        # 同时检查 isinstance 和 "status" 键，确保解析结果确实是 ToolResult 格式
        if isinstance(parsed, dict) and "status" in parsed:
            status = parsed.get("status")
            if status == "ok":
                return ToolResult.ok(
                    data=parsed.get("data"),
                    message=parsed.get("message", ""),
                )
            elif status == "error":
                return ToolResult.error(
                    error_code=parsed.get("error_code", ErrorCode.UNKNOWN_ERROR),
                    message=parsed.get("message", ""),
                    suggestion=parsed.get("suggestion"),
                    # fallback_tool 字段用于降级策略：告知调用方有备用工具可用
                    fallback_tool=parsed.get("fallback_tool"),
                )
            elif status == "pending_approval":
                return ToolResult.pending_approval(
                    tool_name=parsed.get("tool_name", ""),
                    proposed_params=parsed.get("proposed_params", {}),
                    message=parsed.get("message", ""),
                )
    except (json.JSONDecodeError, TypeError) as exc:
        if str(content).lstrip().startswith(("{", "[")):
            return ToolResult.error(
                error_code=ErrorCode.UNKNOWN_ERROR,
                message=f"Executor tool result JSON parse failed: {exc}",
                suggestion="Return a valid ToolResult JSON object or plain user-facing text.",
            )

    # 正常结果（非 ToolResult 格式）：LLM 返回了纯文本描述，包装为成功结果
    return ToolResult.ok(data=content, message="Execution completed.")


def _wrap_exception(e: Exception) -> ToolResult:
    """将异常包装为结构化 ToolResult"""
    # 默认未知错误码，后续通过 isinstance 链匹配更精确的错误类型
    error_code = ErrorCode.UNKNOWN_ERROR

    # asyncio.TimeoutError → 工具调用超时，明确区分于其他异常，便于触发重试
    if isinstance(e, asyncio.TimeoutError):
        error_code = ErrorCode.TOOL_TIMEOUT
    # ConnectionError/OSError → 网络或系统层面的连接问题，属于可恢复的瞬时故障
    elif isinstance(e, (ConnectionError, OSError)):
        error_code = ErrorCode.CONNECTION_ERROR

    return ToolResult.error(
        error_code=error_code,
        message=str(e),
        # ERROR_SUGGESTIONS.get 优先取精确匹配的建议，回退到通用未知错误建议
        suggestion=ERROR_SUGGESTIONS.get(error_code, ERROR_SUGGESTIONS[ErrorCode.UNKNOWN_ERROR]),
    )


# ── 超时控制与重试 (async) ─────────────────────────────────────


async def _execute_with_timeout(
    llm_with_tools,
    messages: list,
    timeout_ms: int = 30000,
    max_retries: int = 3,
) -> tuple[Any, float]:
    """带超时和重试的工具执行（异步版本，使用 asyncio.wait_for）

    Args:
        llm_with_tools: 绑定了工具的 LLM
        messages: 消息列表
        timeout_ms: 超时时间（毫秒）
        max_retries: 最大重试次数

    Returns:
        (response, duration_ms): LLM 响应 + 执行耗时

    Raises:
        asyncio.TimeoutError: 超时且所有重试均失败
    """
    # last_exception 保存最后一次异常，重试全部失败时抛出，保留原始错误信息
    last_exception = None
    # 记录开始时间，用于计算总耗时（包含所有重试的等待时间）
    start_time = time.time()

    for attempt in range(max_retries):
        try:
            # 毫秒转秒，asyncio.wait_for 接受秒为单位的超时参数
            timeout_seconds = timeout_ms / 1000.0
            # asyncio.wait_for 包装异步调用，超时自动抛出 asyncio.TimeoutError
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(messages),
                timeout=timeout_seconds,
            )
            # 成功后立即计算耗时（毫秒）并返回，不再重试
            duration_ms = (time.time() - start_time) * 1000
            return response, duration_ms
        except TimeoutError:
            # 构造包含重试信息的异常，保留原始超时参数和尝试次数
            last_exception = TimeoutError(
                f"工具调用超时 ({timeout_ms}ms)，已重试 {attempt + 1}/{max_retries}"
            )
            logger.warning("tool_call_timeout", attempt=attempt + 1, timeout_ms=timeout_ms)
            if attempt < max_retries - 1:
                # 指数退避：1秒/2秒/4秒，避免瞬时高并发导致服务端雪崩
                wait_time = 2**attempt  # 指数退避: 1s/2s/4s
                await asyncio.sleep(wait_time)
        except Exception as e:
            # 捕获其他所有异常（网络错误、LLM 返回异常等），同样走重试逻辑
            last_exception = e
            logger.warning("tool_call_error", attempt=attempt + 1, error=str(e))
            if attempt < max_retries - 1:
                wait_time = 2**attempt
                await asyncio.sleep(wait_time)

    # 所有重试均失败，抛出最后一次捕获的异常，让上层调用方统一处理
    raise last_exception


# ── 四级降级策略 ─────────────────────────────────────────────────


def _degrade_tool(
    tool_name: str,
    step_data: dict,
    available_tools: list,
    step_results: list,
) -> ToolResult:
    """工具调用失败时按四级降级策略处理

    1. 使用缓存数据（由幂等模块处理，此处标注 source: "cache"）
    2. 切换备用数据源（tool_providers.yaml 中配置 fallback_url / fallback_tool）
    3. 跳过非关键步骤（tool_providers.yaml 中配置 critical: false）
    4. 转人工工单（生成工单ID，暂停Agent等待人工介入）
    """
    # 获取工具的全量 metadata，包含 degradation 子配置
    metadata = _get_tool_metadata(tool_name, available_tools)
    # degradation 字段可能不存在或为 None，用 {} 兜底
    degradation = metadata.get("degradation", {})

    # 级别 2: 切换备用数据源
    # 优先从 degradation 取，其次从 metadata 顶层取（兼容两种配置方式）
    fallback_tool = degradation.get("fallback_tool") or metadata.get("fallback_tool")
    fallback_url = degradation.get("fallback_url") or metadata.get("fallback_url")
    if fallback_tool or fallback_url:
        fallback_target = fallback_tool or fallback_url
        # 返回错误结果但携带 fallback_tool 字段，调用方据此决定是否切换到备用工具
        return ToolResult.error(
            error_code=ErrorCode.CONNECTION_ERROR,
            message=f"主工具 '{tool_name}' 不可用",
            suggestion=f"建议使用备用源 '{fallback_target}'",
            fallback_tool=fallback_target,
        )

    # 级别 3: 跳过非关键步骤
    # 默认 critical=True：未配置时视为关键步骤，不会跳过
    is_critical = degradation.get("critical", True)
    if not is_critical:
        # 非关键步骤跳过时返回 ok 状态，data=None 表示无实际产出
        return ToolResult.ok(
            data=None,
            message=f"非关键步骤 '{tool_name}' 已跳过（降级策略3）。继续执行后续步骤。",
        )

    # 级别 4: 转人工工单
    # 在函数内部 import uuid 而非顶部，因为只有真正需要时才加载，属于惰性加载优化
    import uuid

    # 生成 TICKET-XXXXXXXX 格式的工单号，hex 取 8 位平衡可读性和唯一性
    ticket_id = f"TICKET-{uuid.uuid4().hex[:8].upper()}"
    return ToolResult.error(
        error_code=ErrorCode.MAX_CALLS_EXCEEDED,
        message=f"关键步骤 '{tool_name}' 所有降级策略均失败",
        suggestion=f"已转人工处理，工单号: {ticket_id}。请等待人工介入。",
    )


# ── 主执行节点 (async) ──────────────────────────────────────────


async def executor_node(state: State, llm, available_tools: list) -> dict[str, Any]:
    # 从状态中取出执行计划，.get("plan", {}) 防止 plan 未初始化时崩溃
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    # current_step 是 0-based 索引，用于定位当前要执行的步骤
    current_step = state.get("current_step", 0)
    # step_results 是已执行步骤的结果列表，每步执行完追加一条
    step_results = state.get("step_results", [])
    # skill_content 从 planner 透传过来，包含专业工作流程文本
    skill_content = state.get("skill_content", "")
    # tool_call_count 跨步骤累计的调用次数，用于全局 MAX_TOOL_CALLS 限制
    tool_call_count = state.get("tool_call_count", 0)

    # 所有步骤执行完毕，标记计划完成，路由节点据此跳转到 reflector
    if current_step >= len(steps):
        return {"plan_completed": True, "step_results": step_results}

    # 取出当前步骤的数据和描述
    current_step_data = steps[current_step]
    step_description = current_step_data.get("description", "")
    # tool_name 可能为空字符串：表示该步骤不需要特定工具，由 LLM 自行判断
    tool_name = current_step_data.get("tool", "")

    # 可选幂等令牌（idempotency_key / request_id）：调用方可放在 step 数据顶层或 params 内。
    # 同一逻辑请求的意外重试携带相同令牌 => 幂等键相同 => 去重（保留现有保护）；
    # 不同真实操作携带不同令牌 => 幂等键不同 => 都能执行（修复"相同参数被误拦"）。
    # 未提供（None / 空字符串）时退回原有 params-hash 逻辑，保持向后兼容。
    # 这里只取一次，预检(check_only)与存储(store)共用，保证两处幂等键算法一致、查存对得上。
    _step_params_for_idem = current_step_data.get("params") or {}
    step_idempotency_key = (
        current_step_data.get("idempotency_key")
        or current_step_data.get("request_id")
        or _step_params_for_idem.get("idempotency_key")
        or _step_params_for_idem.get("request_id")
        or None
    )

    # 构建包含当前计划、步骤序号、可用工具列表的系统提示词
    system_prompt = _build_executor_prompt(skill_content, plan, current_step, available_tools)

    # bind_tools 将可用工具列表注册到 LLM，使 LLM 能输出 tool_call 格式的响应
    llm_with_tools = llm.bind_tools(available_tools)

    # 构造消息列表：System + Human，顺序保证 LangChain 正确解析角色
    messages = [
        SystemMessage(content=wrap_system_instructions(enrich_system_prompt(system_prompt))),
        HumanMessage(
            content=wrap_user_input(f"执行步骤 {current_step + 1}/{len(steps)}: {step_description}")
        ),
    ]

    # 历史执行结果注入：让 LLM 知道前面步骤做了什么，避免重复或遗漏
    if step_results:
        messages.append(HumanMessage(content=f"历史执行结果: {json.dumps(step_results)}"))

    # ── 执行 + 结构化错误包装 ─────────────────────────
    # 类型注解声明：tool_result 在整个执行流程中只会被赋值一次，但声明在 if/else 外部以消除作用域歧义
    tool_result: ToolResult

    # ── 循环检测 ─────────────────────────────────────────
    # 从状态中取出滚动窗口指纹列表，首次执行时为空列表
    fingerprint_window = state.get("fingerprint_window", [])
    fingerprint_window, is_loop, loop_message = _detect_loop(
        fingerprint_window, tool_name, current_step_data
    )
    if is_loop:
        # 检测到循环时直接返回错误，不再执行当前步骤，避免无限循环消耗资源
        tool_result = ToolResult.error(
            error_code=ErrorCode.MAX_CALLS_EXCEEDED,
            message=loop_message,
            suggestion=ERROR_SUGGESTIONS[ErrorCode.MAX_CALLS_EXCEEDED],
        )
        step_result = _build_step_result(current_step, step_description, tool_name, tool_result)
        return {
            "current_step": current_step + 1,  # 仍然递增步骤，让路由节点进入下一轮判断
            "step_results": step_results + [step_result],
            "messages": state.get("messages", []),
            "tool_call_count": tool_call_count + 1,
            "fingerprint_window": fingerprint_window,  # 更新后的窗口传回状态
        }

    # ── 幂等性检查 ─────────────────────────────────────
    # 从嵌套的公司上下文提取 company_id 和 agent_name，用于生成幂等键
    company_context = state.get("company_context", {})
    company_id = company_context.get("company_id", "")
    agent_name = company_context.get("agent_name", "")

    # 只有被标记为有副作用的工具才需要幂等保护，只读工具不需要
    if _is_side_effect_tool(tool_name, available_tools):
        idempotency_mgr = get_idempotency_manager()
        step_params = current_step_data.get("params", {})
        # 生成幂等键：公司+Agent+工具+参数 的组合，确保不同租户/不同参数被视为不同操作；
        # 透传可选幂等令牌，使不同令牌的相同参数操作各自独立（修复误拦）
        idem_key = idempotency_mgr.generate_key(
            company_id=company_id,
            agent_name=agent_name,
            tool_name=tool_name,
            params=step_params,
            idempotency_key=step_idempotency_key,
        )
        # 仅检查缓存不写入（check_only），因为执行成功后才写入
        cached_result = idempotency_mgr.check_only(idem_key)
        if cached_result is not None:
            # 缓存命中：直接返回历史结果，跳过实际执行，防止重复下单/重复发货等
            tool_result = ToolResult.ok(
                data=cached_result,
                message=f"[幂等命中] 此操作已执行过，返回缓存结果 (key: {idem_key})",
            )
            step_result = _build_step_result(
                current_step,
                step_description,
                tool_name,
                tool_result,
            )
            return {
                "current_step": current_step + 1,
                "step_results": step_results + [step_result],
                "messages": state.get("messages", []),
                "tool_call_count": tool_call_count + 1,
            }

    # ── 从 tool_providers.yaml 配置读取超时参数 ─────────
    # 获取工具的完整 metadata，从中读取超时和重试配置
    tool_metadata = _get_tool_metadata(tool_name, available_tools)
    # 默认 30 秒超时，单个工具配置可覆盖此值
    timeout_ms = tool_metadata.get("timeout_ms", 30000)
    max_retries = tool_metadata.get("retry", {}).get("max_attempts", 3)
    # retry 配置可能来自于 provider 级别的 retry 字段（整个 provider 共用一套重试策略）
    # 如果取到的 retry 值本身是 dict 而非 int，说明配置格式有误，回退到默认值 3
    if isinstance(max_retries, dict):
        max_retries = 3

    try:
        # 使用异步超时控制 + 重试 + 耗时追踪：一次调用集成了三个能力
        response, duration_ms = await _execute_with_timeout(
            llm_with_tools,
            messages,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
        )
        # 包装 LLM 响应为结构化 ToolResult，统一后续处理逻辑
        # tool_call_count + 1 是因为当前这次调用正在执行中，尚未计入
        tool_result = _wrap_tool_result(response, tool_call_count + 1, available_tools)
        logger.info(
            "tool_call_completed",
            tool=tool_name,
            duration_ms=round(duration_ms, 2),  # 四舍五入到两位小数，避免浮点精度问题
            step=current_step + 1,
            timeout_ms=timeout_ms,
        )
    except Exception as e:
        # 将异常包装为结构化 ToolResult，统一错误处理
        tool_result = _wrap_exception(e)
        logger.warning("tool_call_failed", tool=tool_name, error=str(e), step=current_step + 1)
        # 应用降级策略：根据工具 metadata 配置，尝试备用数据源/跳过/转人工
        degraded = _degrade_tool(tool_name, current_step_data, available_tools, step_results)
        # 如果降级策略产出了可用的替代结果（ok 或包含 fallback_tool），则使用降级结果
        if degraded.is_ok() or degraded.fallback_tool:
            tool_result = degraded

    # ── 构建 step_result ──────────────────────────────
    step_result = _build_step_result(current_step, step_description, tool_name, tool_result)

    # ── 幂等存储：副作用工具执行后缓存结果 ─────────────
    # 只有副作用工具并且执行成功时才缓存，避免缓存错误结果污染后续请求
    if _is_side_effect_tool(tool_name, available_tools) and tool_result.is_ok():
        try:
            idempotency_mgr = get_idempotency_manager()
            step_params = current_step_data.get("params", {})
            idem_key = idempotency_mgr.generate_key(
                company_id=company_id,
                agent_name=agent_name,
                tool_name=tool_name,
                params=step_params,
                idempotency_key=step_idempotency_key,
            )
            # 将成功结果写入缓存，下次相同参数调用时直接命中
            idempotency_mgr.store(idem_key, tool_result.data)
        except Exception as e:
            # 缓存写入失败不影响主流程，仅记录告警日志
            logger.warning("idempotency_store_failed", error=str(e))

    new_step_results = step_results + [step_result]

    # ── 错误自愈: 结构化 JSON 注入消息历史 ──────────────
    # 构造新的消息列表（不修改原列表），确保消息历史的不可变性
    new_messages = list(state.get("messages", []))
    if tool_result.is_error():
        # 工具调用失败时，将结构化的错误信息以 ToolResult JSON 格式注入消息历史
        # 这样 LLM 在下一步可以"看到"错误详情，具备自愈能力（自动调整策略重试）
        error_msg = HumanMessage(content=f"工具调用失败:\n{tool_result.to_json()}")
        new_messages.append(error_msg)
    else:
        # 成功时直接追加 LLM 的原始响应，保留完整的上下文
        new_messages.append(response)

    return {
        "current_step": current_step + 1,  # 递增到下一步，路由节点检查是否完成
        "step_results": new_step_results,
        "messages": new_messages,
        "tool_call_count": tool_call_count + 1,  # 全局计数器递增
        "fingerprint_window": fingerprint_window,  # 将更新后的指纹窗口传回状态，供下一步检测
    }


def _build_executor_prompt(
    skill_content: str, plan: dict, current_step: int, available_tools: list
) -> str:
    # ensure_ascii=False 保证中文在 JSON 中不被转义为 \uXXXX，LLM 能直接理解中文内容
    prompt = f"""
你是一位专业的执行者。请严格按照计划执行当前步骤。

当前计划：
{json.dumps(plan, ensure_ascii=False)}

当前执行步骤：{current_step + 1}

请根据计划和历史执行结果，完成当前步骤。

可用工具列表：
{_get_tool_descriptions(available_tools)}

要求：
1. 根据步骤描述选择合适的工具
2. 如果需要调用工具，请使用正确的工具调用格式
3. 执行完成后提供详细的执行结果
"""

    if skill_content:
        prompt += f"\n\n参考工作流程：\n{skill_content}"

    return prompt


def _get_tool_descriptions(tools: list) -> str:
    descriptions = []
    for tool_obj in tools:
        # 同时检查 name 和 description 属性，缺少任一都说明工具配置不完整，跳过
        if hasattr(tool_obj, "name") and hasattr(tool_obj, "description"):
            descriptions.append(f"- {tool_obj.name}: {tool_obj.description}")
    # 用换行符连接，生成类似 markdown 列表的格式，方便 LLM 阅读
    return "\n".join(descriptions)
