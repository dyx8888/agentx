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
      data_source_warning: 'imported_non_official_sources',
    });
    mockSearchKols.mockResolvedValue({ total: 0, results: [], data_source_summary: {} });
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

    expect(await screen.findByText('公开网页 1')).toBeInTheDocument();
    expect(screen.getByText('人工导入 1')).toBeInTheDocument();
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
