import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProfileSection from '@/pages/settings/ProfileSection';

const { mockUpdateUserProfile } = vi.hoisted(() => ({
  mockUpdateUserProfile: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  updateUserProfile: mockUpdateUserProfile,
}));

describe('ProfileSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:avatar-preview');
  });

  it('allows avatar image selection and local preview instead of a disabled placeholder', () => {
    const { container } = render(
      <ProfileSection
        user={{
          username: 'alice',
          email: 'alice@example.com',
          company_name: 'Acme',
          brand_name: 'Acme Beauty',
          category: 'beauty',
        }}
      />
    );

    const changeButton = screen.getByRole('button', { name: /更换/ });
    expect(changeButton).not.toBeDisabled();

    const input = container.querySelector('input[type="file"]');
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp');

    const file = new File(['avatar'], 'avatar.png', { type: 'image/png' });
    fireEvent.change(input, { target: { files: [file] } });

    expect(globalThis.URL.createObjectURL).toHaveBeenCalledWith(file);
    expect(container.querySelector('img')).toHaveAttribute('src', 'blob:avatar-preview');
  });
});
