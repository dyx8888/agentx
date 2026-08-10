import { useRef, useState } from 'react';
import { Camera, Check, Loader2, Save } from 'lucide-react';
import Field from './Field';
import { updateUserProfile } from '../../api/auth';

// 状态色（保存成功 / 失败提示）
const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';
const ERROR_COLOR = 'oklch(0.65 0.17 25)';

/* ═══════════════════════════════════════════════════════════════
   骨架屏 — user 为 null 时显示，避免空白或崩溃
   ═══════════════════════════════════════════════════════════════ */
function ProfileSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <div className="skeleton h-7 w-32 rounded-md" />
        <div className="skeleton mt-2 h-4 w-64 rounded-md" />
      </header>
      <div className="flex items-center gap-4 rounded-2xl border border-border bg-card p-4">
        <div className="skeleton size-16 rounded-2xl" />
        <div className="flex-1 space-y-2">
          <div className="skeleton h-4 w-16 rounded-md" />
          <div className="skeleton h-3 w-56 rounded-md" />
        </div>
        <div className="skeleton h-9 w-16 rounded-md" />
      </div>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <div className="skeleton h-4 w-20 rounded-md" />
            <div className="skeleton h-10 w-full rounded-md" />
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   1) 个人资料
   ═══════════════════════════════════════════════════════════════ */
export default function ProfileSection({ user, onSave }) {
  // user 为 null 时显示骨架屏，避免崩溃
  if (!user) return <ProfileSkeleton />;

  return <ProfileForm user={user} onSave={onSave} />;
}

function ProfileForm({ user, onSave }) {
  const [form, setForm] = useState({
    username: user?.username || '',
    email: user?.email || '',
    company: user?.company_name || '',
    brand: user?.brand_name || '',
    category: user?.category || '',
    bio: user?.bio || '',
    avatar_url: user?.avatar_url || '',
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  // 头像加载失败 → 降级显示首字母
  const [avatarError, setAvatarError] = useState(false);
  const avatarInputRef = useRef(null);

  // 调用后端 PUT /api/auth/users/me 保存资料（邮箱不允许修改，不发送）
  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await updateUserProfile({
        username: form.username,
        company_name: form.company,
        brand_name: form.brand,
        category: form.category,
        bio: form.bio,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(
        typeof detail === 'string' ? detail : (err?.message || '保存失败，请稍后重试')
      );
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError('请选择图片文件');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setError('头像文件不能超过 2MB');
      return;
    }
    const previewUrl = URL.createObjectURL(file);
    setAvatarError(false);
    setError('');
    setForm((prev) => ({ ...prev, avatar_url: previewUrl }));
  };

  // 头像降级：有 avatar_url 且未出错 → 显示图片；否则显示首字母
  // user.username 为空时降级显示 '?'
  const initial = (form.username || '?').slice(0, 1).toUpperCase();
  const showImage = form.avatar_url && !avatarError;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          个人资料
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          这些信息会显示在你的个人主页和对话署名中
        </p>
      </header>

      {/* 头像区 */}
      <div className="flex items-center gap-4 rounded-2xl border border-border bg-card p-4">
        <div
          className="flex size-16 items-center justify-center overflow-hidden rounded-2xl bg-primary text-2xl font-heading font-semibold text-primary-foreground"
          aria-hidden="true"
        >
          {showImage ? (
            <img
              src={form.avatar_url}
              alt=""
              className="size-full object-cover"
              onError={() => setAvatarError(true)}
            />
          ) : (
            <span>{initial}</span>
          )}
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium text-foreground">头像</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            支持 PNG / JPG，建议 256×256，大小不超过 2MB
          </p>
        </div>
        <button
          type="button"
          onClick={() => avatarInputRef.current?.click()}
          className="btn btn-outline h-9 px-3 text-xs"
        >
          <Camera className="size-3.5" />
          更换
        </button>
      </div>
      <input
        ref={avatarInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={handleAvatarChange}
      />
      <p className="text-xs text-muted-foreground">头像仅本地预览；保存资料不会外发或上传图片。</p>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <Field label="用户名">
          <input
            type="text"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            placeholder="未设置"
            className="input-base h-10"
          />
        </Field>
        <Field label="邮箱" hint="不可修改">
          <input
            type="email"
            value={form.email}
            readOnly
            placeholder="未设置"
            className="input-base h-10 cursor-not-allowed opacity-70"
          />
        </Field>
        <Field label="公司名称">
          <input
            type="text"
            value={form.company}
            onChange={(e) => setForm({ ...form, company: e.target.value })}
            placeholder="例如：星辰电商"
            className="input-base h-10"
          />
        </Field>
        <Field label="品牌名">
          <input
            type="text"
            value={form.brand}
            onChange={(e) => setForm({ ...form, brand: e.target.value })}
            placeholder="例如：Lumière"
            className="input-base h-10"
          />
        </Field>
        <Field label="主营类目">
          <input
            type="text"
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            placeholder="例如：美妆护肤"
            className="input-base h-10"
          />
        </Field>
      </div>

      <Field label="个人简介" hint="一句话介绍你和你的品牌">
        <textarea
          rows={3}
          value={form.bio}
          onChange={(e) => setForm({ ...form, bio: e.target.value })}
          placeholder="例如：专注小众美妆品牌的电商运营..."
          className="input-base h-auto py-2 leading-relaxed"
        />
      </Field>

      <div className="flex items-center justify-end gap-3">
        {error && (
          <span className="text-xs" style={{ color: ERROR_COLOR }}>
            {error}
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
          className="btn btn-primary h-10 px-4"
          disabled={saving}
        >
          {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          保存修改
        </button>
      </div>
    </div>
  );
}
