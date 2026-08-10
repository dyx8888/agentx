import '@testing-library/jest-dom';

// Mock window.matchMedia for Ant Design
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
  }

  send() {}

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }
}

Object.defineProperty(window, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
});

Object.defineProperty(globalThis, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
});
