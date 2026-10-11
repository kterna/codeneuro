import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/app/',
  build: { outDir: '../src/codeneuro/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8801' } },
})
