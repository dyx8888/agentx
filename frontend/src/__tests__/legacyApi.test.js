import { afterEach, describe, expect, it, vi } from 'vitest';

function okStreamResponse() {
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: vi.fn().mockResolvedValue({ done: true }),
      }),
    },
  };
}

describe('legacy lib API compatibility', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('routes legacy agent chat through cookie-backed same-origin chat endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okStreamResponse());
    vi.stubGlobal('fetch', fetchMock);
    const { chatWithAgent } = await import('@/lib/api');

    await chatWithAgent('amy', 'hello', vi.fn());

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers).not.toHaveProperty('Authorization');
    expect(JSON.parse(options.body)).toEqual({ message: 'hello', agent_id: 'amy' });
  });
});
