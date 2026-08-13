import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Loader2,
  Layers,
  AlertTriangle,
  Bell,
  X,
  Activity,
} from 'lucide-react';
import { useAuth } from '@/lib/AuthContext';
import { formatFileSize, cn } from '@/lib/utils';
import { streamChat } from '@/api/chat';
import {
  getConversations,
  getConversation,
  createConversation,
  deleteConversation,
} from '@/api/conversations';
import { approveToolResult, rejectToolResult } from '@/api/review';
import { useWebSocket } from '@/lib/useWebSocket';
import Sidebar from '@/components/Sidebar';
import TopBar from '@/components/TopBar';
import ChatArea from '@/components/ChatArea';
import ChatInput from '@/components/ChatInput';
import FilePanel from '@/components/FilePanel';
import FilePreviewModal from '@/components/FilePreviewModal';

function resolveChatErrorMessage(err) {
  const code = err?.code || err?.data?.code;
  const requiresConfig = Boolean(err?.requires_config || err?.data?.requires_config);
  const configTarget = err?.config_target || err?.data?.config_target;
  if (code === 'model_api_key_missing' || (requiresConfig && configTarget === 'llm_api_key')) {
    return (
      err?.message ||
      err?.content ||
      '未配置模型 API Key。请到「设置 > 大模型配置」填写企业模型 Key，或联系管理员配置 DEEPSEEK_API_KEY。'
    );
  }

  const candidates = [
    err?.message,
    err?.content,
    err?.data?.message,
    err?.data?.content,
    err?.data?.detail,
    err?.detail,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim();
    }
  }
  if (typeof err === 'string' && err.trim()) {
    return err.trim();
  }
  return '未知错误';
}

/**
 * ChatPage 鈥?涓昏亰澶╅〉闈?
 * 缁勫悎 Sidebar + ChatArea + ChatInput锛岀鐞嗗叏灞€鐘舵€佸拰 SSE 娴佸紡閫氫俊
 * 鏂板锛欶ilePreviewModal 鐘舵€佺鐞?
 */
