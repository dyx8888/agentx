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

async function loadStreamChat(apiBase) {
  vi.resetModules();
  vi.unstubAllEnvs();
  if (apiBase !== undefined) {
    vi.stubEnv('VITE_API_BASE_URL', apiBase);
  }
  return (await import('@/api/chat')).streamChat;
}

describe('streamChat API routing', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('defaults to same-origin /api and includes credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okStreamResponse());
    vi.stubGlobal('fetch', fetchMock);
    const streamChat = await loadStreamChat();

    streamChat({ message: 'hello' }, {});

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    );
  });

  it('includes the selected model provider key in the request body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okStreamResponse());
    vi.stubGlobal('fetch', fetchMock);
    const streamChat = await loadStreamChat();

    streamChat({ message: 'hello', model_provider: 'custom_proxy' }, {});

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(options.body)).toEqual(
      expect.objectContaining({
        message: 'hello',
        model_provider: 'custom_proxy',
      })
    );
  });

  it('uses VITE_API_BASE_URL override when configured', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okStreamResponse());
    vi.stubGlobal('fetch', fetchMock);
    const streamChat = await loadStreamChat('https://backend.example.test/api');

    streamChat({ message: 'hello' }, {});

    expect(fetchMock).toHaveBeenCalledWith(
      'https://backend.example.test/api/chat',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('normalizes a trailing slash in VITE_API_BASE_URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okStreamResponse());
    vi.stubGlobal('fetch', fetchMock);
    const streamChat = await loadStreamChat('https://backend.example.test/api/');

    streamChat({ message: 'hello' }, {});

    expect(fetchMock).toHaveBeenCalledWith(
      'https://backend.example.test/api/chat',
      expect.objectContaining({ credentials: 'include' }),
    );
  });
});
