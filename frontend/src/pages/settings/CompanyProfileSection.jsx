import { useState, useEffect, useRef } from 'react';
import { Loader2, AlertTriangle, Check, Save } from 'lucide-react';
import { useAuth } from '@/lib/AuthContext';
import { getCompanyProfile, updateCompanyProfile } from '@/api/rag';
import Field from './Field';

// 状态色（保存成功提示）
const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';

// localStorage 自动保存的 key（按公司隔离）
const draftKey = (companyId) => `company_profile_draft_${companyId}`;
const AUTOSAVE_DEBOUNCE_MS = 1000;
const PROFILE_FIELD_LABELS = {
  industry: '\u884c\u4e1a',
  brand_description: '\u54c1\u724c\u63cf\u8ff0',
  target_audience: '\u76ee\u6807\u53d7\u4f17',
  product_categories: '\u4e3b\u8425\u7c7b\u76ee',
  competitors: '\u7ade\u54c1',
  usp: '\u72ec\u7279\u5356\u70b9',
};

/* ═══════════════════════════════════════════════════════════════
   5) 公司资料 — 紧凑单页布局
   - 6 个字段压缩为 3×2 网格 + 全宽品牌描述
   - 适配 1080p 不出现滚动条
   - 字段变更时自动保存到 localStorage（debounce 1 秒，标"自动保存"）
   ═══════════════════════════════════════════════════════════════ */
