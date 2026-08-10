import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Loader2,
  Check,
  AlertTriangle,
  RefreshCw,
  ArrowLeft,
  Link2,
} from 'lucide-react';
import { exchangeCode } from '@/api/oauth';

/**
 * OAuthCallback — 平台授权回调页
 *
 * 平台授权完成后跳转回前端 /oauth/callback?code=xxx&state=yyy&platform=zzz
 * 本页负责：解析参数 → 调后端换 token → 成功跳设置页 / 失败给重试入口
 *
 * 与 PlatformAuthSection 配合：
 *   点击"去平台授权" → 跳转平台 → 平台回跳本页 → 换 token → 跳 /settings?oauth=success
 */
export default function OAuthCallback() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const code = params.get('code') || '';
  const state = params.get('state') || '';
  const platform = params.get('platform') || '';

  // status: 'loading' | 'success' | 'error'
  const [status, setStatus] = useState('loading');
  const [errorMsg, setErrorMsg] = useState('');

  // 参数缺失则直接报错，不发请求
  const paramsMissing = !code || !state || !platform;

  const runExchange = useCallback(async () => {
    if (!code || !state || !platform) {
      setStatus('error');
      setErrorMsg('回调参数缺失（code/state/platform），请重新发起授权。');
      return;
    }
    setStatus('loading');
    setErrorMsg('');
    try {
      await exchangeCode(platform, code, state);
      setStatus('success');
      // 成功后短暂展示，再跳回设置页（带 oauth=success 标记触发刷新+提示）
      setTimeout(() => {
        navigate('/settings?oauth=success', { replace: true });
      }, 900);
    } catch (e) {
      setStatus('error');
      setErrorMsg(
        e?.response?.data?.detail ||
        e?.userMessage ||
        '授权失败，请稍后重试或检查授权是否已过期'
      );
    }
  }, [code, state, platform, navigate]);

  useEffect(() => {
    if (paramsMissing) {
      setStatus('error');
      setErrorMsg('回调参数缺失（code/state/platform），请重新发起授权。');
      return;
    }
    runExchange();
  }, []);

  return (
    <div className="flex h-svh w-full items-center justify-center bg-background px-4">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-sm">
        {/* 顶部图标 */}
        <div className="mb-5 flex items-center gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-macaron-mint">
            <Link2 className="size-5 text-foreground/75" />
          </div>
          <div className="min-w-0">
            <h1 className="font-heading text-lg font-semibold text-foreground">
              平台授权
            </h1>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {platform ? `正在绑定 ${platform}` : '正在处理授权'}
            </p>
          </div>
        </div>

        {/* 状态主体 */}
        {status === 'loading' && (
          <div className="flex items-center gap-3 rounded-xl bg-secondary/50 px-4 py-4 text-sm text-foreground">
            <Loader2 className="size-4 animate-spin text-primary" />
            <span>授权中，正在换取访问令牌…</span>
          </div>
        )}

        {status === 'success' && (
          <div
            className="flex items-center gap-3 rounded-xl px-4 py-4 text-sm"
            style={{
              backgroundColor: 'color-mix(in oklch, oklch(0.92 0.05 145) 40%, transparent)',
              color: 'oklch(0.55 0.12 145)',
            }}
            role="status"
          >
            <Check className="size-4 shrink-0" />
            <span>授权成功，即将返回设置页…</span>
          </div>
        )}

        {status === 'error' && (
          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-3 rounded-xl border border-macaron-rose bg-macaron-rose/5 px-4 py-4 text-sm text-foreground/80">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span className="leading-relaxed">{errorMsg}</span>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => navigate('/settings', { replace: true })}
                className="btn btn-outline h-9 px-3.5 text-sm"
              >
                <ArrowLeft className="size-4" />
                返回设置
              </button>
              <button
                type="button"
                onClick={runExchange}
                disabled={paramsMissing}
                className="btn btn-primary h-9 px-3.5 text-sm"
              >
                <RefreshCw className="size-4" />
                重试
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
