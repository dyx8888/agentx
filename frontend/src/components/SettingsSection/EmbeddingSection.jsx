import { useState, useEffect, useCallback } from 'react';
import {
  HardDrive,
  Globe,
  KeyRound,
  Hash,
  Link as LinkIcon,
  Eye,
  EyeOff,
  Check,
  AlertTriangle,
  Loader2,
  Save,
  Zap,
  Cpu,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  getEmbeddingConfig,
  updateEmbeddingConfig,
  testEmbeddingConnection,
} from '@/api/rag';

/* ═══════════════════════════════════════════════════════════════
   嵌入模式定义 — 与后端 EmbeddingMode 枚举对齐
   每个模式带预设值（base_url / model_name），减少用户填写成本
   ═══════════════════════════════════════════════════════════════ */
const EMBEDDING_MODES = [
  {
    value: 'local',
    label: '本地模型',
    desc: '免费，~500MB 内存',
    icon: HardDrive,
    tint: 'bg-macaron-mint',
  },
  {
    value: 'api_siliconflow',
    label: '硅基流动 API',
    desc: '免费额度，推荐',
    icon: Globe,
    tint: 'bg-macaron-pink',
    preset: {
      api_base_url: 'https://api.siliconflow.cn/v1',
      model_name: 'BAAI/bge-large-zh-v1.5',
    },
  },
  {
    value: 'api_deepseek',
    label: 'DeepSeek API',
    desc: '按量计费',
    icon: Globe,
    tint: 'bg-macaron-yellow',
    preset: {
      api_base_url: 'https://api.deepseek.com/v1',
      model_name: 'deepseek-embedding',
    },
  },
  {
    value: 'api_openai',
    label: 'OpenAI API',
    desc: '按量计费',
    icon: Globe,
    tint: 'bg-macaron-rose',
    preset: {
      api_base_url: 'https://api.openai.com/v1',
      model_name: 'text-embedding-3-small',
    },
  },
];

const MODE_MAP = Object.fromEntries(EMBEDDING_MODES.map((m) => [m.value, m]));
const isApiMode = (mode) => mode && mode.startsWith('api_');

/* ═══════════════════════════════════════════════════════════════
   通用字段 — label 在上，input 在下（遵守设计约定）
   ═══════════════════════════════════════════════════════════════ */
function Field({ label, hint, children, icon: Icon }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="flex items-center gap-1.5 text-sm font-medium text-foreground">
        {Icon && <Icon className="size-3.5 text-muted-foreground" />}
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] leading-relaxed text-muted-foreground">{hint}</p>}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   嵌入模式选择 + API 配置 + 测试 / 保存
   ═══════════════════════════════════════════════════════════════ */
