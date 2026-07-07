import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

const API_TARGET = process.env.MKWORLD2SNAP_API_TARGET ?? 'http://localhost:8080';

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
    proxy: {
      '/engine': {
        target: API_TARGET,
        changeOrigin: true,
        secure: false,
      },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: 'assets',
  },
});
