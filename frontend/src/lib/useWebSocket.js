import { useEffect, useReducer, useRef } from 'react';

/**
 * useWebSocket — 实时通知接入 Hook
 *
 * 监听后端 /ws/connect/{company_id} WebSocket，消费以下消息类型（对齐 ws.py）：
 *   - task_status           任务状态变更
 *   - review_notification   审核通知（需人工审批）
 *   - agent_status          Agent 运行状态
 *   - chain_progress        多 Agent 协作链路进度
 *   - alert                 告警
 *
 * 设计要点：
 *   1. useReducer 聚合状态，单次 dispatch 触发一次重渲染，避免高频消息刷屏
 *   2. ws 实例 / 重连定时器 / 重试次数用 useRef 持有，不进 React 状态
 *   3. 指数退避重连（1s→2s→4s→8s→16s），最多 5 次，避免后端不可用时打满连接
 *   4. 心跳 ping 每 30s 一次，穿透代理/防火墙的空闲断连
 *   5. 异常会记录为前端告警并降级，不阻塞主聊天功能
 *   6. companyId 缺失时不连接；鉴权依赖同源 httpOnly cookie 自动携带
 *
 * cookie 鉴权说明（与 client.js 的 withCredentials 同源带 cookie 一致）：
 *   切换到 httpOnly cookie 后，JS 不再读取 token，URL 不拼 ?token=。
 *   只要 WS URL 与页面同源，浏览器在 WebSocket 握手阶段会自动携带 access_token
 *   httpOnly cookie，后端 ws.py 的 _authenticate_ws 会从 cookie 读取校验。
 *
 * @param {string|number} companyId - 公司 ID
 * @returns {{connected: boolean, taskStatus: object|null, reviewNotifications: array, agentStatus: object, chainProgress: object, alerts: array, dismissReview: function, dismissAlert: function}}
 */
const MAX_RETRIES = 5;            // 最大重连次数
const HEARTBEAT_INTERVAL = 30000; // 心跳间隔 30s
const REVIEW_QUEUE_LIMIT = 20;    // 审核通知队列上限，超出丢弃最旧的
const ALERT_QUEUE_LIMIT = 10;     // 告警队列上限

// ── 构建 WebSocket URL ──────────────────────────────────────────
// 开发环境走 vite 代理 /ws → :8000；生产可用 VITE_WS_BASE 直连（如 wss://api.example.com/ws）
// cookie 方案：不再拼接 ?token=，鉴权依赖同源 httpOnly cookie（WebSocket 握手时浏览器自动携带）
export function buildWsUrl(companyId) {
  const override = import.meta.env.VITE_WS_BASE;
  let base;
  if (override) {
    base = normalizeWsBase(override);
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${proto}//${window.location.host}/ws`;
  }
  return `${base}/connect/${encodeURIComponent(companyId)}`;
}

function normalizeWsBase(value) {
  const trimmed = String(value).replace(/\/+$/, '');
  if (trimmed.endsWith('/ws')) return trimmed;
  return `${trimmed}/ws`;
}

// ── reducer：按消息类型路由到不同状态切片 ──────────────────────
const initialState = {
  connected: false,
  taskStatus: null,        // 最近一条任务状态 {taskId, status, agent, result}
  reviewNotifications: [], // 审核通知队列（FIFO，保留最近 N 条）
  agentStatus: {},         // { [agentKey]: { status, taskCount } }
  chainProgress: {},       // { [chainName]: { completedSteps, totalSteps, currentStep } }
  alerts: [],              // 告警队列
};

function reducer(state, action) {
  switch (action.type) {
    case 'SET_CONNECTED':
      // 重连成功时清空重试计数由 effect 处理；这里只更新连接状态
      return { ...state, connected: action.value };

    case 'TASK_STATUS':
      return { ...state, taskStatus: action.payload };

    case 'REVIEW_NOTIFICATION': {
      const next = [...state.reviewNotifications, action.payload];
      // 超出上限丢弃最旧的，避免内存无限增长
      if (next.length > REVIEW_QUEUE_LIMIT) next.shift();
      return { ...state, reviewNotifications: next };
    }

    case 'AGENT_STATUS':
      return {
        ...state,
        agentStatus: {
          ...state.agentStatus,
          [action.payload.agent]: {
            status: action.payload.status,
            taskCount: action.payload.taskCount ?? 0,
          },
        },
      };

    case 'CHAIN_PROGRESS':
      return {
        ...state,
        chainProgress: {
          ...state.chainProgress,
          [action.payload.chain]: {
            completedSteps: action.payload.completedSteps ?? 0,
            totalSteps: action.payload.totalSteps ?? 0,
            currentStep: action.payload.currentStep ?? null,
          },
        },
      };

    case 'ALERT': {
      const next = [...state.alerts, action.payload];
      if (next.length > ALERT_QUEUE_LIMIT) next.shift();
      return { ...state, alerts: next };
    }

    case 'DISMISS_REVIEW':
      return {
        ...state,
        reviewNotifications: state.reviewNotifications.filter((n) => n.reviewId !== action.reviewId),
      };

    case 'DISMISS_ALERT':
      return {
        ...state,
        alerts: state.alerts.filter((a) => a.alertId !== action.alertId),
      };

    case 'RESET':
      return initialState;

    default:
      return state;
  }
}

