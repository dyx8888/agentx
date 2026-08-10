import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  Loader2,
  Mail,
  KeyRound,
  Sparkles,
} from 'lucide-react';
import client from '../api/client';

/* ═══════════════════════════════════════════════════════════════
   左侧品牌区 — 复用 LoginPage 的视觉语言，但标志字母改为 "x"
   设计意图：副页面用小写 x 作为"恢复 / 重置"语义的弱化标识
   ═══════════════════════════════════════════════════════════════ */
function BrandPanel() {
  return (
    <section
      className="relative hidden w-1/2 flex-col justify-between overflow-hidden p-12 lg:flex"
      style={{ backgroundColor: 'var(--sidebar)' }}
    >
      {/* 马卡龙光斑 — 与 LoginPage 保持一致 */}
      <div className="pointer-events-none absolute -left-20 -top-20 size-72 rounded-full bg-macaron-blue opacity-25 blur-3xl animate-mesh-a z-0" />
      <div className="pointer-events-none absolute -bottom-24 right-0 size-80 rounded-full bg-macaron-pink opacity-20 blur-3xl animate-mesh-b z-0" />
      <div className="pointer-events-none absolute left-1/3 top-1/2 size-64 rounded-full bg-macaron-mint opacity-20 blur-3xl animate-mesh-a z-0" />

      {/* 顶部品牌标识 — 字母 x（小写，弱化语义） */}
      <div className="relative z-10">
        <div className="flex items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <span className="font-heading text-lg font-semibold lowercase">x</span>
          </div>
          <span className="font-heading text-xl font-semibold text-foreground">
            AgentX
          </span>
        </div>
      </div>

      {/* 中部标题 + 插画 */}
      <div className="relative z-10 max-w-md">
        <h2 className="font-heading text-4xl font-semibold leading-tight text-balance text-foreground">
          忘了密码？没关系
        </h2>
        <p className="mt-4 text-sm leading-relaxed text-pretty text-muted-foreground">
          请输入与账户绑定的邮箱地址，系统将向该邮箱发送一封带有重置链接的验证邮件。
        </p>

        {/* 步骤卡片 — 用 macaron 色块串成线性流程 */}
        <ol className="mt-10 flex flex-col gap-3">
          {[
            { step: '01', label: '输入注册邮箱', desc: '我们会核对账户是否存在' },
            { step: '02', label: '查收邮件链接', desc: '链接 30 分钟内有效' },
            { step: '03', label: '设置新密码', desc: '至少 6 位，建议含大小写' },
          ].map(({ step, label, desc }) => (
            <li
              key={step}
              className="glass-card flex items-start gap-3 rounded-2xl p-4"
            >
              <span
                className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-macaron-mint font-heading text-sm font-semibold text-foreground/80"
                aria-hidden="true"
              >
                {step}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">{label}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {desc}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>

      {/* 底部版权 */}
      <div className="relative z-10 text-xs text-muted-foreground">
        © 2026 AgentX · 对话式 AI 电商工作助手
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════
   ResetForm — 右侧表单（已发送状态切换）
   ═══════════════════════════════════════════════════════════════ */
function ResetForm() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const trimmed = email.trim();
    if (!trimmed) {
      setError('请输入邮箱');
      return;
    }
    if (!/.+@.+\..+/.test(trimmed)) {
      setError('请输入有效的邮箱地址');
      return;
    }

    setLoading(true);
    try {
      // 调用后端忘记密码接口
      // 安全策略：无论邮箱是否存在，后端都返回相同成功响应（防枚举攻击）
      await client.post('/auth/password/forgot', { email: trimmed });
      setSent(true);
    } catch (err) {
      // 网络或服务异常时显示通用错误，不暴露邮箱是否存在
      setError('提交失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-sm">
      {/* 返回链接 */}
      <button
        type="button"
        onClick={() => navigate('/login')}
        className="mb-6 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        返回登录
      </button>

      {sent ? (
        /* ── 已发送状态 ── */
        <div className="animate-fade-in-up text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-macaron-mint">
            <Check className="size-6 text-foreground/80" />
          </div>
          <h1 className="mt-5 font-heading text-2xl font-semibold tracking-tight text-foreground">
            重置链接已发送
          </h1>
          <p className="mt-2 text-sm text-pretty text-muted-foreground">
            我们已经把重置链接发到{' '}
            <span className="font-medium text-foreground">{email}</span>。
            请在 30 分钟内查收邮件并完成重置。
          </p>
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="btn btn-primary btn-block mt-6 h-10"
          >
            返回登录
          </button>
          <button
            type="button"
            onClick={() => {
              setSent(false);
              setEmail('');
            }}
            className="mt-3 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            没收到？换一封邮箱再试
          </button>
        </div>
      ) : (
        /* ── 默认表单状态 ── */
        <>
          <div className="mb-8">
            <h1 className="font-heading text-3xl font-semibold tracking-tight text-foreground">
              重置密码
            </h1>
            <p className="mt-2 text-sm text-pretty text-muted-foreground">
              输入注册时使用的邮箱，我们会发送重置链接
            </p>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <label htmlFor="email" className="text-sm font-medium text-foreground">
                邮箱
              </label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  className="input-base input-pl h-10"
                />
              </div>
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
              disabled={loading}
            >
              {loading && <Loader2 className="size-4 animate-spin" />}
              发送重置链接
            </button>
          </form>

          {/* 安全提示 */}
          <div className="mt-6 flex items-start gap-2 rounded-xl border border-border bg-card/50 p-3 text-xs leading-relaxed text-muted-foreground">
            <Sparkles className="mt-0.5 size-3.5 shrink-0 text-primary" />
            <p>
              出于安全考虑，系统不会透露该邮箱是否已注册。如确认邮箱无误却未收到邮件，请检查垃圾邮件文件夹或联系管理员。
            </p>
          </div>
        </>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   ForgotPassword — 公开页面（无需登录）
   与 LoginPage 一致的左右分栏布局，但品牌字母改为小写 x
   ═══════════════════════════════════════════════════════════════ */
export default function ForgotPassword() {
  return (
    <main className="flex min-h-svh w-full">
      <BrandPanel />

      <section className="flex w-full flex-col items-center justify-center px-6 py-12 lg:w-1/2">
        <ResetForm />
      </section>
    </main>
  );
}
