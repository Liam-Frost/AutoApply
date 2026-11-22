// The interface served by Vite against a demo instance (python scripts/demo.py --serve 8022) - made-up data, for
// working on pages and for looking at /ui-lab:   npx vite --config vite.demo.config.js --port 5180
// AA_API names another server. (vite.config.js proxies to 8000, where a real installation listens.)
import { defineConfig, mergeConfig } from 'vite'
import base from './vite.config.js'

const target = process.env.AA_API || 'http://127.0.0.1:8022'
// The server refuses a write whose Origin is not its own (a page of another site must not act for the person signed
// in): through this proxy the page's origin is Vite's, so the request is passed on as the demo's own.
const asItsOwn = (proxy) => proxy.on('proxyReq', (req) => { if (req.getHeader('origin')) req.setHeader('origin', target) })

export default mergeConfig(base, defineConfig({ base: '/', server: { proxy: { '/api': { target, changeOrigin: true, configure: asItsOwn } } } }))
