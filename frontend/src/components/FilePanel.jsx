import { useEffect, useState } from 'react';
import {
  File,
  X,
  Sparkles,
  Loader2,
  FolderOpen,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { FILE_ICON_MAP } from '@/lib/fileIcons';
import { getConversationFiles } from '@/api/conversations';

/* 后端 snake_case → 前端 camelCase（FilePreviewModal 读取 file.uploadedAt） */
function normalizeFile(f) {
  return { ...f, uploadedAt: f.uploadedAt ?? f.uploaded_at };
}

/* ═══════════════════════════════════════════════════════════════
   FilePanel — 对话关联文件浏览器
   数据来源：GET /api/conversations/{id}/files
   分类：我上传的 (uploaded) / Agent 生成 (agent)
   点击文件项 → 触发 onPreview(file)
   ═══════════════════════════════════════════════════════════════ */
export default function FilePanel({ onClose, onPreview, conversationId }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!conversationId) {
      setFiles([]);
      setError('');
      setLoading(false);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);
    setError('');

    getConversationFiles(conversationId)
      .then((data) => {
        if (cancelled) return;
        const items = Array.isArray(data?.items) ? data.items : [];
        setFiles(items.map(normalizeFile));
      })
      .catch(() => {
        if (cancelled) return;
        setError('文件加载失败');
        setFiles([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  const uploaded = files.filter((f) => f.source === 'uploaded');
  const agent = files.filter((f) => f.source === 'agent');
  const isEmpty = !loading && !error && files.length === 0;

  return (
    <aside className="flex h-svh w-72 shrink-0 flex-col border-l border-border bg-sidebar">
      {/* 顶栏 */}
      <div className="flex h-14 items-center justify-between border-b border-border px-4">
        <h3 className="text-sm font-medium text-foreground">文件</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭面板"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      {/* 文件列表 */}
      <div className="scrollbar-thin flex-1 overflow-y-auto px-3 pb-4">
        {/* 加载态 */}
        {loading && (
          <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
            <p className="text-xs">加载文件中…</p>
          </div>
        )}

        {/* 错误态 */}
        {!loading && error && (
          <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
            <p className="text-sm text-foreground">{error}</p>
            <p className="text-xs">请稍后重试</p>
          </div>
        )}

        {/* 空态 */}
        {isEmpty && (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <div className="flex size-12 items-center justify-center rounded-2xl bg-secondary">
              <FolderOpen className="size-5 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium text-foreground">暂无文件</p>
            <p className="px-6 text-xs text-muted-foreground">
              对话中引用或生成的文件会显示在这里
            </p>
          </div>
        )}

        {/* 我上传的 */}
        {!loading && !error && uploaded.length > 0 && (
          <div className="mb-4">
            <p className="px-1 pb-2 text-xs font-medium text-muted-foreground">
              我上传的 · {uploaded.length}
            </p>
            <ul className="flex flex-col gap-1">
              {uploaded.map((f) => (
                <FileItem key={f.id} file={f} onClick={() => onPreview?.(f)} />
              ))}
            </ul>
          </div>
        )}

        {/* Agent 生成 */}
        {!loading && !error && agent.length > 0 && (
          <div>
            <p className="flex items-center gap-1 px-1 pb-2 text-xs font-medium text-muted-foreground">
              <Sparkles className="size-3 text-primary" />
              Agent 生成 · {agent.length}
            </p>
            <ul className="flex flex-col gap-1">
              {agent.map((f) => (
                <FileItem key={f.id} file={f} onClick={() => onPreview?.(f)} />
              ))}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}

/* ═══════════════════════════════════════════════════════════════
   FileItem — 单个文件项
   ═══════════════════════════════════════════════════════════════ */
function FileItem({ file, onClick }) {
  const { Icon, tint } = FILE_ICON_MAP[file.type] || { Icon: File, tint: 'bg-secondary' };
  const isAgent = file.source === 'agent';

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="group flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-sidebar-accent/60"
      >
        <div
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-lg',
            tint
          )}
        >
          <Icon className="size-4 text-foreground/80" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-foreground">{file.name}</p>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            {isAgent && (
              <span className="inline-flex items-center gap-0.5 text-primary">
                <Sparkles className="size-2.5" />
              </span>
            )}
            {file.size || file.tag || ''}
          </p>
        </div>
      </button>
    </li>
  );
}
