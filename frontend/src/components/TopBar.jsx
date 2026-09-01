import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Zap,
  Check,
  PanelRight,
  Sparkles,
  ChevronDown,
  Activity,
  Brain,
  AlertTriangle,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/lib/AuthContext';
import { getTodayCost, getCostSummary } from '@/api/costs';
import { getEmbeddingConfig } from '@/api/rag';
import { getLlmConfig } from '@/api/llmConfig';

/* ═══════════════════════════════════════════════════════════════
   模型列表 — 沿用项目后端支持的模型
   ═══════════════════════════════════════════════════════════════ */
const MODEL_OPTIONS = [
  { value: 'glm-5.2', label: 'GLM-5.2', provider: 'zhipu' },
  { value: 'deepseek-chat', label: 'DeepSeek-V3', provider: 'deepseek' },
  { value: 'deepseek-coder', label: 'DeepSeek-Coder', provider: 'deepseek' },
  { value: 'gpt-4o', label: 'GPT-4o', provider: 'openai' },
  { value: 'gpt-4o-mini', label: 'GPT-4o mini', provider: 'openai' },
  { value: 'claude-3-5-sonnet', label: 'Claude 3.5', provider: 'anthropic' },
];

const PROVIDER_LABELS = {
  zhipu: '智谱',
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  custom_proxy: '自定义中转站',
};

function isProviderConfigured(providerConfig) {
  if (!providerConfig || providerConfig.enabled === false) return false;
  const gateway = providerConfig.gateway || providerConfig.baseUrl;
  const maskedKey = providerConfig.apiKeyMasked || providerConfig.api_key_masked;
  return Boolean(gateway && maskedKey);
}

function getProviderLabel(providerKey) {
  return PROVIDER_LABELS[providerKey] || providerKey;
}

/* ═══════════════════════════════════════════════════════════════
   嵌入模式标签 — 变更① T1.8：与后端 EmbeddingMode 枚举对齐
   TopBar 显示模式名称而非模型文件名
   ═══════════════════════════════════════════════════════════════ */
const EMBEDDING_MODE_LABELS = {
  local: '本地模型',
  api_siliconflow: '硅基流动 API',
  api_deepseek: 'DeepSeek API',
  api_openai: 'OpenAI API',
};

/* ═══════════════════════════════════════════════════════════════
   嵌入模型列表 — 用于本地模式下的模型快速切换
   真实场景应来自后端 /api/rag/embedding/models 接口
   ═══════════════════════════════════════════════════════════════ */
const EMBEDDING_OPTIONS = [
  { value: 'bge-large-zh', label: 'BGE-Large-ZH', desc: '中文场景 · 1024 维' },
  { value: 'bge-m3',       label: 'BGE-M3',       desc: '多语言 · 1024 维' },
  { value: 'm3e-large',    label: 'M3E-Large',    desc: '中文 · 1024 维' },
  { value: 'e5-large-v2',  label: 'E5-Large-v2',  desc: '英文场景 · 1024 维' },
];

/* ═══════════════════════════════════════════════════════════════
   Token 消耗 — 真实数据
   数据源：GET /api/admin/costs/today + GET /api/admin/costs/summary?days=1
   非 admin 用户不渲染入口，也不调用 admin 成本接口。
   ═══════════════════════════════════════════════════════════════ */

// Macaron 调色板（按模型分布着色）
const MACARON_COLORS = [
  'oklch(0.78 0.14 230)',  // 蓝灰
  'oklch(0.80 0.13 145)',  // 薄荷绿
  'oklch(0.80 0.10 60)',   // 杏黄
  'oklch(0.80 0.10 340)',  // 蜜桃粉
  'oklch(0.78 0.14 280)',  // 薰衣草
  'oklch(0.80 0.13 200)',  // 雾青
];

// 今日 Token 软上限默认值；运行时从 /api/admin/companies/{cid}/llm-config 的 tpm 汇总覆盖
const DEFAULT_TOKEN_LIMIT = 100000;

