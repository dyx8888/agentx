import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API modules using vi.hoisted
const { mockStreamChat, mockGetConversations, mockGetConversation, mockDeleteConversation, mockApproveToolResult, mockRejectToolResult } = vi.hoisted(() => ({
  mockStreamChat: vi.fn(() => vi.fn()),
  mockGetConversations: vi.fn(),
  mockGetConversation: vi.fn(),
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
  deleteConversation: mockDeleteConversation,
}));

vi.mock('@/api/review', () => ({
  approveToolResult: mockApproveToolResult,
  rejectToolResult: mockRejectToolResult,
}));

// Mock child components to simplify testing
vi.mock('@/components/Sidebar', () => ({
  default: ({ collapsed, conversations, activeId, onNew, onSelect, onDelete }) => (
    <div data-testid="sidebar">
      <span data-testid="sidebar-collapsed">{collapsed ? 'collapsed' : 'open'}</span>
      <span data-testid="conversation-count">{conversations?.length || 0}</span>
      <button data-testid="new-chat-btn" onClick={onNew}>新建对话</button>
      <button data-testid="select-conv-btn" onClick={() => onSelect('conv-1')}>选择对话</button>
      <button data-testid="delete-conv-btn" onClick={() => onDelete('conv-1')}>删除对话</button>
    </div>
  ),
}));

vi.mock('@/components/ChatArea', () => ({
  default: ({ messages, isStreaming, statusText }) => (
    <div data-testid="chat-area">
      <span data-testid="message-count">{messages?.length || 0}</span>
      <span data-testid="streaming">{isStreaming ? 'streaming' : 'idle'}</span>
      {statusText && <span data-testid="status-text">{statusText}</span>}
    </div>
  ),
}));

vi.mock('@/components/ChatInput', () => ({
  default: ({ onSend, disabled }) => (
    <div data-testid="chat-input">
      <button
        data-testid="send-btn"
        disabled={disabled}
        onClick={() => onSend('Hello, AI!')}
      >
        发送
      </button>
    </div>
  ),
}));

// Mock antd message
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      info: vi.fn(),
    },
  };
});

// Import after mocks
import ChatPage from '@/pages/ChatPage';

const renderChatPage = (route = '/chat') => {
  window.history.pushState({}, '', route);
  return render(
    <BrowserRouter>
      <ChatPage />
    </BrowserRouter>
  );
};

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConversations.mockResolvedValue({ items: [] });
    mockGetConversation.mockResolvedValue({ messages: [] });
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

    renderChatPage();

    await waitFor(() => {
      expect(mockGetConversations).toHaveBeenCalled();
    });
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
  });

  it('toggles sidebar collapse', async () => {
    renderChatPage();

    await waitFor(() => {
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    });

    // Sidebar should start open (collapsed = false)
    expect(screen.getByTestId('sidebar-collapsed')).toHaveTextContent('open');
  });
});