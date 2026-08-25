import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

async function loadWebSocketModule(wsBase) {
  vi.resetModules();
  vi.unstubAllEnvs();
  if (wsBase !== undefined) {
    vi.stubEnv('VITE_WS_BASE', wsBase);
  }
  return import('@/lib/useWebSocket');
}

describe('useWebSocket routing', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
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

  it('does not add token query parameters', async () => {
    const { buildWsUrl } = await loadWebSocketModule('wss://backend.example.test/ws');

    expect(buildWsUrl(42)).not.toContain('?token=');
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

    const { useWebSocket } = await loadWebSocketModule();

    renderHook(() => useWebSocket(undefined));

    expect(WebSocketMock).not.toHaveBeenCalled();
  });
});
