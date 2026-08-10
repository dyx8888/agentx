/**
 * PageSkeleton — 通用页面级骨架屏
 *
 * 复用项目内置的 .skeleton shimmer 动画（见 src/index.css 第 7 节），
 * 提供「侧栏 + 顶栏 + 内容区」三段式占位，覆盖大多数页面加载态。
 *
 * 用法：<Suspense fallback={<PageSkeleton />}>...</Suspense>
 */
export default function PageSkeleton() {
  return (
    <div
      className="flex h-screen w-full"
      style={{ background: 'var(--background)', color: 'var(--foreground)' }}
      aria-busy="true"
      aria-live="polite"
    >
      {/* 侧栏 —— 与 lg 断点一致，小屏隐藏 */}
      <aside
        className="hidden w-60 shrink-0 flex-col gap-3 p-4 lg:flex"
        style={{
          background: 'var(--sidebar)',
          borderRight: '1px solid var(--sidebar-border)',
        }}
      >
        <div className="skeleton h-7 w-28" />
        <div className="skeleton h-9 w-full" />
        <div className="mt-2 flex flex-col gap-2">
          <div className="skeleton h-8 w-full" />
          <div className="skeleton h-8 w-full" />
          <div className="skeleton h-8 w-3/4" />
        </div>
      </aside>

      {/* 主区域 */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* 顶栏 */}
        <header
          className="flex h-14 items-center justify-between px-5"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div className="skeleton h-6 w-40" />
          <div className="skeleton h-7 w-7 rounded-full" />
        </header>

        {/* 内容区 */}
        <div className="flex-1 space-y-4 overflow-hidden p-6">
          <div className="skeleton h-5 w-1/3" />
          <div className="skeleton h-24 w-full" />
          <div className="skeleton h-3 w-full" />
          <div className="skeleton h-3 w-5/6" />
          <div className="skeleton h-3 w-2/3" />
        </div>
      </main>
    </div>
  );
}
