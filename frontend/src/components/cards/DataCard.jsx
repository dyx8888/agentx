import {
  RiseOutlined,
  FallOutlined,
  BarChartOutlined,
  LineChartOutlined,
  PieChartOutlined,
} from '@ant-design/icons';

const CHART_TYPE_ICONS = {
  bar: <BarChartOutlined />,
  line: <LineChartOutlined />,
  pie: <PieChartOutlined />,
};

/**
 * 数据分析卡片
 * 展示数据分析结果：图表预览、数据点、趋势、摘要
 */
export default function DataCard({ data }) {
  const chartType = data.chart_type || data.type || 'bar';

  return (
    <div className="mt-3 p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-surface)]
      shadow-sm hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className="w-8 h-8 rounded-lg bg-[var(--color-bg-hover)]
          flex items-center justify-center text-sm text-[var(--color-accent)]">
          {CHART_TYPE_ICONS[chartType] || <BarChartOutlined />}
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-semibold text-[var(--color-text-primary)] truncate">
            {data.title || '数据分析'}
          </h4>
          {data.period && (
            <span className="text-[10px] text-[var(--color-text-tertiary)]">{data.period}</span>
          )}
        </div>
      </div>

      {/* Chart Preview (Simulated) */}
      {data.data_points && data.data_points.length > 0 && (
        <div className="mb-3">
          {/* Mini bar chart */}
          {chartType === 'bar' && (
            <div className="flex items-end gap-1.5 h-24 p-2 rounded-lg bg-[var(--color-bg-hover)]">
              {data.data_points.map((point, i) => {
                const maxVal = Math.max(...data.data_points.map((p) => p.value));
                const height = maxVal > 0 ? (point.value / maxVal) * 90 : 0;
                return (
                  <div key={i} className="flex-1 flex flex-col items-center justify-end h-full">
                    <div
                      className="w-full rounded-t-sm transition-all"
                      style={{
                        height: `${height}%`,
                        background: 'linear-gradient(180deg, var(--color-accent), var(--color-accent-light))',
                        minHeight: point.value > 0 ? '4px' : '0',
                      }}
                    />
                    <span className="text-[9px] text-[var(--color-text-tertiary)] mt-1 truncate w-full text-center">
                      {point.label}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Mini line chart approximation */}
          {chartType === 'line' && (
            <div className="p-2 rounded-lg bg-[var(--color-bg-hover)]">
              <div className="relative h-20 flex items-end">
                <svg className="w-full h-full" viewBox="0 0 100 40" preserveAspectRatio="none">
                  <polyline
                    fill="none"
                    stroke="var(--color-accent)"
                    strokeWidth="2"
                    points={data.data_points
                      .map((p, i) => {
                        const maxVal = Math.max(...data.data_points.map((dp) => dp.value));
                        const x = (i / (data.data_points.length - 1)) * 100;
                        const y = maxVal > 0 ? 40 - (p.value / maxVal) * 35 : 40;
                        return `${x},${y}`;
                      })
                      .join(' ')}
                  />
                </svg>
              </div>
              <div className="flex justify-between mt-1">
                {data.data_points.slice(0, 6).map((point, i) => (
                  <span key={i} className="text-[9px] text-[var(--color-text-tertiary)]">
                    {point.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Key Metrics */}
      {data.metrics && data.metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-2 mb-3">
          {data.metrics.map((metric, i) => (
            <div
              key={i}
              className="p-2.5 rounded-lg bg-[var(--color-bg-hover)]
                border border-[var(--color-border)]"
            >
              <div className="text-[10px] text-[var(--color-text-tertiary)] mb-0.5">{metric.label}</div>
              <div className="flex items-baseline gap-1">
                <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                  {metric.value}
                </span>
                {metric.change != null && (
                  <span
                    className={`flex items-center text-[10px] font-medium
                      ${metric.change >= 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-error)]'}`}
                  >
                    {metric.change >= 0 ? <RiseOutlined /> : <FallOutlined />}
                    {Math.abs(metric.change)}%
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Summary */}
      {data.summary && (
        <p className="text-xs text-[var(--color-text-secondary)] bg-[var(--color-bg-hover)] p-2.5 rounded-lg border border-[var(--color-border)]">
          {data.summary}
        </p>
      )}
    </div>
  );
}