export default function EmbeddingSection({ onModeChange }) {
  const [mode, setMode] = useState('local');
  const [apiBaseUrl, setApiBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelName, setModelName] = useState('');
  const [apiKeyMasked, setApiKeyMasked] = useState(''); // 后端返回的脱敏 key，仅展示
  const [showKey, setShowKey] = useState(false);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // {ok, dims?, latency_ms?, message?, error?}
  const [error, setError] = useState('');

  /* ── 页面加载时回填配置 ── */
  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getEmbeddingConfig();
      setMode(data.mode || 'local');
      setApiBaseUrl(data.api_base_url || '');
      setModelName(data.model_name || '');
      setApiKeyMasked(data.api_key_masked || '');
      // 已有脱敏 key 时清空明文输入框，避免误覆盖
      setApiKey('');
      onModeChange?.(data.mode || 'local');
    } catch (err) {
      setError(err.response?.data?.detail || '加载嵌入配置失败');
    } finally {
      setLoading(false);
    }
  }, [onModeChange]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  /* ── 模式切换：切到 API 时若字段空则回填预设 ── */
  const handleModeChange = (nextMode) => {
    setMode(nextMode);
    setTestResult(null); // 清空上次测试结果
    const preset = MODE_MAP[nextMode]?.preset;
    if (preset) {
      // 仅在字段为空时回填预设，不覆盖用户已输入的值
      if (!apiBaseUrl) setApiBaseUrl(preset.api_base_url);
      if (!modelName) setModelName(preset.model_name);
    }
    onModeChange?.(nextMode);
  };

  /* ── 测试连接 ── */
  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    setError('');
    try {
      const params = {
        mode,
        api_base_url: apiBaseUrl,
        api_key: apiKey, // 用当前输入的明文 key 测试（不存档）
        model_name: modelName,
      };
      const result = await testEmbeddingConnection(params);
      setTestResult(result);
    } catch (err) {
      setTestResult({
        ok: false,
        error: err.response?.data?.detail || err.message || '测试失败',
      });
    } finally {
      setTesting(false);
    }
  };

  /* ── 保存配置 ── */
  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const payload = { mode };
      if (isApiMode(mode)) {
        payload.api_base_url = apiBaseUrl;
        payload.model_name = modelName;
        // 仅在用户输入了新明文 key 时才提交，避免用空串覆盖已存的 key
        if (apiKey) payload.api_key = apiKey;
      }
      await updateEmbeddingConfig(payload);
      setSaved(true);
      setApiKey(''); // 保存后清空明文 key
      setTimeout(() => setSaved(false), 1800);
      // 重新拉取配置以刷新脱敏 key
      await loadConfig();
    } catch (err) {
      setError(err.response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const activeMode = MODE_MAP[mode] || EMBEDDING_MODES[0];
  const ActiveIcon = activeMode.icon;

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        加载嵌入配置…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* 错误提示 */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-2.5 text-xs text-foreground/80">
          <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
          {error}
          <button
            type="button"
            onClick={() => setError('')}
            className="ml-auto text-muted-foreground hover:text-foreground"
          >
            关闭
          </button>
        </div>
      )}

      {/* ── 嵌入模式选择 ── */}
      <Field
        label="嵌入模式"
        hint="本地模型零成本但占用内存；API 模式响应更快，按调用量计费"
        icon={Cpu}
      >
        <div className="relative">
          <div
            className={cn(
              'pointer-events-none absolute left-3 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-md',
              activeMode.tint
            )}
            aria-hidden="true"
          >
            <ActiveIcon className="size-3.5 text-foreground/80" />
          </div>
          <select
            value={mode}
            onChange={(e) => handleModeChange(e.target.value)}
            className="input-base h-10 w-full cursor-pointer pl-11 pr-8 text-sm appearance-none bg-card"
          >
            {EMBEDDING_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}（{m.desc}）
              </option>
            ))}
          </select>
          <svg
            className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </div>
      </Field>

      {/* ── 本地模式：提示文字 ── */}
      {!isApiMode(mode) && (
        <div className="flex items-start gap-3 rounded-2xl border border-border bg-card/60 p-4">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-macaron-yellow">
            <AlertTriangle className="size-4 text-foreground/80" />
          </div>
          <div className="flex-1 text-xs leading-relaxed text-muted-foreground">
            <p className="font-medium text-foreground">本地模式说明</p>
            <p className="mt-1">
              选择「本地」需约 <span className="font-medium text-foreground">500MB 内存</span>，
              首次启动下载模型约 <span className="font-medium text-foreground">2 分钟</span>。
              嵌入向量在本地计算，无需联网，零 API 成本。
            </p>
            <p className="mt-1.5">
              选择「API」按调用量计费，响应更快，适合高并发场景。
            </p>
          </div>
        </div>
      )}

      {/* ── API 模式：三个输入框 ── */}
      {isApiMode(mode) && (
        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-4">
          {/* API Key */}
          <Field label="API Key" icon={KeyRound}>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={apiKeyMasked ? `当前已保存：${apiKeyMasked}（留空则不修改）` : 'sk-...'}
                className="input-base h-10 w-full pr-9 text-sm"
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                aria-label={showKey ? '隐藏密钥' : '显示密钥'}
                className="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
              </button>
            </div>
          </Field>

          {/* 模型名称 */}
          <Field
            label="模型名称"
            hint="向量维度由模型决定，切换模型后新文档将使用新模型向量化"
            icon={Hash}
          >
            <input
              type="text"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder={activeMode.preset?.model_name || 'BAAI/bge-large-zh-v1.5'}
              className="input-base h-10 text-sm"
            />
          </Field>

          {/* Base URL */}
          <Field
            label="Base URL"
            hint="OpenAI 兼容接口基址，后端会自动拼接 /embeddings 路径"
            icon={LinkIcon}
          >
            <input
              type="url"
              value={apiBaseUrl}
              onChange={(e) => setApiBaseUrl(e.target.value)}
              placeholder={activeMode.preset?.api_base_url || 'https://api.siliconflow.cn/v1'}
              className="input-base h-10 text-sm"
            />
          </Field>

          {/* 测试结果 */}
          {testResult && (
            <div
              className={cn(
                'flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-xs',
                testResult.ok
                  ? 'border-macaron-mint bg-macaron-mint/5 text-foreground/80'
                  : 'border-macaron-rose bg-macaron-rose/5 text-foreground/80'
              )}
            >
              {testResult.ok ? (
                <>
                  <Check className="size-3.5 shrink-0" style={{ color: 'oklch(0.7 0.09 145)' }} />
                  <span>
                    {testResult.message || '连接成功'} · 向量维度{' '}
                    <span className="font-medium text-foreground">{testResult.dims}</span>
                    {' · 耗时 '}
                    <span className="font-medium text-foreground">{testResult.latency_ms}ms</span>
                  </span>
                </>
              ) : (
                <>
                  <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
                  <span>连接失败：{testResult.error}</span>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── 操作按钮 ── */}
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {isApiMode(mode)
            ? '保存后立即热切换，无需重启服务。'
            : '本地模式无需额外配置，直接保存即可。'}
        </p>
        <div className="flex items-center gap-2">
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs text-foreground">
              <Check className="size-3.5" style={{ color: 'oklch(0.7 0.09 145)' }} />
              已保存
            </span>
          )}
          {isApiMode(mode) && (
            <button
              type="button"
              onClick={handleTest}
              disabled={testing || saving}
              className="btn btn-outline h-10 px-4 text-sm"
            >
              {testing ? <Loader2 className="size-4 animate-spin" /> : <Zap className="size-4" />}
              测试连接
            </button>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || testing}
            className="btn btn-primary h-10 px-4 text-sm"
          >
            {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存配置
          </button>
        </div>
      </div>
    </div>
  );
}
