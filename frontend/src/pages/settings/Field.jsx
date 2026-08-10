import { cn } from '@/lib/utils';

/* ═══════════════════════════════════════════════════════════════
   通用 — 标签 + 表单行（label 在上、input 在下，同一列）
   - error:    错误状态，显示 macaron-pink 错误文案（input 边框由调用方控制）
   - disabled: disabled 状态，label 文字 muted
   - hint:     输入框下方的辅助说明
   focus 状态由 .input-base 的 CSS 全局处理（box-shadow 软紫色光晕）
   ═══════════════════════════════════════════════════════════════ */
export default function Field({ label, hint, error, disabled, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        className={cn(
          'text-sm font-medium',
          disabled ? 'text-muted-foreground' : 'text-foreground'
        )}
      >
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-[11px] font-medium text-[oklch(0.62_0.18_25)]" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
