import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/',
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setupTests.ts',
  },
  server: {
    port: 3000,
    proxy: {
      '/workflows': {
        target: 'ws://localhost:8005',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../webapp-build',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          motion: ['framer-motion'],
          markdown: ['react-markdown', 'remark-gfm'],
          icons: ['lucide-react'],
          state: ['zustand'],
          dates: ['date-fns'],
        },
      },
    },
  },
})
