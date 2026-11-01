import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The studio is served by the shop itself at /studio; in development its API calls go to the local shop.
export default defineConfig({
  plugins: [react()],
  base: '/studio/',
  server: { port: 5199, proxy: { '/api': 'http://127.0.0.1:8811' } },
  build: { outDir: '../web/studio', emptyOutDir: true },
});
