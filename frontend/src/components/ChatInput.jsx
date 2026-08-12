import { useEffect, useRef, useState } from 'react';
import { Paperclip, ArrowUp, Square, File, X } from 'lucide-react';
import { cn, formatFileSize } from '@/lib/utils';
import { getToolCapabilities } from '@/api/tools';

/* ═══════════════════════════════════════════════════════════════
   常量
   ═══════════════════════════════════════════════════════════════ */
const MAX_FILE_SIZE = 10 * 1024 * 1024;

/* T4.12: 后端不可用时的降级默认快捷指令 */
const FALLBACK_COMMANDS = [
  { key: 'search', label: '/达人搜索' },
  { key: 'analysis', label: '/数据分析' },
  { key: 'content', label: '/内容创作' },
  { key: 'logistics', label: '/物流查询' },
];

/* ═══════════════════════════════════════════════════════════════
   ChatInput — 完全对齐 v0 components/chat/composer.tsx
   快捷指令标签 + 输入卡片（附件 + textarea + 发送/停止）
   ═══════════════════════════════════════════════════════════════ */
export default function ChatInput({
  onSend,
  isStreaming = false,
  onStop,
}) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState([]);
  const [fileError, setFileError] = useState('');
  const [quickCommands, setQuickCommands] = useState(FALLBACK_COMMANDS);

  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  // T4.12: 从后端动态获取快捷指令
  useEffect(() => {
    let cancelled = false;
    getToolCapabilities()
      .then((caps) => {
        if (!cancelled && Array.isArray(caps) && caps.length > 0) {
          setQuickCommands(caps);
        }
      })
      .catch(() => {
        // 降级使用 FALLBACK_COMMANDS，无需处理
      });
    return () => { cancelled = true; };
  }, []);

  // 自动增高（v0: max 200px）
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed && files.length === 0) return;
    if (isStreaming) return;
    onSend?.(trimmed, files);
    setText('');
    setFiles([]);
    setFileError('');
    requestAnimationFrame(() => {
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
    });
  };

  const handleStop = () => onStop?.();

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileButtonClick = () => fileInputRef.current?.click();

  const handleFileChange = (e) => {
    const selected = Array.from(e.target.files || []);
    setFileError('');
    const valid = [];
    for (const f of selected) {
      if (f.size > MAX_FILE_SIZE) {
        setFileError(`文件「${f.name}」超过 10MB 限制`);
        continue;
      }
      valid.push(f);
    }
    if (valid.length > 0) setFiles((prev) => [...prev, ...valid]);
    e.target.value = '';
  };

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const handleQuickCommand = (label) => {
    setText((prev) => `${prev}${label} `);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const canSend = text.trim().length > 0 || files.length > 0;

  // T4.12: 最多显示 4 个 + "… 更多"
  const visibleCommands = quickCommands.slice(0, 4);
  const hasMore = quickCommands.length > 4;

  return (
    <div className="w-full shrink-0 px-4 pb-4 pt-2">
      <div className="mx-auto w-full max-w-2xl">
        {/* 快捷指令小标签 */}
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {visibleCommands.map((cmd) => (
            <button
              key={cmd.key}
              type="button"
              onClick={() => handleQuickCommand(cmd.label)}
              className="rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
            >
              {cmd.label}
            </button>
          ))}
          {hasMore && (
            <span className="px-1 text-xs text-muted-foreground">… 更多</span>
          )}
        </div>

        {/* 输入卡片 */}
        <div className="rounded-2xl border border-border bg-card p-2 shadow-sm transition-shadow focus-within:shadow-md">
          {/* 文件附件区 */}
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 px-1 pb-2">
              {files.map((f, idx) => (
                <div
                  key={`${f.name}-${idx}`}
                  className="flex items-center gap-1.5 rounded-md bg-secondary px-2 py-1.5"
                >
                  <span className="inline-flex text-muted-foreground">
                    <File className="size-3.5" />
                  </span>
                  <span className="max-w-[160px] truncate text-xs text-foreground">
                    {f.name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatFileSize(f.size)}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFile(idx)}
                    aria-label="移除文件"
                    className="ml-1 inline-flex size-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 主输入行：附件 + textarea + 发送/停止 */}
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={handleFileButtonClick}
              disabled={isStreaming}
              aria-label="添加附件"
              title="添加附件"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-40"
            >
              <Paperclip className="size-5" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.md,image/*"
              onChange={handleFileChange}
              className="hidden"
              aria-hidden="true"
            />

            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="输入你想做什么…"
              aria-label="消息输入框"
              className={cn(
                'scrollbar-thin max-h-[200px] flex-1 resize-none bg-transparent py-2',
                'text-sm leading-relaxed text-foreground outline-none',
                'placeholder:text-muted-foreground'
              )}
            />

            {isStreaming ? (
              <button
                type="button"
                onClick={handleStop}
                aria-label="停止生成"
                className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-transform duration-150 hover:scale-105"
              >
                <Square className="size-4 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={!canSend}
                aria-label="发送"
                className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-transform duration-150 hover:scale-105 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:scale-100"
              >
                <ArrowUp className="size-5" />
              </button>
            )}
          </div>

          {fileError && (
            <div className="px-1 pb-1 text-xs text-destructive">
              {fileError}
            </div>
          )}
        </div>

        {/* 底部提示 */}
        <p className="mt-2 text-center text-xs text-muted-foreground">
          AgentX 可能会出错，请核对重要信息
        </p>
      </div>
    </div>
  );
}
