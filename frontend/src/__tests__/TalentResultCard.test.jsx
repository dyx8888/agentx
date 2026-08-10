import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TalentResultCard from '@/components/TalentResultCard';

const talents = [
  {
    name: 'Alice Beauty',
    handle: '@alice',
    category: 'skincare',
    followers: 120000,
    rate: '5.2%',
  },
  {
    name: 'Bob Style',
    handle: '@bob',
    category: 'fashion',
    followers: 88000,
    rate: '4.4%',
  },
  {
    name: 'Carol Lab',
    handle: '@carol',
    category: 'ingredients',
    followers: 76000,
    rate: '4.9%',
  },
  {
    name: 'Dora Review',
    handle: '@dora',
    category: 'review',
    followers: 64000,
    rate: '3.8%',
  },
];

describe('TalentResultCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:talent-csv');
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  it('uses real local actions for outreach copy, expansion, and CSV export', async () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    render(<TalentResultCard query="skincare" talents={talents} total={talents.length} />);

    expect(screen.queryByText(/即将上线|敬请期待/)).not.toBeInTheDocument();
    expect(screen.queryByText('Dora Review')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /\u67e5\u770b\u5168\u90e8/ }));
    expect(screen.getByText('Dora Review')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: /\u590d\u5236\u9080\u7ea6\u8349\u7a3f/ })[0]);

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        expect.stringContaining('Alice Beauty')
      );
    });
    expect(
      screen.getByText(/\u5df2\u590d\u5236\u9080\u7ea6\u8349\u7a3f/)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /\u5bfc\u51fa/ }));

    expect(globalThis.URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickSpy).toHaveBeenCalled();
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:talent-csv');
  });
});
