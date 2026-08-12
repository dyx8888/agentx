import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';   // 新增
import path from 'path';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),   // 新增
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    // 强制 React 单实例：避免预构建批次不一致导致出现两份 React，
    // 引发 "Invalid hook call / Cannot read properties of null (reading 'useState')"
    dedupe: ['react', 'react-dom'],
  },
  // 启动时一次性预构建全部依赖，避免运行中发现新依赖触发二次优化与整页重载
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-dom/client',
      'react-router-dom',
      'axios',
      'react-markdown',
      'remark-gfm',
      'lucide-react',
      'clsx',
      'tailwind-merge',
    ],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // WebSocket 代理：目标与 /api 一致，启用 ws 升级支持实时通信
      '/ws': {
        target: 'http://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
});