import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // vue-i18n: the Composition API only; messages are compiled when first used (no eval: the page works under a strict
  // content policy); no devtools in the build
  define: { __VUE_I18N_FULL_INSTALL__: true, __VUE_I18N_LEGACY_API__: false, __INTLIFY_PROD_DEVTOOLS__: false, __INTLIFY_DROP_MESSAGE_COMPILER__: false },
  base: './',      // files are found from the <base> the server puts into the page: the program can be served under any path
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
})
