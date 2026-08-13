import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API modules using vi.hoisted
const { mockStreamChat, mockGetConversations, mockGetConversation, mockCreateConversation, mockDeleteConversation, mockApproveToolResult, mockRejectToolResult } = vi.hoisted(() => ({
  mockStreamChat: vi.fn(() => vi.fn()),
  mockGetConversations: vi.fn(),
  mockGetConversation: vi.fn(),
  mockCreateConversation: vi.fn(),
  mockDeleteConversation: vi.fn(),
  mockApproveToolResult: vi.fn(),
  mockRejectToolResult: vi.fn(),
}));

vi.mock('@/api/chat', () => ({
  streamChat: mockStreamChat,
}));

vi.mock('@/api/conversations', () => ({
  getConversations: mockGetConversations,
  getConversation: mockGetConversation,
  createConversation: mockCreateConversation,
  deleteConversation: mockDeleteConversation,
}));

vi.mock('@/api/review', () => ({
  approveToolResult: mockApproveToolResult,
  rejectToolResult: mockRejectToolResult,
}));

// Mock useAuth
vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({
    user: { username: 'testuser' },
    logout: vi.fn(),
    loading: false,
    isAuthenticated: true,
  }),
  AuthProvider: ({ children }) => children,
}));

// Mock child components to simplify testing — prop names match actual interfaces
vi.mock('@/components/Sidebar', () => ({
  default: ({ conversations, activeConversationId, onNewChat, onSelectConversation, onDeleteConversation, loading, isOpen, onClose }) => (
    <div data-testid="sidebar">
      <span data-testid="sidebar-open">{isOpen ? 'open' : 'closed'}</span>
      <span data-testid="conversation-count">{conversations?.length || 0}</span>
      <span data-testid="loading">{loading ? 'loading' : 'loaded'}</span>
      <button data-testid="new-chat-btn" onClick={onNewChat}>新建对话</button>
      <button data-testid="select-conv-btn" onClick={() => onSelectConversation('conv-1')}>选择对话</button>
      <button data-testid="delete-conv-btn" onClick={() => onDeleteConversation('conv-1')}>删除对话</button>
    </div>
  ),
}));

vi.mock('@/components/ChatArea', () => ({
  default: ({ messages, isStreaming, conversationTitle }) => {
    const lastMessage = messages?.[messages.length - 1] || {};
    return (
      <div data-testid="chat-area">
        <span data-testid="message-count">{messages?.length || 0}</span>
        <span data-testid="streaming">{isStreaming ? 'streaming' : 'idle'}</span>
        <span data-testid="title">{conversationTitle}</span>
        <span data-testid="last-content">{lastMessage.content || ''}</span>
        <span data-testid="warning-count">{lastMessage.warnings?.length || 0}</span>
        <span data-testid="warning-text">{lastMessage.warnings?.[0]?.message || ''}</span>
      </div>
    );
  },
}));

vi.mock('@/components/ChatInput', () => ({
  default: ({ onSend, isStreaming, onStop }) => (
    <div data-testid="chat-input">
      <span data-testid="streaming-input">{isStreaming ? 'streaming' : 'idle'}</span>
      <button
        data-testid="send-btn"
        onClick={() => onSend('Hello, AI!')}
      >
        发送
      </button>
      {isStreaming && <button data-testid="stop-btn" onClick={onStop}>停止</button>}
    </div>
  ),
}));

// Mock TopBar (extracted from ChatInput) — receives model + apiKey + files toggle
vi.mock('@/components/TopBar', () => ({
  default: ({ model, apiKey, filesOpen, onToggleFiles }) => (
    <div data-testid="top-bar">
      <span data-testid="model">{model}</span>
      <span data-testid="api-key">{apiKey}</span>
      <span data-testid="files-open">{filesOpen ? 'open' : 'closed'}</span>
      <button data-testid="toggle-files" onClick={onToggleFiles}>文件</button>
    </div>
  ),
}));

// Mock FilePanel (collapsible file browser)
vi.mock('@/components/FilePanel', () => ({
  default: ({ onClose }) => (
    <div data-testid="file-panel">
      <button data-testid="close-files" onClick={onClose}>关闭</button>
    </div>
  ),
}));

// Import after mocks
import ChatPage from '@/pages/ChatPage';

