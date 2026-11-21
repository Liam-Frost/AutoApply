// npm run i18n:status - how complete each translation is, written into src/locales/languages.json (the language
// picker marks those below `beta_below` as a test). Run it after changing a catalog; the tests fail when it was not.
import { readFileSync, writeFileSync } from 'node:fs'
import { completeness } from '../src/i18n/completeness.js'

const dir = new URL('../src/locales/', import.meta.url)
const read = (f) => JSON.parse(readFileSync(new URL(f, dir), 'utf-8'))
const manifest = read('languages.json')
// what the interface says and what the program says (locales/server/): one figure for both
const both = (id) => { let server = {}; try { server = read('server/' + id + '.json') } catch (e) { /* none yet */ } return { ...read(id + '.json'), server } }
const source = both(manifest.source)
for (const l of manifest.languages) {
  l.complete = l.id === manifest.source ? 100 : completeness(source, both(l.id))
  console.log(`${l.id.padEnd(6)} ${String(l.complete).padStart(3)}%${l.complete < manifest.beta_below ? '  (beta)' : ''}`)
}
writeFileSync(new URL('languages.json', dir), JSON.stringify(manifest, null, 2) + '\n')
