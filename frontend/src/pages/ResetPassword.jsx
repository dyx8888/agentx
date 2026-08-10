import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Check, Loader2, LockKeyhole, ShieldCheck } from 'lucide-react';
import client from '@/api/client';

function ResetPasswordForm() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!token) {
      setError('重置链接无效或已过期，请重新申请。');
      return;
    }
    if (password.length < 8) {
      setError('新密码至少需要 8 位。');
      return;
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致。');
      return;
    }

    setLoading(true);
    try {
      await client.post('/auth/password/reset', {
        token,
        new_password: password,
      });
      setSuccess(true);
    } catch (err) {
      setError(err?.userMessage || err?.response?.data?.detail || '重置失败，请重新申请链接。');
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="w-full max-w-sm animate-fade-in-up text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-macaron-mint">
          <Check className="size-6 text-foreground/80" />
        </div>
        <h1 className="mt-5 font-heading text-2xl font-semibold tracking-tight text-foreground">
          密码已重置
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          请使用新密码重新登录 AgentX。
        </p>
        <button
          type="button"
          onClick={() => navigate('/login')}
          className="btn btn-primary btn-block mt-6 h-10"
        >
          返回登录
        </button>
      </div>
    );
  }

  return (
    <div className="w-full max-w-sm">
      <Link
        to="/login"
        className="mb-6 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        返回登录
      </Link>

      <div className="mb-8">
        <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
          <LockKeyhole className="size-6" />
        </div>
        <h1 className="font-heading text-3xl font-semibold tracking-tight text-foreground">
          设置新密码
        </h1>
        <p className="mt-2 text-sm text-pretty text-muted-foreground">
          重置链接 30 分钟内有效，提交后旧登录态会失效。
        </p>
      </div>

      {!token && (
        <div
          role="alert"
          className="mb-4 rounded-xl border border-destructive/30 bg-card/80 p-3 text-sm leading-5"
          style={{ color: 'var(--destructive)' }}
        >
          重置链接无效或已过期，请重新申请。
          <Link to="/forgot-password" className="ml-1 underline">
            重新发送邮件
          </Link>
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <div className="flex flex-col gap-2">
          <label htmlFor="new-password" className="text-sm font-medium text-foreground">
            新密码
          </label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            className="input-base h-10"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="confirm-password" className="text-sm font-medium text-foreground">
            确认新密码
          </label>
          <input
            id="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            className="input-base h-10"
          />
        </div>

        {error && (
          <div
            role="alert"
            className="text-sm leading-5"
            style={{ color: 'var(--destructive)' }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary btn-block mt-2 h-10"
          disabled={loading || !token}
        >
          {loading && <Loader2 className="size-4 animate-spin" />}
          重置密码
        </button>
      </form>

      <div className="mt-6 flex items-start gap-2 rounded-xl border border-border bg-card/50 p-3 text-xs leading-relaxed text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-primary" />
        <p>如果不是你本人申请，请关闭此页面并联系管理员检查账号安全。</p>
      </div>
    </div>
  );
}

export default function ResetPassword() {
  return (
    <main className="flex min-h-svh w-full items-center justify-center px-6 py-12">
      <ResetPasswordForm />
    </main>
  );
}