export default function CompanyProfileSection() {
  const { user } = useAuth();
  const companyId = user?.company_id ? String(user.company_id) : '';

  const [form, setForm] = useState({
    company_name: '',
    industry: '',
    brand_description: '',
    target_audience: '',
    product_categories: [],
    core_products: [],
    brand_voice: '',
    competitors: [],
    usp: '',
    social_media_accounts: {},
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [autoSaved, setAutoSaved] = useState(false); // localStorage 自动保存指示
  const [error, setError] = useState('');
  const [categoriesText, setCategoriesText] = useState('');
  const [competitorsText, setCompetitorsText] = useState('');
  // 自动保存 debounce 定时器
  const autoSaveTimerRef = useRef(null);
  // 标记初次加载完成，避免初次 setForm 触发自动保存
  const initializedRef = useRef(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError('');
      if (!companyId) {
        setError('当前账号未关联公司，无法加载公司资料');
        setLoading(false);
        initializedRef.current = false;
        return;
      }
      // 先尝试读取 localStorage 草稿（若后端加载失败可用作回退）
      let draft = null;
      try {
        const raw = localStorage.getItem(draftKey(companyId));
        if (raw) draft = JSON.parse(raw);
      } catch { /* noop */ }

      try {
        const data = await getCompanyProfile(companyId);
        // 后端成功：以后端数据为准，但若草稿更新则提示用户
        setForm(data);
        setCategoriesText((data.product_categories || []).join('、'));
        setCompetitorsText((data.competitors || []).join('、'));
      } catch (err) {
        // 后端失败：若有草稿则用草稿，否则报错
        if (draft) {
          setForm(draft.form || draft);
          setCategoriesText(draft.categoriesText || '');
          setCompetitorsText(draft.competitorsText || '');
        } else {
          setError('加载公司资料失败');
          console.error(err);
        }
      } finally {
        setLoading(false);
        initializedRef.current = true;
      }
    };
    load();
  }, [companyId]);

  // 自动保存到 localStorage（debounce 1 秒）
  // 监听 form / categoriesText / competitorsText 变化
  useEffect(() => {
    if (!companyId) return undefined;
    if (!initializedRef.current) return;
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      try {
        localStorage.setItem(
          draftKey(companyId),
          JSON.stringify({ form, categoriesText, competitorsText })
        );
        setAutoSaved(true);
        setTimeout(() => setAutoSaved(false), 1500);
      } catch {
        /* localStorage 写入失败（如配额满）— 忽略 */
      }
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [form, categoriesText, competitorsText, companyId]);

  const handleSave = async () => {
    if (!companyId) {
      setError('当前账号未关联公司，无法保存公司资料');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const payload = {
        ...form,
        product_categories: categoriesText.split(/[,，、]/).map((s) => s.trim()).filter(Boolean),
        competitors: competitorsText.split(/[,，、]/).map((s) => s.trim()).filter(Boolean),
      };
      await updateCompanyProfile(payload, companyId);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } catch (err) {
      setError(err.response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        加载中...
      </div>
    );
  }

  const missingProfileLabels = (form.missing_fields || []).map(
    (field) => PROFILE_FIELD_LABELS[field] || field
  );

  return (
    <div className="flex flex-col gap-5">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          公司资料
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          这些信息会作为 RAG 的 Layer 1 上下文注入到 Agent 的 System Prompt 中
        </p>
      </header>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-2.5 text-xs text-foreground/80">
          <AlertTriangle className="size-3.5 shrink-0" style={{ color: 'var(--destructive)' }} />
          {error}
        </div>
      )}

      {form.setup_required && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">{'\u516c\u53f8\u8d44\u6599\u672a\u5b8c\u6574\uff0cAgent \u56de\u7b54\u53ef\u80fd\u7f3a\u5c11\u54c1\u724c\u4e0a\u4e0b\u6587\u3002'}</p>
            <p>{'\u5f85\u8865\u5168\uff1a'}{missingProfileLabels.join('\u3001')}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Field label="公司名称">
          <input
            type="text"
            value={form.company_name}
            onChange={(e) => setForm({ ...form, company_name: e.target.value })}
            placeholder="例如：星辰电商"
            className="input-base h-9 text-sm"
          />
        </Field>
        <Field label="行业">
          <input
            type="text"
            value={form.industry}
            onChange={(e) => setForm({ ...form, industry: e.target.value })}
            placeholder="例如：美妆护肤"
            className="input-base h-9 text-sm"
          />
        </Field>
        <Field label="品牌调性">
          <input
            type="text"
            value={form.brand_voice}
            onChange={(e) => setForm({ ...form, brand_voice: e.target.value })}
            placeholder="例如：年轻、时尚、专业"
            className="input-base h-9 text-sm"
          />
        </Field>
        <Field label="目标受众">
          <input
            type="text"
            value={form.target_audience}
            onChange={(e) => setForm({ ...form, target_audience: e.target.value })}
            placeholder="例如：18-35 岁女性"
            className="input-base h-9 text-sm"
          />
        </Field>
        <Field label="独特卖点 (USP)">
          <input
            type="text"
            value={form.usp}
            onChange={(e) => setForm({ ...form, usp: e.target.value })}
            placeholder="例如：纯天然成分，敏感肌可用"
            className="input-base h-9 text-sm"
          />
        </Field>
        <Field label="主营类目" hint="用逗号 / 顿号分隔">
          <input
            type="text"
            value={categoriesText}
            onChange={(e) => setCategoriesText(e.target.value)}
            placeholder="例如：面膜、精华、面霜"
            className="input-base h-9 text-sm"
          />
        </Field>
      </div>

      <Field label="竞品" hint="用逗号 / 顿号分隔">
        <input
          type="text"
          value={competitorsText}
          onChange={(e) => setCompetitorsText(e.target.value)}
          placeholder="例如：竞品A、竞品B、竞品C"
          className="input-base h-9 text-sm"
        />
      </Field>

      <Field label="品牌描述">
        <textarea
          rows={2}
          value={form.brand_description}
          onChange={(e) => setForm({ ...form, brand_description: e.target.value })}
          placeholder="描述你的品牌定位、理念和特色..."
          className="input-base h-auto py-2 text-sm leading-relaxed"
        />
      </Field>

      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          填写完整的品牌信息可显著提升 Agent 回答的准确性和相关性。
        </p>
        <div className="flex items-center gap-3">
          {autoSaved && (
            <span
              className="inline-flex items-center gap-1 text-xs text-muted-foreground"
              role="status"
              aria-live="polite"
            >
              <Check className="size-3.5" style={{ color: SUCCESS_COLOR }} />
              自动保存
            </span>
          )}
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs text-foreground">
              <Check className="size-3.5" style={{ color: SUCCESS_COLOR }} />
              已保存
            </span>
          )}
          <button
            type="button"
            onClick={handleSave}
            className="btn btn-primary h-9 px-4"
            disabled={saving}
          >
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
            保存资料
          </button>
        </div>
      </div>
    </div>
  );
}
