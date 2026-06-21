import KOLCard from './KOLCard';
import DataCard from './DataCard';
import ContentCard from './ContentCard';
import ArtifactCard from './ArtifactCard';
import ReviewActions from './ReviewActions';

/**
 * 卡片渲染分发器
 * 根据 tool_result 事件中的 tool 名称和 data 类型，渲染对应的内联卡片
 * 并附带审核操作按钮
 */
export default function CardRenderer({ toolResult, onReview }) {
  if (!toolResult) return null;

  const { tool, data, result } = toolResult;
  const payload = data || result || {};
  const reviewStatus = toolResult.reviewStatus || payload.review_status;

  // 根据工具名称匹配
  const toolLower = (tool || '').toLowerCase();
  let card = null;

  if (
    toolLower.includes('kol') ||
    toolLower.includes('达人') ||
    toolLower.includes('influencer') ||
    toolLower.includes('search_daren')
  ) {
    card = <KOLCard data={payload} />;
  } else if (
    toolLower.includes('data') ||
    toolLower.includes('分析') ||
    toolLower.includes('analytics') ||
    toolLower.includes('chart') ||
    toolLower.includes('report')
  ) {
    card = <DataCard data={payload} />;
  } else if (
    toolLower.includes('content') ||
    toolLower.includes('script') ||
    toolLower.includes('内容') ||
    toolLower.includes('策划') ||
    toolLower.includes('文案')
  ) {
    card = <ContentCard data={payload} />;
  } else {
    // 根据 data 中的 type 字段二次匹配
    const dataType = (payload.type || '').toLowerCase();
    if (dataType === 'kol' || dataType === '达人') {
      card = <KOLCard data={payload} />;
    } else if (dataType === 'data' || dataType === 'chart' || dataType === '分析') {
      card = <DataCard data={payload} />;
    } else if (dataType === 'content' || dataType === 'script' || dataType === '内容') {
      card = <ContentCard data={payload} />;
    } else if (payload.title || payload.summary || payload.file_type) {
      card = <ArtifactCard data={payload} />;
    }
  }

  if (!card) return null;

  return (
    <div>
      {card}
      <ReviewActions
        reviewStatus={reviewStatus}
        onApprove={() => onReview?.('approve', toolResult)}
        onReject={(reason) => onReview?.('reject', toolResult, reason)}
      />
    </div>
  );
}