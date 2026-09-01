import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const browserConnectorApi = vi.hoisted(() => ({
  getBrowserConnectorStatus: vi.fn(() => Promise.resolve({
    enabled: true,
    reason: 'enabled',
    feature: 'browser_connector',
    company_id: 239,
    user_id: 7,
  })),
  listBrowserConnectorRecords: vi.fn((kind) => {
    const data = {
      creator_profile: [
        {
          kind: 'creator_profile',
          source_event_id: 101,
          platform: 'douyin',
          record: { name: '护肤测评小鹿', platform: 'douyin', followers: 86000 },
        },
        {
          kind: 'creator_profile',
          source_event_id: 102,
          platform: 'douyin',
          record: { name: '彩妆达人A', platform: 'douyin', followers: 120000 },
        },
      ],
      knowledge_observation: [
        {
          kind: 'knowledge_observation',
          source_event_id: 201,
          platform: 'douyin',
          record: { title: '样品履约规则摘要', content: '样品申请需要在商家后台完成审核。' },
        },
      ],
      unmapped_capture: [
        {
          kind: 'unmapped_capture',
          source_event_id: 301,
          platform: 'douyin',
          record: { reason: 'no_normalization_rule_matched' },
        },
      ],
    };
    return Promise.resolve({ total: data[kind]?.length || 0, records: data[kind] || [] });
  }),
  listBrowserConnectorCampaignSnapshots: vi.fn(() => Promise.resolve({
    total: 1,
    read_only: true,
    records: [
      {
        kind: 'campaign_metrics',
        source_event_id: 401,
        platform: 'oceanengine',
        record: { campaign_name: '护肤套装七夕投放', roi: 4.2, spend: 3000 },
      },
    ],
  })),
  importBrowserConnectorKols: vi.fn(() => Promise.resolve({ imported: 2, updated: 1, skipped: 0, records: [] })),
  importBrowserConnectorKnowledge: vi.fn(() => Promise.resolve({ imported: 1, updated: 0, skipped: 0, records: [] })),
}));

vi.mock('@/api/browserConnector', () => browserConnectorApi);

vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({
    user: { username: 'alice', company_id: 239, is_admin: false },
    logout: vi.fn(),
  }),
}));

vi.mock('@/components/SettingsSection/PlatformAuthSection', () => ({
  default: () => <div>平台授权内容</div>,
}));

vi.mock('@/pages/settings/ProfileSection', () => ({
  default: () => <div>个人资料内容</div>,
}));

vi.mock('@/pages/settings/SecuritySection', () => ({
  default: () => <div>账户安全内容</div>,
}));

vi.mock('@/pages/settings/LlmConfigSection', () => ({
  default: () => <div>大模型配置内容</div>,
}));

vi.mock('@/pages/settings/KnowledgeSection', () => ({
  default: () => <div>知识库内容</div>,
}));

vi.mock('@/pages/settings/CompanyProfileSection', () => ({
  default: () => <div>公司资料内容</div>,
}));

vi.mock('@/pages/settings/KolDataSection', () => ({
  default: () => <div>达人数据内容</div>,
}));

import SettingsPage from '@/pages/SettingsPage';

afterEach(() => {
  delete window.__AGENTX_CONNECTOR_CONTENT_SCRIPT__;
  delete window.__AGENTX_CONNECTOR_INJECTED__;
  window.localStorage.clear();
  vi.clearAllMocks();
});

function renderSettingsPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>
  );
}

describe('SettingsPage', () => {
  it('shows onboarding checklist and jumps to setup sections', () => {
    renderSettingsPage();

    expect(screen.getByText('上线前配置清单')).toBeInTheDocument();
    expect(screen.getByText('1. 配置大模型')).toBeInTheDocument();
    expect(screen.getByText('未连接真实数据源时，系统不会用 mock/fallback 冒充业务结果。', { exact: false })).toBeInTheDocument();

    fireEvent.click(screen.getByText('3. 导入达人数据'));
    expect(screen.getByText('达人数据内容')).toBeInTheDocument();

    fireEvent.click(screen.getByText('5. 绑定平台授权'));
    expect(screen.getByText('平台授权内容')).toBeInTheDocument();
  });

  it('shows browser connector as disconnected by default', async () => {
    renderSettingsPage();

    fireEvent.click(screen.getByText('浏览器连接器'));

    expect(screen.getByText('浏览器连接器：未连接')).toBeInTheDocument();
    expect(await screen.findByText('浏览器连接器采集 / 只读来源')).toBeInTheDocument();
    expect(await screen.findByText('后端能力：已开启')).toBeInTheDocument();
  });

  it('shows browser connector as connected when extension marker exists', async () => {
    window.__AGENTX_CONNECTOR_CONTENT_SCRIPT__ = true;

    renderSettingsPage();
    fireEvent.click(screen.getByText('浏览器连接器'));

    expect(screen.getByText('浏览器连接器：已连接')).toBeInTheDocument();
    expect(await screen.findByText('达人候选')).toBeInTheDocument();
  });

  it('shows connector source counts and confirmed import actions', async () => {
    renderSettingsPage();
    fireEvent.click(screen.getByText('浏览器连接器'));

    expect(await screen.findByText('达人候选')).toBeInTheDocument();
    expect(screen.getByText('知识片段')).toBeInTheDocument();
    expect(screen.getByText('投放快照')).toBeInTheDocument();
    expect(screen.getByText('待映射')).toBeInTheDocument();
    expect(await screen.findByText('护肤测评小鹿')).toBeInTheDocument();
    expect(screen.getByText('样品履约规则摘要')).toBeInTheDocument();
    expect(screen.getByText('护肤套装七夕投放')).toBeInTheDocument();
    expect(screen.getByText('已选 2 位达人 / 1 条知识')).toBeInTheDocument();
    expect(screen.getByText('确认导入达人')).not.toBeDisabled();
    expect(screen.getByText('确认写入知识库')).not.toBeDisabled();

    fireEvent.click(screen.getByText('确认导入达人'));
    expect(await screen.findByText('已导入 2 条达人，更新 1 条')).toBeInTheDocument();

    fireEvent.click(screen.getByText('确认写入知识库'));
    expect(await screen.findByText('已写入 1 条知识片段')).toBeInTheDocument();
    expect(browserConnectorApi.importBrowserConnectorKols).toHaveBeenCalledWith({
      dry_run: false,
      event_ids: [101, 102],
    });
    expect(browserConnectorApi.importBrowserConnectorKnowledge).toHaveBeenCalledWith({
      dry_run: false,
      event_ids: [201],
    });
  });

  it('shows browser connector global disabled state without loading records', async () => {
    browserConnectorApi.getBrowserConnectorStatus.mockResolvedValueOnce({
      enabled: false,
      reason: 'browser_connector_disabled',
      feature: 'browser_connector',
      company_id: 239,
      user_id: 7,
    });

    renderSettingsPage();
    fireEvent.click(screen.getByText('浏览器连接器'));

    expect(await screen.findByText('后端能力：未开启')).toBeInTheDocument();
    expect(screen.getByText('浏览器连接器已被全局安全开关关闭', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('确认导入达人')).toBeDisabled();
    expect(screen.getByText('确认写入知识库')).toBeDisabled();
    expect(browserConnectorApi.listBrowserConnectorRecords).not.toHaveBeenCalled();
    expect(browserConnectorApi.listBrowserConnectorCampaignSnapshots).not.toHaveBeenCalled();
  });
});
