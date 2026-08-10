import { Component } from 'react';
import { AlertCircle, RotateCw, Home } from 'lucide-react';

/**
 * ErrorBoundary — 全局错误边界
 *
 * 捕获子组件树在渲染期 / 生命周期内的 JavaScript 错误，展示友好降级 UI，
 * 避免整页白屏。错误统一记录到 console.error（生产可在此接入 Sentry / 自建监控）。
 *
 * 注意：错误边界无法捕获 事件回调、异步代码、SSR 错误，
 * 这些场景需自行 try/catch 并上报。
 *
 * 用法：在应用最外层包裹 <ErrorBoundary>...</ErrorBoundary>。
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  // 渲染期抛错时触发，更新 state 以展示降级 UI
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  // 副作用通道：上报错误（生产可替换为监控 SDK）
  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] 捕获到未处理错误:', error, errorInfo);
  }

  handleReload = () => {
    // 整页刷新，最可靠地清空异常状态
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = '/';
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const errMsg = this.state.error?.message || '未知错误';

    return (
      <div
        className="flex min-h-svh flex-col items-center justify-center gap-4 px-6 text-center"
        style={{ background: 'var(--background)', color: 'var(--foreground)' }}
        role="alert"
      >
        <AlertCircle className="size-12" style={{ color: 'var(--destructive)' }} />
        <div>
          <h1 className="font-heading text-2xl font-semibold">页面出错了</h1>
          <p
            className="mt-2 max-w-md text-sm text-pretty"
            style={{ color: 'var(--muted-foreground)' }}
          >
            应用遇到了意外错误，请尝试重新加载；若问题持续，请联系管理员。
          </p>
        </div>

        <details className="w-full max-w-md text-left text-xs">
          <summary
            className="cursor-pointer select-none"
            style={{ color: 'var(--muted-foreground)' }}
          >
            查看错误详情
          </summary>
          <pre
            className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-lg p-3"
            style={{ background: 'var(--muted)', color: 'var(--foreground)' }}
          >
            {errMsg}
          </pre>
        </details>

        <div className="flex gap-3">
          <button type="button" onClick={this.handleReload} className="btn btn-primary h-10">
            <RotateCw className="size-4" />
            重新加载
          </button>
          <button type="button" onClick={this.handleGoHome} className="btn btn-outline h-10">
            <Home className="size-4" />
            返回首页
          </button>
        </div>
      </div>
    );
  }
}
