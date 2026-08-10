import { UserOutlined, LinkOutlined, StarFilled, EnvironmentOutlined } from '@ant-design/icons';
import { Avatar } from 'antd';

/**
 * 达人搜索卡片
 * 展示 KOL 达人信息：头像、名称、粉丝数、标签、平台、简介
 */
export default function KOLCard({ data }) {
  const kol = data.kol || data;

  return (
    <div className="mt-3 p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-surface)]
      shadow-sm hover:shadow-md transition-shadow">
      {/* Header: Avatar + Name */}
      <div className="flex items-center gap-3 mb-3">
        <Avatar
          src={kol.avatar || kol.avatar_url}
          icon={!kol.avatar && <UserOutlined />}
          size={44}
          className="flex-shrink-0"
          style={{ backgroundColor: 'var(--color-bg-active)' }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-[var(--color-text-primary)] truncate">
              {kol.name || kol.nickname || '未知达人'}
            </h4>
            {kol.verified && (
              <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full
                bg-[var(--color-success-light)] text-[var(--color-success)]">
                已认证
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-xs text-[var(--color-text-tertiary)]">
            {kol.platform && (
              <span className="flex items-center gap-1">
                <EnvironmentOutlined />
                {kol.platform}
              </span>
            )}
            {kol.followers != null && (
              <span className="flex items-center gap-1">
                <StarFilled className="text-amber-400" />
                {formatNumber(kol.followers)} 粉丝
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Description */}
      {kol.description && (
        <p className="text-xs text-[var(--color-text-secondary)] mb-3 line-clamp-2">
          {kol.description}
        </p>
      )}

      {/* Tags */}
      {kol.tags && kol.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {kol.tags.map((tag, i) => (
            <span
              key={i}
              className="px-2 py-0.5 text-[10px] rounded-full
                bg-[var(--color-bg-hover)] text-[var(--color-text-tertiary)]
                border border-[var(--color-border)]"
            >
              {typeof tag === 'string' ? tag : tag.name || tag.label}
            </span>
          ))}
        </div>
      )}

      {/* Stats */}
      {kol.stats && (
        <div className="flex gap-4 mb-3 p-2 rounded-lg bg-[var(--color-bg-hover)]">
          {kol.stats.posts != null && (
            <div className="text-center">
              <div className="text-xs font-semibold text-[var(--color-text-primary)]">{formatNumber(kol.stats.posts)}</div>
              <div className="text-[10px] text-[var(--color-text-tertiary)]">作品</div>
            </div>
          )}
          {kol.stats.avg_likes != null && (
            <div className="text-center">
              <div className="text-xs font-semibold text-[var(--color-text-primary)]">{formatNumber(kol.stats.avg_likes)}</div>
              <div className="text-[10px] text-[var(--color-text-tertiary)]">均赞</div>
            </div>
          )}
          {kol.stats.engagement_rate != null && (
            <div className="text-center">
              <div className="text-xs font-semibold text-[var(--color-text-primary)]">{kol.stats.engagement_rate}%</div>
              <div className="text-[10px] text-[var(--color-text-tertiary)]">互动率</div>
            </div>
          )}
        </div>
      )}

      {/* Link */}
      {kol.link && (
        <a
          href={kol.link}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-accent)]
            hover:text-[var(--color-accent-hover)] transition-colors"
        >
          <LinkOutlined />
          查看主页
        </a>
      )}
    </div>
  );
}

/** 格式化数字（万为单位） */
function formatNumber(num) {
  if (num >= 10000) {
    return (num / 10000).toFixed(1) + '万';
  }
  return num?.toLocaleString?.() || String(num);
}