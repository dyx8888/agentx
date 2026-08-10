import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Eye,
  EyeOff,
  Loader2,
  Mail,
  Lock,
  User,
  Users,
  BarChart3,
  FileText,
  Truck,
} from 'lucide-react';
import { login as apiLogin, register as apiRegister } from '@/api/auth';
import { useAuth } from '@/lib/AuthContext';

/* ═══════════════════════════════════════════════════════════════
   Demo / 访客账号 — 通过环境变量控制，避免在源码中硬编码密码
   仅用于本地开发与演示：在 frontend/.env 中设置
   VITE_DEMO_ENABLED=true
   VITE_DEMO_USERNAME=demo
   VITE_DEMO_PASSWORD=your-dev-only-password
   ═══════════════════════════════════════════════════════════════ */
const DEMO_ENABLED = import.meta.env.VITE_DEMO_ENABLED === 'true';
const DEMO_USERNAME = import.meta.env.VITE_DEMO_USERNAME || '';
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD || '';
const LOGIN_PASSWORD_MIN_LENGTH = 6;
const REGISTER_PASSWORD_MIN_LENGTH = 8;

/* ═══════════════════════════════════════════════════════════════
   左侧品牌区 — 4 个能力高亮卡片
   完全对齐 v0 app/page.tsx
   ═══════════════════════════════════════════════════════════════ */
const HIGHLIGHTS = [
  { icon: Users, label: '达人搜索与建联', desc: '基于已导入/已授权达人数据筛选，生成待审核草稿' },
  { icon: BarChart3, label: '数据分析与报告', desc: '接入真实店铺数据后汇总指标，并标明数据来源' },
  { icon: FileText, label: '内容策划与脚本', desc: '基于品牌资料和知识库生成可编辑草稿' },
  { icon: Truck, label: '物流跟踪与样品', desc: '接入订单/物流数据后查询状态，不伪造结果' },
];

/* ═══════════════════════════════════════════════════════════════
   AuthForm — 右侧表单
   完全对齐 v0 components/auth/auth-form.tsx
   ═══════════════════════════════════════════════════════════════ */
