import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
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
});
