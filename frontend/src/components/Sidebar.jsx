import { useState } from 'react';
import { MessageOutlined, PlusOutlined, DeleteOutlined, LogoutOutlined, SettingOutlined } from '@ant-design/icons';
import { Modal, Tooltip } from 'antd';
import { useAuth } from '@/lib/AuthContext';

export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, collapsed, onToggle }) {
  const { user, logout } = useAuth();
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDeleteClick = (e, conv) => {
    e.stopPropagation();
    setDeleteTarget(conv);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await onDelete(deleteTarget.id);
    } finally {
      setIsDeleting(false);
      setDeleteTarget(null);
    }
  };

  const handleDeleteCancel = () => {
    setDeleteTarget(null);
  };

  return (
    <>
      {/* Mobile overlay */}
      {!collapsed && (
        <div
          className="fixed inset-0 bg-black/20 z-40 lg:hidden"
          onClick={onToggle}
        />
      )}

      <aside
        data-testid="sidebar"
        className={`fixed lg:relative z-50 h-full w-[260px] min-w-[260px] flex flex-col
          border-r border-[var(--color-hairline)] bg-[var(--color-canvas-soft)]
          transition-transform duration-200 ease-out
          ${collapsed ? '-translate-x-full lg:-translate-x-full lg:hidden' : 'translate-x-0'}`}
      >
        {/* Hidden test id for collapsed state */}
        <span data-testid="sidebar-collapsed" className="hidden">{collapsed ? 'collapsed' : 'open'}</span>

        {/* Header */}
        <div className="flex items-center justify-between px-3 py-3 border-b border-[var(--color-hairline)]">
          <div className="flex items-center gap-2">
            <div
              className="w-7 h-7 rounded-md flex items-center justify-center text-white text-xs font-bold"
              style={{ background: 'linear-gradient(135deg, #007cf0, #00dfd8)' }}
            >
              A
            </div>
            <span className="font-semibold text-sm text-[var(--color-ink)]">AgentX</span>
          </div>
        </div>

        {/* New Chat Button */}
        <div className="p-2">
          <button
            onClick={onNew}
            data-testid="new-chat-btn"
            className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium
              text-[var(--color-ink)] bg-white border border-[var(--color-hairline)]
              rounded-lg hover:bg-[var(--color-canvas-soft-2)] transition-colors"
          >
            <PlusOutlined className="text-xs" />
            新建对话
          </button>
        </div>

        {/* Conversation List */}
        <div className="flex-1 overflow-y-auto px-2">
          {conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[var(--color-mute)] text-sm gap-2">
              <MessageOutlined className="text-2xl opacity-30" />
              <span>暂无对话记录</span>
            </div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => onSelect(conv.id)}
                className={`group flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer
                  mb-0.5 transition-colors
                  ${activeId === conv.id
                    ? 'bg-[var(--color-canvas-soft-2)]'
                    : 'hover:bg-[var(--color-canvas-soft-2)]'
                  }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-[var(--color-ink)] truncate">
                    {conv.title || '新对话'}
                  </div>
                  <div className="text-xs text-[var(--color-mute)] mt-0.5">
                    {conv.formattedTime || conv.updated_at || conv.created_at || ''}
                  </div>
                </div>
                <Tooltip title="删除对话">
                  <button
                    onClick={(e) => handleDeleteClick(e, conv)}
                    data-testid="delete-conv-btn"
                    className="opacity-0 group-hover:opacity-100 p-1 text-[var(--color-mute)]
                      hover:text-[var(--color-error)] transition-all"
                  >
                    <DeleteOutlined className="text-xs" />
                  </button>
                </Tooltip>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-[var(--color-hairline)] p-2">
          <div className="flex items-center justify-between px-3 py-2">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-[var(--color-ink)] text-white flex items-center justify-center text-xs font-semibold">
                {user?.username?.charAt(0)?.toUpperCase() || 'U'}
              </div>
              <span className="text-sm text-[var(--color-ink)] truncate">
                {user?.username || '用户'}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <Tooltip title="设置">
                <button className="p-1.5 text-[var(--color-mute)] hover:text-[var(--color-ink)] transition-colors rounded-md hover:bg-[var(--color-canvas-soft-2)]">
                  <SettingOutlined className="text-xs" />
                </button>
              </Tooltip>
              <Tooltip title="退出登录">
                <button
                  onClick={logout}
                  className="p-1.5 text-[var(--color-mute)] hover:text-[var(--color-error)] transition-colors rounded-md hover:bg-[var(--color-canvas-soft-2)]"
                >
                  <LogoutOutlined className="text-xs" />
                </button>
              </Tooltip>
            </div>
          </div>
        </div>
      </aside>

      {/* Delete Confirmation Modal */}
      <Modal
        title="删除对话"
        open={!!deleteTarget}
        onOk={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
        confirmLoading={isDeleting}
        okText="确认删除"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        centered
        width={400}
      >
        <p className="text-sm text-[var(--color-body)]">
          确定要删除对话「{deleteTarget?.title || '新对话'}」吗？删除后不可恢复。
        </p>
      </Modal>
    </>
  );
}