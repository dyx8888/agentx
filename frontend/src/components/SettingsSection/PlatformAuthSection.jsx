import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
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
  Search,
  Check,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  Loader2,
  Link2,
  ExternalLink,
  Wrench,
  X,
} from 'lucide-react';
import { useAuth } from '@/lib/AuthContext';
import { cn } from '@/lib/utils';
import { getPlatforms, getBoundCredentials } from '@/api/platforms';
import { getAuthorizeUrl } from '@/api/oauth';
import PlatformCredentialForm from './PlatformCredentialForm';

/* ═══════════════════════════════════════════════════════════════
   平台图标映射 — 后端 icon 字段 → lucide 图标
   ═══════════════════════════════════════════════════════════════ */
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

// 马卡龙色轮换（避免蓝色，遵守设计约定）
const TINTS = ['bg-macaron-mint', 'bg-macaron-pink', 'bg-macaron-yellow', 'bg-macaron-rose'];

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'authorized', label: '已授权' },
  { key: 'unauthorized', label: '未授权' },
];

/* ═══════════════════════════════════════════════════════════════
   状态徽章
   ═══════════════════════════════════════════════════════════════ */
function StatusBadge({ bound, verifyValid }) {
  if (!bound) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
        未授权
      </span>
    );
  }
  if (verifyValid === false) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-macaron-rose px-2.5 py-0.5 text-[11px] font-medium text-foreground/80">
        <AlertTriangle className="size-3" />
        验证失败
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-macaron-mint px-2.5 py-0.5 text-[11px] font-medium text-foreground/80">
      <Check className="size-3" />
      已授权
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════
   单个平台卡片
   ═══════════════════════════════════════════════════════════════ */
