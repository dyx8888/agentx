import { useMemo, useState } from 'react';
import { Shield, Check, Loader2, KeyRound } from 'lucide-react';
import Field from './Field';
import { changePassword } from '@/lib/auth';

// 状态色（保存成功提示）
const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';

/* ═══════════════════════════════════════════════════════════════
   2) 账户安全
   ═══════════════════════════════════════════════════════════════ */
export default function SecuritySection() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  // 密码强度（前端检测，不传后端）：
  // 长度≥8 +1 / 含数字 +1 / 含特殊字符 +1 / 长度≥12 +1
  // 4 分=强(mint) · 3 分=中(yellow) · ≤2 分=弱(pink)
  const strength = useMemo(() => {
    const pwd = form.next;
    if (!pwd) return { score: 0, label: '', color: '' };
    let score = 0;
    if (pwd.length >= 8) score += 1;
    if (/\d/.test(pwd)) score += 1;
    if (/[^A-Za-z0-9]/.test(pwd)) score += 1;
    if (pwd.length >= 12) score += 1;
    if (score >= 4) return { score, label: '强', color: 'oklch(0.72 0.15 165)' };
    if (score === 3) return { score, label: '中', color: 'oklch(0.78 0.13 95)' };
    return { score, label: '弱', color: 'oklch(0.75 0.15 10)' };
  }, [form.next]);
  const strengthScore = strength.score;
  const strengthLabel = strength.label;
  const strengthColor = strength.color;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.current) return setError('请输入当前密码');
    if (form.next.length < 8) return setError('新密码至少 8 位');
    if (form.next !== form.confirm) return setError('两次输入的新密码不一致');

    setSaving(true);
    setSaved(false);
    try {
      await changePassword(form.current, form.next);
      setForm({ current: '', next: '', confirm: '' });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : '密码更新失败，请稍后重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          账户安全
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          定期更换密码能有效保护你的账户
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-5 rounded-2xl border border-border bg-card p-5"
      >
        <Field label="当前密码">
          <input
            type="password"
            value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })}
            placeholder="••••••••"
            className="input-base h-10"
            autoComplete="current-password"
          />
        </Field>
        <Field label="新密码" hint="至少 8 位，建议包含大小写字母与数字">
          <input
            type="password"
            value={form.next}
            onChange={(e) => setForm({ ...form, next: e.target.value })}
            placeholder="••••••••"
            className="input-base h-10"
            autoComplete="new-password"
          />
        </Field>
        <Field label="确认新密码">
          <input
            type="password"
            value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })}
            placeholder="••••••••"
            className="input-base h-10"
            autoComplete="new-password"
          />
        </Field>

        {error && (
          <div role="alert" className="text-sm" style={{ color: 'var(--destructive)' }}>
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-3">
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs text-foreground">
              <Check className="size-3.5" style={{ color: SUCCESS_COLOR }} />
              密码已更新
            </span>
          )}
          <button
            type="submit"
            className="btn btn-primary h-10 px-4"
            disabled={saving}
          >
            {saving ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
            更新密码
          </button>
        </div>
      </form>

      {/* 安全增强 */}
      <section className="flex flex-col gap-3">
        <header className="flex items-center gap-2">
          <Shield className="size-4 text-foreground/70" />
          <h3 className="text-sm font-semibold text-foreground">安全增强</h3>
        </header>

        {/* 密码强度检测（前端实时检测） */}
        <div className="flex items-start gap-4 rounded-2xl border border-border bg-card/50 p-4">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-macaron-pink">
            <KeyRound className="size-5 text-foreground/80" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">密码强度检测</p>
              {form.next && (
                <span
                  className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                  style={{
                    backgroundColor: `color-mix(in oklch, ${strengthColor} 18%, transparent)`,
                    color: strengthColor,
                  }}
                >
                  {strengthLabel}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {form.next
                ? '基于长度与字符复杂度的前端检测'
                : '在上方「新密码」框中输入以检测强度'}
            </p>
            {/* 强度条：4 段，按得分填充，颜色随级别变化 */}
            <div className="mt-2 flex gap-1" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <span
                  key={i}
                  className="h-1.5 flex-1 rounded-full transition-colors"
                  style={{
                    backgroundColor:
                      i < strengthScore ? strengthColor : 'var(--secondary)',
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
