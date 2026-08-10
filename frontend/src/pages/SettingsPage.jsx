import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  User,
  Shield,
  Server,
  Database,
  Building2,
  Link2,
  Sparkles,
  Users,
  CheckCircle2,
} from 'lucide-react';
import { useAuth } from '@/lib/AuthContext';
import { cn } from '@/lib/utils';
import PlatformAuthSection from '@/components/SettingsSection/PlatformAuthSection';
import ProfileSection from './settings/ProfileSection';
import SecuritySection from './settings/SecuritySection';
import LlmConfigSection from './settings/LlmConfigSection';
import KnowledgeSection from './settings/KnowledgeSection';
import CompanyProfileSection from './settings/CompanyProfileSection';
import KolDataSection from './settings/KolDataSection';

/* ═══════════════════════════════════════════════════════════════
   设置分组
   — 合并 知识库 / 嵌入模型 / RAG 总览 为单一「知识库」入口
   ═══════════════════════════════════════════════════════════════ */
const SECTIONS = [
  { key: 'profile',   label: '个人资料',   icon: User,    desc: '头像、昵称、联系信息' },
  { key: 'security',  label: '账户安全',   icon: Shield,  desc: '密码、双因素认证' },
  { key: 'llm',       label: '大模型配置', icon: Server,  desc: '网关地址 · API Key · 限额' },
  { key: 'platformAuth', label: '平台授权', icon: Link2,  desc: '电商平台账号绑定与凭证' },
  { key: 'knowledge', label: '知识库',     icon: Database,desc: '文档 · 嵌入模型 · 系统状态' },
  { key: 'kolData',   label: '达人数据',   icon: Users,   desc: '导入 · 来源 · 搜索验证' },
  { key: 'company',   label: '公司资料',   icon: Building2,desc: '品牌信息与 RAG 上下文' },
];

const SETUP_STEPS = [
  {
    key: 'llm',
    title: '1. 配置大模型',
    desc: '先配置网关、API Key 与 Token 限额，避免聊天入口使用不可用模型。',
  },
  {
    key: 'company',
    title: '2. 填写公司资料',
    desc: '补齐品牌、类目、受众和 USP，让 Agent 有明确企业上下文。',
  },
  {
    key: 'kolData',
    title: '3. 导入达人数据',
    desc: '上传或接入真实达人库，聊天达人搜索只基于当前企业数据返回。',
  },
  {
    key: 'knowledge',
    title: '4. 建立知识库',
    desc: '导入业务文档并完成索引，知识库问题才会给出可追溯来源。',
  },
  {
    key: 'platformAuth',
    title: '5. 绑定平台授权',
    desc: '需要真实平台数据时再授权；未授权时系统会明确提示数据源不可用。',
  },
];

function SetupChecklist({ activeSection, onSelect }) {
  return (
    <section className="mb-6 rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Sparkles className="size-4" />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">上线前配置清单</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            新用户建议按顺序完成模型、公司资料、达人数据、知识库和平台授权配置；
            未连接真实数据源时，系统不会用 mock/fallback 冒充业务结果。
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-2">
        {SETUP_STEPS.map((step) => (
          <button
            key={step.key}
            type="button"
            onClick={() => onSelect(step.key)}
            className={cn(
              'flex items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
              activeSection === step.key
                ? 'border-primary bg-primary/10 text-foreground'
                : 'border-border bg-background text-foreground hover:border-primary/60'
            )}
          >
            <CheckCircle2
              className={cn(
                'mt-0.5 size-4 shrink-0',
                activeSection === step.key ? 'text-primary' : 'text-muted-foreground'
              )}
            />
            <span className="min-w-0">
              <span className="block text-xs font-semibold">{step.title}</span>
              <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                {step.desc}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════
   SettingsPage — 主页面
   ═══════════════════════════════════════════════════════════════ */
export default function SettingsPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [section, setSection] = useState('profile');
  const [isMobileNavOpen, setMobileNavOpen] = useState(false);

  // ESC 关闭移动端菜单
  useEffect(() => {
    if (!isMobileNavOpen) return undefined;
    const handle = (e) => {
      if (e.key === 'Escape') setMobileNavOpen(false);
    };
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, [isMobileNavOpen]);

  const currentSection = SECTIONS.find((s) => s.key === section) || SECTIONS[0];

  return (
    <div className="flex h-svh w-full flex-col overflow-hidden bg-background">
      {/* 顶部导航 */}
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur md:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            aria-label="返回对话"
          >
            <ArrowLeft className="size-4" />
            <span className="hidden sm:inline">返回对话</span>
          </button>
          <div className="hidden h-5 w-px bg-border sm:block" />
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <span className="font-heading text-sm font-semibold lowercase">x</span>
            </div>
            <span className="font-heading text-sm font-semibold text-foreground">
              账户设置
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {user?.username ? `已登录 · ${user.username}` : '已登录'}
          </span>
          <button
            type="button"
            onClick={() => {
              logout();
              navigate('/login');
            }}
            className="btn btn-outline h-8 px-3 text-xs"
          >
            退出
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* 左侧菜单 */}
        <aside
          className={cn(
            'fixed inset-y-0 left-0 top-14 z-20 w-64 shrink-0 border-r border-border bg-sidebar',
            'transition-transform duration-300 ease-out md:sticky md:top-14 md:h-[calc(100vh-3.5rem)] md:translate-x-0',
            isMobileNavOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
          )}
        >
          <nav className="flex h-full flex-col gap-1 p-3">
            <p className="px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              设置
            </p>
            {SECTIONS.map(({ key, label, icon: Icon, desc }) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setSection(key);
                  setMobileNavOpen(false);
                }}
                className={cn(
                  'group flex items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors',
                  section === key
                    ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                    : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60'
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg',
                    section === key
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-secondary text-muted-foreground group-hover:text-foreground'
                  )}
                >
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{label}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {desc}
                  </span>
                </span>
              </button>
            ))}
          </nav>
        </aside>

        {/* 移动端遮罩 */}
        {isMobileNavOpen && (
          <div
            className="fixed inset-0 top-14 z-10 bg-black/30 md:hidden"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
        )}

        {/* 右侧内容 */}
        <main className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">
          {/* 移动端 section 切换器 */}
          <div className="flex items-center gap-2 border-b border-border px-4 py-3 md:hidden">
            <button
              type="button"
              onClick={() => setMobileNavOpen(true)}
              className="btn btn-outline h-8 px-3 text-xs"
            >
              {currentSection.label}
            </button>
          </div>

          <div className="mx-auto w-full max-w-3xl px-6 py-6">
            {/* 标题提示 — 移动端用 */}
            <div className="mb-5 flex items-center gap-2 text-xs text-muted-foreground md:hidden">
              <Sparkles className="size-3.5 text-primary" />
              修改后请点击保存
            </div>

            <SetupChecklist
              activeSection={section}
              onSelect={(nextSection) => {
                setSection(nextSection);
                setMobileNavOpen(false);
              }}
            />

            {section === 'profile' && <ProfileSection user={user} />}
            {section === 'security' && <SecuritySection />}
            {section === 'llm' && <LlmConfigSection />}
            {section === 'platformAuth' && <PlatformAuthSection />}
            {section === 'knowledge' && <KnowledgeSection />}
            {section === 'kolData' && <KolDataSection />}
            {section === 'company' && <CompanyProfileSection />}
          </div>
        </main>
      </div>
    </div>
  );
}
