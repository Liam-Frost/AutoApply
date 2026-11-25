import { t as T } from './i18n/catalog'
// A page left open while the program was updated and started again kept running the interface it was loaded with: the
// server answered with the new build, the page went on showing the old one, and what the update brought was not there
// until the page was loaded again by hand (2026-11-24). The server says which build it serves - in the page when it is
// served (<meta name="autoapply-build">) and in every answer (X-Build, api.js). When they differ, the page loads the new
// build at the first moment that loses nothing:
// - when another page of the program is opened (what was typed and not saved has been asked about by then: dirty.js);
// - while it is not looked at, when nothing has been typed into it;
// and until then a notice that stays says so, with the button to do it now.
import { served } from './api'
import { unsaved } from './dirty'
import { toast } from './ui'

const PAGE = (document.querySelector('meta[name="autoapply-build"]') || { content: '' }).content
let stale = false

// (what loading the page again would lose: something typed that dirty.js keeps track of, or a field typed into that it
// does not know of - a reply being written, an address being chosen)
const NOT_TYPED = ['checkbox', 'radio', 'hidden', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image']
const typed = () => unsaved.value.length > 0
  || [...document.querySelectorAll('input, textarea')].some((el) => !NOT_TYPED.includes(el.type) && el.value && el.value !== el.defaultValue)
const loadAgain = () => window.location.reload()

export function isStale() { return stale }

export function noticeBuild(build) {
  if (!PAGE || !build || build === PAGE || stale) return
  stale = true
  if (document.hidden && !typed()) return loadAgain()
  toast(T('common.newBuild'), '', { act: loadAgain, link: T('common.loadItNow'), stay: true })
}

export function installFresh(router) {
  served.onBuild = noticeBuild
  // (registered after dirty.js's guard: by the time this one runs, leaving was allowed)
  router.beforeEach((to, from) => {
    if (!stale || !from.matched.length || to.path === from.path) return true
    window.location.assign(router.resolve(to).href)
    return false
  })
  document.addEventListener('visibilitychange', () => { if (stale && document.hidden && !typed()) loadAgain() })
}
