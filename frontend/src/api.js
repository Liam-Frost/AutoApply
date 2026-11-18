// Where the program is served: "" at the root, "/autoapply" behind a proxy that puts it under that path. The server
// writes it into the page as <base href>.
export const ROOT = new URL(document.baseURI).pathname.replace(/\/$/, '')
// A request the server answers with "sign in first": the page shows the login again (App.vue listens).
export const auth = { onLogin: () => {} }

async function req(method, path, body, isForm) {
  const opt = { method, headers: {} }
  if (body !== undefined) {
    if (isForm) opt.body = body
    else { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body) }
  }
  let r
  // (no answer at all - the server is restarting, stopped, or the network is gone - is said in the applicant's words;
  // what the browser calls it is "Failed to fetch", in whatever language the browser speaks)
  try { r = await fetch(ROOT + '/api' + path, opt) } catch (e) { throw Object.assign(new Error('连接不上服务：它可能正在重启，或者已经停了'), { status: 0, offline: true }) }
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
// Server timestamps are UTC without a zone suffix.
const asDate = (iso) => new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
export const fmt = (iso) => (iso ? asDate(iso).toLocaleString('zh-CN', { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')
