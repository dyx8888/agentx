import { useState, useCallback, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  DownOutlined,
  KeyOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
  SettingOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import { message, Modal } from 'antd';
import Sidebar from '@/components/Sidebar';
import ChatArea from '@/components/ChatArea';
import ChatInput from '@/components/ChatInput';
import { streamChat } from '@/api/chat';
import { getConversations, getConversation, deleteConversation } from '@/api/conversations';
import { approveToolResult, rejectToolResult } from '@/api/review';

const AVAILABLE_MODELS = [
  { key: 'gpt-4o', label: 'GPT-4o', desc: 'OpenAI 旗舰模型', color: '#10b981' },
  { key: 'gpt-4o-mini', label: 'GPT-4o Mini', desc: '轻量高效', color: '#6366f1' },
  { key: 'claude-sonnet', label: 'Claude 3.5 Sonnet', desc: 'Anthropic 高性能', color: '#f59e0b' },
  { key: 'deepseek-v3', label: 'DeepSeek V3', desc: '国产高性能', color: '#3b82f6' },
];

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

function normalizeMessages(apiMessages) {
  if (!apiMessages || !Array.isArray(apiMessages)) return [];
  return apiMessages.map((m) => ({
    id: m.id,
    role: m.role === 'assistant' ? 'master' : m.role,
    content: m.content || '',
    metadata: m.metadata || {},
  }));
}

function estimateTokens(messages) {
  return messages.reduce((total, m) => {
    const content = m.content || '';
    const chineseChars = (content.match(/[\u4e00-\u9fff]/g) || []).length;
    const otherChars = content.length - chineseChars;
    return total + Math.ceil(chineseChars / 1.5) + Math.ceil(otherChars / 4);
  }, 0);
}

/* ============================================================
   Model Selector — Capsule pill (DeepSeek style)
   ============================================================ */
function ModelSelector({ selectedModel, onSelect, disabled }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const current = AVAILABLE_MODELS.find((m) => m.key === selectedModel) || AVAILABLE_MODELS[0];

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
          text-zinc-600 bg-zinc-100 rounded-full
          hover:bg-zinc-200/70 hover:text-zinc-800
          transition-all duration-150 disabled:opacity-50"
      >
        <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: current.color }} />
        <span className="truncate max-w-[100px]">{current.label}</span>
        <DownOutlined className="text-[10px] text-zinc-400" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-64 bg-white
          border border-zinc-200 rounded-2xl shadow-[0_10px_15px_-3px_rgba(0,0,0,0.06),0_4px_6px_-4px_rgba(0,0,0,0.04)]
          z-50 py-1 overflow-hidden animate-slide-down">
          <div className="px-3 py-2 text-[11px] font-medium text-zinc-400 uppercase tracking-wider">
            选择模型
          </div>
          {AVAILABLE_MODELS.map((model) => {
            const isSelected = model.key === selectedModel;
            return (
              <button
                key={model.key}
                onClick={() => { onSelect(model.key); setOpen(false); }}
                className={`w-full text-left px-4 py-3 transition-colors
                  ${isSelected ? 'bg-indigo-50' : 'hover:bg-zinc-50'}`}
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: model.color }} />
                  <div>
                    <div className={`text-sm ${isSelected ? 'font-semibold text-indigo-600' : 'text-zinc-700'}`}>
                      {model.label}
                    </div>
                    <div className="text-[11px] text-zinc-400 mt-0.5">{model.desc}</div>
                  </div>
                  {isSelected && <CheckCircleOutlined className="text-indigo-500 text-xs ml-auto" />}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Settings Dropdown — contains API Keys, etc.
   ============================================================ */
function SettingsDropdown() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-center w-8 h-8 rounded-full
          text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100
          transition-all duration-150"
        title="设置"
      >
        <SettingOutlined className="text-sm" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-64 bg-white
          border border-zinc-200 rounded-2xl shadow-[0_10px_15px_-3px_rgba(0,0,0,0.06),0_4px_6px_-4px_rgba(0,0,0,0.04)]
          z-50 py-1 overflow-hidden animate-slide-down">
          <div className="px-3 py-2 text-[11px] font-medium text-zinc-400 uppercase tracking-wider">
            设置
          </div>
          <button
            onClick={() => {
              const apiMgr = document.querySelector('[data-testid="api-key-trigger"]');
              if (apiMgr) apiMgr.click();
              setOpen(false);
            }}
            className="w-full text-left px-4 py-2.5 flex items-center gap-2.5
              text-sm text-zinc-600 hover:bg-zinc-50 transition-colors"
          >
            <KeyOutlined className="text-xs" />
            API Keys 管理
          </button>
        </div>
      )}
    </div>
  );
}

/* ============================================================
   API Key Manager — Modal with pill tabs
   ============================================================ */