export default function ChatPage() {
  const { user, logout } = useAuth();

  // 鈹€鈹€ 瀹炴椂閫氱煡锛圵ebSocket锛夆攢鈹€
  // 杩炴帴澶辫触浼氶潤榛橀檷绾э紝涓嶅奖鍝嶄笅鏂规祦寮忚亰澶╀富閾捐矾
  const companyId = user?.company_id ? String(user.company_id) : '';
  const ws = useWebSocket(companyId);

  // 浠诲姟鐘舵€?toast锛歨ook 浠呬繚鐣欐渶鏂颁竴鏉?taskStatus锛岃繖閲岃浆鎴愮煭鏆傞槦鍒楀睍绀?
  const [taskToasts, setTaskToasts] = useState([]);
  const wsTaskStatus = ws.taskStatus;
  useEffect(() => {
    if (!wsTaskStatus) return;
    const id = `task-${wsTaskStatus.taskId}-${wsTaskStatus.status}-${Date.now()}`;
    // 浠呬繚鐣欐渶杩?5 鏉★紝閬垮厤鍫嗙Н
    setTaskToasts((prev) => [...prev.slice(-4), { id, task: wsTaskStatus }]);
  }, [wsTaskStatus]);
  const dismissTaskToast = useCallback((id) => {
    setTaskToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  // 鈹€鈹€ 瀵硅瘽鐘舵€?鈹€鈹€
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);

  // 鈹€鈹€ 鏂囦欢棰勮鐘舵€?鈹€鈹€
  const [previewFile, setPreviewFile] = useState(null);

  // 鈹€鈹€ 妯″瀷閫夋嫨 鈹€鈹€
  const [selectedModel, setSelectedModel] = useState(
    () => {
      const stored = localStorage.getItem('selected_model');
      return !stored || stored === 'deepseek-chat' ? 'glm-5.2' : stored;
    }
  );

  // 鈹€鈹€ 宓屽叆妯″瀷閫夋嫨 鈹€鈹€
  const [selectedEmbedding, setSelectedEmbedding] = useState(
    () => localStorage.getItem('selected_embedding') || 'bge-large-zh'
  );

  const abortRef = useRef(null);

  // 鈹€鈹€ 鍔犺浇瀵硅瘽鍒楄〃 鈹€鈹€
  const loadConversations = useCallback(async () => {
    try {
      setLoadingConversations(true);
      const data = await getConversations({ limit: 50 });
      setConversations(data.items || []);
    } catch (err) {
      console.error('加载对话列表失败:', err);
    } finally {
      setLoadingConversations(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // 鈹€鈹€ 淇濆瓨妯″瀷閫夋嫨 鈹€鈹€
  useEffect(() => {
    localStorage.setItem('selected_model', selectedModel);
  }, [selectedModel]);

  // 鈹€鈹€ 鏂板缓瀵硅瘽 鈹€鈹€
  const handleNewChat = useCallback(() => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
    }
    setActiveConversationId(null);
    setMessages([]);
    setIsStreaming(false);
    setSidebarOpen(false);
  }, []);

  // 鈹€鈹€ 閫夋嫨瀵硅瘽 鈹€鈹€
  const handleSelectConversation = useCallback(async (id) => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
    }
    try {
      const data = await getConversation(id);
      setActiveConversationId(id);
      setMessages(
        (data.messages || []).map((m) => ({
          ...m,
          isStreaming: false,
        }))
      );
      setIsStreaming(false);
      setSidebarOpen(false);
    } catch (err) {
      console.error('加载对话详情失败:', err);
    }
  }, []);

  // 鈹€鈹€ 鍒犻櫎瀵硅瘽 鈹€鈹€
  const handleDeleteConversation = useCallback(
    async (id) => {
      try {
        await deleteConversation(id);
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (activeConversationId === id) {
          setActiveConversationId(null);
          setMessages([]);
        }
      } catch (err) {
        console.error('删除对话失败:', err);
      }
    },
    [activeConversationId]
  );

  // 鈹€鈹€ 鏇存柊鏈€鍚庝竴鏉?assistant 娑堟伅 鈹€鈹€
  const updateLastAssistant = useCallback((updater) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const lastIdx = prev.length - 1;
      if (prev[lastIdx].role !== 'assistant') return prev;
      return [...prev.slice(0, lastIdx), updater(prev[lastIdx])];
    });
  }, []);

  // 鈹€鈹€ 鍙戦€佹秷鎭紙SSE 娴佸紡锛?鈹€鈹€
  const handleSend = useCallback(
    async (text, files = []) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      // 鍒涘缓鐢ㄦ埛娑堟伅 鈥?鍖呭惈闄勪欢
      const userMsg = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: trimmed,
        attachments: files.map((f, i) => ({
          id: `att-${Date.now()}-${i}`,
          name: f.name,
          size: formatFileSize(f.size),
          type: inferFileType(f.name),
          source: 'uploaded',
          rawFile: f,
        })),
        createdAt: new Date().toISOString(),
      };

      // 鍒涘缓 assistant 鍗犱綅娑堟伅
      const assistantMsg = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: '',
        thinking: '',
        plan: '',
        sources: [],
        warnings: [],
        toolResults: [],
        agentFiles: [],
        isStreaming: true,
        createdAt: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      // 濡傛灉娌℃湁娲诲姩瀵硅瘽锛屽厛鍒涘缓涓€涓?
      let convId = activeConversationId;
      if (!convId) {
        try {
          const conv = await createConversation({ title: trimmed.slice(0, 30) });
          convId = conv.id;
          setActiveConversationId(convId);
          setConversations((prev) => [
            { id: conv.id, title: conv.title || trimmed.slice(0, 30), created_at: conv.created_at },
            ...prev,
          ]);
        } catch (err) {
          console.error('创建对话失败:', err);
        }
      }

      // 鍙戣捣 SSE 娴佸紡璇锋眰
      const chatPayload = {
        message: trimmed,
        conversation_id: convId,
      };
      if (companyId) {
        chatPayload.company_id = companyId;
      }

      const abort = streamChat(
        chatPayload,
        {
          onThinking: (event) => {
            updateLastAssistant((msg) => ({
              ...msg,
              thinking: event.content || event.data?.content || '',
            }));
          },
          onIntent: () => {},
          onPlan: () => {},
          onContent: (event) => {
            const chunk = event.content || event.data?.content || '';
            updateLastAssistant((msg) => ({
              ...msg,
              content: msg.content + chunk,
            }));
          },
          onSources: (event) => {
            updateLastAssistant((msg) => ({
              ...msg,
              sources: event.sources || event.data?.sources || [],
            }));
          },
          onWarning: (event) => {
            const warning = {
              id: event.id || `${event.code || 'warning'}-${event.from_model || ''}-${event.to_model || ''}`,
              code: event.code || 'warning',
              message: event.message || event.content || event.data?.message || '系统已降级处理本次请求。',
              from_model: event.from_model || event.data?.from_model || '',
              to_model: event.to_model || event.data?.to_model || '',
            };
            updateLastAssistant((msg) => {
              const existing = msg.warnings || [];
              if (existing.some((item) => item.id === warning.id)) {
                return msg;
              }
              return { ...msg, warnings: [...existing, warning] };
            });
          },
          onToolResult: (event) => {
            const toolName = event.name || event.data?.name || '??';
            // 閫忎紶缁撴瀯鍖栨暟鎹細杈句汉鎼滅储宸ュ叿璧颁笓鐢ㄥ崱鐗?
            if (event.tool === 'searchTalents' || toolName === 'searchTalents') {
              const payload = {
                id: event.id || event.data?.id || `tool-${Date.now()}`,
                type: 'searchTalents',
                name: toolName,
                loading: Boolean(event.loading ?? event.data?.loading),
                query: event.query ?? event.data?.query,
                talents: event.talents ?? event.data?.talents,
                total: event.total ?? event.data?.total,
              };
              updateLastAssistant((msg) => {
                const existing = msg.toolResults || [];
                const idx = existing.findIndex((t) => t.id === payload.id);
                if (idx >= 0) {
                  const next = [...existing];
                  next[idx] = { ...next[idx], ...payload };
                  return { ...msg, toolResults: next };
                }
                return { ...msg, toolResults: [...existing, payload] };
              });
              return;
            }
            // 閫氱敤宸ュ叿缁撴灉 鈥?鎸?id 鍖归厤骞舵洿鏂帮紙涓?searchTalents 鐩稿悓鐨勬ā寮忥級
            return;
          },
          onReflection: () => {},
          onRetry: () => {
            // 閲嶈瘯鏃舵竻绌哄綋鍓嶅唴瀹?
            updateLastAssistant((msg) => ({
              ...msg,
              content: '',
            }));
          },
          onDelegation: () => {},
          onDone: (event) => {
            // 鎹曡幏杩斿洖鐨?conversation_id
            const newConvId = event?.conversation_id || event?.data?.conversation_id;
            if (newConvId && !activeConversationId) {
              setActiveConversationId(newConvId);
            }
            updateLastAssistant((msg) => ({
              ...msg,
              isStreaming: false,
            }));
            setIsStreaming(false);
            abortRef.current = null;
            // 鍒锋柊瀵硅瘽鍒楄〃
            loadConversations();
          },
          onError: (err) => {
            const readableError = resolveChatErrorMessage(err);
            updateLastAssistant((msg) => ({
              ...msg,
              isStreaming: false,
              content:
                msg.content ||
                `抱歉，处理时出错了：${readableError}`,
            }));
            setIsStreaming(false);
            abortRef.current = null;
          },
        }
      );

      abortRef.current = abort;
    },
    [isStreaming, activeConversationId, updateLastAssistant, loadConversations]
  );

  // 鈹€鈹€ 鍋滄娴佸紡 鈹€鈹€
  const handleStop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
    }
    setIsStreaming(false);
    updateLastAssistant((msg) => ({
      ...msg,
      isStreaming: false,
    }));
  }, [updateLastAssistant]);

  // 鈹€鈹€ 瀹℃牳閫氳繃 鈹€鈹€
  const handleApprove = useCallback(async (toolResultId) => {
    try {
      await approveToolResult(toolResultId);
      updateLastAssistant((msg) => ({
        ...msg,
        toolResults: (msg.toolResults || []).map((t) =>
          t.id === toolResultId ? { ...t, approved: true } : t
        ),
      }));
    } catch (err) {
      console.error('审核通过失败:', err);
    }
  }, [updateLastAssistant]);

  // 鈹€鈹€ 瀹℃牳椹冲洖 鈹€鈹€
  const handleReject = useCallback(async (toolResultId, reason) => {
    try {
      await rejectToolResult(toolResultId, reason);
      updateLastAssistant((msg) => ({
        ...msg,
        toolResults: (msg.toolResults || []).map((t) =>
          t.id === toolResultId ? { ...t, rejected: true, rejectReason: reason } : t
        ),
      }));
    } catch (err) {
      console.error('审核驳回失败:', err);
    }
  }, [updateLastAssistant]);

  // 鈹€鈹€ 鏂囦欢棰勮 鈹€鈹€
  const handlePreviewFile = useCallback((file) => {
    if (!file) return;
    setPreviewFile(file);
  }, []);

  const handleClosePreview = useCallback(() => {
    setPreviewFile(null);
  }, []);

  // 鈹€鈹€ 涓嬭浇鏂囦欢 鈹€鈹€
  const handleDownloadFile = useCallback((file) => {
    if (!file) return;
    const url = file.url || file.download_url;
    if (!url) {
      console.warn('文件缺少可下载的 URL:', file);
      return;
    }
    const a = document.createElement('a');
    a.href = url;
    a.download = file.name || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, []);

  // 鈹€鈹€ 淇濆瓨宓屽叆妯″瀷閫夋嫨 鈹€鈹€
  useEffect(() => {
    localStorage.setItem('selected_embedding', selectedEmbedding);
  }, [selectedEmbedding]);

  // 鈹€鈹€ 褰撳墠瀵硅瘽鏍囬 鈹€鈹€
  const conversationTitle =
    conversations.find((c) => String(c.id) === String(activeConversationId))?.title ||
    '新对话';

  return (
    <div className="flex h-svh w-full overflow-hidden bg-background">
      {/* 渚ц竟鏍?*/}
      <Sidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        loading={loadingConversations}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        user={user}
        onLogout={logout}
      />

      {/* 涓诲唴瀹瑰尯 */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 椤舵爮锛氭ā鍨嬮€夋嫨 + 宓屽叆妯″瀷 + Token 娑堣€?+ 鏂囦欢闈㈡澘 */}
        <TopBar
          model={selectedModel}
          setModel={setSelectedModel}
          embedding={selectedEmbedding}
          setEmbedding={setSelectedEmbedding}
          filesOpen={filesOpen}
          onToggleFiles={() => setFilesOpen((s) => !s)}
          conversationTitle={conversationTitle}
        />

        {/* 鑱婂ぉ鍖哄煙 */}
        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <ChatArea
            messages={messages}
            isStreaming={isStreaming}
            conversationTitle={conversationTitle}
            onApprove={handleApprove}
            onReject={handleReject}
            onSendMessage={(text) => handleSend(text)}
            onFileClick={handlePreviewFile}
            onUserFileClick={handlePreviewFile}
          />
        </main>

        {/* 杈撳叆鍖哄煙 */}
        <ChatInput
          onSend={handleSend}
          isStreaming={isStreaming}
          onStop={handleStop}
        />
      </div>

      {/* 鏂囦欢闈㈡澘锛堝彲鎶樺彔锛?*/}
      {filesOpen && (
        <FilePanel
          conversationId={activeConversationId}
          onClose={() => setFilesOpen(false)}
          onPreview={handlePreviewFile}
        />
      )}

      {/* 鏂囦欢棰勮妯℃€佹锛堝叏灞€锛岃法椤甸潰涔熷彲澶嶇敤锛?*/}
      <FilePreviewModal
        file={previewFile}
        onClose={handleClosePreview}
        onDownload={handleDownloadFile}
      />

      {/* WebSocket 瀹炴椂閫氱煡灞傦細浠诲姟/瀹℃牳/鍛婅/Agent 鐘舵€?閾捐矾杩涘害 */}
      <WsNotifications
        ws={ws}
        taskToasts={taskToasts}
        dismissTaskToast={dismissTaskToast}
      />
    </div>
  );
}

