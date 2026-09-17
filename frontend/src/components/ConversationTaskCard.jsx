import { Loader2, RefreshCw } from 'lucide-react';

const LABELS = {
  pending: '等待执行', running: '执行中', completed: '已完成', failed: '执行失败',
  timeout: '执行超时', blocked: '需要人工确认', expired: '已过期', interrupted: '执行中断',
};

export default function ConversationTaskCard({ tasks = [], onResume }) {
  if (!tasks.length) return null;
  return (
    <section className="mx-auto w-full max-w-3xl border-b border-border px-4 py-3" aria-label="对话任务">
      <h2 className="text-sm font-semibold text-foreground">对话任务</h2>
      <div className="mt-2 space-y-2">
        {tasks.map((task) => (
          <article key={task.id} className="rounded-md border border-border bg-card px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              {(task.status === 'pending' || task.status === 'running') && <Loader2 className="size-4 animate-spin" />}
              <strong>{task.agent_name}</strong><span>{LABELS[task.status] || task.status}</span>
              {task.status === 'pending' && (
                <button type="button" onClick={() => onResume?.(task)} className="ml-auto inline-flex items-center gap-1 rounded border px-2 py-1 text-xs">
                  <RefreshCw className="size-3" />继续执行
                </button>
              )}
            </div>
            {task.status === 'completed' && task.result && <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{task.result}</p>}
            {task.error_code && <p className="mt-1 text-xs text-destructive">错误代码：{task.error_code}</p>}
          </article>
        ))}
      </div>
    </section>
  );
}
