import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import PlatformAuthSection, {
  PLATFORM_API_PAUSED_MESSAGE,
} from '@/components/SettingsSection/PlatformAuthSection';

describe('PlatformAuthSection', () => {
  it('shows the platform API paused state without real authorization actions', () => {
    render(<PlatformAuthSection />);

    expect(screen.getByRole('status')).toHaveTextContent(PLATFORM_API_PAUSED_MESSAGE);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByText(/去平台授权|重新授权|OAuth callback/i)).not.toBeInTheDocument();
  });

  it('does not render sensitive platform credential markers', () => {
    render(<PlatformAuthSection />);

    const text = document.body.textContent || '';
    expect(text).not.toMatch(/Authorization|Bearer|access_token|refresh_token|cookie/i);
    expect(text).not.toContain('secret-that-must-not-appear');
  });
});
