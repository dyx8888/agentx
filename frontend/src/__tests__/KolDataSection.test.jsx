import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import KolDataSection from '@/pages/settings/KolDataSection';

const { mockImportKols, mockSearchKols } = vi.hoisted(() => ({
  mockImportKols: vi.fn(),
  mockSearchKols: vi.fn(),
}));

vi.mock('@/api/kol', () => ({
  importKols: mockImportKols,
  searchKols: mockSearchKols,
}));

function uploadCsv(container, text, name = 'kols.csv') {
  const input = container.querySelector('input[type="file"]');
  const file = new File([text], name, { type: 'text/csv' });
  fireEvent.change(input, { target: { files: [file] } });
}

describe('KolDataSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockImportKols.mockResolvedValue({
      imported: 2,
      updated: 0,
      skipped: 0,
      dry_run: false,
      data_source_summary: { public_web: 1, manual_upload: 1 },
      source_labels: { public_web: '公开网页整理', manual_upload: '人工导入' },
      data_source_warning: 'imported_non_official_sources',
    });
    mockSearchKols.mockResolvedValue({
      total: 0,
      results: [],
      data_source_summary: {},
      source_labels: {},
    });
  });

  it('shows an actionable empty data prompt', () => {
    render(<KolDataSection />);

    expect(screen.getByText('暂无企业达人数据')).toBeInTheDocument();
    expect(screen.getByText(/上传 CSV/)).toBeInTheDocument();
    expect(screen.getByText(/平台授权/)).toBeInTheDocument();
  });

  it('shows readable data source labels after uploading KOL CSV', async () => {
    const { container } = render(<KolDataSection />);
    uploadCsv(
      container,
      [
        'name,platform,category,data_source,followers,engagement_rate',
        '公开网页达人,douyin,护肤,public_web,100000,3.2',
        '人工导入达人,xiaohongshu,护肤,manual_upload,80000,4.1',
      ].join('\n')
    );

    expect(await screen.findByText('公开网页整理 1')).toBeInTheDocument();
    expect(screen.getByText('人工导入 1')).toBeInTheDocument();
  });

  it('shows imported source labels after successful CSV import', async () => {
    const { container } = render(<KolDataSection />);
    uploadCsv(
      container,
      [
        'name,platform,category,data_source,followers,engagement_rate',
        '公开网页达人,douyin,护肤,public_web,100000,3.2',
      ].join('\n')
    );

    fireEvent.click(await screen.findByRole('button', { name: /导入/ }));

    expect(await screen.findByText('导入完成')).toBeInTheDocument();
    expect(screen.getAllByText('公开网页整理 1').length).toBeGreaterThan(0);
    expect(screen.getByText(/聊天回答会使用同一套来源标签/)).toBeInTheDocument();
  });

  it('shows search verification fields aligned with chat KOL cards', async () => {
    mockSearchKols.mockResolvedValueOnce({
      total: 1,
      data_source_summary: { manual_upload: 1 },
      source_labels: { manual_upload: '人工导入' },
      results: [
        {
          id: 1,
          name: '企业护肤达人',
          platform: 'xiaohongshu',
          followers: 120000,
          engagement_rate: 4.2,
          category: '护肤',
          data_source: 'manual_upload',
          source_label: '人工导入',
          source_available_for_search: true,
        },
      ],
    });

    render(<KolDataSection />);
    fireEvent.click(screen.getByRole('button', { name: /搜索验证/ }));

    expect(await screen.findByText('企业护肤达人')).toBeInTheDocument();
    expect(screen.getByText('搜索结果已按企业达人库字段验证：1 条')).toBeInTheDocument();
    expect(screen.getByText(/xiaohongshu · 120,000 粉丝 · 互动率 4.2% · 护肤/)).toBeInTheDocument();
    expect(screen.getAllByText('人工导入').length).toBeGreaterThan(0);
  });

  it('marks mock/demo search results as unavailable for real business search', async () => {
    mockSearchKols.mockResolvedValueOnce({
      total: 1,
      data_source_summary: { demo: 1 },
      source_labels: { demo: '演示数据' },
      results: [
        {
          id: 99,
          name: '演示达人',
          platform: 'douyin',
          followers: 999999,
          engagement_rate: 9.9,
          category: '护肤',
          data_source: 'demo',
          source_label: '演示数据',
          source_available_for_search: false,
        },
      ],
    });

    render(<KolDataSection />);
    fireEvent.click(screen.getByRole('button', { name: /搜索验证/ }));

    expect(await screen.findByText('演示达人')).toBeInTheDocument();
    expect(screen.getByText(/不能用于真实业务搜索/)).toBeInTheDocument();
  });

  it('rejects mock/demo/seed data sources before import', async () => {
    const { container } = render(<KolDataSection />);
    uploadCsv(
      container,
      [
        'name,platform,category,data_source',
        '演示达人,douyin,护肤,mock',
      ].join('\n')
    );

    await waitFor(() => {
      expect(screen.getByText(/data_source 不支持：mock/)).toBeInTheDocument();
    });
    expect(mockImportKols).not.toHaveBeenCalled();
  });

  it('rejects mock/demo source labels before import', async () => {
    const { container } = render(<KolDataSection />);
    uploadCsv(
      container,
      [
        'name,platform,category,data_source,source_label',
        '演示达人,douyin,护肤,manual_upload,demo',
      ].join('\n')
    );

    await waitFor(() => {
      expect(screen.getByText(/来源不能标记为 mock\/demo\/seed\/sample/)).toBeInTheDocument();
    });
    expect(mockImportKols).not.toHaveBeenCalled();
  });

  it('shows a clear error when the CSV is missing required headers', async () => {
    const { container } = render(<KolDataSection />);
    uploadCsv(
      container,
      [
        'name,platform,data_source',
        '缺分类达人,douyin,manual_upload',
      ].join('\n')
    );

    await waitFor(() => {
      expect(screen.getByText(/CSV 缺少必填列：category/)).toBeInTheDocument();
    });
    expect(mockImportKols).not.toHaveBeenCalled();
  });

  it('shows a clear error when the CSV has no data rows', async () => {
    const { container } = render(<KolDataSection />);
    uploadCsv(container, 'name,platform,category,data_source');

    await waitFor(() => {
      expect(screen.getByText(/CSV 至少需要表头和 1 行数据/)).toBeInTheDocument();
    });
    expect(mockImportKols).not.toHaveBeenCalled();
  });
});
