// The few things of a browser that the modules under test touch when they are loaded (ui.js reads the theme).
// Nothing here behaves like a page - there is no document: a test that needs one belongs in the sandbox walk.
const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)) },
  removeItem: (k) => { store.delete(k) },
  clear: () => store.clear(),
}
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {} }
