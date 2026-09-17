
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

/**
 * SSE 流式聊天
 *
 * 使用 fetch + ReadableStream 实现 SSE 流式接收。
 * 返回一个 abort 函数用于取消请求。
 *
 * @param {Object} params
 * @param {string} params.message - 用户消息
 * @param {string} [params.conversation_id] - 对话 ID（可选）
 * @param {string} [params.agent_name] - 指定 Agent 名称（可选）
 * @param {string} [params.mode] - 工作模式（可选）
 * @param {Object} callbacks - SSE 事件回调
 * @param {Function} [callbacks.onThinking] - thinking 事件
 * @param {Function} [callbacks.onIntent] - intent 事件
 * @param {Function} [callbacks.onPlan] - plan 事件
 * @param {Function} [callbacks.onSources] - sources 事件
 * @param {Function} [callbacks.onToolResult] - tool_result 事件
 * @param {Function} [callbacks.onContent] - content 事件（增量文本）
 * @param {Function} [callbacks.onWarning] - warning 事件（可见降级/风险提示）
 * @param {Function} [callbacks.onReflection] - reflection 事件
 * @param {Function} [callbacks.onRetry] - retry 事件
 * @param {Function} [callbacks.onDelegation] - delegation 事件（子 Agent 委派状态）
 * @param {Function} [callbacks.onDone] - done 事件（对话完成）
 * @param {Function} [callbacks.onError] - error 事件
 * @returns {Function} abort - 取消请求的函数
 */
export function streamChat(params, callbacks) {
  const controller = new AbortController();
  let terminalReceived = false;
  let errorNotified = false;
  const notifyError = (error) => {
    if (errorNotified || terminalReceived || controller.signal.aborted) return;
    errorNotified = true;
    callbacks.onError?.(error);
  };
  const interruptedError = () => ({
    code: 'chat_stream_interrupted',
    message: '回答连接中断，尚未确认完成。请打开左侧当前历史对话查看已保存结果；不会自动重发模型请求。',
  });

  const body = {
    message: params.message,
    ...(params.conversation_id && { conversation_id: params.conversation_id }),
    ...(params.agent_name && { agent_name: params.agent_name }),
    ...(params.company_id && { company_id: String(params.company_id) }),
    ...(params.model_provider && { model_provider: String(params.model_provider) }),
    ...(params.mode && { mode: params.mode }),
  };

  const headers = { 'Content-Type': 'application/json' };

  fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    credentials: 'include',
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        // 兼容 FastAPI HTTPException（detail）和全局异常处理器（message）两种格式
        const message = err.detail || err.message || `Chat failed (${response.status})`;
        const error = new Error(message);
        error.status = response.status;
        error.data = err;
        notifyError(error);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const notifyDone = (event) => {
        if (terminalReceived) return;
        terminalReceived = true;
        if (!errorNotified) callbacks.onDone?.(event);
      };

      const processLine = (line) => {
        line = line.endsWith('\r') ? line.slice(0, -1) : line;
        if (!line.startsWith('data: ')) return false;

        const data = line.slice(6);
        if (data === '[DONE]') {
          notifyDone();
          return true;
        }

        let event;
        try {
          event = JSON.parse(data);
        } catch {
          return false;
        }
        if (event.type === 'done') {
          notifyDone(event);
          return true;
        }
        if (event.type === 'error') {
          notifyError(_normalizeErrorEvent(event));
        } else {
          _dispatchEvent(event, callbacks);
        }
        return false;
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (processLine(line)) return;
          }
        }

        // EOF is transport termination, not proof of successful model completion.
        // Still accept a complete terminal event without a trailing newline.
        buffer += decoder.decode();
        if (buffer) {
          for (const line of buffer.split('\n')) {
            if (processLine(line)) break;
          }
        }
        if (!terminalReceived) notifyError(interruptedError());
      } finally {
        if (terminalReceived || controller.signal.aborted) {
          await reader.cancel?.().catch(() => {});
        }
        reader.releaseLock?.();
      }
    })
    .catch((err) => {
      if (err.name === 'AbortError') return;
      notifyError(interruptedError());
    });

  return () => controller.abort();
}

/**
 * 分发 SSE 事件到对应的回调
 */
function _dispatchEvent(event, callbacks) {
  switch (event.type) {
    case 'thinking':
      callbacks.onThinking?.(event);
      break;
    case 'intent':
      callbacks.onIntent?.(event);
      break;
    case 'plan':
      callbacks.onPlan?.(event);
      break;
    case 'sources':
      callbacks.onSources?.(event);
      break;
    case 'tool_result':
      callbacks.onToolResult?.(event);
      break;
    case 'content':
      callbacks.onContent?.(event);
      break;
    case 'warning':
      callbacks.onWarning?.(event);
      break;
    case 'reflection':
      callbacks.onReflection?.(event);
      break;
    case 'retry':
      callbacks.onRetry?.(event);
      break;
    case 'delegation':
      callbacks.onDelegation?.(event);
      break;
    case 'done':
      callbacks.onDone?.(event);
      break;
    case 'error':
      callbacks.onError?.(_normalizeErrorEvent(event));
      break;
    default:
      // 未知事件类型，忽略
      break;
  }
}

function _normalizeErrorEvent(event) {
  const message =
    event.message ||
    event.content ||
    event.data?.message ||
    event.data?.content ||
    '聊天处理失败';
  return {
    ...event,
    message,
    content: message,
    code: event.code || event.data?.code || 'chat_stream_error',
    requires_config: Boolean(event.requires_config || event.data?.requires_config),
    config_target: event.config_target || event.data?.config_target || '',
  };
}
