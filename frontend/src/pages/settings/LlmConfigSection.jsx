import { useState, useEffect } from 'react';
import {
  Cpu,
  Check,
  Loader2,
  Save,
  Globe,
  KeyRound,
  Hash,
  AlertTriangle,
  Eye,
  EyeOff,
} from 'lucide-react';
import { useAuth } from '@/lib/AuthContext';
import { cn } from '@/lib/utils';
import { getLlmConfig, updateLlmConfig } from '@/api/llmConfig';

// 状态色（保存成功提示）
const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';
const LLM_STATUS_LABELS = {
  provider: '\u6a21\u578b\u5382\u5546',
  gateway: '\u7f51\u5173\u5730\u5740',
  apiKey: 'API Key',
};

/* ═══════════════════════════════════════════════════════════════
   3) 大模型配置 — 模型按钮选择 + 配置卡片
   - 顶部一行 provider 按钮
   - 点击后展示该 provider 的配置（网关 / API Key / 限额 / 超额提醒）
   ═══════════════════════════════════════════════════════════════ */

const LLM_PROVIDERS = [
  {
    key: 'deepseek',
    name: 'DeepSeek',
    desc: '深度求索 — 中文场景优秀',
    defaultGateway: 'https://api.deepseek.com/v1',
    models: [
      { value: 'deepseek-chat',  label: 'DeepSeek-V3',     defaultTpm: 200000 },
      { value: 'deepseek-coder', label: 'DeepSeek-Coder',  defaultTpm: 100000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'openai',
    name: 'OpenAI',
    desc: 'GPT-4o 系列 — 多模态与推理',
    defaultGateway: 'https://api.openai.com/v1',
    models: [
      { value: 'gpt-4o',      label: 'GPT-4o',      defaultTpm: 200000 },
      { value: 'gpt-4o-mini', label: 'GPT-4o mini', defaultTpm: 500000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'anthropic',
    name: 'Anthropic',
    desc: 'Claude 系列 — 长文本与代码',
    defaultGateway: 'https://api.anthropic.com/v1',
    models: [
      { value: 'claude-3-5-sonnet', label: 'Claude 3.5 Sonnet', defaultTpm: 100000 },
    ],
    placeholder: 'sk-ant-...',
  },
];

/* ═══════════════════════════════════════════════════════════════
   ProviderCardSkeleton — 加载中骨架屏（替代简单 spinner）
   ═══════════════════════════════════════════════════════════════ */
function ProviderCardSkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="skeleton size-8 rounded-lg" />
            <div className="skeleton h-4 w-24 rounded-md" />
          </div>
          <div className="skeleton h-3 w-40 rounded-md" />
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="skeleton h-4 w-20 rounded-full" />
          <div className="skeleton h-3 w-28 rounded-md" />
        </div>
      </div>
      <div className="mb-3 flex flex-col gap-1.5">
        <div className="skeleton h-3 w-16 rounded-md" />
        <div className="skeleton h-9 w-full rounded-md" />
      </div>
      <div className="mb-3 flex flex-col gap-1.5">
        <div className="skeleton h-3 w-16 rounded-md" />
        <div className="skeleton h-9 w-full rounded-md" />
      </div>
      <div className="mt-4 flex flex-col gap-2.5">
        <div className="skeleton h-3 w-32 rounded-md" />
        <div className="skeleton h-16 w-full rounded-lg" />
        <div className="skeleton h-16 w-full rounded-lg" />
      </div>
    </div>
  );
}

function ProviderCard({ provider, data, onChange, apiKeyPlaceholder }) {
  const [showKey, setShowKey] = useState(false);
  const modelsWithUsage = provider.models.map((m) => {
    const used = data.usage?.[m.value] ?? 0;
    const limit = data.tpm?.[m.value] ?? m.defaultTpm;
    return { ...m, used, limit };
  });
  const totalUsed = modelsWithUsage.reduce((s, m) => s + m.used, 0);
  const totalLimit = modelsWithUsage.reduce((s, m) => s + m.limit, 0);
  const pct = totalLimit > 0 ? Math.min(100, Math.round((totalUsed / totalLimit) * 100)) : 0;
  const tone =
    pct >= 90 ? 'var(--destructive)' :
    pct >= 70 ? 'oklch(0.78 0.14 60)'  :
                'oklch(0.78 0.13 145)';

  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-secondary">
              <Cpu className="size-4 text-foreground/80" />
            </div>
            <h3 className="font-heading text-base font-semibold text-foreground">
              {provider.name}
            </h3>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">{provider.desc}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-medium"
            style={{
              backgroundColor: `color-mix(in oklch, ${tone} 12%, transparent)`,
              color: tone,
            }}
          >
            今日已用 {pct}%
          </span>
          <span className="text-[10px] text-muted-foreground">
            {totalUsed.toLocaleString()} / {totalLimit.toLocaleString()} tokens
          </span>
        </div>
      </div>

      {/* 网关地址 */}
      <div className="mb-3 flex flex-col gap-1.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <Globe className="size-3" />
          网关地址
        </label>
        <input
          type="url"
          value={data.gateway ?? provider.defaultGateway}
          onChange={(e) => onChange(provider.key, { gateway: e.target.value })}
          placeholder={provider.defaultGateway}
          className="input-base h-9 text-xs"
        />
      </div>

      {/* API Key */}
      <div className="mb-3 flex flex-col gap-1.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <KeyRound className="size-3" />
          API Key
        </label>
        <div className="relative">
          <input
            type={showKey ? 'text' : 'password'}
            value={data.apiKey ?? ''}
            onChange={(e) => onChange(provider.key, { apiKey: e.target.value })}
            placeholder={apiKeyPlaceholder || provider.placeholder}
            className="input-base h-9 w-full pr-9 text-xs"
            autoComplete="off"
          />
          <button
            type="button"
            onClick={() => setShowKey((v) => !v)}
            aria-label={showKey ? '隐藏' : '显示'}
            className="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
          </button>
        </div>
      </div>

      {/* 各模型限额 */}
      <div className="mt-4 flex flex-col gap-2.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <Hash className="size-3" />
          模型与每日 Token 限额
        </label>
        {modelsWithUsage.map((m) => {
          const mpct = m.limit > 0 ? Math.min(100, Math.round((m.used / m.limit) * 100)) : 0;
          const mtone =
            mpct >= 90 ? 'var(--destructive)' :
            mpct >= 70 ? 'oklch(0.78 0.14 60)'  :
                        'oklch(0.78 0.13 145)';
          return (
            <div key={m.value} className="rounded-lg border border-border bg-background/40 p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-foreground">{m.label}</span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {m.used.toLocaleString()} / {m.limit.toLocaleString()}
                </span>
              </div>
              <div
                className="mb-1.5 h-1 w-full overflow-hidden rounded-full"
                style={{ backgroundColor: 'var(--secondary)' }}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${mpct}%`, backgroundColor: mtone }}
                />
              </div>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  min="0"
                  step="10000"
                  value={m.limit}
                  onChange={(e) =>
                    onChange(provider.key, {
                      tpm: { ...(data.tpm || {}), [m.value]: Number(e.target.value) || 0 },
                    })
                  }
                  className="input-base h-7 w-32 text-[11px]"
                  aria-label={`${m.label} 限额`}
                />
                <span className="text-[11px] text-muted-foreground">tokens / 日</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 超标警告开关 */}
      <div className="mt-4 flex items-center justify-between rounded-lg bg-background/40 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <AlertTriangle className="size-3.5 text-foreground/70" />
          <div>
            <p className="text-xs font-medium text-foreground">超额提醒</p>
            <p className="text-[10px] text-muted-foreground">达到 90% 时站内通知</p>
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={data.warnAt90 ?? true}
          onClick={() => onChange(provider.key, { warnAt90: !(data.warnAt90 ?? true) })}
          className={cn(
            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors',
            (data.warnAt90 ?? true) ? 'bg-primary' : 'bg-border'
          )}
        >
          <span
            className={cn(
              'inline-block size-4 rounded-full bg-card shadow-sm transition-transform',
              (data.warnAt90 ?? true) ? 'translate-x-4' : 'translate-x-0.5'
            )}
          />
        </button>
      </div>
    </div>
  );
}

export default function LlmConfigSection() {
  const { user } = useAuth();
  const companyId = user?.company_id ? String(user.company_id) : '';
  const [activeKey, setActiveKey] = useState(LLM_PROVIDERS[0].key);
  const [providers, setProviders] = useState({});
  // 单独保存后端返回的脱敏 key（用作 placeholder 显示，不会进入提交体）
  const [maskedKeys, setMaskedKeys] = useState({});
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [llmStatus, setLlmStatus] = useState(null);
  // toast：保存成功 / 失败时浮层提示（无第三方 toast 库，用 setTimeout 自实现）
  const [toast, setToast] = useState(null); // null | { type: 'success' | 'error', message: string }

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 2400);
  };

  // 加载：先调 API；为兼容旧版本，若 API 返回空则回退读取 localStorage('llm_providers')（deprecated）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      if (!companyId) {
        setProviders({});
        setMaskedKeys({});
        setLlmStatus({
          status: 'missing_company',
          setup_required: true,
          missing_required: ['company_id'],
        });
        setError('当前账号未关联公司，无法加载大模型配置');
        setLoading(false);
        return;
      }
      try {
        const data = await getLlmConfig(companyId);
        if (cancelled) return;
        const remote = data?.providers || {};
        const next = {};
        const nextMasked = {};
        for (const [key, cfg] of Object.entries(remote)) {
          next[key] = {
            gateway: cfg.gateway || '',
            apiKey: '',  // 输入框留空，避免覆盖
            tpm: cfg.tpm || {},
            warnAt90: cfg.warnAt90 ?? true,
          };
          if (cfg.apiKeyMasked) nextMasked[key] = cfg.apiKeyMasked;
        }
        // 旧 localStorage 迁移（deprecated）：仅在 API 返回为空时使用一次
        if (Object.keys(next).length === 0) {
          try {
            const raw = localStorage.getItem('llm_providers');
            if (raw) {
              const legacy = JSON.parse(raw);
              if (legacy && typeof legacy === 'object') {
                for (const [k, v] of Object.entries(legacy)) {
                  next[k] = {
                    gateway: v.gateway || '',
                    apiKey: '',  // 不复制明文 key，引导用户重新输入
                    tpm: v.tpm || {},
                    warnAt90: v.warnAt90 ?? true,
                  };
                  // 若旧数据已有 apiKey，提示用户原值已弃用，需重新输入
                  if (v.apiKey) nextMasked[k] = '****（旧值未迁移，请重新输入）';
                }
              }
            }
          } catch { /* noop */ }
        }
        setProviders(next);
        setMaskedKeys(nextMasked);
        setLlmStatus({
          status: data?.status || 'not_configured',
          setup_required: data?.setup_required ?? Object.keys(remote).length === 0,
          missing_required: data?.missing_required || [],
        });
      } catch (err) {
        if (!cancelled) setError(err?.message || '加载配置失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [companyId]);

  const handleChange = (key, patch) => {
    setProviders((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), ...patch },
    }));
  };

  const handleSave = async () => {
    if (!companyId) {
      const msg = '当前账号未关联公司，无法保存大模型配置';
      setError(msg);
      showToast('error', msg);
      return;
    }
    setSaving(true);
    setError('');
    try {
      // 整份配置提交：apiKey 为空表示保留原值
      const payload = Object.fromEntries(
        Object.entries(providers).map(([k, v]) => [
          k,
          {
            gateway: v.gateway || '',
            apiKey: v.apiKey || '',
            tpm: v.tpm || {},
            warnAt90: v.warnAt90 ?? true,
          },
        ])
      );
      const data = await updateLlmConfig(companyId, payload);
      // 用响应刷新脱敏 key + 清空输入框
      const remote = data?.providers || {};
      const nextMasked = {};
      const next = {};
      for (const [k, cfg] of Object.entries(remote)) {
        next[k] = {
          gateway: cfg.gateway || '',
          apiKey: '',
          tpm: cfg.tpm || {},
          warnAt90: cfg.warnAt90 ?? true,
        };
        if (cfg.apiKeyMasked) nextMasked[k] = cfg.apiKeyMasked;
      }
      // 保留前端未提交的 provider（如未在响应中返回）
      setProviders((prev) => {
        const merged = { ...next };
        for (const [k, v] of Object.entries(prev)) {
          if (!merged[k]) merged[k] = v;
        }
        return merged;
      });
      setMaskedKeys((prev) => ({ ...prev, ...nextMasked }));
      setLlmStatus({
        status: data?.status || 'not_configured',
        setup_required: data?.setup_required ?? Object.keys(remote).length === 0,
        missing_required: data?.missing_required || [],
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      showToast('success', '配置已保存');
    } catch (err) {
      const msg = err?.message || '保存失败';
      setError(msg);
      showToast('error', msg);
    } finally {
      setSaving(false);
    }
  };

  const activeProvider = LLM_PROVIDERS.find((p) => p.key === activeKey) || LLM_PROVIDERS[0];
  const missingLlmLabels = (llmStatus?.missing_required || []).map(
    (field) => LLM_STATUS_LABELS[field] || field
  );

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          大模型配置
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          选择模型厂商并配置网关地址、API Key 与每日 Token 限额
        </p>
      </header>

      {llmStatus?.setup_required && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">{'\u5927\u6a21\u578b\u914d\u7f6e\u672a\u5b8c\u6574\uff0c\u7cfb\u7edf\u53ef\u80fd\u4f1a\u4f9d\u8d56\u5168\u5c40\u73af\u5883\u53d8\u91cf\u6216\u8c03\u7528\u5931\u8d25\u3002'}</p>
            {missingLlmLabels.length > 0 && (
              <p>{'\u5f85\u8865\u5168\uff1a'}{missingLlmLabels.join('\u3001')}</p>
            )}
          </div>
        </div>
      )}


      {/* 模型厂商按钮组 */}
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          选择模型厂商
        </p>
        <div className="flex flex-wrap gap-2">
          {LLM_PROVIDERS.map((p) => {
            const isActive = p.key === activeKey;
            return (
              <button
                key={p.key}
                type="button"
                onClick={() => setActiveKey(p.key)}
                aria-pressed={isActive}
                className={cn(
                  'group inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-all',
                  isActive
                    ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                    : 'border-border bg-card text-foreground hover:border-primary/40 hover:bg-accent'
                )}
              >
                <Cpu className={cn('size-3.5', isActive ? 'text-primary-foreground' : 'text-primary')} />
                <span>{p.name}</span>
                {isActive && <Check className="size-3.5" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* 当前选中厂商的配置卡片 */}
      {loading ? (
        <ProviderCardSkeleton />
      ) : (
        <ProviderCard
          provider={activeProvider}
          data={providers[activeProvider.key] || {}}
          onChange={handleChange}
          apiKeyPlaceholder={maskedKeys[activeProvider.key] || ''}
        />
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          <AlertTriangle className="size-3.5" />
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        {saved && (
          <span className="inline-flex items-center gap-1 text-xs text-foreground">
            <Check className="size-3.5" style={{ color: SUCCESS_COLOR }} />
            已保存
          </span>
        )}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || loading}
          className="btn btn-primary h-10 px-4"
        >
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          保存配置
        </button>
      </div>

      {/* Toast 浮层：保存成功 / 失败提示 */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed right-4 top-4 z-[200] animate-fade-in-up"
        >
          <div
            className={cn(
              'pointer-events-auto flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium shadow-lg',
              toast.type === 'success'
                ? 'border-macaron-mint/40 bg-macaron-mint/20 text-foreground'
                : 'border-macaron-pink/40 bg-macaron-pink/20 text-foreground'
            )}
          >
            {toast.type === 'success' ? (
              <Check className="size-4 text-macaron-mint" />
            ) : (
              <AlertTriangle className="size-4 text-macaron-pink" />
            )}
            <span>{toast.message}</span>
          </div>
        </div>
      )}
    </div>
  );
}
