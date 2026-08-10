import { useEffect, useMemo, useRef, useState } from 'react';
import {
  X,
  Download,
  Copy,
  Check,
  File,
  Sparkles,
  Eye,
  Clock,
  HardDrive,
  Tag,
  Loader2,
  RotateCw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { FILE_ICON_MAP } from '@/lib/fileIcons';

/* ═══════════════════════════════════════════════════════════════
   PreviewBody — 按文件类型分发预览（纯前端，不依赖预览后端 API）
   - 图片（jpg/png/gif/webp/svg）：<img>
   - 文本（txt/md/json/csv/log）  ：fetch 后 <pre> 渲染
   - PDF                          ：<iframe>
   - 其他类型                     ：占位 + 文件名/大小
   文件 URL 取自 file.url（由调用方在 file 对象上携带）。
   ═══════════════════════════════════════════════════════════════ */
const IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'];
const TEXT_EXTS = ['txt', 'md', 'markdown', 'json', 'csv', 'log'];
const PDF_EXTS = ['pdf'];

function getExt(name) {
  const n = String(name || '');
  const i = n.lastIndexOf('.');
  return i < 0 ? '' : n.slice(i + 1).toLowerCase();
}

function getPreviewKind(file) {
  const ext = getExt(file?.name);
  if (IMAGE_EXTS.includes(ext) || file?.type === 'image') return 'image';
  if (PDF_EXTS.includes(ext) || file?.type === 'pdf') return 'pdf';
  if (TEXT_EXTS.includes(ext) || file?.type === 'text') return 'text';
  return 'unsupported';
}

/* 不支持预览的文件：占位 + 文件名/大小 */
function UnsupportedView({ file }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card/50 p-10 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-secondary">
        <Eye className="size-6 text-muted-foreground" />
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">预览暂不可用</p>
        <p className="mt-1 text-xs text-muted-foreground">
          该文件暂不支持在线预览，请下载后查看
        </p>
      </div>
      {(file?.name || file?.size) && (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
          {file?.name && (
            <span className="inline-flex items-center gap-1">
              <File className="size-3" />
              {file.name}
            </span>
          )}
          {file?.size && (
            <span className="inline-flex items-center gap-1">
              <HardDrive className="size-3" />
              {file.size}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function LoadingView() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <Loader2 className="size-8 animate-spin text-primary" />
      <p className="text-sm text-muted-foreground">加载中...</p>
    </div>
  );
}

function ErrorView({ onRetry }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card/50 p-10 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-macaron-pink">
        <Eye className="size-6 text-foreground/80" />
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">文件加载失败</p>
        <p className="mt-1 text-xs text-muted-foreground">
          无法读取文件内容，请检查网络后重试
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="btn btn-outline h-8 px-3 text-xs"
        aria-label="重新加载文件"
      >
        <RotateCw className="size-3.5" />
        重试
      </button>
    </div>
  );
}

function PreviewBody({ file }) {
  const kind = getPreviewKind(file);
  const url = file?.url;
  // 预览状态：idle / loading / done / error / nourl（文本与图片使用）
  const [status, setStatus] = useState('idle');
  const [content, setContent] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  // 文本类型：fetch 内容后渲染
  useEffect(() => {
    if (kind !== 'text') return undefined;
    if (!url) {
      setStatus('nourl');
      return undefined;
    }
    let cancelled = false;
    setStatus('loading');
    setContent('');
    fetch(url, { credentials: 'include' })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((text) => {
        if (cancelled) return;
        // 超大文本截断，避免渲染卡顿
        const trimmed =
          text.length > 200000
            ? text.slice(0, 200000) + '\n…（内容过长已截断）'
            : text;
        setContent(trimmed);
        setStatus('done');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [kind, url, reloadKey]);

  // 图片：浏览器原生加载
  if (kind === 'image') {
    if (!url) return <UnsupportedView file={file} />;
    if (status === 'error') {
      return (
        <ErrorView
          onRetry={() => {
            setStatus('idle');
            setReloadKey((k) => k + 1);
          }}
        />
      );
    }
    return (
      <div className="flex items-center justify-center">
        <img
          key={reloadKey}
          src={url}
          alt={file?.name || '图片预览'}
          className="max-h-[60vh] max-w-full rounded-lg object-contain"
          onError={() => setStatus('error')}
        />
      </div>
    );
  }

  // PDF：iframe 内嵌
  if (kind === 'pdf') {
    if (!url) return <UnsupportedView file={file} />;
    return (
      <iframe
        src={url}
        title={file?.name || 'PDF 预览'}
        className="h-[60vh] w-full rounded-lg border border-border bg-background"
      />
    );
  }

  // 文本：fetch 后 <pre> 渲染
  if (kind === 'text') {
    if (!url) return <UnsupportedView file={file} />;
    if (status === 'loading') return <LoadingView />;
    if (status === 'error') {
      return <ErrorView onRetry={() => setReloadKey((k) => k + 1)} />;
    }
    if (status === 'done') {
      return (
        <pre className="scrollbar-thin max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-background p-4 font-mono text-xs leading-relaxed text-foreground">
          {content}
        </pre>
      );
    }
    return null;
  }

  return <UnsupportedView file={file} />;
}

/* ═══════════════════════════════════════════════════════════════
   主组件 — FilePreviewModal
   支持上传文件（FilePanel）和 Agent 生成文件（MessageBubble）
   ═══════════════════════════════════════════════════════════════ */
export default function FilePreviewModal({ file, onClose, onDownload }) {
  const [copied, setCopied] = useState(false);
  const dialogRef = useRef(null);
  const closeBtnRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // 焦点陷阱 + ESC 关闭 + 关闭后焦点返回触发元素
  useEffect(() => {
    if (!file) return undefined;

    const dialog = dialogRef.current;
    // 记录触发元素，关闭时归还焦点
    const trigger = document.activeElement;

    const getFocusables = () => {
      if (!dialog) return [];
      return Array.from(
        dialog.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
    };

    // 打开时聚焦关闭按钮（最常用操作）
    const raf = requestAnimationFrame(() => {
      if (closeBtnRef.current) {
        closeBtnRef.current.focus();
      } else {
        const focusables = getFocusables();
        if (focusables.length > 0) {
          focusables[0].focus();
        } else {
          dialog?.focus();
        }
      }
    });

    const handleKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current?.();
        return;
      }
      if (e.key === 'Tab' && dialog) {
        const focusables = getFocusables();
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (e.shiftKey) {
          // Shift+Tab 在首个可聚焦元素时循环到最后
          if (active === first || !dialog.contains(active)) {
            e.preventDefault();
            last.focus();
          }
        } else {
          // Tab 在最后一个可聚焦元素时循环到首个
          if (active === last || !dialog.contains(active)) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    document.addEventListener('keydown', handleKey);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener('keydown', handleKey);
      // 关闭时焦点返回触发按钮
      if (trigger && typeof trigger.focus === 'function') {
        trigger.focus();
      }
    };
  }, [file]);

  // 打开时锁定 body 滚动
  useEffect(() => {
    if (!file) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [file]);

  const meta = useMemo(() => {
    if (!file) return null;
    const isAgent = file.source === 'agent';
    const { Icon, tint } = FILE_ICON_MAP[file.type] || {
      Icon: File,
      tint: 'bg-secondary',
    };
    return { isAgent, Icon, tint };
  }, [file]);

  if (!file || !meta) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(file.name);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  };

  const handleDownload = () => {
    if (onDownload) {
      onDownload(file);
      return;
    }
    // Fallback：用文件 URL 触发浏览器原生下载
    const url = file?.url || file?.download_url;
    if (!url) {
      console.warn('文件缺少可下载的 URL:', file);
      return;
    }
    const a = document.createElement('a');
    a.href = url;
    a.download = file?.name || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="文件预览"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="flex h-[min(90vh,720px)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-2xl animate-fade-in-up"
        style={{ boxShadow: '0 24px 60px rgba(28, 27, 24, 0.18)' }}
      >
        {/* 顶栏 */}
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <div
              className={cn(
                'flex size-10 shrink-0 items-center justify-center rounded-xl',
                meta.tint
              )}
            >
              <meta.Icon className="size-5 text-foreground/80" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-sm font-semibold text-foreground">
                  {file.name}
                </h2>
                {meta.isAgent && (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-macaron-pink px-2 py-0.5 text-[10px] font-medium text-foreground/80">
                    <Sparkles className="size-2.5" />
                    Agent 生成
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                {file.size && (
                  <span className="inline-flex items-center gap-1">
                    <HardDrive className="size-3" />
                    {file.size}
                  </span>
                )}
                {file.uploadedAt && (
                  <span className="inline-flex items-center gap-1">
                    <Clock className="size-3" />
                    {file.uploadedAt}
                  </span>
                )}
                {file.tag && (
                  <span className="inline-flex items-center gap-1">
                    <Tag className="size-3" />
                    {file.tag}
                  </span>
                )}
              </div>
            </div>
          </div>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </header>

        {/* 主体预览区 — role=document 让屏幕阅读器以文档方式朗读 */}
        <div
          role="document"
          aria-label="文件预览"
          className="scrollbar-thin flex-1 overflow-y-auto bg-muted/30 p-5"
        >
          <PreviewBody file={file} />
        </div>

        {/* 底栏操作 */}
        <footer className="flex items-center justify-between gap-2 border-t border-border bg-background/80 px-5 py-3 backdrop-blur">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleCopy}
              className="btn btn-ghost h-8 px-3 text-xs"
              aria-label="复制文件名"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? '已复制' : '复制名称'}
            </button>
          </div>
          <button
            type="button"
            onClick={handleDownload}
            className="btn btn-primary h-9 px-4 text-xs"
          >
            <Download className="size-3.5" />
            下载文件
          </button>
        </footer>
      </div>
    </div>
  );
}