const renderChatPage = (route = '/') => {
  window.history.pushState({}, '', route);
  return render(
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ChatPage />
    </BrowserRouter>
  );
};

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConversations.mockResolvedValue({ items: [] });
    mockGetConversation.mockResolvedValue({ messages: [] });
    mockCreateConversation.mockResolvedValue({ id: 'new-conv', title: 'Test' });
    mockDeleteConversation.mockResolvedValue({});
    mockStreamChat.mockReturnValue(vi.fn());
  });

  it('renders sidebar and chat area', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    });

    expect(screen.getByTestId('chat-area')).toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
  });

  it('loads conversations on mount', async () => {
    mockGetConversations.mockResolvedValue({
      items: [
        { id: '1', title: 'Conversation 1', updated_at: new Date().toISOString() },
        { id: '2', title: 'Conversation 2', updated_at: new Date().toISOString() },
      ],
    });

    renderChatPage();

    await waitFor(() => {
      expect(mockGetConversations).toHaveBeenCalled();
    });
  });

  it('handles conversations load failure', async () => {
    mockGetConversations.mockRejectedValue(new Error('Network error'));
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    try {
      renderChatPage();

      await waitFor(() => {
        expect(mockGetConversations).toHaveBeenCalled();
      });
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        '加载对话列表失败:',
        expect.any(Error)
      );
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('handles new chat', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('new-chat-btn'));

    // Should clear messages
    expect(screen.getByTestId('message-count')).toHaveTextContent('0');
  });

  it('handles conversation selection', async () => {
    mockGetConversation.mockResolvedValue({
      messages: [
        { id: 'm1', role: 'user', content: 'Hello' },
        { id: 'm2', role: 'assistant', content: 'Hi there!' },
      ],
    });

    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('select-conv-btn'));

    await waitFor(() => {
      expect(mockGetConversation).toHaveBeenCalledWith('conv-1');
    });
  });

  it('handles conversation deletion', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('delete-conv-btn'));

    await waitFor(() => {
      expect(mockDeleteConversation).toHaveBeenCalledWith('conv-1');
    });
  });

  it('sends a message via streamChat', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(mockStreamChat).toHaveBeenCalled();
    });
    expect(mockStreamChat.mock.calls[0][0]).not.toHaveProperty('company_id');
  });

  it('stores visible warning events from streamChat on the assistant message', async () => {
    mockStreamChat.mockImplementation((_params, callbacks) => {
      callbacks.onWarning?.({
        type: 'warning',
        code: 'model_fallback',
        message: 'Primary model failed; switched to backup model.',
        from_model: 'primary',
        to_model: 'backup',
      });
      return vi.fn();
    });

    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('warning-count')).toHaveTextContent('1');
    });
    expect(screen.getByTestId('warning-text')).toHaveTextContent(
      'Primary model failed; switched to backup model.'
    );
  });

  it('shows readable SSE error content instead of unknown error', async () => {
    mockStreamChat.mockImplementation((_params, callbacks) => {
      callbacks.onError?.({
        type: 'error',
        content: 'MasterAgentRouter 未初始化',
      });
      return vi.fn();
    });

    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('streaming')).toHaveTextContent('idle');
    });
    expect(screen.getByTestId('last-content')).toHaveTextContent(
      '抱歉，处理时出错了：MasterAgentRouter 未初始化'
    );
  });

  it('shows actionable model API key configuration errors', async () => {
    mockStreamChat.mockImplementation((_params, callbacks) => {
      callbacks.onError?.({
        type: 'error',
        code: 'model_api_key_missing',
        message: '模型 deepseek 缺少 API Key。请配置 DEEPSEEK_API_KEY 环境变量。',
        requires_config: true,
        config_target: 'llm_api_key',
      });
      return vi.fn();
    });

    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('streaming')).toHaveTextContent('idle');
    });
    expect(screen.getByTestId('last-content')).toHaveTextContent(
      '抱歉，处理时出错了：模型 deepseek 缺少 API Key。请配置 DEEPSEEK_API_KEY 环境变量。'
    );
  });

  it('creates conversation when sending first message', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('send-btn'));

    await waitFor(() => {
      expect(mockCreateConversation).toHaveBeenCalled();
    });
  });

  it('starts with sidebar closed on mobile', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    });

    // Sidebar should start closed (mobile default)
    expect(screen.getByTestId('sidebar-open')).toHaveTextContent('closed');
  });

  it('passes selected model to top bar', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('top-bar')).toBeInTheDocument();
    });

    expect(screen.getByTestId('model')).toHaveTextContent('glm-5.2');
  });

  it('toggles file panel on demand', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('top-bar')).toBeInTheDocument();
    });

    // Initially closed
    expect(screen.queryByTestId('file-panel')).not.toBeInTheDocument();

    // Open
    fireEvent.click(screen.getByTestId('toggle-files'));
    expect(screen.getByTestId('file-panel')).toBeInTheDocument();

    // Close
    fireEvent.click(screen.getByTestId('close-files'));
    expect(screen.queryByTestId('file-panel')).not.toBeInTheDocument();
  });
});
