import { useState } from 'react';
import { MessageOutlined, PlusOutlined, DeleteOutlined, LogoutOutlined, SettingOutlined, RocketOutlined, InboxOutlined } from '@ant-design/icons';
import { Modal, Tooltip } from 'antd';
import { useAuth } from '@/lib/AuthContext';

export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, collapsed, onToggle }) {
  const { user, logout } = useAuth();
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDeleteClick = (e, conv) => { e.stopPropagation(); setDeleteTarget(conv); };
  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try { await onDelete(deleteTarget.id); } finally { setIsDeleting(false); setDeleteTarget(null); }
  };
  const handleDeleteCancel = () => { setDeleteTarget(null); };

  return (
    <>
      {/* Mobile overlay */}
      {!collapsed && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40 lg:hidden" onClick={onToggle} />
      )}

      <aside
        data-testid="sidebar"
        className={`fixed lg:relative z-50 h-full w-[260px] min-w-[260px] flex flex-col
          border-r border-gray-200 bg-gray-50
          transition-transform duration-300 ease-out
          ${collapsed ? '-translate-x-full lg:-translate-x-full lg:hidden' : 'translate-x-0'}`}
      >
        <span data-testid="sidebar-collapsed" className="hidden">{collapsed ? 'collapsed' : 'open'}</span>

        {/* Brand Header — bigger, more space */}
        <div className="px-5 pt-5 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm"
              style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
              <RocketOutlined className="text-base text-white" />
            </div>
            <span className="text-lg font-bold text-gray-900 tracking-tight">AgentX</span>
          </div>
        </div>

        {/* New Chat Button — outline, h-10, mx-4 */}
        <div className="mx-4">
          <button
            onClick={onNew}
            data-testid="new-chat-btn"
            className="w-full h-10 flex items-center justify-center gap-2
              text-sm font-medium
              border border-gray-200 bg-white text-gray-700
              rounded-lg
              hover:bg-gray-50 hover:border-gray-300
              transition-all duration-150"
          >
            <PlusOutlined />
            新建对话
          </button>
        </div>

        {/* Divider */}
        <div className="px-4 py-3">
          <div className="h-px bg-gray-200" />
        </div>

        {/* Conversation List */}
        <div className="flex-1 overflow-y-auto px-3">
          {conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <InboxOutlined className="text-xl text-gray-300 mb-3" />
              <span className="text-xs text-gray-400">暂无对话记录</span>
            </div>
          ) : (
            <div className="space-y-0.5">
              {conversations.map((conv) => {
                const isActive = activeId === conv.id;
                return (
                  <div
                    key={conv.id}
                    onClick={() => onSelect(conv.id)}
                    className={`group relative flex items-center justify-between px-3 py-2.5
                      rounded-lg cursor-pointer transition-colors duration-150
                      ${isActive ? 'bg-gray-200/60' : 'hover:bg-gray-200/40'}`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <MessageOutlined className={`text-sm flex-shrink-0 ${isActive ? 'text-gray-700' : 'text-gray-400'}`} />
                      <div className="flex-1 min-w-0">
                        <div className={`text-sm truncate ${isActive ? 'font-medium text-gray-900' : 'text-gray-600'}`}>
                          {conv.title || '新对话'}
                        </div>
                      </div>
                    </div>
                    <Tooltip title="删除对话">
                      <button
                        onClick={(e) => handleDeleteClick(e, conv)}
                        data-testid="delete-conv-btn"
                        className="opacity-0 group-hover:opacity-100 p-1
                          text-gray-400 hover:text-red-500 hover:bg-red-50
                          rounded-md transition-all"
                      >
                        <DeleteOutlined className="text-sm" />
                      </button>
                    </Tooltip>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer - User Area — larger, more space */}
        <div className="border-t border-gray-200 py-4 px-4 bg-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0
                text-sm font-semibold text-gray-600">
                {user?.username?.charAt(0)?.toUpperCase() || 'U'}
              </div>
              <div className="flex flex-col min-w-0">
                <span className="text-sm font-medium text-gray-800 truncate">
                  {user?.username || 'demo'}
                </span>
                <span className="inline-flex items-center w-fit mt-0.5 px-1.5 py-0.5
                  text-[10px] font-medium rounded-md
                  bg-gray-100 text-gray-500">
                  演示模式
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Tooltip title="设置">
                <button className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-all">
                  <SettingOutlined className="text-base" />
                </button>
              </Tooltip>
              <Tooltip title="退出登录">
                <button
                  onClick={logout}
                  className="p-2 text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all"
                >
                  <LogoutOutlined className="text-base" />
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
        <p className="text-sm text-gray-600">
          确定要删除对话「{deleteTarget?.title || '新对话'}」吗？删除后不可恢复。
        </p>
      </Modal>
    </>
  );
}