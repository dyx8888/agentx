import { memo, useEffect, useRef, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Plus,
  MessageCircle,
  Trash2,
  Settings,
  LogOut,
  ChevronUp,
} from 'lucide-react';
import { cn } from '@/lib/utils';

/* ═══════════════════════════════════════════════════════════════
   Time group helpers — 今天 / 昨天 / 更早
   ═══════════════════════════════════════════════════════════════ */
function getTimeGroup(date) {
  if (!date) return 'older';
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return 'older';
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((today - msgDay) / (24 * 60 * 60 * 1000));
  if (dayDiff <= 0) return 'today';
  if (dayDiff === 1) return 'yesterday';
  return 'older';
}

const GROUPS = [
  { key: 'today', label: '今天' },
  { key: 'yesterday', label: '昨天' },
  { key: 'older', label: '更早' },
];

function groupConversations(conversations) {
  const groups = { today: [], yesterday: [], older: [] };
  for (const conv of conversations || []) {
    const key = getTimeGroup(conv.updated_at || conv.created_at);
    groups[key].push(conv);
  }
  return groups;
}

/* ═══════════════════════════════════════════════════════════════
   UserSection — 自定义 Popover 菜单（v0 DropdownMenu 风格）
   ═══════════════════════════════════════════════════════════════ */
function UserSection({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return undefined;
    const handle = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const esc = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handle);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', handle);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  const username = user?.username || '用户';
  const initial = username.slice(0, 1).toUpperCase();

  const handleSettings = () => {
    setOpen(false);
    navigate('/settings');
  };

  return (
    <div ref={ref} className="relative border-t border-sidebar-border p-3">
      {open && (
        <div
          className="dropdown-content absolute bottom-full left-3 right-3 mb-1"
          role="menu"
        >
          <button
            type="button"
            className="dropdown-item"
            role="menuitem"
            onClick={handleSettings}
          >
            <Settings className="size-4" />
            <span>账户设置</span>
          </button>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            className="dropdown-item dropdown-item-danger"
            onClick={() => {
              if (!window.confirm('确定要退出登录吗？')) return;
              setOpen(false);
              onLogout?.();
            }}
            role="menuitem"
          >
            <LogOut className="size-4" />
            <span>退出登录</span>
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors hover:bg-sidebar-accent/60"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-xs font-medium text-primary-foreground">
          {initial}
        </div>
        <div className="min-w-0 flex-1 overflow-hidden">
          <p className="truncate text-sm font-medium text-sidebar-foreground">
            {username}
          </p>
        </div>
        <ChevronUp className="size-4 text-muted-foreground" />
      </button>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Sidebar — 完全对齐 v0 components/chat/sidebar.tsx
   移动端：fixed + 遮罩；桌面端：sticky 静态
   ═══════════════════════════════════════════════════════════════ */
function Sidebar({
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  loading,
  isOpen,
  onClose,
  user,
  onLogout,
}) {
  // 对话分组只在 conversations 变化时重算，避免每次渲染都重算
  const groups = useMemo(() => groupConversations(conversations), [conversations]);

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={cn(
          'fixed left-0 top-0 z-50 flex h-svh w-[260px] shrink-0 flex-col',
          'border-r border-sidebar-border bg-sidebar',
          'transition-transform duration-300 ease-out',
          'md:relative md:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        )}
        aria-label="对话侧边栏"
      >
        {/* 品牌 + 新建对话 */}
        <div className="flex flex-col gap-3 p-4">
          <div className="flex items-center gap-2 px-1">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <span className="font-heading text-base font-semibold lowercase">x</span>
            </div>
            <span className="font-heading text-lg font-semibold text-sidebar-foreground">
              AgentX
            </span>
          </div>
          <button
            type="button"
            onClick={onNewChat}
            className="btn btn-primary btn-block justify-start"
          >
            <Plus className="size-4" />
            新建对话
          </button>
        </div>

        {/* 对话历史 */}
        <nav
          className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-2"
          aria-label="对话列表"
        >
          {loading ? (
            <div className="px-2 py-3">
              <div className="flex flex-col gap-2">
                <div className="skeleton h-5 rounded-md" style={{ width: '85%' }} />
                <div className="skeleton h-5 rounded-md" style={{ width: '65%' }} />
                <div className="skeleton h-5 rounded-md" style={{ width: '45%' }} />
              </div>
            </div>
          ) : !conversations || conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
              <span className="text-sm text-muted-foreground">还没有对话</span>
              <span className="mt-1 text-xs text-muted-foreground">点击上方新建对话</span>
            </div>
          ) : (
            (() => {
              return GROUPS.map(({ key, label }) => {
                const items = groups[key];
                if (!items || items.length === 0) return null;
                return (
                  <div key={key} className="mb-3">
                    <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                      {label}
                    </p>
                    <ul className="flex flex-col gap-0.5">
                      {items.map((c) => (
                        <li key={c.id}>
                          <button
                            type="button"
                            onClick={() => onSelectConversation(c.id)}
                            className={cn(
                              'group flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors',
                              String(c.id) === String(activeConversationId)
                                ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                                : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60'
                            )}
                          >
                            <MessageCircle className="size-4 shrink-0 opacity-70" />
                            <span className="flex-1 truncate">
                              {c.title || '新对话'}
                            </span>
                            <span
                              role="button"
                              tabIndex={0}
                              aria-label={`删除对话 ${c.title || '新对话'}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (window.confirm('确定要删除该对话吗？此操作不可撤销。')) {
                                  onDeleteConversation(c.id);
                                }
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  e.stopPropagation();
                                if (window.confirm('确定要删除该对话吗？此操作不可撤销。')) {
                                  onDeleteConversation(c.id);
                                }
                                }
                              }}
                              className="invisible shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-all hover:bg-background hover:text-destructive group-hover:visible group-hover:opacity-100 focus-visible:opacity-100 focus-visible:visible"
                            >
                              <Trash2 className="size-3.5" />
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              });
            })()
          )}
        </nav>

        {/* 用户菜单 */}
        <UserSection user={user} onLogout={onLogout} />
      </aside>
    </>
  );
}

export default memo(Sidebar);