/* 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
   Helpers
   鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?*/
function inferFileType(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  if (['xls', 'xlsx', 'csv'].includes(ext)) return 'sheet';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return 'image';
  if (ext === 'pdf') return 'pdf';
  if (['doc', 'docx'].includes(ext)) return 'doc';
  if (['md', 'txt'].includes(ext)) return 'text';
  return 'text';
}

/* 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
   WebSocket 瀹炴椂閫氱煡 UI
   鈥?澶嶇敤 macaron 閰嶈壊 + 鐜版湁鎸夐挳椋庢牸锛屼笉浣跨敤 alert/confirm
   鈥?鍏ㄩ儴 fixed 瀹氫綅锛宲ointer-events-none 瀹瑰櫒 + pointer-events-auto 鍗＄墖
     閬垮厤閬尅鑱婂ぉ鍖轰氦浜?
   鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?*/

// tone 鈫?棰滆壊鏄犲皠锛堜笌 TopBar/PlatformAuthSection 椋庢牸涓€鑷达級
const WS_TONE_STYLES = {
  info: { dot: 'oklch(0.72 0.15 230)' },   // 闆捐摑
  success: { dot: 'oklch(0.72 0.15 145)' }, // 钖勮嵎缁?
  warn: { dot: 'oklch(0.78 0.14 95)' },     // 鏉忛粍
  error: { dot: 'oklch(0.70 0.18 20)' },    // 铚滄绾?
};

