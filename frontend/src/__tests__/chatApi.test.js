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

  it('reports incomplete EOF instead of successful completion', async () => {
    const onDone = vi.fn();
    const onError = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode('data: {"type":"content","content":"answer"}'),
            })
            .mockResolvedValueOnce({ done: true }),
        }),
      },
    });
    vi.stubGlobal('fetch', fetchMock);
    const streamChat = await loadStreamChat();

    streamChat({ message: 'hello' }, { onDone, onError });
    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'chat_stream_interrupted' })));
    expect(onDone).not.toHaveBeenCalled();
  });
  it('processes multiple final SSE lines and CRLF before completing at EOF', async () => {
    const onContent = vi.fn();
    const onDone = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              done: false,
              value: new TextEncoder().encode(
                'data: {"type":"content","content":"answer"}\r\ndata: [DONE]',
              ),
            })
            .mockResolvedValueOnce({ done: true }),
        }),
      },
    });
    vi.stubGlobal('fetch', fetchMock);
    const streamChat = await loadStreamChat();

    streamChat({ message: 'hello' }, { onContent, onDone });
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onContent).toHaveBeenCalledWith({ type: 'content', content: 'answer' });
  });
});

describe('streamChat terminal-state contract', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  async function run(chunks, { failure, abort = false } = {}) {
    const read = vi.fn();
    chunks.forEach((text) => read.mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(text) }));
    if (failure) read.mockRejectedValueOnce(failure);
    else read.mockResolvedValueOnce({ done: true });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read }) } }));
    const callbacks = { onContent: vi.fn(), onDone: vi.fn(), onError: vi.fn() };
    const streamChat = await loadStreamChat();
    const stop = streamChat({ message: 'synthetic test' }, callbacks);
    if (abort) stop();
    await new Promise((resolve) => setTimeout(resolve, 10));
    return callbacks;
  }

  it('accepts terminal done without final newline exactly once', async () => {
    const c = await run(['data: {"type":"done","conversation_id":42}']);
    expect(c.onDone).toHaveBeenCalledOnce();
    expect(c.onDone).toHaveBeenCalledWith(expect.objectContaining({ conversation_id: 42 }));
    expect(c.onError).not.toHaveBeenCalled();
  });

  it('ignores heartbeat comments and preserves Unicode content', async () => {
    const c = await run([': keepalive\n\ndata: {"type":"content","content":"测试"}\n\n', 'data: {"type":"done"}\n\n']);
    expect(c.onContent).toHaveBeenCalledOnce();
    expect(c.onContent).toHaveBeenCalledWith({ type: 'content', content: '测试' });
    expect(c.onDone).toHaveBeenCalledOnce();
  });

  it('keeps partial content but reports network interruption, not completion', async () => {
    const c = await run(['data: {"type":"content","content":"partial"}\n\n'], { failure: new TypeError('network error') });
    expect(c.onContent).toHaveBeenCalledOnce();
    expect(c.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'chat_stream_interrupted' }));
    expect(c.onDone).not.toHaveBeenCalled();
  });

  it('does not report a completed terminal event as a later network error', async () => {
    const c = await run(['data: {"type":"done"}\n\n'], { failure: new TypeError('network error') });
    expect(c.onDone).toHaveBeenCalledOnce();
    expect(c.onError).not.toHaveBeenCalled();
  });

  it('retains the server error exactly once even when the stream then closes', async () => {
    const c = await run(['data: {"type":"error","code":"model_timeout","message":"model timed out"}\n\n']);
    expect(c.onError).toHaveBeenCalledOnce();
    expect(c.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'model_timeout' }));
    expect(c.onDone).not.toHaveBeenCalled();
  });

  it('does not turn an error followed by done into success', async () => {
    const c = await run(['data: {"type":"error","message":"failed"}\n\ndata: {"type":"done"}\n\n']);
    expect(c.onError).toHaveBeenCalledOnce();
    expect(c.onDone).not.toHaveBeenCalled();
  });

  it('does not emit a transport error after user cancellation', async () => {
    const c = await run([], { failure: new DOMException('Aborted', 'AbortError'), abort: true });
    expect(c.onError).not.toHaveBeenCalled();
    expect(c.onDone).not.toHaveBeenCalled();
  });
});
