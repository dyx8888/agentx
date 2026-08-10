import { memo, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Copy,
  Check,
  RefreshCw,
  ChevronRight,
  Link2,
  Sparkles,
  FileText,
  FileSpreadsheet,
  Image as ImageIcon,
  File,
  Paperclip,
  Loader2,
  CheckCircle2,
  XCircle,
  Users,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import TalentResultCard from '@/components/TalentResultCard';

/* ═══════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════ */

function formatTimestamp(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handle = async () => {
    try {
      await navigator.clipboard.writeText(text || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      type="button"
      className="msg-action-btn"
      onClick={handle}
      aria-label="复制"
      title={copied ? '已复制' : '复制'}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </button>
  );
}

function getStreamingStatusText(message) {
  const sources = message?.sources || [];
  const toolResults = (message?.toolResults || []).filter(isTalentToolResult);
  const delegations = message?.delegations || [];

  if (toolResults.some((tool) => tool?.loading)) {
    return '工具正在执行，请稍等...';
  }
  if (delegations.some((item) => ['started', 'running', 'processing'].includes(item?.status))) {
    return '子 Agent 正在协作处理...';
  }
  if (sources.length > 0) {
    return '已找到相关证据，正在组织回答...';
  }
  if (message?.plan) {
    return '已生成执行计划，正在处理...';
  }
  if (message?.thinking) {
    return '正在分析问题并检索相关信息...';
  }
  return '正在理解问题并选择合适的数据源...';
}

function isTalentToolResult(toolResult) {
  return toolResult?.type === 'searchTalents' || toolResult?.name === 'searchTalents';
}

const SOURCE_TYPE_LABELS = {
  knowledge_base: '知识库',
  knowledge: '知识库',
  rag: '知识库',
  vector: '向量检索',
  bm25: '关键词检索',
  hybrid: '混合检索',
  enterprise: '企业数据',
  enterprise_data: '企业数据',
  manual: '人工导入',
  manual_upload: '人工导入',
  public_web: '公开网页',
  web: '公开网页',
  official_api: '官方 API',
  partner_api: '合作方 API',
  cached_snapshot: '缓存快照',
  mock: 'mock 数据',
  demo: 'demo 数据',
  seed: 'seed 数据',
  sample: 'sample 数据',
};

function getSourceType(src) {
  if (typeof src === 'string') return src.startsWith('http') ? 'web' : 'knowledge_base';
  return (
    src?.data_source ||
    src?.source_type ||
    src?.sourceType ||
    src?.source ||
    src?.kind ||
    src?.type ||
    ''
  );
}

function getSourceTypeLabel(src) {
  const type = String(getSourceType(src) || '').trim().toLowerCase();
  return SOURCE_TYPE_LABELS[type] || '未标注来源';
}

/* ═══════════════════════════════════════════════════════════════
   AgentFileCard — Agent 生成的文件附件卡
   点击 → onFileClick(file)
   ═══════════════════════════════════════════════════════════════ */

const FILE_ICON_MAP = {
  doc:    { Icon: FileText,       tint: 'bg-macaron-blue' },
  sheet:  { Icon: FileSpreadsheet,tint: 'bg-macaron-mint' },
  image:  { Icon: ImageIcon,      tint: 'bg-macaron-pink' },
  pdf:    { Icon: File,           tint: 'bg-macaron-yellow' },
  text:   { Icon: FileText,       tint: 'bg-macaron-blue' },
  report: { Icon: FileText,       tint: 'bg-macaron-mint' },
  data:   { Icon: FileSpreadsheet,tint: 'bg-macaron-pink' },
};

function AgentFileCard({ file, onClick }) {
  const { Icon, tint } = FILE_ICON_MAP[file.type] || { Icon: File, tint: 'bg-secondary' };
  return (
    <button
      type="button"
      onClick={() => onClick?.(file)}
      className="group flex w-full items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left transition-all hover:border-primary/40 hover:shadow-sm"
    >
      <div className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', tint)}>
        <Icon className="size-4 text-foreground/80" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1 truncate text-sm font-medium text-foreground">
          <span className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-macaron-pink px-1.5 py-0.5 text-[10px] font-normal text-foreground/80">
            <Sparkles className="size-2.5" />
            Agent
          </span>
          <span className="truncate">{file.name}</span>
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {file.size} · {file.uploadedAt || '刚刚生成'}
        </p>
      </div>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
    </button>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Sub-components — sources / business tool results
   ═══════════════════════════════════════════════════════════════ */

function SourcesSection({ sources }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-3 rounded-md border border-border bg-muted p-2.5">
      <div className="mb-1.5 text-xs font-medium text-muted-foreground">
        数据来源与证据（{sources.length} 条）
      </div>
      <ul className="space-y-1">
        {sources.map((src, i) => {
          const url = typeof src === 'string' ? src : src?.url;
          const label =
            typeof src === 'string'
              ? src
              : src?.title || src?.name || src?.document_title || src?.url || `来源 ${i + 1}`;
          const sourceTypeLabel = getSourceTypeLabel(src);
          const sourceNote =
            typeof src === 'string'
              ? ''
              : src?.source_note || src?.note || src?.metadata?.source_note || '';
          return (
            <li key={url || `${label}-${i}`} className="flex items-start gap-1.5 text-xs">
              <span className="mt-0.5 inline-flex shrink-0 text-muted-foreground">
                <Link2 className="size-3" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="mr-1 inline-flex shrink-0 rounded border border-border bg-card px-1.5 py-0.5 text-[10px] leading-none text-muted-foreground">
                  {sourceTypeLabel}
                </span>
                {url ? (
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="break-all text-link underline hover:text-link-deep"
                  >
                    {label}
                  </a>
                ) : (
                  <span className="break-all text-foreground">{label}</span>
                )}
                {sourceNote ? (
                  <span className="ml-1 text-muted-foreground">· {sourceNote}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   AI Avatar — purple square "M"
   ═══════════════════════════════════════════════════════════════ */

function AssistantAvatar() {
  return (
    <div
      className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-xs font-medium text-primary-foreground"
      aria-hidden="true"
    >
      M
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   DelegationSection — 子 Agent 委派状态条（T2.9）
   展示 master 委派子 Agent 的进行中 / 已完成 / 失败状态
   配色用马卡龙（不用蓝色）
   ═══════════════════════════════════════════════════════════════ */

// 委派状态 → 马卡龙配色 + 图标
const DELEGATION_STYLES = {
  started: {
    bg: 'bg-macaron-yellow/15',
    border: 'border-macaron-yellow/30',
    text: 'text-foreground',
    label: '进行中',
    Icon: Loader2,
    iconClass: 'animate-spin text-macaron-yellow',
  },
  completed: {
    bg: 'bg-macaron-mint/15',
    border: 'border-macaron-mint/30',
    text: 'text-foreground',
    label: '已完成',
    Icon: CheckCircle2,
    iconClass: 'text-macaron-mint',
  },
  failed: {
    bg: 'bg-macaron-pink/15',
    border: 'border-macaron-pink/30',
    text: 'text-foreground',
    label: '失败',
    Icon: XCircle,
    iconClass: 'text-macaron-pink',
  },
};

const DELEGATION_COLLAPSE_THRESHOLD = 3;
const DELEGATION_COLLAPSE_PREVIEW = 2;

function DelegationSection({ delegations }) {
  const [expanded, setExpanded] = useState(false);

  // 1.1 顺序保序 + 1.4 边界处理：过滤 null/undefined，用 Map 按 agent_name 去重并保留首次插入顺序
  // 同一 agent 的多次状态更新覆盖旧状态，但顺序以首次出现为准
  const orderedDelegations = useMemo(() => {
    if (!Array.isArray(delegations) || delegations.length === 0) return [];
    const map = new Map();
    for (const d of delegations) {
      if (!d) continue; // 过滤 null/undefined
      const key = d.agent_name || d.agent_display || `agent-${map.size}`;
      map.set(key, d); // 覆盖旧状态，保留插入顺序
    }
    return Array.from(map.values());
  }, [delegations]);

  // 1.4 空数组不渲染
  if (orderedDelegations.length === 0) return null;

  // 1.2 计算整体状态：all started / any failed / all completed
  const totalCount = orderedDelegations.length;
  const startedCount = orderedDelegations.filter((d) => d.status === 'started').length;
  const failedCount = orderedDelegations.filter((d) => d.status === 'failed').length;
  const completedCount = orderedDelegations.filter((d) => d.status === 'completed').length;
  const allStarted = startedCount === totalCount;
  const anyFailed = failedCount > 0;
  const allCompleted = completedCount === totalCount;

  // 1.2 全部完成 → 折叠为单行摘要
  if (allCompleted) {
    return (
      <div className="mb-2 flex items-center gap-2 rounded-lg border border-macaron-mint/30 bg-macaron-mint/15 px-3 py-2">
        <Users className="size-3.5 shrink-0 text-macaron-mint" />
        <span className="flex-1 text-xs font-medium text-foreground">
          {totalCount} 个子任务已完成
        </span>
        <CheckCircle2 className="size-3.5 shrink-0 text-macaron-mint" />
      </div>
    );
  }

  // 1.3 折叠：>3 条时默认只显示前 2 条
  const shouldCollapse = totalCount > DELEGATION_COLLAPSE_THRESHOLD;
  const visibleDelegations = shouldCollapse && !expanded
    ? orderedDelegations.slice(0, DELEGATION_COLLAPSE_PREVIEW)
    : orderedDelegations;

  return (
    <div className="mb-2 flex flex-col gap-1.5">
      {/* 1.2 顶部状态文案 */}
      {allStarted && (
        <div className="flex items-center gap-1.5 rounded-lg border border-macaron-yellow/30 bg-macaron-yellow/15 px-3 py-1.5 text-xs font-medium text-foreground">
          <Loader2 className="size-3.5 shrink-0 animate-spin text-macaron-yellow" />
          <span>子 Agent 工作中...</span>
        </div>
      )}
      {anyFailed && (
        <div className="flex items-center gap-1.5 rounded-lg border border-macaron-pink/30 bg-macaron-pink/15 px-3 py-1.5 text-xs font-medium text-foreground">
          <AlertTriangle className="size-3.5 shrink-0 text-macaron-pink" />
          <span>部分子任务失败</span>
        </div>
      )}

      {/* 委派条目列表 */}
      {visibleDelegations.map((d, i) => {
        const style = DELEGATION_STYLES[d.status] || DELEGATION_STYLES.started;
        const { Icon } = style;
        // 1.4 缺 agent_display 时降级显示 agent_name
        const display = d.agent_display || d.agent_name || '子 Agent';
        return (
          <div
            key={`${d.agent_name || display}-${i}`}
            className={cn(
              'flex items-center gap-2 rounded-lg border px-3 py-2',
              style.bg,
              style.border,
            )}
          >
            <Users className={cn('size-3.5 shrink-0', style.iconClass)} />
            <span className={cn('flex-1 text-xs font-medium', style.text)}>
              {display}
            </span>
            <Icon className={cn('size-3.5 shrink-0', style.iconClass)} />
            <span className="text-[10px] text-muted-foreground">{style.label}</span>
          </div>
        );
      })}

      {/* 1.3 展开 / 收起按钮 */}
      {shouldCollapse && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="self-start rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          {expanded
            ? '收起'
            : `展开查看全部 ${totalCount} 条`}
        </button>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   MessageBubble (default export)
   Props:
     - message
     - onFileClick (NEW) — 点击 Agent 生成文件时触发
     - onUserFileClick (NEW) — 点击用户消息中的附件时触发
   ═══════════════════════════════════════════════════════════════ */

function WarningSection({ warnings }) {
  if (!Array.isArray(warnings) || warnings.length === 0) return null;

  return (
    <div className="mb-2 flex flex-col gap-1.5">
      {warnings.map((warning, index) => (
        <div
          key={warning.id || `${warning.code || 'warning'}-${index}`}
          className="flex items-start gap-2 rounded-lg border border-macaron-yellow/30 bg-macaron-yellow/10 px-3 py-2 text-xs leading-5 text-foreground/80"
          role="status"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-macaron-yellow" />
          <span>{warning.message || '系统已降级处理本次请求。'}</span>
        </div>
      ))}
    </div>
  );
}

function MessageBubble({
  message,
  onFileClick,
  onUserFileClick,
  onRegenerate,
  slowNoticeMs = 20000,
}) {
  const {
    role,
    content,
    sources,
    warnings,
    toolResults,
    agentFiles,
    delegations,
    attachments,
    isStreaming,
    timestamp,
    created_at: createdAt,
  } = message || {};

  const isUser = role === 'user';
  const ts = timestamp || createdAt;
  const businessToolResults = useMemo(
    () => (toolResults || []).filter(isTalentToolResult),
    [toolResults]
  );

  const markdown = useMemo(() => {
    if (isUser || !content) return null;
    return <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>;
  }, [isUser, content]);

  const waitingForFirstContent = !isUser && isStreaming && !content;
  const [showSlowNotice, setShowSlowNotice] = useState(false);

  useEffect(() => {
    setShowSlowNotice(false);
    if (!waitingForFirstContent) return undefined;
    if (slowNoticeMs <= 0) {
      setShowSlowNotice(true);
      return undefined;
    }
    const timer = setTimeout(() => setShowSlowNotice(true), slowNoticeMs);
    return () => clearTimeout(timer);
  }, [waitingForFirstContent, slowNoticeMs]);

  return (
    <div
      className={cn(
        'flex w-full animate-fade-in-up gap-3',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      {!isUser && <AssistantAvatar />}

      <div
        className={cn(
          'flex max-w-[85%] flex-col gap-1',
          isUser ? 'items-end' : 'items-start'
        )}
      >
        {isUser ? (
          /* ── 用户气泡 ── */
          <>
            {/* 用户附件（如有）— 在气泡上方 */}
            {attachments && attachments.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {attachments.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => onUserFileClick?.(a)}
                    className="group flex items-center gap-2 rounded-xl border border-border bg-card px-2.5 py-2 text-xs text-foreground transition-colors hover:border-primary/40"
                  >
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-secondary">
                      <Paperclip className="size-3.5 text-muted-foreground" />
                    </span>
                    <span className="max-w-[200px] truncate">{a.name}</span>
                    {a.size && (
                      <span className="shrink-0 text-muted-foreground">· {a.size}</span>
                    )}
                  </button>
                ))}
              </div>
            )}
            <div
              className={cn(
                'whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm px-4 py-2.5',
                'bg-secondary text-sm leading-relaxed text-secondary-foreground',
                isStreaming && 'typing-caret'
              )}
            >
              {content}
            </div>
          </>
        ) : (
          /* ── AI 气泡 ── */
          <div
            className={cn(
              'rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-2.5',
              'text-sm leading-relaxed text-card-foreground shadow-sm'
            )}
          >
            {/* 委派状态条 */}
            <WarningSection warnings={warnings} />
            <DelegationSection delegations={delegations} />

            {/* 正文 */}
            {content ? (
              <div className={cn('prose-chat', isStreaming && 'typing-caret')}>
                {markdown}
              </div>
            ) : isStreaming ? (
              /* 等待正文 — 给用户明确进度，而不是只显示空白加载 */
              <div className="py-1 text-sm text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Loader2 className="size-3.5 shrink-0 animate-spin" />
                  <span>{getStreamingStatusText(message)}</span>
                </div>
                {showSlowNotice && (
                  <div className="mt-2 flex items-start gap-2 rounded-lg border border-macaron-yellow/30 bg-macaron-yellow/10 px-2.5 py-2 text-xs leading-5 text-foreground/80">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-macaron-yellow" />
                    <span>
                      外部模型或工具响应较慢。你可以继续等待，或点击输入框右侧的停止按钮后重试。
                    </span>
                  </div>
                )}
              </div>
            ) : null}

            {/* 工具结果 */}
            {businessToolResults.length > 0 ? (
              <div className="mt-3">
                {businessToolResults.map((tr) => {
                  if (tr.loading) {
                    return <TalentResultCard key={tr.id} loading />;
                  }
                  return (
                    <TalentResultCard
                      key={tr.id}
                      query={tr.query}
                      talents={tr.talents}
                      total={tr.total}
                    />
                  );
                })}
              </div>
            ) : null}

            {/* Agent 生成的文件附件 */}
            {agentFiles && agentFiles.length > 0 ? (
              <div className="mt-3 flex flex-col gap-2">
                {agentFiles.map((f) => (
                  <AgentFileCard
                    key={f.id}
                    file={f}
                    onClick={onFileClick}
                  />
                ))}
              </div>
            ) : null}

            {/* 搜索来源 */}
            <SourcesSection sources={sources} />

            {/* 操作栏：复制 / 重新生成 */}
            {!isStreaming && content ? (
              <div className="msg-actions">
                <CopyButton text={content} />
                <button
                  type="button"
                  className="msg-action-btn"
                  aria-label="重新生成"
                  title={onRegenerate ? '重新生成' : '重新生成（需要对话上下文）'}
                  disabled={!onRegenerate}
                  onClick={() => onRegenerate?.()}
                >
                  <RefreshCw className="size-3.5" />
                </button>
              </div>
            ) : null}
          </div>
        )}

        {ts ? (
          <span className="px-1 text-xs text-muted-foreground">
            {formatTimestamp(ts)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export default memo(MessageBubble);
