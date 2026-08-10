import { useState, useEffect, useCallback } from 'react';
import {
  Star,
  Store,
  Compass,
  ShoppingBag,
  ShoppingCart,
  BarChart3,
  LineChart,
  BookHeart,
  Megaphone,
  Radio,
  Layers,
  Globe,
  Eye,
  EyeOff,
  Loader2,
  Check,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  Save,
  Trash2,
  Plug,
  HelpCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  getCredentialFields,
  getPlatformGuide,
  bindCredentials,
  verifyCredentials,
  unbindCredentials,
} from '@/api/platforms';

const ICON_MAP = {
  star: Star,
  shop: Store,
  compass: Compass,
  taobao: ShoppingBag,
  chanmama: BarChart3,
  xiaohongshu: BookHeart,
  shengyi_canshu: LineChart,
  pinduoduo: ShoppingCart,
  qianchuan: Megaphone,
  ocean_engine: Radio,
  wanxiangtai: Layers,
  default: Globe,
};

// 敏感字段（默认 masking）：含 secret / token / key / password 的字段名
const isSecretField = (name) => /secret|token|key|password/i.test(name);

const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';

/* ═══════════════════════════════════════════════════════════════
   动态凭证表单 — 字段从 credential-fields 接口动态渲染
   ═══════════════════════════════════════════════════════════════ */
