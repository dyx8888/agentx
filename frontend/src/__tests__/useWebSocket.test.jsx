import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

async function loadWebSocketModule(wsBase, wsTicket = 'test.ws.ticket') {
  vi.resetModules();
  vi.unstubAllEnvs();
  if (wsBase !== undefined) {
    vi.stubEnv('VITE_WS_BASE', wsBase);
  }
  const createWsTicket = vi.fn(() => Promise.resolve({ ws_ticket: wsTicket }));
  vi.doMock('@/api/auth', () => ({ createWsTicket }));
  const module = await import('@/lib/useWebSocket');
  return { ...module, createWsTicket };
}

describe('useWebSocket routing', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.doUnmock('@/api/auth');
    vi.restoreAllMocks();
  });

  it('defaults to same-origin /ws/connect/{companyId}', async () => {
    const { buildWsUrl } = await loadWebSocketModule();

    expect(buildWsUrl(42)).toBe(`ws://${window.location.host}/ws/connect/42`);
  });

  it('normalizes VITE_WS_BASE override without duplicate /ws', async () => {
    const { buildWsUrl } = await loadWebSocketModule('wss://backend.example.test/ws/');

    expect(buildWsUrl('tenant a')).toBe('wss://backend.example.test/ws/connect/tenant%20a');
  });

  it('appends /ws to override origins that omit it', async () => {
    const { buildWsUrl } = await loadWebSocketModule('wss://backend.example.test/');

    expect(buildWsUrl(42)).toBe('wss://backend.example.test/ws/connect/42');
  });

  it('converts HTTPS override origins to WSS', async () => {
    const { buildWsUrl } = await loadWebSocketModule('https://backend.example.test');

    expect(buildWsUrl(42)).toBe('wss://backend.example.test/ws/connect/42');
  });

  it('does not add token query parameters', async () => {
    const { buildWsUrl } = await loadWebSocketModule('wss://backend.example.test/ws');

    expect(buildWsUrl(42)).not.toContain('?token=');
  });

  it('requests a WS ticket and passes it as a subprotocol', async () => {
    const WebSocketMock = vi.fn(function MockWebSocket(url, protocols) {
      this.url = url;
      this.protocols = protocols;
      this.readyState = WebSocketMock.CONNECTING;
      this.send = vi.fn();
      this.close = vi.fn();
    });
    WebSocketMock.CONNECTING = 0;
    WebSocketMock.OPEN = 1;
    vi.stubGlobal('WebSocket', WebSocketMock);
    Object.defineProperty(window, 'WebSocket', {
      writable: true,
      value: WebSocketMock,
    });

    const { createWsTicket, useWebSocket } = await loadWebSocketModule(
      'wss://backend.example.test/ws',
      'short.ticket.value',
    );

    renderHook(() => useWebSocket(42));

    await waitFor(() => expect(createWsTicket).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(WebSocketMock).toHaveBeenCalledTimes(1));

    expect(WebSocketMock).toHaveBeenCalledWith(
      'wss://backend.example.test/ws/connect/42',
      ['agentx.ws.v1', 'agentx-ticket.short.ticket.value'],
    );
    expect(WebSocketMock.mock.calls[0][0]).not.toContain('?token=');
  });

  it('does not connect when companyId is missing', async () => {
    const WebSocketMock = vi.fn(function MockWebSocket(url) {
      this.url = url;
      this.readyState = WebSocketMock.CONNECTING;
      this.send = vi.fn();
      this.close = vi.fn();
    });
    WebSocketMock.CONNECTING = 0;
    WebSocketMock.OPEN = 1;
    vi.stubGlobal('WebSocket', WebSocketMock);
    Object.defineProperty(window, 'WebSocket', {
      writable: true,
      value: WebSocketMock,
    });

    const { createWsTicket, useWebSocket } = await loadWebSocketModule();

    renderHook(() => useWebSocket(undefined));

    expect(createWsTicket).not.toHaveBeenCalled();
    expect(WebSocketMock).not.toHaveBeenCalled();
  });
});
