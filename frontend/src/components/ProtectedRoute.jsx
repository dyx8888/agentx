import { Navigate } from 'react-router-dom';
import { useAuth } from '@/lib/AuthContext';

/**
 * 路由守卫 — 未认证时重定向到登录页
 * 加载中显示简洁的 CSS spinner（不依赖 Ant Design）
 */
export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();

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
    return <Navigate to="/login" replace />;
  }

  return children;
}