export function useWebSocket(companyId) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // ── ref 持有可变且不触发渲染的实例 ──
  const wsRef = useRef(null);          // 当前 WebSocket 实例
  const reconnectTimerRef = useRef(null); // 重连定时器
  const heartbeatTimerRef = useRef(null); // 心跳定时器
  const retryCountRef = useRef(0);     // 已重试次数
  const closedByUsRef = useRef(false); // 组件卸载主动关闭标记，避免触发重连

  useEffect(() => {
    // cookie 方案：不再依赖 getAuthToken()，鉴权由同源 httpOnly cookie 在 WebSocket 握手时自动携带
    // companyId 缺失则不连接（静默降级）
    if (!companyId) {
      dispatch({ type: 'SET_CONNECTED', value: false });
      return undefined;
    }

    const url = buildWsUrl(companyId);

    // 清理所有定时器（重连 + 心跳）
    const clearTimers = () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
    };

    // 主动关闭连接并标记，阻止 onclose 触发重连
    const teardown = () => {
      closedByUsRef.current = true;
      clearTimers();
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* noop */
        }
        wsRef.current = null;
      }
    };

    // 建立连接
    const connect = () => {
      let ws;
      try {
        ws = new WebSocket(url);
      } catch (e) {
        // 构造异常（如 URL 非法）—— 静默降级，不重连
        console.warn('[useWebSocket] 构造失败，已降级:', e);
        dispatch({ type: 'SET_CONNECTED', value: false });
        return;
      }
      wsRef.current = ws;
      closedByUsRef.current = false;

      ws.onopen = () => {
        retryCountRef.current = 0; // 连接成功，重置重试计数
        dispatch({ type: 'SET_CONNECTED', value: true });
        // 心跳：穿透代理空闲断连，服务端收到 ping 回 pong
        heartbeatTimerRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try {
              ws.send(JSON.stringify({ type: 'ping' }));
            } catch {
              /* noop */
            }
          }
        }, HEARTBEAT_INTERVAL);
      };

      ws.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch (err) {
          console.warn('WebSocket: invalid JSON message', err);
          dispatch({
            type: 'ALERT',
            payload: {
              alertId: `ws-invalid-json-${Date.now()}`,
              alert_type: 'websocket_invalid_json',
              message: '收到无法解析的实时消息',
            },
          });
          return;
        }
        const t = msg?.type;
        if (!t) return;
        // 按消息类型路由到对应 reducer 分支
        switch (t) {
          case 'task_status':
            dispatch({ type: 'TASK_STATUS', payload: msg });
            break;
          case 'review_notification':
            dispatch({ type: 'REVIEW_NOTIFICATION', payload: msg });
            break;
          case 'agent_status':
            dispatch({ type: 'AGENT_STATUS', payload: msg });
            break;
          case 'chain_progress':
            dispatch({ type: 'CHAIN_PROGRESS', payload: msg });
            break;
          case 'alert':
            dispatch({ type: 'ALERT', payload: msg });
            break;
          case 'pong':
            // 心跳响应，无需处理
            break;
          default:
            break;
        }
      };

      ws.onerror = () => {
        // 不在此处弹错误，由 onclose 统一走重连逻辑；出错会让 readyState 变化
        console.warn('[useWebSocket] 连接异常');
      };

      ws.onclose = () => {
        dispatch({ type: 'SET_CONNECTED', value: false });
        if (heartbeatTimerRef.current) {
          clearInterval(heartbeatTimerRef.current);
          heartbeatTimerRef.current = null;
        }
        // 主动关闭（卸载）则不再重连
        if (closedByUsRef.current) return;
        // 指数退避重连：1s, 2s, 4s, 8s, 16s
        if (retryCountRef.current >= MAX_RETRIES) {
          console.warn(`[useWebSocket] 已达最大重连次数 ${MAX_RETRIES}，停止重连`);
          return;
        }
        const delay = Math.min(1000 * 2 ** retryCountRef.current, 16000);
        retryCountRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          connect();
        }, delay);
      };
    };

    connect();

    // 卸载时主动关闭 + 清理定时器
    return () => {
      teardown();
    };
  }, [companyId]);

  // 关闭审核通知（用户已处理或手动忽略）
  const dismissReview = (reviewId) =>
    dispatch({ type: 'DISMISS_REVIEW', reviewId });

  // 关闭告警
  const dismissAlert = (alertId) =>
    dispatch({ type: 'DISMISS_ALERT', alertId });

  return {
    connected: state.connected,
    taskStatus: state.taskStatus,
    reviewNotifications: state.reviewNotifications,
    agentStatus: state.agentStatus,
    chainProgress: state.chainProgress,
    alerts: state.alerts,
    dismissReview,
    dismissAlert,
  };
}

