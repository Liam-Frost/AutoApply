// Tests of the interface's own logic: pure functions and what the composables decide (what counts as changed, what a
// deadline is called, which rows stay selected). They run in Node, without a browser; a page as a whole is looked at
// in the demo sandbox (scripts/demo.py), not here.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.js'],
    setupFiles: ['./tests/setup.js'],
  },
})
