import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/lib/AuthContext';

/**
 * RouteGuard — 受保护路由守卫
 *
 * 未登录访问受保护路由时重定向到 /login，并通过 query 参数 redirect 与
 * location state 携带原始目标路径，便于登录后回跳。
 *
 * 与现有 ProtectedRoute 的区别：后者仅跳转不带目标路径；
 * RouteGuard 额外携带 redirect 参数，供登录页按需回跳（当前 LoginPage
 * 默认回首页，携带参数为前置预留，不破坏现有行为）。
 */
export default function RouteGuard({ children }) {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

  // 认证状态尚未就绪 —— 显示简洁 CSS spinner（不依赖额外组件库）
  if (loading) {
    return (
      <div
        className="flex items-center justify-center h-screen"
        style={{ background: 'var(--background)' }}
      >
        <div
          className="w-6 h-6 rounded-full border-2 animate-spin"
          style={{
            borderColor: 'var(--border)',
            borderTopColor: 'var(--foreground)',
          }}
          aria-label="加载中"
          role="status"
        />
      </div>
    );
  }

  if (!isAuthenticated) {
    // 携带原始路径（含 query），登录成功后可回跳
    const redirect = location.pathname + location.search;
    return (
      <Navigate
        to={`/login?redirect=${encodeURIComponent(redirect)}`}
        replace
        state={{ from: location }}
      />
    );
  }

  return children;
}
