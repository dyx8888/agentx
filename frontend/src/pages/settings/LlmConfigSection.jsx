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
import {
  LLM_PROVIDERS,
  PROVIDER_BY_KEY,
  TASK_OPTIONS,
  buildProviderPayload,
  isProviderConfigured,
  modelOptionsForProvider,
  normalizePreferredTasks,
  normalizeProviderState,
  preferredTasksToInput,
} from '@/lib/llmProviders';

const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';
const LLM_STATUS_LABELS = {
  provider: '模型厂商',
  gateway: '网关地址',
  baseUrl: '网关地址',
  modelName: '模型名称',
  apiKey: 'API 密钥',
};

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
    </div>
  );
}

function ProviderCard({ provider, data, onChange, apiKeyPlaceholder }) {
  const [showKey, setShowKey] = useState(false);
  const formData = normalizeProviderState(provider, data);
  const providerModels = modelOptionsForProvider(provider, formData.modelName);
  const modelsWithUsage = providerModels.map((model) => {
    const used = formData.usage?.[model.value] ?? 0;
    const limit = formData.tpm?.[model.value] ?? model.defaultTpm;
    return { ...model, used, limit };
  });
  const totalUsed = modelsWithUsage.reduce((sum, model) => sum + model.used, 0);
  const totalLimit = modelsWithUsage.reduce((sum, model) => sum + model.limit, 0);
  const pct = totalLimit > 0 ? Math.min(100, Math.round((totalUsed / totalLimit) * 100)) : 0;
  const tone = pct >= 90 ? 'var(--destructive)' : pct >= 70 ? 'oklch(0.78 0.14 60)' : 'oklch(0.78 0.13 145)';

  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-secondary">
              <Cpu className="size-4 text-foreground/80" />
            </div>
            <h3 className="font-heading text-base font-semibold text-foreground">{provider.name}</h3>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">{provider.desc}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-medium"
            style={{ backgroundColor: `color-mix(in oklch, ${tone} 12%, transparent)`, color: tone }}
          >
            今日已用 {pct}%
          </span>
          <span className="text-[10px] text-muted-foreground">
            已用 {totalUsed.toLocaleString()} / {totalLimit.toLocaleString()} Token
          </span>
        </div>
      </div>

      <div className="mb-3 grid gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-foreground">模型厂商类型</label>
          <select
            aria-label="模型厂商类型"
            value={formData.providerType}
            onChange={(event) => onChange(provider.key, { providerType: event.target.value })}
            className="input-base h-9 text-xs"
          >
            <option value="openai_compatible">兼容 OpenAI</option>
          </select>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-background/40 px-3 py-2.5">
          <div>
            <p className="text-xs font-medium text-foreground">启用模型厂商</p>
            <p className="text-[10px] text-muted-foreground">关闭后后端会安全拒绝调用</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-label="启用模型厂商"
            aria-checked={formData.enabled}
            onClick={() => onChange(provider.key, { enabled: !formData.enabled })}
            className={cn(
              'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors',
              formData.enabled ? 'bg-primary' : 'bg-border'
            )}
          >
            <span
              className={cn(
                'inline-block size-4 rounded-full bg-card shadow-sm transition-transform',
                formData.enabled ? 'translate-x-4' : 'translate-x-0.5'
              )}
            />
          </button>
        </div>
      </div>

      <div className="mb-3 flex flex-col gap-1.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <Globe className="size-3" />
          网关地址（Base URL）
        </label>
        <input
          aria-label="网关地址"
          type="url"
          value={formData.baseUrl}
          onChange={(event) => onChange(provider.key, { baseUrl: event.target.value, gateway: event.target.value })}
          placeholder={provider.defaultGateway}
          className="input-base h-9 text-xs"
        />
      </div>

      <div className="mb-3 flex flex-col gap-1.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <Cpu className="size-3" />
          模型名称
        </label>
        <input
          aria-label="模型名称"
          list={`${provider.key}-model-options`}
          value={formData.modelName}
          onChange={(event) => onChange(provider.key, { modelName: event.target.value })}
          placeholder={provider.defaultModelName}
          className="input-base h-9 text-xs"
        />
        <datalist id={`${provider.key}-model-options`}>
          {providerModels.map((model) => (
            <option key={model.value} value={model.value}>{model.label}</option>
          ))}
        </datalist>
      </div>

      <div className="mb-3 flex flex-col gap-1.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <KeyRound className="size-3" />
          API 密钥
        </label>
        <div className="relative">
          <input
            aria-label="API 密钥"
            type={showKey ? 'text' : 'password'}
            value={formData.apiKey}
            onChange={(event) => onChange(provider.key, { apiKey: event.target.value })}
            placeholder={apiKeyPlaceholder || provider.placeholder}
            className="input-base h-9 w-full pr-9 text-xs"
            autoComplete="off"
          />
          <button
            type="button"
            onClick={() => setShowKey((value) => !value)}
            aria-label={showKey ? '隐藏密钥' : '显示密钥'}
            className="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
          </button>
        </div>
      </div>

      <div className="mb-3 flex flex-col gap-1.5">
        <label className="text-xs font-medium text-foreground">适用任务</label>
        <input
          aria-label="适用任务"
          value={preferredTasksToInput(formData.preferredTasks)}
          onChange={(event) => onChange(provider.key, { preferredTasks: normalizePreferredTasks(event.target.value) })}
          placeholder="chat, analysis"
          className="input-base h-9 text-xs"
        />
        <div className="flex flex-wrap gap-1.5">
          {TASK_OPTIONS.map((task) => {
            const selected = formData.preferredTasks.includes(task.value);
            return (
              <button
                key={task.value}
                type="button"
                onClick={() => {
                  const next = selected
                    ? formData.preferredTasks.filter((item) => item !== task.value)
                    : [...formData.preferredTasks, task.value];
                  onChange(provider.key, { preferredTasks: next });
                }}
                className={cn(
                  'rounded-full border px-2 py-0.5 text-[10px] transition-colors',
                  selected ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'
                )}
              >
                {task.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2.5">
        <label className="flex items-center gap-1 text-xs font-medium text-foreground">
          <Hash className="size-3" />
          每日 Token 限额
        </label>
        {modelsWithUsage.map((model) => {
          const modelPct = model.limit > 0 ? Math.min(100, Math.round((model.used / model.limit) * 100)) : 0;
          const modelTone = modelPct >= 90 ? 'var(--destructive)' : modelPct >= 70 ? 'oklch(0.78 0.14 60)' : 'oklch(0.78 0.13 145)';
          return (
            <div key={model.value} className="rounded-lg border border-border bg-background/40 p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-foreground">{model.label}</span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {model.used.toLocaleString()} / {model.limit.toLocaleString()}
                </span>
              </div>
              <div className="mb-1.5 h-1 w-full overflow-hidden rounded-full" style={{ backgroundColor: 'var(--secondary)' }}>
                <div className="h-full rounded-full transition-all" style={{ width: `${modelPct}%`, backgroundColor: modelTone }} />
              </div>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  min="0"
                  step="10000"
                  value={model.limit}
                  onChange={(event) =>
                    onChange(provider.key, {
                      tpm: { ...(formData.tpm || {}), [model.value]: Number(event.target.value) || 0 },
                    })
                  }
                  className="input-base h-7 w-32 text-[11px]"
                  aria-label={`${model.label} 限额`}
                />
                <span className="text-[11px] text-muted-foreground">tokens / 日</span>
              </div>
            </div>
          );
        })}
      </div>

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
          aria-label="超额提醒"
          aria-checked={formData.warnAt90}
          onClick={() => onChange(provider.key, { warnAt90: !formData.warnAt90 })}
          className={cn(
            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors',
            formData.warnAt90 ? 'bg-primary' : 'bg-border'
          )}
        >
          <span
            className={cn(
              'inline-block size-4 rounded-full bg-card shadow-sm transition-transform',
              formData.warnAt90 ? 'translate-x-4' : 'translate-x-0.5'
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
  const [maskedKeys, setMaskedKeys] = useState({});
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [llmStatus, setLlmStatus] = useState(null);
  const [toast, setToast] = useState(null);

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 2400);
  };

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
          const provider = PROVIDER_BY_KEY[key] || { key };
          next[key] = normalizeProviderState(provider, { ...cfg, apiKey: '' });
          const maskedKey = cfg.apiKeyMasked || cfg.api_key_masked || '';
          if (maskedKey) nextMasked[key] = maskedKey;
        }
        if (Object.keys(next).length === 0) {
          try {
            localStorage.removeItem('llm_providers');
          } catch { /* noop */ }
        }
        const configuredKey =
          LLM_PROVIDERS.find((provider) => isProviderConfigured(remote[provider.key]))?.key ||
          Object.keys(remote).find((key) => isProviderConfigured(remote[key]));
        if (configuredKey) {
          setActiveKey(configuredKey);
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
      [key]: { ...normalizeProviderState(PROVIDER_BY_KEY[key] || { key }, prev[key] || {}), ...patch },
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
      const payload = Object.fromEntries(
        Object.entries(providers).map(([key, value]) => [key, buildProviderPayload(key, value)])
      );
      const data = await updateLlmConfig(companyId, payload);
      const remote = data?.providers || {};
      const nextMasked = {};
      const next = {};
      for (const [key, cfg] of Object.entries(remote)) {
        const provider = PROVIDER_BY_KEY[key] || { key };
        next[key] = normalizeProviderState(provider, { ...cfg, apiKey: '' });
        const maskedKey = cfg.apiKeyMasked || cfg.api_key_masked || '';
        if (maskedKey) nextMasked[key] = maskedKey;
      }
      setProviders((prev) => {
        const cleared = Object.fromEntries(
          Object.entries(prev).map(([key, value]) => [
            key,
            { ...normalizeProviderState(PROVIDER_BY_KEY[key] || { key }, value), apiKey: '' },
          ])
        );
        return { ...cleared, ...next };
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

  const activeProvider = LLM_PROVIDERS.find((provider) => provider.key === activeKey) || LLM_PROVIDERS[0];
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
          配置模型厂商类型、网关地址、模型名称、API 密钥、任务路由与 Token 限额。
        </p>
      </header>

      {llmStatus?.setup_required && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">大模型配置未完整，系统可能安全拒绝调用或使用服务端全局配置。</p>
            {missingLlmLabels.length > 0 && (
              <p>待补全：{missingLlmLabels.join('、')}</p>
            )}
          </div>
        </div>
      )}

      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          选择模型厂商
        </p>
        <div className="flex flex-wrap gap-2">
          {LLM_PROVIDERS.map((provider) => {
            const isActive = provider.key === activeKey;
            const configured = isProviderConfigured(providers[provider.key]);
            return (
              <button
                key={provider.key}
                type="button"
                onClick={() => setActiveKey(provider.key)}
                aria-pressed={isActive}
                className={cn(
                  'group inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-all',
                  isActive
                    ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                    : 'border-border bg-card text-foreground hover:border-primary/40 hover:bg-accent'
                )}
              >
                <Cpu className={cn('size-3.5', isActive ? 'text-primary-foreground' : 'text-primary')} />
                <span>{provider.name}</span>
                {configured && (
                  <span
                    className={cn(
                      'rounded-full px-1.5 py-0.5 text-[10px]',
                      isActive
                        ? 'bg-primary-foreground/20 text-primary-foreground'
                        : 'bg-primary/10 text-primary'
                    )}
                  >
                    已配置
                  </span>
                )}
                {isActive && <Check className="size-3.5" />}
              </button>
            );
          })}
        </div>
      </div>

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

      {toast && (
        <div role="status" aria-live="polite" className="pointer-events-none fixed right-4 top-4 z-[200] animate-fade-in-up">
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
