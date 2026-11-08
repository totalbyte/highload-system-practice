import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// `npm run dev` — сторінки з Vite (гаряче перезавантаження), API — зі стеку Docker через HAProxy.
// Той самий origin, що й у контейнері web за балансувальником, тому CORS не потрібен ні там, ні тут.
const api = process.env.API_URL ?? 'http://localhost:8080';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': api,
      '/health': api,
    },
  },
});