function AuthForm() {
  const navigate = useNavigate();
  const { login: authLogin } = useAuth();

  const [mode, setMode] = useState('login');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [loginForm, setLoginForm] = useState({ email: '', password: '' });
  const [registerForm, setRegisterForm] = useState({
    username: '',
    email: '',
    password: '',
  });

  const resolveErrorMessage = (err) => {
    const detail = err?.response?.data?.detail;
    if (detail === 'Incorrect username or password') return '用户名或密码错误';
    if (typeof detail === 'string' && detail) return detail;
    return err?.message || '登录失败，请稍后重试';
  };

  const performLogin = async (username, password, redirectTo = '/') => {
    setError('');
    setLoading(true);
    try {
      const data = await apiLogin(username, password);
      if (!data?.access_token) {
        setError('未获取到有效的访问令牌');
        return;
      }
      await authLogin(data.access_token, data.refresh_token);
      navigate(redirectTo);
    } catch (err) {
      setError(resolveErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (mode === 'login') {
      const email = loginForm.email.trim();
      const { password } = loginForm;
      if (!email) {
        setError('请输入用户名');
        return;
      }
      if (!password || password.length < LOGIN_PASSWORD_MIN_LENGTH) {
        setError(`密码长度至少为 ${LOGIN_PASSWORD_MIN_LENGTH} 位`);
        return;
      }
      performLogin(email, password);
      return;
    }

    const username = registerForm.username.trim();
    const email = registerForm.email.trim();
    const { password } = registerForm;
    if (!username) {
      setError('请输入用户名');
      return;
    }
    if (!email || !/.+@.+\..+/.test(email)) {
      setError('请输入有效的邮箱地址');
      return;
    }
    if (!password || password.length < REGISTER_PASSWORD_MIN_LENGTH) {
      setError(`密码长度至少为 ${REGISTER_PASSWORD_MIN_LENGTH} 位`);
      return;
    }

    setLoading(true);
    try {
      await apiRegister({
        username,
        password,
        email,
        company_name: `${username} 的工作区`,
        brand_name: username,
        category: '其他',
      });
      await performLogin(username, password, '/settings');
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (typeof detail === 'string' && detail) {
        setError(detail);
      } else {
        setError(err?.message || '注册失败，请稍后重试');
      }
      setLoading(false);
    }
  };

  const handleGuest = () => {
    if (loading) return;
    if (!DEMO_USERNAME || !DEMO_PASSWORD) {
      setError('演示账号未配置，请联系管理员设置 VITE_DEMO_USERNAME / VITE_DEMO_PASSWORD');
      return;
    }
    performLogin(DEMO_USERNAME, DEMO_PASSWORD);
  };

  const switchMode = (next) => {
    if (loading || next === mode) return;
    setMode(next);
    setShowPassword(false);
    setError('');
  };

  return (
    <div className="w-full max-w-sm">
      {/* 标题 */}
      <div className="mb-8 text-center">
        <h1 className="font-heading text-3xl font-semibold tracking-tight text-foreground">
          AgentX
        </h1>
        <p className="mt-2 text-sm text-pretty text-muted-foreground">
          {mode === 'login' ? '欢迎回来，登录开始你的工作' : '创建账户，开启对话式电商助手'}
        </p>
      </div>

      {/* Tabs — v0 segmented control */}
      <div className="tabs-list mb-6" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'login'}
          onClick={() => switchMode('login')}
          className={`tab-trigger ${mode === 'login' ? 'active' : ''}`}
        >
          登录
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'register'}
          onClick={() => switchMode('register')}
          className={`tab-trigger ${mode === 'register' ? 'active' : ''}`}
        >
          注册
        </button>
      </div>

      {/* 表单 */}
      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        {mode === 'register' && (
          <div className="flex flex-col gap-2">
            <label htmlFor="name" className="text-sm font-medium text-foreground">
              用户名
            </label>
            <div className="relative">
              <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                id="name"
                type="text"
                placeholder="你的名字"
                value={registerForm.username}
                onChange={(e) =>
                  setRegisterForm({ ...registerForm, username: e.target.value })
                }
                autoComplete="username"
                className="input-base input-pl h-10"
              />
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <label htmlFor="email" className="text-sm font-medium text-foreground">
            {mode === 'login' ? '用户名' : '邮箱'}
          </label>
          <div className="relative">
            <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              id="email"
              type={mode === 'login' ? 'text' : 'email'}
              placeholder={mode === 'login' ? '请输入用户名' : 'you@example.com'}
              value={mode === 'login' ? loginForm.email : registerForm.email}
              onChange={(e) => {
                const v = e.target.value;
                if (mode === 'login') setLoginForm({ ...loginForm, email: v });
                else setRegisterForm({ ...registerForm, email: v });
              }}
              autoComplete={mode === 'login' ? 'username' : 'email'}
              className="input-base input-pl h-10"
            />
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label htmlFor="password" className="text-sm font-medium text-foreground">
              密码
            </label>
            {mode === 'login' && (
              <Link
                to="/forgot-password"
                className="text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                忘记密码？
              </Link>
            )}
          </div>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              placeholder="••••••••"
              value={mode === 'login' ? loginForm.password : registerForm.password}
              onChange={(e) => {
                const v = e.target.value;
                if (mode === 'login') setLoginForm({ ...loginForm, password: v });
                else setRegisterForm({ ...registerForm, password: v });
              }}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              className="input-base input-pl input-pr h-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
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

        <button type="submit" className="btn btn-primary btn-block mt-2 h-10" disabled={loading}>
          {loading && <Loader2 className="size-4 animate-spin" />}
          {mode === 'login' ? '登录' : '创建账户'}
        </button>
      </form>

      {/* 分隔线 + 访客入口 — 仅在 demo 启用时渲染 */}
      {DEMO_ENABLED && (
        <>
          <div className="my-6 flex items-center gap-3">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">或</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <button
            type="button"
            onClick={handleGuest}
            disabled={loading}
            className="btn btn-outline btn-block h-10"
          >
            以访客身份继续
          </button>
        </>
      )}

      <p className="mt-6 text-center text-xs text-pretty text-muted-foreground">
        继续即表示你同意我们的{' '}
        <Link
          to="/terms"
          className="underline underline-offset-2 transition-colors hover:text-foreground"
        >
          服务条款
        </Link>{' '}
        与{' '}
        <Link
          to="/privacy"
          className="underline underline-offset-2 transition-colors hover:text-foreground"
        >
          隐私政策
        </Link>
      </p>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   LoginPage — 左右分栏
   完全对齐 v0 app/page.tsx
   ═══════════════════════════════════════════════════════════════ */
export default function LoginPage() {
  return (
    <main className="flex min-h-svh w-full">
      {/* 左侧品牌区 — 渐变背景 + 马卡龙光斑 + 能力卡片 */}
      <section
        className="relative hidden w-1/2 flex-col justify-between overflow-hidden p-12 lg:flex"
        style={{ backgroundColor: 'var(--sidebar)' }}
      >
        {/* 马卡龙光斑 — 明确 z-0 并降低不透明度，避免 blur 盖住文字 */}
        <div className="pointer-events-none absolute -left-20 -top-20 size-72 rounded-full bg-macaron-blue opacity-25 blur-3xl animate-mesh-a z-0" />
        <div className="pointer-events-none absolute -bottom-24 right-0 size-80 rounded-full bg-macaron-pink opacity-20 blur-3xl animate-mesh-b z-0" />
        <div className="pointer-events-none absolute left-1/3 top-1/2 size-64 rounded-full bg-macaron-mint opacity-20 blur-3xl animate-mesh-a z-0" />

        {/* 顶部品牌标识 */}
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

        {/* 中部标题 + 能力卡片 */}
        <div className="relative z-10 max-w-md">
          <h2 className="font-heading text-4xl font-semibold leading-tight text-balance text-foreground">
            用真实数据驱动电商运营对话
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-pretty text-muted-foreground">
            先配置模型、公司资料、达人/知识库或平台授权；系统会标明数据来源，只生成待审核草稿，不自动外发。
          </p>

          <div className="mt-10 grid grid-cols-2 gap-3">
            {HIGHLIGHTS.map(({ icon: Icon, label, desc }) => (
              <div
                key={label}
                className="glass-card rounded-2xl p-4"
              >
                <Icon className="size-5 text-primary" />
                <p className="mt-3 text-sm font-medium text-foreground">{label}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* 底部版权 */}
        <div className="relative z-10 text-xs text-muted-foreground">
          © 2026 AgentX · 对话式 AI 电商工作助手
        </div>
      </section>

      {/* 右侧表单区 */}
      <section className="flex w-full flex-col items-center justify-center px-6 py-12 lg:w-1/2">
        <AuthForm />
      </section>
    </main>
  );
}