function formatTokens(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function formatCost(c) {
  if (c == null) return '—';
  if (c < 0.01) return c.toFixed(4);
  return c.toFixed(2);
}

function computeResetIn() {
  const now = new Date();
  const midnight = new Date(now);
  midnight.setHours(24, 0, 0, 0);
  const diff = midnight - now;
  const hours = Math.floor(diff / 3600000);
  const mins = Math.floor((diff % 3600000) / 60000);
  return `今日剩余 ${hours} 小时 ${mins} 分钟`;
}

/* ═══════════════════════════════════════════════════════════════
   TopBar — 模型 + 嵌入模型 + Token 消耗 + 文件面板
   完全对齐 v0 components/chat/top-bar.tsx
   ═══════════════════════════════════════════════════════════════ */
export default function TopBar({
  model,
  setModel,
  embedding,
  setEmbedding,
  filesOpen,
  onToggleFiles,
  conversationTitle,
}) {
  const [modelOpen, setModelOpen] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [embeddingOpen, setEmbeddingOpen] = useState(false);

  // ── 键盘导航：当前高亮 option 索引 ──
  const [modelActiveIndex, setModelActiveIndex] = useState(0);
  const [embeddingActiveIndex, setEmbeddingActiveIndex] = useState(0);

  // ── 真实成本数据 ──
  // null = 加载中或加载失败；object = 已加载
  const [usage, setUsage] = useState(null);
  const [usageLoading, setUsageLoading] = useState(true);

  // ── 变更① T1.8：嵌入模式配置 ──
  // embConfig: {mode, api_base_url?, model_name?, api_key_masked?}
  // embConfigError: true 表示加载失败（API 异常可能已降级本地），状态点显示橙色
  const [embConfig, setEmbConfig] = useState(null);
  const [embConfigError, setEmbConfigError] = useState(false);

  // ── Token 软上限：从后端 llm-config 读取 tpm 汇总，失败降级默认值 ──
  const { user } = useAuth();
  const companyId = user?.company_id ? String(user.company_id) : '';
  const [tokenLimit, setTokenLimit] = useState(DEFAULT_TOKEN_LIMIT);
  const [llmProviders, setLlmProviders] = useState({});
  const [llmConfigStatus, setLlmConfigStatus] = useState('loading');
  // 超标警告关闭状态：按级别（warn/over）记忆，级别变化时重新弹出
  const [dismissedLevel, setDismissedLevel] = useState(null);

  const modelRef = useRef(null);
  const usageRef = useRef(null);
  const embeddingRef = useRef(null);

  // ── 键盘导航：listbox 容器与触发按钮引用 ──
  const modelListRef = useRef(null);
  const modelTriggerRef = useRef(null);
  const embeddingListRef = useRef(null);
  const embeddingTriggerRef = useRef(null);

  // ── 拉取今日 / 月度成本 ──
  useEffect(() => {
    let cancelled = false;
    async function loadUsage() {
      if (!user?.is_admin) {
        setUsage(null);
        setUsageLoading(false);
        return;
      }
      try {
        setUsageLoading(true);
        // 三个端点独立容错：任一失败不影响其他
        const [today, summaryToday, summaryMonth] = await Promise.all([
          getTodayCost().catch(() => null),
          getCostSummary(1).catch(() => null),
          getCostSummary(30).catch(() => null),
        ]);
        if (cancelled) return;

        const inputTokens = today?.total_input_tokens || 0;
        const outputTokens = today?.total_output_tokens || 0;
        const used = inputTokens + outputTokens;

        const byModel = (summaryToday?.cost_by_model || [])
          .map((m, i) => ({
            name: m.model_name,
            value: (m.total_input_tokens || 0) + (m.total_output_tokens || 0),
            color: MACARON_COLORS[i % MACARON_COLORS.length],
          }))
          .filter((m) => m.value > 0);

        setUsage({
          used,
          inputTokens,
          outputTokens,
          todayCost: today?.total_cost || 0,
          todayRequests: today?.total_requests || 0,
          monthlyCost: summaryMonth?.total_cost || 0,
          monthlyRequests: summaryMonth?.total_requests || 0,
          monthlyInputTokens: summaryMonth?.total_input_tokens || 0,
          monthlyOutputTokens: summaryMonth?.total_output_tokens || 0,
          resetIn: computeResetIn(),
          byModel,
        });
      } catch (err) {
        console.warn('TopBar: 加载成本数据失败', err);
        setUsage(null);
      } finally {
        if (!cancelled) setUsageLoading(false);
      }
    }
    loadUsage();
    return () => {
      cancelled = true;
    };
  }, [user?.is_admin]);

  // ── 变更① T1.8：拉取嵌入模式配置 ──
  // 页面加载时调 getEmbeddingConfig() 获取当前模式，用于下拉显示模式名称
  // 加载失败时 embConfigError=true，状态点显示橙色（API 异常可能已降级本地）
  useEffect(() => {
    let cancelled = false;
    async function loadEmbConfig() {
      try {
        const data = await getEmbeddingConfig();
        if (cancelled) return;
        setEmbConfig(data);
        setEmbConfigError(false);
      } catch (err) {
        if (cancelled) return;
        // 加载失败不阻塞 UI，降级显示"本地模型" + 橙色状态点
        console.warn('TopBar: 加载嵌入配置失败', err);
        setEmbConfig(null);
        setEmbConfigError(true);
      }
    }
    loadEmbConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── 拉取 LLM 配置中的 tpm 限额，汇总为今日 Token 软上限 ──
  // 加载失败不阻塞 UI，沿用默认值 DEFAULT_TOKEN_LIMIT
  useEffect(() => {
    let cancelled = false;
    async function loadTokenLimit() {
      if (!companyId) {
        setLlmProviders({});
        setLlmConfigStatus('missing_company');
        setTokenLimit(DEFAULT_TOKEN_LIMIT);
        return;
      }
      try {
        const data = await getLlmConfig(companyId);
        if (cancelled) return;
        const providers = data?.providers || {};
        setLlmProviders(providers);
        setLlmConfigStatus(data?.status || 'not_configured');
        let total = 0;
        Object.values(providers).forEach((p) => {
          const tpm = p?.tpm;
          if (tpm && typeof tpm === 'object') {
            Object.values(tpm).forEach((v) => {
              if (typeof v === 'number' && v > 0) total += v;
            });
          }
        });
        if (total > 0) setTokenLimit(total);
      } catch (err) {
        console.warn('TopBar: 加载 LLM 配置失败，Token 限额使用默认值', err);
        if (!cancelled) {
          setLlmProviders({});
          setLlmConfigStatus('unavailable');
        }
      }
    }
    loadTokenLimit();
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  // 点击外部关闭下拉
  useEffect(() => {
    function handle(e) {
      if (modelRef.current && !modelRef.current.contains(e.target)) setModelOpen(false);
      if (usageRef.current && !usageRef.current.contains(e.target)) setUsageOpen(false);
      if (embeddingRef.current && !embeddingRef.current.contains(e.target)) setEmbeddingOpen(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  const modelOptions = useMemo(
    () => {
      const baseOptions = MODEL_OPTIONS.map((option) => {
        const configured = isProviderConfigured(llmProviders[option.provider]);
        return {
          ...option,
          providerLabel: getProviderLabel(option.provider),
          disabled: !configured,
          statusLabel: configured ? '已配置' : '未配置',
        };
      });

      const customOptions = Object.entries(llmProviders || {}).flatMap(([providerKey, providerConfig]) => {
        if (!isProviderConfigured(providerConfig)) return [];
        const modelName = String(providerConfig?.modelName || providerConfig?.model_name || '').trim();
        if (!modelName) return [];
        const knownStaticOption = MODEL_OPTIONS.some(
          (option) => option.provider === providerKey && option.value === modelName
        );
        if (knownStaticOption) return [];
        return [{
          value: modelName,
          label: modelName,
          provider: providerKey,
          providerLabel: getProviderLabel(providerKey),
          disabled: false,
          statusLabel: '已配置',
        }];
      });

      return [...customOptions, ...baseOptions];
    },
    [llmProviders]
  );
  const configuredModelOptions = useMemo(
    () => modelOptions.filter((m) => !m.disabled),
    [modelOptions]
  );
  const configuredModelCount = configuredModelOptions.length;
  const currentModelOption =
    modelOptions.find((m) => m.value === model && !m.disabled) ||
    modelOptions.find((m) => m.value === model);
  const currentLabel = currentModelOption?.label ?? model;
  const currentModelUnavailable = currentModelOption?.disabled ?? true;

  useEffect(() => {
    if (llmConfigStatus === 'loading' || configuredModelOptions.length === 0) return;
    const currentConfigured = modelOptions.some((m) => m.value === model && !m.disabled);
    if (!currentConfigured) {
      setModel?.(configuredModelOptions[0].value);
    }
  }, [configuredModelOptions, llmConfigStatus, model, modelOptions, setModel]);

  // 变更① T1.8：显示嵌入模式名称（本地模型/硅基流动 API/DeepSeek API/OpenAI API）
  // 而非模型文件名；加载中或失败时默认显示"本地模型"
  const currentModeLabel =
    EMBEDDING_MODE_LABELS[embConfig?.mode] ?? '本地模型';
  const isLocalMode = !embConfig?.mode || embConfig.mode === 'local';

  // 顶部按钮用量显示
  const used = usage?.used ?? 0;
  const limit = tokenLimit;
  const usagePctRaw = limit > 0 ? Math.round((used / limit) * 100) : 0;
  const usagePct = Math.min(100, usagePctRaw); // 仅用于进度条宽度
  const usageTone =
    usagePctRaw >= 90 ? 'var(--destructive)' :
    usagePctRaw >= 70 ? 'oklch(0.78 0.14 60)'  :
                     'oklch(0.78 0.13 145)';

  // 超标警告：>100% 粉色 · >90% 黄色 · 可按级别关闭
  const warningLevel =
    usagePctRaw > 100 ? 'over' : usagePctRaw > 90 ? 'warn' : null;
  const showWarning = warningLevel !== null && dismissedLevel !== warningLevel;

  // ── 键盘导航：模型下拉打开时，定位到当前选中项并聚焦 listbox ──
  useEffect(() => {
    if (!modelOpen) return;
    const idx = modelOptions.findIndex((m) => m.value === model);
    setModelActiveIndex(idx >= 0 ? idx : 0);
    const t = setTimeout(() => modelListRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [modelOpen, model, modelOptions]);

  // ── 键盘导航：嵌入模型下拉打开时，定位到当前选中项并聚焦 listbox ──
  useEffect(() => {
    if (!embeddingOpen) return;
    const idx = EMBEDDING_OPTIONS.findIndex((o) => o.value === embedding);
    setEmbeddingActiveIndex(idx >= 0 ? idx : 0);
    const t = setTimeout(() => embeddingListRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [embeddingOpen, embedding]);

  // 共享键盘导航：方向键切换 / Enter 选择 / Escape 关闭
  // 模型下拉和嵌入模型下拉共用此逻辑，避免重复实现
  const handleListKeyDown = (e, {
    options,
    activeIndex,
    setActiveIndex,
    onSelect,
    onClose,
    enabled = true,
  }) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (!enabled) return;
    const count = options.length;
    if (count === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % count);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + count) % count);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const opt = options[activeIndex];
      if (opt) onSelect(opt);
    }
  };

  // 模型下拉键盘导航（基于共享函数）
  const handleModelKeyDown = (e) => handleListKeyDown(e, {
    options: modelOptions,
    activeIndex: modelActiveIndex,
    setActiveIndex: setModelActiveIndex,
    onSelect: (m) => {
      if (m.disabled) return;
      setModel(m.value);
      setModelOpen(false);
      modelTriggerRef.current?.focus();
    },
    onClose: () => {
      setModelOpen(false);
      modelTriggerRef.current?.focus();
    },
  });

  // 嵌入模型下拉键盘导航（基于共享函数）
  const handleEmbeddingKeyDown = (e) => handleListKeyDown(e, {
    options: EMBEDDING_OPTIONS,
    activeIndex: embeddingActiveIndex,
    setActiveIndex: setEmbeddingActiveIndex,
    onSelect: (opt) => {
      setEmbedding?.(opt.value);
      setEmbeddingOpen(false);
      embeddingTriggerRef.current?.focus();
    },
    onClose: () => {
      setEmbeddingOpen(false);
      embeddingTriggerRef.current?.focus();
    },
    enabled: isLocalMode,
  });

  return (
    <header className="relative z-[100] flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-background/80 px-4 backdrop-blur">
      {/* 左侧：当前对话标题 */}
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-primary" />
        <h2 className="text-sm font-medium text-foreground">新对话</h2>
      </div>

      {/* 右侧：模型 + 嵌入模型 + Token 消耗 + 文件面板 */}
      <div className="flex items-center gap-2">
        {/* 模型选择 */}
        <div ref={modelRef} className="relative">
          <button
            ref={modelTriggerRef}
            type="button"
            onClick={() => setModelOpen((v) => !v)}
            aria-label="选择模型"
            aria-haspopup="listbox"
            aria-expanded={modelOpen}
            title={currentModelUnavailable ? '当前模型未完成企业 LLM 配置' : '选择模型'}
            className={cn(
              'btn btn-outline h-8 w-[170px] justify-between px-3 text-xs',
              currentModelUnavailable && 'text-muted-foreground'
            )}
          >
            <span className="truncate">{currentLabel}</span>
            {currentModelUnavailable && (
              <AlertTriangle className="size-3.5 shrink-0 text-muted-foreground" />
            )}
            <ChevronDown className="size-3.5 shrink-0" />
          </button>
          {modelOpen && (
            <div
              ref={modelListRef}
              role="listbox"
              tabIndex={-1}
              aria-activedescendant={
                modelActiveIndex >= 0 && modelOptions[modelActiveIndex]
                  ? `model-option-${modelActiveIndex}`
                  : undefined
              }
              onKeyDown={handleModelKeyDown}
              className="dropdown-content absolute left-0 top-full z-[120] mt-1 w-64 py-1 outline-none"
              style={{ boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)' }}
            >
              <div className="border-b border-border px-3 py-2">
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  企业模型配置
                </p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {configuredModelCount > 0
                    ? `可用模型 ${configuredModelCount} 个`
                    : llmConfigStatus === 'unavailable'
                      ? '配置状态暂不可用'
                      : '请先在设置中配置 API Key'}
                </p>
              </div>
              {modelOptions.map((m, i) => (
                <button
                  key={`${m.provider}:${m.value}`}
                  id={`model-option-${i}`}
                  type="button"
                  role="option"
                  tabIndex={-1}
                  aria-selected={m.value === model}
                  aria-disabled={m.disabled}
                  disabled={m.disabled}
                  onClick={() => {
                    if (m.disabled) return;
                    setModel(m.value);
                    setModelOpen(false);
                  }}
                  onMouseEnter={() => setModelActiveIndex(i)}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs transition-colors',
                    m.disabled && 'cursor-not-allowed opacity-55',
                    i === modelActiveIndex || m.value === model
                      ? 'bg-accent text-accent-foreground'
                      : 'text-foreground hover:bg-accent hover:text-accent-foreground'
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{m.label}</span>
                    <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">
                      {m.providerLabel}
                    </span>
                  </span>
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                    {m.statusLabel}
                  </span>
                  {m.value === model && <Check className="size-3.5 text-muted-foreground" />}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 嵌入模式选择 — 变更① T1.8：显示模式名称 + 状态指示点 */}
        <div ref={embeddingRef} className="relative">
          <button
            ref={embeddingTriggerRef}
            type="button"
            onClick={() => setEmbeddingOpen((v) => !v)}
            aria-label="嵌入模式"
            aria-haspopup="listbox"
            aria-expanded={embeddingOpen}
            className="btn btn-outline h-8 w-auto min-w-[150px] max-w-[200px] justify-between px-3 text-xs"
          >
            <Brain className="size-3.5 shrink-0 text-primary" />
            <span className="truncate flex-1 text-left">{currentModeLabel}</span>
            {/* 状态指示点：绿色=正常，橙色=API异常已降级本地 */}
            <span
              className="size-1.5 shrink-0 rounded-full"
              style={{
                backgroundColor: embConfigError
                  ? 'oklch(0.75 0.15 60)'   // 杏黄 — 异常/降级
                  : 'oklch(0.72 0.15 145)',  // 薄荷绿 — 正常
              }}
              title={embConfigError ? '嵌入服务异常，可能已降级本地' : '嵌入服务正常'}
              aria-label={embConfigError ? '嵌入服务异常' : '嵌入服务正常'}
            />
            <ChevronDown className="size-3.5 shrink-0" />
          </button>
          {embeddingOpen && (
            <div
              ref={embeddingListRef}
              role="listbox"
              tabIndex={-1}
              aria-activedescendant={
                isLocalMode && embeddingActiveIndex >= 0 && EMBEDDING_OPTIONS[embeddingActiveIndex]
                  ? `embedding-option-${EMBEDDING_OPTIONS[embeddingActiveIndex].value}`
                  : undefined
              }
              onKeyDown={handleEmbeddingKeyDown}
              className="dropdown-content absolute right-0 top-full z-[120] mt-1 w-64 py-1 outline-none"
              style={{ boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)' }}
            >
              {/* 当前模式信息 */}
              <p className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                嵌入模式
              </p>
              <div className="flex items-center gap-2 px-3 py-1.5">
                <span
                  className="size-1.5 shrink-0 rounded-full"
                  style={{
                    backgroundColor: embConfigError
                      ? 'oklch(0.75 0.15 60)'
                      : 'oklch(0.72 0.15 145)',
                  }}
                />
                <span className="text-xs font-medium text-foreground">{currentModeLabel}</span>
              </div>
              {embConfig?.model_name && (
                <p className="px-3 pb-1.5 font-mono text-[10px] text-muted-foreground">
                  {embConfig.model_name}
                </p>
              )}
              {embConfig?.api_key_masked && (
                <p className="px-3 pb-1.5 font-mono text-[10px] text-muted-foreground">
                  Key: {embConfig.api_key_masked}
                </p>
              )}

              {/* 本地模式：显示本地模型快速切换列表 */}
              {isLocalMode && (
                <>
                  <div className="border-t border-border" />
                  <p className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    本地模型
                  </p>
                  {EMBEDDING_OPTIONS.map((e, i) => (
                    <button
                      key={e.value}
                      id={`embedding-option-${e.value}`}
                      type="button"
                      role="option"
                      tabIndex={-1}
                      aria-selected={e.value === embedding}
                      onClick={() => {
                        setEmbedding?.(e.value);
                        setEmbeddingOpen(false);
                      }}
                      onMouseEnter={() => setEmbeddingActiveIndex(i)}
                      className={cn(
                        'flex w-full items-start gap-2 px-3 py-2 text-left transition-colors',
                        i === embeddingActiveIndex || e.value === embedding
                          ? 'bg-accent text-accent-foreground'
                          : 'text-foreground hover:bg-accent hover:text-accent-foreground'
                      )}
                    >
                      <Brain className="mt-0.5 size-3.5 shrink-0 text-primary" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-xs font-medium">{e.label}</span>
                        <span className="mt-0.5 block text-[10px] text-muted-foreground">
                          {e.desc}
                        </span>
                      </span>
                      {e.value === embedding && (
                        <Check className="mt-1 size-3.5 shrink-0 text-muted-foreground" />
                      )}
                    </button>
                  ))}
                </>
              )}

              {/* 提示：前往设置页修改 */}
              <div className="border-t border-border px-3 py-2">
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  在「设置 → 知识库 → 嵌入模型」中修改配置
                </p>
              </div>
            </div>
          )}
        </div>

        {user?.is_admin && (
        <div ref={usageRef} className="relative">
          <button
            type="button"
            onClick={() => setUsageOpen((v) => !v)}
            aria-label="Token 消耗"
            aria-haspopup="dialog"
            aria-expanded={usageOpen}
            className="btn btn-outline h-8 px-3 text-xs"
          >
            <Zap className="size-3.5" style={{ color: usageTone }} />
            {usageLoading ? (
              <span className="skeleton inline-block h-3 w-10" aria-hidden="true" />
            ) : (
              <span className="font-mono">{formatTokens(used)}</span>
            )}
            <span className="text-muted-foreground">/ {formatTokens(limit)}</span>
            <span
              className="size-1.5 rounded-full"
              style={{ backgroundColor: usageTone }}
            />
          </button>
          {usageOpen && (
            <div
              role="dialog"
              aria-label="Token 消耗详情"
              className="dropdown-content absolute right-0 top-full z-[120] mt-1 w-80 p-4"
              style={{ boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)' }}
            >
              {usageLoading ? (
                /* ── 加载骨架屏 ── */
                <div className="space-y-2">
                  <div className="skeleton h-3 w-24" />
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <div className="skeleton h-12 w-full" />
                    <div className="skeleton h-12 w-full" />
                  </div>
                  <div className="skeleton h-5 w-32 pt-1" />
                  <div className="skeleton h-1.5 w-full" />
                  <div className="skeleton h-3 w-28" />
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <div className="skeleton h-14 w-full" />
                    <div className="skeleton h-14 w-full" />
                  </div>
                  <div className="mt-2 space-y-2 border-t border-border pt-2">
                    <div className="skeleton h-3 w-16" />
                    <div className="skeleton h-3 w-full" />
                    <div className="skeleton h-3 w-full" />
                  </div>
                </div>
              ) : usage ? (
                /* ── 真实数据 ── */
                <>
                  {/* 标题 */}
                  <div className="mb-3 flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Activity className="size-3.5 text-primary" />
                      <p className="text-xs font-medium text-foreground">今日 Token 消耗</p>
                    </div>
                    <span
                      className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                      style={{
                        backgroundColor: `color-mix(in oklch, ${usageTone} 12%, transparent)`,
                        color: usageTone,
                      }}
                    >
                      {usagePctRaw}%
                    </span>
                  </div>

                  {/* 今日输入/输出 Token 分别展示 */}
                  <div className="mb-3 grid grid-cols-2 gap-2">
                    <div className="rounded-md border border-border bg-background/50 p-2">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        输入 Token
                      </p>
                      <p className="mt-0.5 font-mono text-sm font-medium text-foreground">
                        {usage.inputTokens.toLocaleString()}
                      </p>
                    </div>
                    <div className="rounded-md border border-border bg-background/50 p-2">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        输出 Token
                      </p>
                      <p className="mt-0.5 font-mono text-sm font-medium text-foreground">
                        {usage.outputTokens.toLocaleString()}
                      </p>
                    </div>
                  </div>

                  {/* 总量 + 进度条 */}
                  <div className="mb-1 flex items-baseline justify-between">
                    <span className="font-heading text-xl font-semibold text-foreground">
                      {usage.used.toLocaleString()}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      / {limit.toLocaleString()}
                    </span>
                  </div>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-full"
                    style={{ backgroundColor: 'var(--secondary)' }}
                  >
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${usagePct}%`, backgroundColor: usageTone }}
                    />
                  </div>
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    {usage.resetIn}
                  </p>

                  {/* 今日花费 + 月度累计 */}
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <div className="rounded-md border border-border bg-background/50 p-2">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        今日花费
                      </p>
                      <p className="mt-0.5 font-mono text-sm font-medium text-foreground">
                        ${formatCost(usage.todayCost)}
                      </p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {usage.todayRequests} 次请求
                      </p>
                    </div>
                    <div className="rounded-md border border-border bg-background/50 p-2">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                        月度累计
                      </p>
                      <p className="mt-0.5 font-mono text-sm font-medium text-foreground">
                        ${formatCost(usage.monthlyCost)}
                      </p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {usage.monthlyRequests} 次请求
                      </p>
                    </div>
                  </div>

                  {/* 分模型明细 */}
                  {usage.byModel.length > 0 && (
                    <div className="mt-3 border-t border-border pt-3">
                      <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                        按模型分布
                      </p>
                      <div className="flex flex-col gap-2">
                        {usage.byModel.map((m) => {
                          const pct = used > 0 ? Math.round((m.value / used) * 100) : 0;
                          return (
                            <div key={m.name} className="flex items-center gap-2">
                              <span
                                className="size-2 shrink-0 rounded-full"
                                style={{ backgroundColor: m.color }}
                                aria-hidden="true"
                              />
                              <span className="flex-1 truncate text-xs text-foreground">
                                {m.name}
                              </span>
                              <span className="font-mono text-[11px] text-muted-foreground">
                                {formatTokens(m.value)}
                              </span>
                              <span className="w-9 text-right text-[11px] text-muted-foreground">
                                {pct}%
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* 超标警告：>90% 黄色 · >100% 粉色 · 可按级别关闭 */}
                  {showWarning && warningLevel === 'warn' && (
                    <div
                      role="alert"
                      className="mt-3 flex items-start gap-2 rounded-lg border p-2"
                      style={{
                        borderColor: 'oklch(0.78 0.13 95)',
                        backgroundColor: 'color-mix(in oklch, oklch(0.94 0.06 95) 32%, transparent)',
                      }}
                    >
                      <AlertTriangle
                        className="mt-0.5 size-3.5 shrink-0"
                        style={{ color: 'oklch(0.66 0.13 95)' }}
                      />
                      <p className="flex-1 text-[11px] leading-relaxed text-foreground">
                        今日 Token 使用已达 {usagePctRaw}%，建议关注用量
                      </p>
                      <button
                        type="button"
                        onClick={() => setDismissedLevel('warn')}
                        aria-label="关闭警告"
                        className="inline-flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  )}
                  {showWarning && warningLevel === 'over' && (
                    <div
                      role="alert"
                      className="mt-3 flex items-start gap-2 rounded-lg border p-2"
                      style={{
                        borderColor: 'oklch(0.75 0.15 10)',
                        backgroundColor: 'color-mix(in oklch, oklch(0.92 0.05 10) 38%, transparent)',
                      }}
                    >
                      <AlertTriangle
                        className="mt-0.5 size-3.5 shrink-0"
                        style={{ color: 'oklch(0.60 0.18 10)' }}
                      />
                      <p className="flex-1 text-[11px] leading-relaxed text-foreground">
                        今日 Token 已超出软上限，可能影响服务
                      </p>
                      <button
                        type="button"
                        onClick={() => setDismissedLevel('over')}
                        aria-label="关闭警告"
                        className="inline-flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  )}
                </>
              ) : (
                /* ── 加载失败空态 ── */
                <div className="py-6 text-center">
                  <Activity className="mx-auto size-4 text-muted-foreground" />
                  <p className="mt-1 text-xs text-muted-foreground">暂无成本数据</p>
                </div>
              )}
            </div>
          )}
        </div>
        )}

        {/* 文件面板切换 */}
        <button
          type="button"
          onClick={onToggleFiles}
          aria-label="切换文件面板"
          title="文件面板"
          className={cn(
            'inline-flex size-8 items-center justify-center rounded-md transition-colors hover:bg-accent',
            filesOpen ? 'text-foreground' : 'text-muted-foreground'
          )}
        >
          <PanelRight className="size-4" />
        </button>
      </div>
    </header>
  );
}