function PlatformCard({ platform, boundInfo, tint, expanded, onToggle, children }) {
  const Icon = ICON_MAP[platform.icon] || ICON_MAP.default;
  const bound = !!boundInfo?.bound;

  return (
    <div
      className={cn(
        'rounded-2xl border bg-card transition-colors',
        expanded ? 'border-primary/40' : 'border-border hover:border-primary/30'
      )}
    >
      <div className="flex items-center gap-4 p-4">
        <div
          className={cn('flex size-11 shrink-0 items-center justify-center rounded-xl', tint)}
          aria-hidden="true"
        >
          <Icon className="size-5 text-foreground/75" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-heading text-base font-semibold text-foreground">
              {platform.name_display}
            </h3>
            <StatusBadge bound={bound} verifyValid={boundInfo?.last_verify_valid} />
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {platform.description || '—'}
          </p>
        </div>

        <button
          type="button"
          onClick={onToggle}
          className={cn(
            'h-9 shrink-0 px-3.5 text-sm',
            bound ? 'btn btn-outline' : 'btn btn-primary'
          )}
        >
          {bound ? '管理' : '去授权'}
          {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-border px-4 pb-4 pt-4">{children}</div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   授权区主体 — OAuth 主流程 + 折叠的"手动填写"
   主推 OAuth 跳转授权（安全、免复制 token）；手动填写作为高级备选
   ═══════════════════════════════════════════════════════════════ */
const SUCCESS_COLOR = 'oklch(0.7 0.09 145)';

function PlatformAuthBody({
  platform,
  companyId,
  boundInfo,
  oauthLoading,
  oauthError,
  onAuthorize,
  onFormDone,
  onCancel,
}) {
  const bound = !!boundInfo?.bound;
  const [manualOpen, setManualOpen] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      {/* OAuth 主按钮：跳转平台官方授权页 */}
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={onAuthorize}
          disabled={oauthLoading}
          className="btn btn-primary h-9 w-fit px-3.5 text-sm"
        >
          {oauthLoading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <ExternalLink className="size-4" />
          )}
          {bound ? '重新授权' : '去平台授权'}
        </button>
        {oauthError && (
          <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-3 py-2 text-xs text-foreground/80">
            <AlertTriangle className="size-3.5 shrink-0" />
            <span className="leading-relaxed">{oauthError}</span>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          跳转至平台官方授权页，安全便捷，无需手动复制 Token
        </p>
      </div>

      {/* 高级 · 手动填写凭证（折叠） */}
      <div className="border-t border-border pt-3">
        <button
          type="button"
          onClick={() => setManualOpen((v) => !v)}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          aria-expanded={manualOpen}
        >
          <Wrench className="size-3.5" />
          高级 · 手动填写凭证
          {manualOpen ? (
            <ChevronDown className="size-3.5" />
          ) : (
            <ChevronRight className="size-3.5" />
          )}
        </button>
        {manualOpen && (
          <div className="mt-3">
            <PlatformCredentialForm
              platform={platform}
              companyId={companyId}
              boundInfo={boundInfo}
              onSaved={onFormDone}
              onCancel={onCancel}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   平台授权中心
   ═══════════════════════════════════════════════════════════════ */
export default function PlatformAuthSection() {
  const { user } = useAuth();
  const companyId = user?.company_id ? String(user.company_id) : '';
  const [searchParams, setSearchParams] = useSearchParams();

  const [platforms, setPlatforms] = useState([]);
  const [boundMap, setBoundMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [expandedCode, setExpandedCode] = useState(null);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const searchInputRef = useRef(null);

  // OAuth 相关状态
  const [oauthLoadingCode, setOauthLoadingCode] = useState(null); // 正在拉授权 URL 的平台 code
  const [oauthError, setOauthError] = useState(null);             // { platform, message } | null
  const [oauthToast, setOauthToast] = useState(null);             // { type, message } | null

  // 打开搜索时自动聚焦
  useEffect(() => {
    if (isSearchOpen && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [isSearchOpen]);

  const loadBound = useCallback(async () => {
    if (!companyId) {
      setBoundMap({});
      return;
    }
    const bound = await getBoundCredentials(companyId);
    const map = {};
    (bound || []).forEach((b) => {
      map[b.platform] = b;
    });
    setBoundMap(map);
  }, [companyId]);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const list = await getPlatforms();
        const bound = companyId
          ? await getBoundCredentials(companyId).catch(() => [])
          : [];
        if (!alive) return;
        setPlatforms(list || []);
        if (!companyId) {
          setError('当前账号未关联公司，无法读取或保存平台授权状态');
        }
        const map = {};
        (bound || []).forEach((b) => {
          map[b.platform] = b;
        });
        setBoundMap(map);
      } catch (e) {
        if (!alive) return;
        setError(e?.response?.data?.detail || '加载平台列表失败，请稍后重试');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [companyId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return platforms.filter((p) => {
      const bound = !!boundMap[p.code]?.bound;
      if (filter === 'authorized' && !bound) return false;
      if (filter === 'unauthorized' && bound) return false;
      if (!q) return true;
      return (
        p.name_display?.toLowerCase().includes(q) ||
        p.description?.toLowerCase().includes(q) ||
        p.code?.toLowerCase().includes(q)
      );
    });
  }, [platforms, boundMap, filter, query]);

  const counts = useMemo(() => {
    const authorized = platforms.filter((p) => boundMap[p.code]?.bound).length;
    return { all: platforms.length, authorized, unauthorized: platforms.length - authorized };
  }, [platforms, boundMap]);

  const handleToggle = (code) => {
    setExpandedCode((prev) => (prev === code ? null : code));
  };

  // 凭证表单保存/解绑后回调：刷新已授权状态并收起表单
  const handleFormDone = useCallback(async () => {
    await loadBound();
    setExpandedCode(null);
  }, [loadBound]);

  // OAuth 回调成功：从 /settings?oauth=success 回来时，弹成功提示并刷新已授权列表
  useEffect(() => {
    if (searchParams.get('oauth') !== 'success') return;
    setOauthToast({ type: 'success', message: '平台授权成功' });
    loadBound();
    // 清掉 oauth 参数，避免刷新或返回时重复触发
    const next = new URLSearchParams(searchParams);
    next.delete('oauth');
    setSearchParams(next, { replace: true });
  }, [searchParams, loadBound, setSearchParams]);

  // toast 自动消失
  useEffect(() => {
    if (!oauthToast) return undefined;
    const t = setTimeout(() => setOauthToast(null), 4000);
    return () => clearTimeout(t);
  }, [oauthToast]);

  // 点击"去平台授权"：拉取授权 URL 并跳转平台官方授权页
  const handleAuthorize = useCallback(async (platformCode) => {
    if (!companyId) {
      setOauthError({
        platform: platformCode,
        message: '当前账号未关联公司，无法发起平台授权',
      });
      return;
    }
    setOauthLoadingCode(platformCode);
    setOauthError(null);
    try {
      const data = await getAuthorizeUrl(platformCode);
      const url = data?.authorize_url;
      if (!url) throw new Error('未返回授权 URL');
      // 跳转平台授权页；授权完成后平台回跳 /oauth/callback
      // 不在此处重置 oauthLoadingCode —— 页面即将整体跳走，组件会卸载
      window.location.href = url;
    } catch (e) {
      setOauthError({
        platform: platformCode,
        message:
          e?.response?.data?.detail ||
          e?.userMessage ||
          e?.message ||
          '获取授权链接失败，请稍后重试',
      });
      setOauthLoadingCode(null);
    }
  }, [companyId]);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          平台授权管理
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          绑定您的电商平台账号，让数字员工为您工作
        </p>
      </header>

      {/* OAuth 结果提示（成功/失败），4 秒后自动消失 */}
      {oauthToast && (
        <div
          className={cn(
            'flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs',
            oauthToast.type === 'success' ? 'bg-macaron-mint/60' : 'bg-macaron-rose/40'
          )}
          style={{
            color: oauthToast.type === 'success' ? SUCCESS_COLOR : 'var(--destructive)',
          }}
          role="status"
        >
          {oauthToast.type === 'success' ? (
            <Check className="size-4 shrink-0" />
          ) : (
            <AlertTriangle className="size-4 shrink-0" />
          )}
          <span className="flex-1">{oauthToast.message}</span>
          <button
            type="button"
            onClick={() => setOauthToast(null)}
            aria-label="关闭提示"
            className="inline-flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        </div>
      )}

      {/* 筛选标签 + 搜索图标按钮（点击展开搜索框） */}
      <div className="flex items-center gap-3">
        <div className="inline-flex w-fit shrink-0 items-center gap-1 rounded-xl border border-border bg-card p-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                filter === f.key
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {f.label}
              <span
                className={cn(
                  'rounded-full px-1.5 text-[10px]',
                  filter === f.key ? 'bg-primary-foreground/20' : 'bg-secondary'
                )}
              >
                {counts[f.key]}
              </span>
            </button>
          ))}
        </div>

        {isSearchOpen ? (
          <div className="relative w-full sm:w-56 sm:shrink-0">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={searchInputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onBlur={() => { if (!query) setIsSearchOpen(false); }}
              placeholder="搜索平台..."
              className="input-base h-10 pl-9"
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setIsSearchOpen(true)}
            aria-label="搜索平台"
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Search className="size-4" />
          </button>
        )}
      </div>

      {/* 列表区 */}
      {loading ? (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-border bg-card py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          加载平台列表…
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-3 text-xs text-foreground/80">
          <AlertTriangle className="size-4" />
          {error}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border bg-card/50 py-16 text-center">
          <Link2 className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">没有匹配的平台</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {filtered.map((p, idx) => (
            <PlatformCard
              key={p.code}
              platform={p}
              boundInfo={boundMap[p.code]}
              tint={TINTS[idx % TINTS.length]}
              expanded={expandedCode === p.code}
              onToggle={() => handleToggle(p.code)}
            >
              <PlatformAuthBody
                platform={p}
                companyId={companyId}
                boundInfo={boundMap[p.code]}
                oauthLoading={oauthLoadingCode === p.code}
                oauthError={oauthError?.platform === p.code ? oauthError.message : null}
                onAuthorize={() => handleAuthorize(p.code)}
                onFormDone={handleFormDone}
                onCancel={() => setExpandedCode(null)}
              />
            </PlatformCard>
          ))}
        </div>
      )}
    </div>
  );
}
