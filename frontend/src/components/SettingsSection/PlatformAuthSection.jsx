import { AlertTriangle } from 'lucide-react';

export const PLATFORM_API_PAUSED_MESSAGE = '平台 API 暂停，数据获取将通过浏览器连接器';

export default function PlatformAuthSection() {
  return (
    <section
      className="rounded-2xl border border-border bg-card p-5"
      aria-label="平台授权管理"
    >
      <div className="flex items-start gap-3">
        <div
          className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-macaron-yellow text-foreground/80"
          aria-hidden="true"
        >
          <AlertTriangle className="size-5" />
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-heading text-lg font-semibold text-foreground">
              平台授权管理
            </h2>
            <span className="rounded-full bg-secondary px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
              已暂停
            </span>
          </div>

          <p role="status" className="text-sm font-medium text-foreground">
            {PLATFORM_API_PAUSED_MESSAGE}
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            平台 OAuth 授权、凭证校验和真实平台 API 同步已暂停；后续数据获取主线将改为浏览器连接器。
          </p>
        </div>
      </div>
    </section>
  );
}
