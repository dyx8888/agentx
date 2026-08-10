import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

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
});
