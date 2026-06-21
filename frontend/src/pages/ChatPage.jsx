import { useState, useCallback, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { message } from 'antd';
import Sidebar from '@/components/Sidebar';
import ChatArea from '@/components/ChatArea';
import ChatInput from '@/components/ChatInput';
import { streamChat } from '@/api/chat';
import { getConversations, getConversation, deleteConversation } from '@/api/conversations';
import { approveToolResult, rejectToolResult } from '@/api/review';

/** 格式化时间为相对时间描述 */
function formatTime(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now - date;
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  if (hours < 24) return `${hours} 小时前`;
  if (days < 7) return `${days} 天前`;
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

/** 将 API 返回的消息格式化为前端消息格式 */
function normalizeMessages(apiMessages) {
  if (!apiMessages || !Array.isArray(apiMessages)) return [];
  return apiMessages.map((m) => ({
    id: m.id,
    role: m.role === 'assistant' ? 'master' : m.role,
    content: m.content || '',
    metadata: m.metadata || {},
  }));
}

export default function ChatPage() {
  const { id } = useParams();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState(id || null);
  const [conversations, setConversations] = useState([]);
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const abortRef = useRef(null);

  // ========= 加载对话列表 =========
  const loadConversations = useCallback(async () => {
    try {
      const data = await getConversations({ limit: 50 });
      const items = (data.items || data || []).map((c) => ({
        ...c,
        formattedTime: formatTime(c.updated_at || c.created_at),
      }));
      setConversations(items);
    } catch (err) {
      message.error('加载对话列表失败');
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // ========= 加载对话消息 =========
  const loadMessages = useCallback(async (convId) => {
    setIsLoadingMessages(true);
    try {
      const data = await getConversation(convId);
      const normalized = normalizeMessages(data.messages || []);
      setMessages(normalized);
    } catch (err) {
      message.error('加载对话消息失败');
      setMessages([]);
    } finally {
      setIsLoadingMessages(false);
    }
  }, []);

  // 当路由参数 id 变化时加载对应对话
  useEffect(() => {
    if (id) {
      setActiveConversationId(id);
      loadMessages(id);
    }
  }, [id, loadMessages]);

  // ========= SSE 流式聊天 =========
  const handleSend = useCallback(async (content) => {
    if (isStreaming) return;

    const userMsg = { role: 'user', content, id: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setStatusText('AI 正在思考...');

    let accumulatedContent = '';
    const masterMsg = { role: 'master', content: '', id: Date.now() + 1 };

    setMessages((prev) => [...prev, masterMsg]);

    const abort = streamChat(
      { message: content, conversation_id: activeConversationId || undefined },
      {
        onThinking(event) {
          setStatusText(event.content || 'AI 正在思考...');
        },
        onIntent(event) {
          setStatusText(`识别意图: ${event.intent_type || '处理中...'}`);
        },
        onPlan(event) {
          setStatusText('正在制定执行计划...');
          if (event.steps) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === 'master') {
                last.metadata = { ...last.metadata, plan: event };
              }
              return updated;
            });
          }
        },
        onSources(event) {
          if (event.references) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === 'master') {
                last.metadata = { ...last.metadata, sources: event.references };
              }
              return updated;
            });
          }
        },
        onToolResult(event) {
          setStatusText(`工具执行: ${event.tool || '处理中...'}`);
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === 'master') {
              const prevResults = last.metadata?.toolResults || [];
              last.metadata = { ...last.metadata, toolResults: [...prevResults, event] };
            }
            return updated;
          });
        },
        onContent(event) {
          setStatusText('');
          accumulatedContent += event.content || '';
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === 'master') {
              last.content = accumulatedContent;
            }
            return updated;
          });
        },
        onReflection(event) {
          if (event.passed) {
            setStatusText('质量检查通过');
          } else {
            setStatusText('质量检查发现问题，正在修正...');
          }
        },
        onRetry() {
          setStatusText('正在重试...');
        },
        onDone(event) {
          setStatusText('');
          setIsStreaming(false);

          // 如果返回了 conversation_id，更新当前对话 ID
          if (event?.conversation_id && !activeConversationId) {
            setActiveConversationId(event.conversation_id);
          }
          // 刷新对话列表
          loadConversations();
        },
        onError(error) {
          setStatusText('');
          setIsStreaming(false);
          const errMsg = error.message || '对话请求失败';
          message.error(errMsg);
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === 'master' && !last.content) {
              last.content = `抱歉，请求出错了：${errMsg}`;
            }
            return updated;
          });
        },
      }
    );

    abortRef.current = abort;
  }, [isStreaming, activeConversationId, loadConversations]);

  // ========= 对话管理 =========
  const handleNewChat = useCallback(() => {
    if (abortRef.current) abortRef.current();
    setActiveConversationId(null);
    setMessages([]);
    setIsStreaming(false);
    setStatusText('');
  }, []);

  const handleSelectConversation = useCallback((convId) => {
    if (abortRef.current) abortRef.current();
    setActiveConversationId(convId);
    setIsStreaming(false);
    setStatusText('');
    loadMessages(convId);
  }, [loadMessages]);

  const handleDeleteConversation = useCallback(async (convId) => {
    try {
      await deleteConversation(convId);
      message.success('对话已删除');
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConversationId === convId) {
        setActiveConversationId(null);
        setMessages([]);
      }
    } catch (err) {
      message.error('删除对话失败');
    }
  }, [activeConversationId]);

  const handleCapabilityClick = useCallback((label) => {
    handleSend(`帮我${label}`);
  }, [handleSend]);

  // ========= 审核操作 =========
  const handleReview = useCallback(async (action, toolResult, reason) => {
    const toolResultId = toolResult.id || toolResult.tool_result_id;

    // 更新本地状态
    setMessages((prev) => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last.role === 'master' && last.metadata?.toolResults) {
        const newToolResults = last.metadata.toolResults.map((tr) => {
          if (tr === toolResult || tr.id === toolResultId) {
            return {
              ...tr,
              reviewStatus: action === 'approve' ? 'approved' : 'rejected',
              rejectReason: reason || undefined,
            };
          }
          return tr;
        });
        last.metadata = { ...last.metadata, toolResults: newToolResults };
      }
      return updated;
    });

    // 调用 API
    try {
      if (action === 'approve') {
        if (toolResultId) await approveToolResult(toolResultId);
        message.success('已通过审核');
      } else {
        if (toolResultId) await rejectToolResult(toolResultId, reason);
        message.success('已驳回');
      }
    } catch (err) {
      message.error('审核操作失败');
    }
  }, []);

  return (
    <div className="flex h-screen bg-white">
      <Sidebar
        conversations={conversations}
        activeId={activeConversationId}
        onSelect={handleSelectConversation}
        onNew={handleNewChat}
        onDelete={handleDeleteConversation}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <header className="flex items-center gap-3 px-4 h-12 min-h-[48px] border-b border-[var(--color-hairline)] bg-white">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="flex items-center justify-center w-8 h-8 border border-[var(--color-hairline)]
              rounded-md hover:bg-[var(--color-canvas-soft)] transition-colors"
          >
            {sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
          <span className="text-sm font-semibold text-[var(--color-ink)]">
            {activeConversationId
              ? conversations.find((c) => c.id === activeConversationId)?.title || '对话'
              : '新对话'}
          </span>

          {isLoadingMessages && (
            <span className="text-xs text-[var(--color-mute)] ml-2">加载中...</span>
          )}

          {/* Streaming Status */}
          {isStreaming && statusText && (
            <div className="flex items-center gap-1.5 ml-auto px-3 py-1 rounded-full
              bg-[var(--color-canvas-soft)] border border-[var(--color-hairline)] text-xs text-[var(--color-mute)]">
              <span className="flex gap-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)] animate-pulse" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)] animate-pulse" style={{ animationDelay: '200ms' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)] animate-pulse" style={{ animationDelay: '400ms' }} />
              </span>
              <span>{statusText}</span>
            </div>
          )}
        </header>

        <ChatArea
          messages={messages}
          isStreaming={isStreaming}
          onCapabilityClick={handleCapabilityClick}
          onReview={handleReview}
        />

        <ChatInput
          onSend={handleSend}
          disabled={isStreaming}
        />
      </div>
    </div>
  );
}