export default function PlatformCredentialForm({ platform, companyId, boundInfo, onSaved, onCancel }) {
  const Icon = ICON_MAP[platform.icon] || ICON_MAP.default;
  const bound = !!boundInfo?.bound;

  const [fields, setFields] = useState([]);
  const [values, setValues] = useState({});
  const [showSecret, setShowSecret] = useState({});
  const [loadingFields, setLoadingFields] = useState(true);
  const [fieldsError, setFieldsError] = useState('');

  const [guide, setGuide] = useState(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideLoading, setGuideLoading] = useState(false);

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [unbinding, setUnbinding] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoadingFields(true);
    setFieldsError('');
    getCredentialFields(platform.code)
      .then((res) => {
        if (!alive) return;
        const fs = res?.fields || [];
        setFields(fs);
        const init = {};
        fs.forEach((f) => {
          init[f.field_name] = '';
        });
        setValues(init);
      })
      .catch((e) => {
        if (!alive) return;
        setFieldsError(e?.response?.data?.detail || '该平台暂无需要配置的凭证字段');
      })
      .finally(() => {
        if (alive) setLoadingFields(false);
      });
    return () => {
      alive = false;
    };
  }, [platform.code]);

  const showToast = useCallback((type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const toggleGuide = async () => {
    if (guideOpen) {
      setGuideOpen(false);
      return;
    }
    setGuideOpen(true);
    if (!guide) {
      setGuideLoading(true);
      try {
        const g = await getPlatformGuide(platform.code);
        setGuide(g);
      } catch {
        setGuide({ title: '授权教程', steps: [] });
      } finally {
        setGuideLoading(false);
      }
    }
  };

  const requiredFilled =
    fields.filter((f) => f.required).every((f) => values[f.field_name]?.trim()) && fields.length > 0;
  const anyFilled = fields.some((f) => values[f.field_name]?.trim());
  const busy = saving || testing || unbinding;

  const handleSave = async () => {
    if (!requiredFilled) {
      showToast('error', '请填写所有必填字段');
      return;
    }
    setSaving(true);
    try {
      await bindCredentials(companyId, platform.code, values);
      showToast('success', '凭证已保存');
      await onSaved?.();
    } catch (e) {
      showToast('error', e?.response?.data?.detail || '保存失败，请稍后重试');
    } finally {
      setSaving(false);
    }
  };

  // 测试连接：填了字段则先持久化再验证；未填则验证已存储凭证（管理模式）
  const handleTest = async () => {
    if (anyFilled && !requiredFilled) {
      showToast('error', '请填写所有必填字段后再测试');
      return;
    }
    if (!anyFilled && !bound) {
      showToast('error', '请先填写凭证字段');
      return;
    }
    setTesting(true);
    try {
      if (anyFilled) {
        await bindCredentials(companyId, platform.code, values);
      }
      const res = await verifyCredentials(companyId, platform.code);
      if (res?.valid) {
        showToast('success', res.message || '连接成功');
      } else {
        showToast('error', res?.message || '连接失败，请检查凭证');
      }
    } catch (e) {
      showToast('error', e?.response?.data?.detail || '测试连接失败');
    } finally {
      setTesting(false);
    }
  };

  const handleUnbind = async () => {
    if (!window.confirm('确定要解绑该平台凭证吗？解绑后相关自动化将无法使用该平台数据。')) return;
    setUnbinding(true);
    try {
      await unbindCredentials(companyId, platform.code);
      showToast('success', '已解绑该平台凭证');
      await onSaved?.();
    } catch (e) {
      showToast('error', e?.response?.data?.detail || '解绑失败，请稍后重试');
    } finally {
      setUnbinding(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-macaron-mint" aria-hidden="true">
          <Icon className="size-4 text-foreground/75" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-heading text-sm font-semibold text-foreground">
            {platform.name_display} 授权
          </p>
          {bound && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              已绑定凭证（出于安全不回显），重新填写可更新
              {boundInfo?.last_verified ? ` · 上次验证 ${boundInfo.last_verified}` : ''}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={toggleGuide}
          className="btn btn-outline h-8 shrink-0 px-2.5 text-xs"
        >
          <HelpCircle className="size-3.5" />
          查看获取方法
          {guideOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
      </div>

      {/* 图文引导 */}
      {guideOpen && (
        <div className="rounded-xl border border-border bg-secondary/40 p-4">
          {guideLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              加载教程…
            </div>
          ) : (
            <>
              <p className="mb-2 text-xs font-semibold text-foreground">
                {guide?.title || '授权教程'}
              </p>
              <ol className="flex flex-col gap-2">
                {(guide?.steps || []).map((s) => (
                  <li key={s.step_num} className="flex gap-2.5 text-xs text-foreground/80">
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-card text-[10px] font-semibold text-foreground/70">
                      {s.step_num}
                    </span>
                    <span className="leading-relaxed">
                      <span className="font-medium text-foreground">{s.action}</span>
                      {s.note ? <span className="text-muted-foreground"> — {s.note}</span> : null}
                    </span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}

      {/* 动态字段 */}
      {loadingFields ? (
        <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          加载凭证字段…
        </div>
      ) : fieldsError ? (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-3 text-xs text-foreground/80">
          <AlertTriangle className="size-4" />
          {fieldsError}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {fields.map((f) => {
            const secret = isSecretField(f.field_name);
            const visible = !!showSecret[f.field_name];
            return (
              <div key={f.field_name} className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-foreground">
                  {f.label_zh}
                  {f.required && <span className="ml-0.5 text-muted-foreground">*</span>}
                </label>
                <div className="relative">
                  <input
                    type={secret && !visible ? 'password' : 'text'}
                    value={values[f.field_name] ?? ''}
                    onChange={(e) => setValues((v) => ({ ...v, [f.field_name]: e.target.value }))}
                    placeholder={bound ? '••••••（如需更新请重新填写）' : `请输入${f.label_zh}`}
                    className={cn('input-base h-10', secret && 'pr-10')}
                    autoComplete="off"
                  />
                  {secret && (
                    <button
                      type="button"
                      onClick={() =>
                        setShowSecret((s) => ({ ...s, [f.field_name]: !s[f.field_name] }))
                      }
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:text-foreground"
                      aria-label={visible ? '隐藏' : '显示'}
                    >
                      {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  )}
                </div>
                {f.help_text && <p className="text-[11px] text-muted-foreground">{f.help_text}</p>}
              </div>
            );
          })}
        </div>
      )}

      {/* 结果提示 */}
      {toast && (
        <div
          className={cn(
            'flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs',
            toast.type === 'success' ? 'bg-macaron-mint/60' : 'bg-macaron-rose/40'
          )}
          style={{ color: toast.type === 'success' ? SUCCESS_COLOR : 'var(--destructive)' }}
          role="status"
        >
          {toast.type === 'success' ? (
            <Check className="size-4" />
          ) : (
            <AlertTriangle className="size-4" />
          )}
          {toast.message}
        </div>
      )}

      {/* 按钮区 */}
      <div className="flex flex-wrap items-center justify-end gap-2.5">
        {bound && (
          <button
            type="button"
            onClick={handleUnbind}
            disabled={busy}
            className="btn btn-outline mr-auto h-9 px-3 text-xs"
            style={{ color: 'var(--destructive)' }}
          >
            {unbinding ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
            解绑
          </button>
        )}
        <button
          type="button"
          onClick={handleTest}
          disabled={busy || (loadingFields && !bound)}
          className="btn btn-outline h-9 px-3.5 text-sm"
        >
          {testing ? <Loader2 className="size-4 animate-spin" /> : <Plug className="size-4" />}
          测试连接
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={busy || !requiredFilled}
          className="btn btn-primary h-9 px-3.5 text-sm"
        >
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          保存
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="btn btn-outline h-9 px-3.5 text-sm"
        >
          取消
        </button>
      </div>
    </div>
  );
}
