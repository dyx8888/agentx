import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ResetPassword from '@/pages/ResetPassword';

const { mockPost } = vi.hoisted(() => ({
  mockPost: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  default: {
    post: mockPost,
  },
}));

const renderResetPassword = (path = '/reset-password?token=reset-token') =>
  render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <ResetPassword />
    </MemoryRouter>
  );

describe('ResetPassword', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits token and new password to reset endpoint', async () => {
    mockPost.mockResolvedValue({ data: { success: true } });
    renderResetPassword();

    fireEvent.change(screen.getByLabelText('新密码'), {
      target: { value: 'newpass123' },
    });
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'newpass123' },
    });
    fireEvent.submit(screen.getByLabelText('新密码').closest('form'));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/auth/password/reset', {
        token: 'reset-token',
        new_password: 'newpass123',
      });
    });
    expect(await screen.findByText('密码已重置')).toBeInTheDocument();
  });

  it('does not call API when passwords do not match', async () => {
    renderResetPassword();

    fireEvent.change(screen.getByLabelText('新密码'), {
      target: { value: 'newpass123' },
    });
    fireEvent.change(screen.getByLabelText('确认新密码'), {
      target: { value: 'otherpass123' },
    });
    fireEvent.submit(screen.getByLabelText('新密码').closest('form'));

    expect(await screen.findByRole('alert')).toHaveTextContent('两次输入的密码不一致。');
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('blocks submit and links back to forgot password when token is missing', () => {
    renderResetPassword('/reset-password');

    expect(screen.getByRole('alert')).toHaveTextContent('重置链接无效或已过期');
    expect(screen.getByRole('link', { name: '重新发送邮件' })).toHaveAttribute(
      'href',
      '/forgot-password'
    );
    expect(screen.getByRole('button', { name: '重置密码' })).toBeDisabled();
  });
});
