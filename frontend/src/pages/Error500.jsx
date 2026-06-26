import { RocketOutlined } from '@ant-design/icons';

export default function Error500() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--color-bg-primary)]">
      <div className="text-center">
        <div
          className="w-20 h-20 rounded-[var(--radius-xl)] flex items-center justify-center mx-auto mb-6
            shadow-[var(--shadow-md)]"
          style={{ background: 'var(--gradient-accent)' }}
        >
          <RocketOutlined className="text-3xl text-white" />
        </div>
        <h1 className="text-5xl font-bold text-[var(--color-text-primary)] mb-4">500</h1>
        <p className="text-[var(--font-size-base)] text-[var(--color-text-tertiary)] mb-8 max-w-md">
          服务器遇到了一些问题，请稍后重试。
        </p>
        <div className="flex gap-3 justify-center">
          <button
            onClick={() => window.location.reload()}
            className="px-6 py-3 bg-[var(--color-text-primary)] text-white
              rounded-[var(--radius-md)] text-[var(--font-size-sm)] font-medium
              hover:bg-[var(--color-text-secondary)] hover:shadow-[var(--shadow-md)]
              transition-all duration-150"
          >
            刷新页面
          </button>
          <button
            onClick={() => window.location.href = '/chat'}
            className="px-6 py-3 border border-[var(--color-border)] text-[var(--color-text-secondary)]
              rounded-[var(--radius-md)] text-[var(--font-size-sm)] font-medium
              hover:bg-[var(--color-bg-hover)] transition-all duration-150"
          >
            返回首页
          </button>
        </div>
      </div>
    </div>
  );
}