import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CaptureRequestCard from '@/components/CaptureRequestCard';

const pendingJob = {
  id: 7,
  status: 'pending',
  purpose: 'generic_evidence',
  target_host: 'example.com',
  target_path_prefix: '/',
  expires_at: new Date(Date.now() + 20 * 60_000).toISOString(),
  ticket_expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
  capability_ticket: 'short-lived-ticket',
};

describe('CaptureRequestCard', () => {
  it('hands a pending job to the extension when its capability is still valid', () => {
    const onUse = vi.fn();
    render(<CaptureRequestCard jobs={[pendingJob]} onUse={onUse} />);

    fireEvent.click(screen.getByRole('button', { name: '交给插件' }));

    expect(onUse).toHaveBeenCalledWith(pendingJob);
    expect(screen.queryByRole('button', { name: '重新授权' })).not.toBeInTheDocument();
  });

  it('requires reauthorization instead of handing the extension an expired capability', () => {
    const onRefreshTicket = vi.fn();
    render(
      <CaptureRequestCard
        jobs={[{
          ...pendingJob,
          ticket_expires_at: new Date(Date.now() - 1_000).toISOString(),
        }]}
        onRefreshTicket={onRefreshTicket}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: '重新授权' }));

    expect(onRefreshTicket).toHaveBeenCalledWith(expect.objectContaining({ id: pendingJob.id }));
    expect(screen.queryByRole('button', { name: '交给插件' })).not.toBeInTheDocument();
  });
});
