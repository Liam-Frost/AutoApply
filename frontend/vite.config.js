import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: './',      // files are found from the <base> the server puts into the page: the program can be served under any path
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
