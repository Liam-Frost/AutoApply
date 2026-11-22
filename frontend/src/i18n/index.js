// Choosing the interface language. The words themselves are catalog.js's (keys, src/locales/<language>.json); this is
// which language the page is in, and following the one the program was set up with.
import { LANGS, chosen, lang, tag, useLanguage } from './catalog'

export { LANGS, lang }

export async function initI18n() {
  document.documentElement.lang = tag()
  await useLanguage(lang.value)
}

// A browser that has not chosen yet follows what the program was set up with (the installer's language, or the system's).
export async function followServerLang() {
  if (chosen()) return
  try {
    const r = await fetch(new URL('api/settings', document.baseURI))
    const v = (await r.json()).settings['ui.lang']
    if (LANGS[v] && v !== lang.value) { lang.value = v; try { localStorage.setItem('lang', v) } catch (e) { /* ignore */ } await initI18n() }
  } catch (e) { /* the page still works in the default language */ }
}

export function setLang(v) {
  try { localStorage.setItem('lang', v) } catch (e) { /* ignore */ }
  // the server needs to know too: notifications, and what the AI writes for the applicant, follow the interface language
  fetch(new URL('api/settings', document.baseURI), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: { 'ui.lang': v } }) }).finally(() => location.reload())
}