function ApiKeyManager() {
  const [open, setOpen] = useState(false);
  const [apiKeys, setApiKeys] = useState({
    deepseek: localStorage.getItem('agentx_api_key_deepseek') || '',
    openai: localStorage.getItem('agentx_api_key_openai') || '',
    anthropic: localStorage.getItem('agentx_api_key_anthropic') || '',
  });
  const [activeTab, setActiveTab] = useState('deepseek');
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    localStorage.setItem('agentx_api_key_deepseek', apiKeys.deepseek);
    localStorage.setItem('agentx_api_key_openai', apiKeys.openai);
    localStorage.setItem('agentx_api_key_anthropic', apiKeys.anthropic);
    setSaved(true);
    message.success('API Key 已保存');
    setTimeout(() => setSaved(false), 2000);
  };

  const handleReset = () => {
    setApiKeys({ deepseek: '', openai: '', anthropic: '' });
    localStorage.removeItem('agentx_api_key_deepseek');
    localStorage.removeItem('agentx_api_key_openai');
    localStorage.removeItem('agentx_api_key_anthropic');
    message.info('API Key 已重置');
  };

  const tabs = [
    { key: 'deepseek', label: 'DeepSeek', color: '#3b82f6' },
    { key: 'openai', label: 'OpenAI', color: '#10b981' },
    { key: 'anthropic', label: 'Anthropic', color: '#f59e0b' },
  ];

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="api-key-trigger"
        className="hidden"
      />{' '}
      {/* Hidden trigger — opened via SettingsDropdown */}

      <Modal
        title={null}
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        centered
        width={480}
        closable={false}
      >
        <div className="pt-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-base font-semibold text-zinc-900">API Key 管理</h2>
            <button
              onClick={() => setOpen(false)}
              className="w-8 h-8 flex items-center justify-center rounded-full
                text-zinc-400 hover:bg-zinc-100 transition-colors"
            >
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <path d="M11.7816 4.03157C12.0062 3.80702 12.0062 3.44295 11.7816 3.2184C11.5571 2.99385 11.193 2.99385 10.9685 3.2184L7.50005 6.68682L4.03164 3.2184C3.80708 2.99385 3.44301 2.99385 3.21846 3.2184C2.99391 3.44295 2.99391 3.80702 3.21846 4.03157L6.68688 7.49999L3.21846 10.9684C2.99391 11.193 2.99391 11.557 3.21846 11.7816C3.44301 12.0061 3.80708 12.0061 4.03164 11.7816L7.50005 8.31316L10.9685 11.7816C11.193 12.0061 11.5571 12.0061 11.7816 11.7816C12.0062 11.557 12.0062 11.193 11.7816 10.9684L8.31322 7.49999L11.7816 4.03157Z" fill="currentColor" />
              </svg>
            </button>
          </div>

          {/* Tab bar — pill style */}
          <div className="flex gap-1 mb-5 p-1 bg-zinc-100 rounded-full">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 text-xs font-medium
                  rounded-full transition-all duration-150
                  ${activeTab === tab.key
                    ? 'bg-white text-zinc-900 shadow-sm'
                    : 'text-zinc-500 hover:text-zinc-700'}`}
              >
                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: tab.color }} />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Input */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-zinc-600 mb-2">
              {tabs.find(t => t.key === activeTab)?.label} API Key
            </label>
            <input
              type="password"
              value={apiKeys[activeTab]}
              onChange={(e) => setApiKeys({ ...apiKeys, [activeTab]: e.target.value })}
              placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
              className="w-full px-4 py-3 text-sm border border-zinc-200
                rounded-xl bg-white text-zinc-900 placeholder:text-zinc-400
                focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/10
                outline-none transition-all"
            />
          </div>

          {/* Info */}
          <div className="flex items-start gap-2 p-3 rounded-xl bg-indigo-50">
            <InfoCircleOutlined className="text-indigo-500 text-xs mt-0.5 flex-shrink-0" />
            <p className="text-xs text-indigo-600">
              API Key 仅存储在本地浏览器中，不会上传到服务器。请妥善保管您的密钥。
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between mt-5 pt-4 border-t border-zinc-100">
            <button
              onClick={handleReset}
              className="text-xs text-zinc-400 hover:text-red-500 transition-colors"
            >
              重置
            </button>
            <div className="flex items-center gap-2">
              {saved && (
                <span className="text-xs text-emerald-600 font-medium flex items-center gap-1">
                  <CheckCircleOutlined /> 已保存
                </span>
              )}
              <button
                onClick={handleSave}
                className="px-5 py-2.5 text-sm font-medium
                  bg-zinc-900 text-white rounded-xl
                  hover:bg-zinc-800 transition-all"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}

/* ============================================================
   Token Display
   ============================================================ */
function TokenDisplay({ messages }) {
  const tokenCount = estimateTokens(messages);
  const formatted = tokenCount >= 1000 ? `${(tokenCount / 1000).toFixed(1)}k` : tokenCount;

  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
      text-zinc-500 bg-zinc-100 rounded-full">
      <span className="font-mono text-xs text-zinc-600 tabular-nums">{formatted}</span>
      <span className="text-xs text-zinc-400">tokens</span>
    </div>
  );
}

/* ============================================================
   ChatPage
   ============================================================ */
export default function ChatPage() {
  const { id } = useParams();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState(id || null);
  const [conversations, setConversations] = useState([]);
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [selectedModel, setSelectedModel] = useState('gpt-4o-mini');
  const abortRef = useRef(null);

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

  useEffect(() => { loadConversations(); }, [loadConversations]);

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

  useEffect(() => {
    if (id) { setActiveConversationId(id); loadMessages(id); }
  }, [id, loadMessages]);

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
      { message: content, conversation_id: activeConversationId || undefined, model: selectedModel },
      {
        onThinking(event) { setStatusText(event.content || 'AI 正在思考...'); },
        onIntent(event) { setStatusText(`识别意图: ${event.intent_type || '处理中...'}`); },
        onPlan(event) {
          setStatusText('正在制定执行计划...');
          if (event.steps) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === 'master') last.metadata = { ...last.metadata, plan: event };
              return updated;
            });
          }
        },
        onSources(event) {
          if (event.references) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === 'master') last.metadata = { ...last.metadata, sources: event.references };
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
            if (last.role === 'master') last.content = accumulatedContent;
            return updated;
          });
        },
        onReflection(event) {
          setStatusText(event.passed ? '质量检查通过' : '质量检查发现问题，正在修正...');
        },
        onRetry() { setStatusText('正在重试...'); },
        onDone(event) {
          setStatusText('');
          setIsStreaming(false);
          if (event?.conversation_id && !activeConversationId) setActiveConversationId(event.conversation_id);
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
            if (last.role === 'master' && !last.content) last.content = `抱歉，请求出错了：${errMsg}`;
            return updated;
          });
        },
      }
    );

    abortRef.current = abort;
  }, [isStreaming, activeConversationId, selectedModel, loadConversations]);

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
      if (activeConversationId === convId) { setActiveConversationId(null); setMessages([]); }
    } catch (err) {
      message.error('删除对话失败');
    }
  }, [activeConversationId]);

  const handleCapabilityClick = useCallback((label) => { handleSend(label); }, [handleSend]);

  const handleReview = useCallback(async (action, toolResult, reason) => {
    const toolResultId = toolResult.id || toolResult.tool_result_id;
    setMessages((prev) => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last.role === 'master' && last.metadata?.toolResults) {
        const newToolResults = last.metadata.toolResults.map((tr) => {
          if (tr === toolResult || tr.id === toolResultId) {
            return { ...tr, reviewStatus: action === 'approve' ? 'approved' : 'rejected', rejectReason: reason || undefined };
          }
          return tr;
        });
        last.metadata = { ...last.metadata, toolResults: newToolResults };
      }
      return updated;
    });

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

  const activeConversationTitle = activeConversationId
    ? conversations.find((c) => c.id === activeConversationId)?.title
    : null;

  return (
    <div className="flex h-screen bg-zinc-50">
      <Sidebar
        conversations={conversations}
        activeId={activeConversationId}
        onSelect={handleSelectConversation}
        onNew={handleNewChat}
        onDelete={handleDeleteConversation}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex-1 flex flex-col min-w-0 bg-white">
        {/* Top Navigation Bar — 48px slim */}
        <header className="flex items-center gap-3 px-5 h-12 min-h-[48px] border-b border-zinc-200/80 bg-white">
          {/* Sidebar toggle */}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="flex items-center justify-center w-8 h-8 rounded-lg
              text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-all"
          >
            {sidebarCollapsed ? <MenuUnfoldOutlined className="text-sm" /> : <MenuFoldOutlined className="text-sm" />}
          </button>

          {/* Title */}
          <span className="text-sm font-medium text-zinc-800 tracking-tight">
            {activeConversationTitle || '新对话'}
          </span>

          {isLoadingMessages && (
            <span className="text-[11px] text-zinc-400">加载中...</span>
          )}

          {/* Right side controls — capsule pills */}
          <div className="ml-auto flex items-center gap-2">
            {/* Streaming status pill */}
            {isStreaming && statusText && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                bg-indigo-50 text-indigo-600 rounded-full animate-fade-in">
                <LoadingOutlined className="animate-spin text-xs" />
                <span className="truncate max-w-[280px]">{statusText}</span>
              </div>
            )}

            <TokenDisplay messages={messages} />
            <SettingsDropdown />
            <ModelSelector selectedModel={selectedModel} onSelect={setSelectedModel} disabled={isStreaming} />
          </div>
        </header>

        <ChatArea
          messages={messages}
          isStreaming={isStreaming}
          onCapabilityClick={handleCapabilityClick}
          onReview={handleReview}
        />

        <ChatInput onSend={handleSend} disabled={isStreaming} />

        {/* Hidden API Key Manager — triggered via Settings dropdown */}
        <ApiKeyManager />
      </div>
    </div>
  );
}