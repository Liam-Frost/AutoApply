// The interface served by Vite against a demo instance (python scripts/demo.py --serve 8022) - made-up data, for
// working on pages and for looking at /ui-lab:   npx vite --config vite.demo.config.js --port 5180
// AA_API names another server. (vite.config.js proxies to 8000, where a real installation listens.)
import { defineConfig, mergeConfig } from 'vite'
import base from './vite.config.js'

export default mergeConfig(base, defineConfig({ base: '/', server: { proxy: { '/api': process.env.AA_API || 'http://127.0.0.1:8022' } } }))
