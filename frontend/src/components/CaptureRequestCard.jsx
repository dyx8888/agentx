import { useState } from 'react';
import { ExternalLink, FileText, Loader2, RefreshCw, Search, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';

const PURPOSES = [
  { value: 'generic_evidence', label: '通用证据' },
  { value: 'competitor_evidence', label: '竞品证据' },
  { value: 'content_reference', label: '内容参考' },
  { value: 'creator', label: '达人候选' },
  { value: 'knowledge', label: '知识候选' },
];

const STATUS_LABELS = {
  pending: '等待采集',
  captured: '已采集，待确认',
  classified: '已分类',
  draft_ready: '草稿已生成',
  expired: '已过期',
};

function formatExpiry(value) {
  if (!value) return '';
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return '';
  return `有效至 ${new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

function hasUsableTicket(job) {
  if (!job?.capability_ticket || !job.ticket_expires_at) return false;
  const expiresAt = new Date(job.ticket_expires_at).getTime();
  return Number.isFinite(expiresAt) && expiresAt > Date.now();
}

export default function CaptureRequestCard({
  jobs = [],
  onCreate,
  onUse,
  onRefreshTicket,
  onClassify,
  onDraft,
  busyJobId = null,
}) {
  const [targetUrl, setTargetUrl] = useState('');
  const [purpose, setPurpose] = useState('generic_evidence');
  const [creating, setCreating] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!targetUrl.trim() || creating) return;
    setCreating(true);
    try {
      await onCreate?.({ target_url: targetUrl.trim(), purpose });
      setTargetUrl('');
    } finally {
      setCreating(false);
    }
  };

  return (
    <section className="mx-auto w-full max-w-3xl border-b border-border px-4 py-3" aria-label="网页采集任务">
      <div className="flex items-center gap-2">
        <Search className="size-4 text-primary" />
        <h2 className="text-sm font-semibold text-foreground">网页采集任务</h2>
        <span className="text-xs text-muted-foreground">只读采集，先回到当前对话</span>
      </div>

      <form className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_9rem_auto]" onSubmit={handleSubmit}>
        <input
          value={targetUrl}
          onChange={(event) => setTargetUrl(event.target.value)}
          type="url"
          placeholder="https://目标公开页面"
          aria-label="目标公开页面 URL"
          className="min-w-0 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none ring-primary/30 placeholder:text-muted-foreground focus:ring-2"
        />
        <select
          value={purpose}
          onChange={(event) => setPurpose(event.target.value)}
          aria-label="采集用途"
          className="rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/30"
        >
          {PURPOSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <button
          type="submit"
          disabled={creating || !targetUrl.trim()}
          className="inline-flex items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          {creating ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
          创建任务
        </button>
      </form>

      {jobs.length > 0 && (
        <div className="mt-3 space-y-2">
          {jobs.map((job) => {
            const isBusy = busyJobId === job.id;
            const canUse = job.status === 'pending' && hasUsableTicket(job);
            const canClassify = job.status === 'captured';
            const canDraft = job.status === 'classified' || job.status === 'draft_ready';
            return (
              <div key={job.id} className="rounded-md border border-border bg-card px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                  <span className="font-medium text-foreground">任务 #{job.id}</span>
                  <span className={cn(
                    'rounded border px-1.5 py-0.5 text-xs',
                    job.status === 'expired' ? 'border-destructive/40 text-destructive' : 'border-border text-muted-foreground'
                  )}>
                    {STATUS_LABELS[job.status] || job.status}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">{job.target_host}{job.target_path_prefix}</span>
                  {job.expires_at && <span className="ml-auto text-xs text-muted-foreground">{formatExpiry(job.expires_at)}</span>}
                </div>
                {job.evidence?.excerpt && (
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{job.evidence.excerpt}</p>
                )}
                <div className="mt-2 flex flex-wrap gap-2">
                  {canUse && (
                    <button type="button" disabled={isBusy} onClick={() => onUse?.(job)} className="inline-flex items-center gap-1 rounded border border-primary/40 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/5 disabled:opacity-50">
                      <ExternalLink className="size-3.5" />交给插件
                    </button>
                  )}
                  {job.status === 'pending' && !canUse && (
                    <button type="button" disabled={isBusy} onClick={() => onRefreshTicket?.(job)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-foreground disabled:opacity-50">
                      <RefreshCw className={cn('size-3.5', isBusy && 'animate-spin')} />重新授权
                    </button>
                  )}
                  {canClassify && (
                    <button type="button" disabled={isBusy} onClick={() => onClassify?.(job)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-foreground disabled:opacity-50">
                      <FileText className="size-3.5" />确认分类
                    </button>
                  )}
                  {canDraft && (
                    <>
                      <button type="button" disabled={isBusy} onClick={() => onDraft?.(job, 'analysis_summary')} className="rounded border border-border px-2 py-1 text-xs text-foreground disabled:opacity-50">生成分析摘要</button>
                      <button type="button" disabled={isBusy} onClick={() => onDraft?.(job, 'invitation_draft')} className="rounded border border-border px-2 py-1 text-xs text-foreground disabled:opacity-50">生成邀约草稿</button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
