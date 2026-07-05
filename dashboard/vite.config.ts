import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// `base` is '/app/' for production builds so the bundle can be served by the
// Nexus API under http://<server>:7777/app/ (assets resolve to /app/assets/…).
// Dev server stays at '/' so `npm run dev` works normally.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/app/' : '/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 7778,
    proxy: {
      '/v1': {
        target: 'http://localhost:7777',
        changeOrigin: true,
      },
      '/mcp': {
        target: 'http://localhost:7777',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:7777',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
}));
