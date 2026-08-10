import { useMemo, useState } from 'react';
import { Users, Download, ArrowRight, Loader2, Copy } from 'lucide-react';

const VISIBLE_LIMIT = 3;
const TEXT = {
  title: '\u8fbe\u4eba\u641c\u7d22\u7ed3\u679c',
  keyword: '\u5173\u952e\u8bcd',
  totalPrefix: '\u5171',
  totalSuffix: '\u4f4d',
  loading: '\u6b63\u5728\u68c0\u7d22\u8fbe\u4eba...',
  followers: '\u7c89\u4e1d',
  engagement: '\u4e92\u52a8\u7387',
  outreach: '\u590d\u5236\u9080\u7ea6\u8349\u7a3f',
  showAll: '\u67e5\u770b\u5168\u90e8',
  collapse: '\u6536\u8d77',
  export: '\u5bfc\u51fa',
  draftCopied: '\u5df2\u590d\u5236\u9080\u7ea6\u8349\u7a3f\uff0c\u8bf7\u5ba1\u6838\u540e\u518d\u53d1\u9001',
  copyFailed: '\u590d\u5236\u5931\u8d25\uff0c\u8bf7\u624b\u52a8\u590d\u5236\u8fbe\u4eba\u4fe1\u606f',
  exported: '\u5df2\u5bfc\u51fa CSV',
  noData: '\u6ca1\u6709\u53ef\u5bfc\u51fa\u7684\u8fbe\u4eba',
};

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function buildOutreachDraft(talent, query) {
  const name = talent.name || talent.handle || 'creator';
  const category = talent.category || query || 'our campaign';
  return [
    `Hi ${name},`,
    `We found your ${category} content relevant to this campaign.`,
    'Could we discuss a collaboration draft? This is only a draft and must be reviewed before sending.',
  ].join('\n');
}

export default function TalentResultCard({ query, talents = [], total, loading }) {
  const [toastMsg, setToastMsg] = useState('');
  const [expanded, setExpanded] = useState(false);
  const visibleTalents = useMemo(
    () => (expanded ? talents : talents.slice(0, VISIBLE_LIMIT)),
    [expanded, talents]
  );

  const showToast = (msg) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 2200);
  };

  const copyOutreachDraft = async (talent) => {
    try {
      await navigator.clipboard.writeText(buildOutreachDraft(talent, query));
      showToast(TEXT.draftCopied);
    } catch {
      showToast(TEXT.copyFailed);
    }
  };

  const exportCsv = () => {
    if (!talents.length) {
      showToast(TEXT.noData);
      return;
    }
    const headers = ['name', 'handle', 'category', 'followers', 'engagement_rate'];
    const rows = talents.map((t) => [t.name, t.handle, t.category, t.followers, t.rate]);
    const csv = [headers, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `talent-search-${Date.now()}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast(TEXT.exported);
  };

  return (
    <>
      <div className="mt-3 w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <div className="flex size-7 items-center justify-center rounded-lg bg-macaron-pink">
            <Users className="size-4 text-foreground/80" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-medium text-foreground">{TEXT.title}</p>
            {query && <p className="text-xs text-muted-foreground">{TEXT.keyword}: {query}</p>}
          </div>
          {total != null && (
            <span className="text-xs text-muted-foreground">
              {TEXT.totalPrefix} {total} {TEXT.totalSuffix}
            </span>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {TEXT.loading}
          </div>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {visibleTalents.map((t) => (
                <li key={t.handle || t.name} className="flex items-center gap-3 px-4 py-3">
                  <div className="flex size-9 items-center justify-center rounded-full bg-secondary text-xs text-secondary-foreground">
                    {(t.name || '?').slice(0, 1)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {t.name}{' '}
                      <span className="text-xs font-normal text-muted-foreground">
                        {TEXT.followers} {t.followers ?? '-'}
                      </span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {t.category || '-'} · {TEXT.engagement} {t.rate ?? '-'}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => copyOutreachDraft(t)}
                    className="inline-flex h-7 shrink-0 items-center gap-1 justify-center rounded-md px-2 text-xs text-foreground transition-colors hover:bg-accent"
                  >
                    <Copy className="size-3" />
                    {TEXT.outreach}
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-2.5">
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-ink transition-colors hover:bg-accent"
              >
                {expanded ? TEXT.collapse : TEXT.showAll}
                <ArrowRight className="size-3.5" />
              </button>
              <button
                type="button"
                onClick={exportCsv}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-transparent px-2 text-xs text-ink transition-colors hover:bg-accent"
              >
                <Download className="size-3.5" />
                {TEXT.export}
              </button>
            </div>
          </>
        )}
      </div>
      {toastMsg && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-lg bg-foreground px-4 py-2 text-sm text-background shadow-lg">
          {toastMsg}
        </div>
      )}
    </>
  );
}
