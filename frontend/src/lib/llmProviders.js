export const DEFAULT_PROVIDER_TYPE = 'openai_compatible';

export const TASK_OPTIONS = [
  { value: 'chat', label: '聊天' },
  { value: 'analysis', label: '分析' },
  { value: 'content', label: '内容' },
  { value: 'workflow', label: '工作流' },
];

export const LLM_PROVIDERS = [
  {
    key: 'deepseek',
    name: 'DeepSeek',
    desc: 'DeepSeek 兼容 OpenAI 的接口',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://api.deepseek.com/v1',
    defaultModelName: 'deepseek-chat',
    defaultPreferredTasks: ['chat', 'analysis'],
    models: [
      { value: 'deepseek-chat', label: 'DeepSeek-V3', defaultTpm: 200000 },
      { value: 'deepseek-reasoner', label: 'DeepSeek-R1', defaultTpm: 100000 },
      { value: 'deepseek-coder', label: 'DeepSeek-Coder', defaultTpm: 100000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'zhipu',
    name: '智谱 GLM',
    desc: '智谱 GLM 兼容 OpenAI 的接口',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://open.bigmodel.cn/api/paas/v4',
    defaultModelName: 'glm-5.2',
    defaultPreferredTasks: ['chat', 'analysis'],
    models: [
      { value: 'glm-5.2', label: 'GLM-5.2', defaultTpm: 100000 },
      { value: 'glm-4-plus', label: 'GLM-4-Plus', defaultTpm: 100000 },
      { value: 'glm-4-air', label: 'GLM-4-Air', defaultTpm: 100000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'openai',
    name: 'OpenAI',
    desc: 'OpenAI 兼容 GPT 接口',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://api.openai.com/v1',
    defaultModelName: 'gpt-4o-mini',
    defaultPreferredTasks: ['chat', 'analysis'],
    models: [
      { value: 'gpt-4o', label: 'GPT-4o', defaultTpm: 200000 },
      { value: 'gpt-4o-mini', label: 'GPT-4o mini', defaultTpm: 500000 },
      { value: 'gpt-4.1', label: 'GPT-4.1', defaultTpm: 200000 },
      { value: 'gpt-4.1-mini', label: 'GPT-4.1 mini', defaultTpm: 500000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'anthropic',
    name: 'Anthropic',
    desc: '通过 OpenAI-compatible 中转站接入 Claude',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://api.anthropic.com/v1',
    defaultModelName: 'claude-3-5-sonnet',
    defaultPreferredTasks: ['chat', 'analysis'],
    models: [
      { value: 'claude-3-5-sonnet', label: 'Claude 3.5 Sonnet', defaultTpm: 100000 },
      { value: 'claude-3-7-sonnet', label: 'Claude 3.7 Sonnet', defaultTpm: 100000 },
      { value: 'claude-sonnet-4', label: 'Claude Sonnet 4', defaultTpm: 100000 },
    ],
    placeholder: 'sk-ant-...',
  },
  {
    key: 'qwen',
    name: '通义千问 Qwen',
    desc: '阿里云 DashScope OpenAI-compatible 接口',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    defaultModelName: 'qwen-plus',
    defaultPreferredTasks: ['chat', 'analysis', 'content'],
    models: [
      { value: 'qwen-plus', label: 'Qwen Plus', defaultTpm: 200000 },
      { value: 'qwen-max', label: 'Qwen Max', defaultTpm: 100000 },
      { value: 'qwen-turbo', label: 'Qwen Turbo', defaultTpm: 300000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'gemini',
    name: 'Gemini',
    desc: 'Google Gemini OpenAI-compatible 接口',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://generativelanguage.googleapis.com/v1beta/openai',
    defaultModelName: 'gemini-2.0-flash',
    defaultPreferredTasks: ['chat', 'analysis'],
    models: [
      { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash', defaultTpm: 200000 },
      { value: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro', defaultTpm: 100000 },
      { value: 'gemini-1.5-flash', label: 'Gemini 1.5 Flash', defaultTpm: 200000 },
    ],
    placeholder: 'AIza...',
  },
  {
    key: 'doubao',
    name: '豆包 Doubao',
    desc: '火山方舟 OpenAI-compatible 接口',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://ark.cn-beijing.volces.com/api/v3',
    defaultModelName: 'doubao-seed-1-6',
    defaultPreferredTasks: ['chat', 'analysis', 'content'],
    models: [
      { value: 'doubao-seed-1-6', label: 'Doubao Seed 1.6', defaultTpm: 200000 },
      { value: 'doubao-pro-32k', label: 'Doubao Pro 32K', defaultTpm: 100000 },
      { value: 'deepseek-chat', label: 'DeepSeek on Ark', defaultTpm: 200000 },
    ],
    placeholder: 'sk-...',
  },
  {
    key: 'custom_proxy',
    name: '自定义中转站',
    desc: '兼容 OpenAI 的网关地址 / 模型 / API 密钥',
    defaultProviderType: DEFAULT_PROVIDER_TYPE,
    defaultGateway: 'https://proxy.example.com/v1',
    defaultModelName: 'custom-chat-model',
    defaultPreferredTasks: ['chat'],
    models: [
      { value: 'custom-chat-model', label: '自定义模型', defaultTpm: 200000 },
    ],
    placeholder: 'sk-...',
  },
];

export const PROVIDER_BY_KEY = Object.fromEntries(
  LLM_PROVIDERS.map((provider) => [provider.key, provider])
);

export function getProviderLabel(providerKey) {
  return PROVIDER_BY_KEY[providerKey]?.name || providerKey;
}

export function normalizePreferredTasks(value) {
  const raw = Array.isArray(value) ? value : String(value || '').split(',');
  const normalized = [];
  for (const item of raw) {
    const task = String(item || '').trim();
    if (task && !normalized.includes(task)) normalized.push(task);
  }
  return normalized;
}

export function preferredTasksToInput(value) {
  return normalizePreferredTasks(value).join(', ');
}

export function providerDefaults(provider) {
  const fallbackModel = provider?.models?.[0]?.value || '';
  return {
    providerType: provider?.defaultProviderType || DEFAULT_PROVIDER_TYPE,
    baseUrl: provider?.defaultGateway || '',
    gateway: provider?.defaultGateway || '',
    modelName: provider?.defaultModelName || fallbackModel,
    enabled: true,
    preferredTasks: provider?.defaultPreferredTasks || [],
    apiKey: '',
    apiKeyMasked: '',
    tpm: {},
    usage: {},
    warnAt90: true,
  };
}

export function normalizeProviderState(provider, cfg = {}) {
  const defaults = providerDefaults(provider);
  const baseUrl = cfg.baseUrl ?? cfg.gateway ?? defaults.baseUrl;
  return {
    ...defaults,
    providerType: cfg.providerType || defaults.providerType,
    baseUrl,
    gateway: cfg.gateway ?? baseUrl,
    modelName: cfg.modelName || cfg.model_name || defaults.modelName,
    enabled: cfg.enabled ?? defaults.enabled,
    preferredTasks: normalizePreferredTasks(
      cfg.preferredTasks ?? cfg.preferred_tasks ?? defaults.preferredTasks
    ),
    apiKey: cfg.apiKey || '',
    apiKeyMasked: cfg.apiKeyMasked || cfg.api_key_masked || '',
    tpm: cfg.tpm || {},
    usage: cfg.usage || {},
    warnAt90: cfg.warnAt90 ?? true,
  };
}

export function buildProviderPayload(key, cfg = {}) {
  const provider = PROVIDER_BY_KEY[key] || { key };
  const normalized = normalizeProviderState(provider, cfg);
  const baseUrl = normalized.baseUrl || normalized.gateway || '';
  return {
    providerType: normalized.providerType || DEFAULT_PROVIDER_TYPE,
    baseUrl,
    gateway: baseUrl,
    modelName: normalized.modelName || '',
    enabled: normalized.enabled ?? true,
    preferredTasks: normalizePreferredTasks(normalized.preferredTasks),
    apiKey: normalized.apiKey || '',
    tpm: normalized.tpm || {},
    warnAt90: normalized.warnAt90 ?? true,
  };
}

export function isProviderConfigured(providerConfig) {
  if (!providerConfig || providerConfig.enabled === false) return false;
  const gateway = providerConfig.gateway || providerConfig.baseUrl;
  const maskedKey = providerConfig.apiKeyMasked || providerConfig.api_key_masked;
  const modelName = providerConfig.modelName || providerConfig.model_name;
  return Boolean(gateway && maskedKey && modelName);
}

export function modelOptionsForProvider(provider, configuredModelName = '') {
  const models = [...(provider?.models || [])];
  const modelName = String(configuredModelName || '').trim();
  if (modelName && !models.some((model) => model.value === modelName)) {
    models.unshift({ value: modelName, label: modelName, defaultTpm: 200000, custom: true });
  }
  return models;
}

export function buildChatModelOptions(llmProviders = {}) {
  const knownKeys = LLM_PROVIDERS.map((provider) => provider.key);
  const remoteKeys = Object.keys(llmProviders || {}).filter((key) => !knownKeys.includes(key));
  const keys = [...knownKeys, ...remoteKeys];
  const configuredKeys = new Set();
  const configured = [];
  const catalog = [];

  for (const key of keys) {
    const provider = PROVIDER_BY_KEY[key] || { key, name: key, models: [] };
    const cfg = llmProviders?.[key] || {};
    const normalized = normalizeProviderState(provider, cfg);
    const tasks = normalizePreferredTasks(cfg.preferredTasks ?? cfg.preferred_tasks ?? normalized.preferredTasks);
    const supportsChat = tasks.length === 0 || tasks.includes('chat');

    if (supportsChat && isProviderConfigured(cfg)) {
      configuredKeys.add(key);
      configured.push({
        value: key,
        label: normalized.modelName,
        modelName: normalized.modelName,
        provider: key,
        providerLabel: getProviderLabel(key),
        disabled: false,
        statusLabel: '已配置',
      });
      continue;
    }

    for (const model of modelOptionsForProvider(provider)) {
      catalog.push({
        value: `${key}:${model.value}`,
        label: model.label,
        modelName: model.value,
        provider: key,
        providerLabel: getProviderLabel(key),
        disabled: true,
        statusLabel: '未配置',
      });
    }
  }

  return [
    ...configured,
    ...catalog.filter((option) => !configuredKeys.has(option.provider)),
  ];
}
