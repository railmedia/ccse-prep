// @ts-check
import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  server: { host: true },
  vite: {
    server: {
      // Same-origin semantics in dev: the browser calls /api, Vite proxies it.
      proxy: {
        '/api': {
          target: process.env.API_URL ?? 'http://localhost:8000',
          changeOrigin: false,
        },
      },
    },
  },
});
