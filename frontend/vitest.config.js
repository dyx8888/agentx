import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_DEMO_ENABLED': JSON.stringify('true'),
    'import.meta.env.VITE_DEMO_USERNAME': JSON.stringify('demo'),
    'import.meta.env.VITE_DEMO_PASSWORD': JSON.stringify('demo123456'),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    globals: true,
    exclude: [
      'e2e/**/*',
      'node_modules/**/*',
    ],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
