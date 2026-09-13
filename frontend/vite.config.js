import { defineConfig } from 'vite';

// Without this file `vite build` produced a dist/ containing only CSS: the
// entry point loaded the application with a plain <script src="script.js">,
// which Vite treats as an external asset rather than a module to bundle. The
// deployed page therefore requested a script that did not exist.
//
// index.html now uses <script type="module" src="/script.js">, which Vite
// follows, bundles and fingerprints.
export default defineConfig({
  root: '.',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
    // Leaflet is loaded from a CDN in index.html; keep the warning threshold
    // meaningful for our own code.
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    proxy: {
      // Lets `npm run dev` talk to a locally running Django without CORS.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
