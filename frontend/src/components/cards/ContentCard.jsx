import {
  CopyOutlined,
  EditOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { message } from 'antd';

/**
 * 内容策划卡片
 * 展示内容策划结果：脚本标题、预览、字数、状态
 */
export default function ContentCard({ data }) {
  const handleCopy = () => {
    if (data.content || data.preview) {
      navigator.clipboard.writeText(data.content || data.preview)
        .then(() => message.success('已复制到剪贴板'))
        .catch(() => message.error('复制失败'));
    }
  };

  const statusConfig = {
    draft: { label: '草稿', color: 'bg-[var(--color-canvas-soft-2)] text-[var(--color-mute)]' },
    ready: { label: '就绪', color: 'bg-[var(--color-success-bg-soft)] text-[var(--color-success)]' },
    pending: { label: '待审核', color: 'bg-amber-50 text-amber-600' },
    approved: { label: '已通过', color: 'bg-[var(--color-success-bg-soft)] text-[var(--color-success)]' },
  };
  const status = statusConfig[data.status] || statusConfig.draft;

  return (
    <div className="mt-3 p-4 rounded-xl border border-[var(--color-hairline)] bg-white
      shadow-sm hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-[var(--color-canvas-soft)]
            flex items-center justify-center text-sm text-[var(--color-link)] flex-shrink-0">
            <FileTextOutlined />
          </div>
          <h4 className="text-sm font-semibold text-[var(--color-ink)] truncate">
            {data.title || '内容策划'}
          </h4>
        </div>
        <span
          className={`px-2 py-0.5 text-[10px] font-medium rounded-full flex-shrink-0 ml-2 ${status.color}`}
        >
          {status.label}
        </span>
      </div>

      {/* Type & Word Count */}
      <div className="flex items-center gap-3 mb-2 text-xs text-[var(--color-mute)]">
        {data.script_type && (
          <span className="flex items-center gap-1">
            <EditOutlined />
            {data.script_type}
          </span>
        )}
        {data.word_count && (
          <span className="flex items-center gap-1">
            <FileTextOutlined />
            {data.word_count} 字
          </span>
        )}
        {data.estimated_time && (
          <span className="flex items-center gap-1">
            <ClockCircleOutlined />
            {data.estimated_time}
          </span>
        )}
      </div>

      {/* Content Preview */}
      {(data.preview || data.content) && (
        <div className="relative mb-2">
          <div
            className="p-3 rounded-lg bg-[var(--color-canvas-soft)] border border-[var(--color-hairline)]
              text-xs text-[var(--color-body)] leading-relaxed whitespace-pre-wrap
              max-h-32 overflow-y-auto"
          >
            {data.preview || data.content}
          </div>
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1.5 rounded-md
              bg-white/80 hover:bg-white border border-[var(--color-hairline)]
              text-[var(--color-mute)] hover:text-[var(--color-ink)] transition-colors"
            title="复制内容"
          >
            <CopyOutlined className="text-xs" />
          </button>
        </div>
      )}

      {/* Tags */}
      {data.tags && data.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.tags.map((tag, i) => (
            <span
              key={i}
              className="px-2 py-0.5 text-[10px] rounded-full
                bg-[var(--color-canvas-soft)] text-[var(--color-mute)]
                border border-[var(--color-hairline)]"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}