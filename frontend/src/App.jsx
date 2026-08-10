import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from '@/lib/AuthContext';
import ErrorBoundary from '@/components/ErrorBoundary';
import RouteGuard from '@/components/RouteGuard';
import PageSkeleton from '@/components/PageSkeleton';

const LoginPage = lazy(() => import('@/pages/LoginPage'));
const ForgotPassword = lazy(() => import('@/pages/ForgotPassword'));
const ResetPassword = lazy(() => import('@/pages/ResetPassword'));
const LegalPage = lazy(() => import('@/pages/LegalPage'));
const ChatPage = lazy(() => import('@/pages/ChatPage'));
const SettingsPage = lazy(() => import('@/pages/SettingsPage'));
const OAuthCallback = lazy(() => import('@/pages/OAuthCallback'));

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Suspense fallback={<PageSkeleton />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/terms" element={<LegalPage type="terms" />} />
            <Route path="/privacy" element={<LegalPage type="privacy" />} />
            <Route
              path="/settings"
              element={
                <RouteGuard>
                  <SettingsPage />
                </RouteGuard>
              }
            />
            {/* OAuth 授权回调页：平台授权后回跳，换 token 后再回设置页 */}
            <Route
              path="/oauth/callback"
              element={
                <RouteGuard>
                  <OAuthCallback />
                </RouteGuard>
              }
            />
            <Route
              path="/"
              element={
                <RouteGuard>
                  <ChatPage />
                </RouteGuard>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </ErrorBoundary>
  );
}