// 鍗曟潯閫氱煡锛氳嚜绠″畾鏃舵秷澶憋紝鍒扮偣璋?onClose 璁╃埗绾хЩ闄?
function WsToast({ onClose, delay = 6000, tone = 'info', icon, title, children }) {
  useEffect(() => {
    const t = setTimeout(onClose, delay);
    return () => clearTimeout(t);
  }, [onClose, delay]);

  const toneStyle = WS_TONE_STYLES[tone] || WS_TONE_STYLES.info;

  return (
    <div
      className="pointer-events-auto flex items-start gap-2 rounded-xl border border-border bg-card/95 px-3 py-2.5 text-xs shadow-sm backdrop-blur"
      role="status"
    >
      <span className="mt-0.5 shrink-0" style={{ color: toneStyle.dot }}>
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        {title && (
          <p className="font-medium text-foreground">{title}</p>
        )}
        {children && (
          <div className="mt-0.5 text-muted-foreground">{children}</div>
        )}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="关闭通知"
        className="inline-flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}

function WsNotifications({ ws, taskToasts, dismissTaskToast }) {
  const {
    connected,
    reviewNotifications,
    agentStatus,
    chainProgress,
    alerts,
    dismissReview,
    dismissAlert,
  } = ws;

  // 姝ｅ湪鎵ц鐨?Agent锛坰tatus 钀藉湪甯歌"蹇欑"鏋氫妇閲岋級
  const runningAgents = Object.entries(agentStatus).filter(([, v]) => {
    const s = String(v?.status || '').toLowerCase();
    return ['running', 'working', 'busy', 'started', 'processing'].includes(s);
  });

  // 娲昏穬鐨勫 Agent 鍗忎綔閾捐矾锛堟湭瀹屾垚锛?
  const activeChains = Object.entries(chainProgress).filter(
    ([, v]) => v.totalSteps > 0 && v.completedSteps < v.totalSteps
  );

  const hasAnyToast =
    taskToasts.length > 0 ||
    reviewNotifications.length > 0 ||
    alerts.length > 0;

  return (
    <>
      {/* 杩炴帴鐘舵€佺偣锛堟瀬绠€锛屽乏涓嬭锛屼笉骞叉壈涓荤晫闈級 */}
      <div
        className="pointer-events-none fixed bottom-2 left-2 z-30 flex items-center gap-1"
        title={connected ? '实时连接正常' : '实时连接未建立（已降级）'}
        aria-label={connected ? '实时连接正常' : '实时连接未建立'}
      >
        <span
          className="size-1.5 rounded-full"
          style={{
            backgroundColor: connected
              ? 'oklch(0.72 0.15 145)'
              : 'oklch(0.7 0.02 0)',
          }}
        />
      </div>

      {/* 鍙充笂瑙掗€氱煡鏍堬細浠诲姟鐘舵€?/ 瀹℃牳 / 鍛婅 */}
      {hasAnyToast && (
        <div className="pointer-events-none fixed right-4 top-16 z-40 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
          {taskToasts.map(({ id, task }) => (
            <WsToast
              key={id}
              onClose={() => dismissTaskToast(id)}
              delay={4000}
              tone="info"
              icon={<Activity className="size-3.5" />}
              title={`任务 #${task.taskId} 状态更新`}
            >
              <span className="capitalize">
                {task.status}
                {task.agent ? ` 路 ${task.agent}` : ''}
              </span>
            </WsToast>
          ))}

          {reviewNotifications.map((n) => (
            <WsToast
              key={`r-${n.reviewId}`}
              onClose={() => dismissReview(n.reviewId)}
              delay={10000}
              tone={
                n.level === 'critical' ? 'error'
                  : n.level === 'warning' ? 'warn'
                  : 'info'
              }
              icon={<Bell className="size-3.5" />}
              title="需要人工审核"
            >
              <span>
                Agent {n.agent || '??'}
                {n.level ? ` 路 ${n.level}` : ''}
              </span>
            </WsToast>
          ))}

          {alerts.map((a) => (
            <WsToast
              key={`a-${a.alertId}`}
              onClose={() => dismissAlert(a.alertId)}
              delay={8000}
              tone={
                a.severity === 'error' ? 'error'
                  : a.severity === 'warning' ? 'warn'
                  : 'info'
              }
              icon={<AlertTriangle className="size-3.5" />}
              title={a.title || '告警通知'}
            >
              <span>{a.message}</span>
            </WsToast>
          ))}
        </div>
      )}

      {/* 椤堕儴閾捐矾杩涘害鏉★紙澶?Agent 鍗忎綔锛?*/}
      {activeChains.length > 0 && (
        <div className="pointer-events-none fixed left-0 right-0 top-14 z-30 flex flex-col gap-1 px-4">
          {activeChains.map(([name, v]) => {
            const pct =
              v.totalSteps > 0
                ? Math.round((v.completedSteps / v.totalSteps) * 100)
                : 0;
            return (
              <div
                key={name}
                className="pointer-events-auto mx-auto flex w-full max-w-2xl items-center gap-2 rounded-lg border border-border bg-card/95 px-3 py-1.5 text-xs shadow-sm backdrop-blur"
              >
                <Layers className="size-3.5 shrink-0 text-primary" />
                <span className="shrink-0 font-medium text-foreground">
                  {name}
                </span>
                <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
                  <div
                    className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="shrink-0 font-mono text-muted-foreground">
                  {v.completedSteps}/{v.totalSteps}
                </span>
                {v.currentStep && (
                  <span className="hidden shrink-0 truncate text-muted-foreground sm:inline">
                    路 {v.currentStep}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 搴曢儴 Agent 鎵ц鐘舵€佸窘鏍?*/}
      {runningAgents.length > 0 && (
        <div className="pointer-events-none fixed bottom-24 right-4 z-40 flex flex-col gap-1.5">
          {runningAgents.map(([key, v]) => (
            <div
              key={key}
              className="pointer-events-auto flex items-center gap-2 rounded-full border border-border bg-card/95 px-3 py-1.5 text-xs shadow-sm backdrop-blur"
            >
              <Loader2 className="size-3.5 animate-spin text-primary" />
              <span className="text-foreground">{key} 正在执行...</span>
              {v.taskCount > 0 && (
                <span className="text-muted-foreground">路 {v.taskCount}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}



