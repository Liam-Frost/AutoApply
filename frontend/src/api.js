import { t as T } from './i18n/catalog'
// Where the program is served: "" at the root, "/autoapply" behind a proxy that puts it under that path. The server
// writes it into the page as <base href>.
import { asDate, dateTimeOf } from './i18n/format'
import { lang } from './i18n/catalog'

export const ROOT = new URL(document.baseURI).pathname.replace(/\/$/, '')
// A request the server answers with "sign in first": the page shows the login again (App.vue listens).
export const auth = { onLogin: () => {} }
// Which build of the interface the server serves - every answer says it (X-Build). fresh.js listens: a page left open
// while the program was updated finds that it is not its own.
export const served = { build: '', onBuild: () => {} }

async function req(method, path, body, isForm) {
  // (the page's language: what the server says - a reason, a label, a refusal - comes in it)
  const opt = { method, headers: { 'X-Lang': lang.value } }
  if (body !== undefined) {
    if (isForm) opt.body = body
    else { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body) }
  }
  let r
  // (no answer at all - the server is restarting, stopped, or the network is gone - is said in the applicant's words;
  // what the browser calls it is "Failed to fetch", in whatever language the browser speaks)
  try { r = await fetch(ROOT + '/api' + path, opt) } catch (e) { throw Object.assign(new Error(T('common.offline')), { status: 0, offline: true }) }
  const build = r.headers.get('X-Build')
  if (build && build !== served.build) { served.build = build; served.onBuild(build) }
  if (r.status === 401 && !path.startsWith('/auth/')) auth.onLogin()
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch (e) { /* not json */ }
    throw Object.assign(new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)), { status: r.status })
  }
  return r.json()
}
export const api = {
  get: (p) => req('GET', p),
  post: (p, b) => req('POST', p, b ?? {}),
  put: (p, b) => req('PUT', p, b),
  patch: (p, b) => req('PATCH', p, b),
  del: (p) => req('DELETE', p),
  upload: (p, form) => req('POST', p, form, true),
}
// a server timestamp (UTC without a zone suffix) as a full date and time in the interface language
export const fmt = (iso) => (iso ? dateTimeOf(asDate(iso)) : '')
