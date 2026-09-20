import { afterEach, describe, expect, it, vi } from 'vitest';

describe('tools API', () => {
  afterEach(() => vi.restoreAllMocks());

  it('uses the authenticated user shortcut route instead of the admin route', async () => {
    vi.resetModules();
    const get = vi.fn().mockResolvedValue({ data: [{ key: 'search', label: '/达人搜索' }] });
    vi.doMock('@/api/client', () => ({ default: { get } }));

    const { getToolCapabilities } = await import('@/api/tools');
    await expect(getToolCapabilities()).resolves.toEqual([{ key: 'search', label: '/达人搜索' }]);
    expect(get).toHaveBeenCalledWith('/tools/capabilities');
  });
});
