// The about page's update state model: from what GET /api/system/update says (updates.status()), the one state the
// update is in, the facts that go with it, and the actions that are valid in it. Only what updates.py and its endpoints
// can really do: a check (POST /check), fetching and preparing the newest release (POST /prepare), the tray's restart
// into the prepared release (POST /switch) and back into the one before ({ back: true }). Pure: no requests, no words -
// the page turns ids into its own words (about.state.*, about.fact.*, ERRORS[code].key).
//
//   unsupported   a checkout or a container: it does not update itself (`how` says how it is updated); a check still
//                 works, and `found` says what it found (unchecked | current | newer | failed)
//   unchecked     never looked
//   checking      the check the page asked for is under way (the page says so: { checking: true })
//   current       looked, nothing newer
//   newer         a newer release is out
//   downloading   fetching it (progress 0-100)
//   preparing     unpacking it and installing what it needs
//   ready         a newer release is prepared beside the one that runs (switching it in needs the tray: kind "managed")
//   switching     a switch was asked for: the tray restarts into it when what is in hand is done
//   failed        the check, the preparing or the switch did not work (`error`: why, from ERRORS)
//
// Going back to the release run before the last switch is not a state of its own: it is an action (and a fact) of
// every state where nothing is under way, as long as that release is still kept.

// A version as backup._key reads it: three numbers, a pre-release after them sorts before the release itself.
export function versionKey(v) {
  const parts = String(v || '').toLowerCase().replace(/^v/, '').match(/\d+|[a-z]+/g) || []
  const nums = parts.filter((p) => /^\d+$/.test(p)).map(Number)
  const pre = parts.find((p) => !/^\d+$/.test(p)) || ''
  return [...[...nums.slice(0, 3), 0, 0, 0].slice(0, 3), pre ? 0 : 1, pre, pre ? nums.slice(3) : []]
}
export function compareVersions(a, b) {
  const x = versionKey(a), y = versionKey(b)
  for (let i = 0; i < 4; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1
  if (x[4] !== y[4]) return x[4] < y[4] ? -1 : 1
  for (let i = 0; i < Math.max(x[5].length, y[5].length); i++) {
    const p = x[5][i] ?? -1, q = y[5][i] ?? -1
    if (p !== q) return p < q ? -1 : 1
  }
  return 0
}

// What each error code of updates.py (and of the switch endpoint's refusals) means: its words, the step it belongs to,
// and whether trying that step again can help (a release without a package, or an installation without its uv, stays so).
export const ERRORS = {
  'no-repo': { key: 'about.error.noRepo', stage: 'check', retry: false },
  'not-here': { key: 'about.error.notHere', stage: 'prepare', retry: false },
  'no-package': { key: 'about.error.noPackage', stage: 'prepare', retry: false },
  'no-uv': { key: 'about.error.noUv', stage: 'prepare', retry: false },
  checksum: { key: 'about.error.checksum', stage: 'prepare', retry: true },
  incomplete: { key: 'about.error.incomplete', stage: 'prepare', retry: true },
  interrupted: { key: 'about.error.interrupted', stage: 'prepare', retry: true },
  'did-not-start': { key: 'about.error.didNotStart', stage: 'switch', retry: true },
  // (the switch endpoint's 409s: said after the press, never kept in the status)
  'nothing prepared': { key: 'about.error.nothingPrepared', stage: 'switch', retry: false },
  'not-managed': { key: 'about.error.notManaged', stage: 'switch', retry: false },
  'no-previous': { key: 'about.error.noPrevious', stage: 'switch', retry: false },
}
// An error code as the page says it: { code, key, params, stage, retry }; null for none. "network:<what>" is a check
// that did not reach GitHub; any other code is what stopped the preparing (updates.prepare keeps the exception's name).
export function errorOf(code) {
  if (!code) return null
  if (ERRORS[code]) return { code, params: {}, ...ERRORS[code] }
  if (String(code).startsWith('network:')) return { code, key: 'about.error.network', params: {}, stage: 'check', retry: true }
  return { code, key: 'about.error.other', params: { code }, stage: 'prepare', retry: true }
}

// A folder of data/releases as the server describes it ({ name, version, date, local }); an older server gave the name
// alone, which then stands for the version too.
const releaseOf = (name, described) => (name ? (described && described.name === name ? described : { name, version: name, date: '', local: false }) : null)
const versionOf = (rel) => (rel ? rel.version || rel.name : '')

// Which way a switch to `target` goes from what runs: back to an older one, or forward again (after a roll-back the
// release kept is the newer one). Equal versions (two local builds of 2.0.2) are told apart by their day.
export function direction(target, runningVersion, runningRelease) {
  const c = compareVersions(versionOf(target), runningVersion)
  if (c) return c > 0 ? 'forward' : 'back'
  return target.date && runningRelease && runningRelease.date && target.date > runningRelease.date ? 'forward' : 'back'
}

const BUSY = ['checking', 'downloading', 'preparing', 'switching']

export function updateState(st, { checking = false } = {}) {
  const kind = st.kind || ''
  const can = { prepare: kind === 'managed' || kind === 'unmanaged', switch: kind === 'managed' }
  const current = st.current || ''
  const build = releaseOf(st.build, st.build_release)
  // what was prepared, offered only while it is newer than what runs (updates.status() says so too; checked again by
  // its own version, which a local build's folder name does not carry)
  let staged = releaseOf(st.staged, st.staged_release)
  if (staged && compareVersions(versionOf(staged), current) <= 0) staged = null
  const previous = releaseOf(st.previous, st.previous_release)
  const switching = releaseOf(st.switching_to, st.switching_release)
  const pending = releaseOf(st.pending, st.pending_release)
  const latest = st.latest ? { name: st.latest, version: st.latest, date: st.published || '', local: false, prerelease: !!st.prerelease } : null
  const newer = !!(latest && st.newer)
  const error = errorOf(st.error)

  let id
  if (switching) id = 'switching'
  else if (st.status === 'downloading') id = 'downloading'
  else if (st.status === 'preparing') id = 'preparing'
  else if (checking) id = 'checking'
  else if (!can.prepare) id = 'unsupported'
  else if (st.status === 'failed' && error && error.stage !== 'check') id = 'failed'
  else if (staged) id = 'ready'
  else if (error && error.stage === 'check' && !newer) id = 'failed'
  else if (newer) id = 'newer'
  else if (st.checked_at) id = 'current'
  else id = 'unchecked'

  // what the look found, for a copy that does not update itself: its title says that, `how` says the rest
  const found = id !== 'unsupported' ? '' : error && error.stage === 'check' ? 'failed' : newer ? 'newer' : st.checked_at ? 'current' : 'unchecked'
  // the release the state is about (the one being fetched, prepared, switched to, or that failed)
  const target = { switching, downloading: latest, preparing: latest, ready: staged, newer: latest }[id]
    || (id === 'failed' && error.stage === 'prepare' ? latest : id === 'failed' && error.stage === 'switch' ? staged : found === 'newer' ? latest : null)

  const actions = []
  const idle = !BUSY.includes(id)
  let retried = ''
  if (id === 'failed' && error.retry) {
    if (error.stage === 'check') retried = 'check'
    else if (error.stage === 'prepare' && can.prepare && newer) retried = 'prepare'
    else if (error.stage === 'switch' && can.switch && staged) retried = 'switch'
    if (retried) actions.push({ id: 'retry', does: retried, target: retried === 'check' ? null : target })
  }
  if (idle) {
    if (retried !== 'check') actions.push({ id: 'check', does: 'check', target: null })
    if (can.switch && previous) actions.push({ id: 'rollback', does: 'rollback', target: previous, direction: direction(previous, current, build) })
    const prepareBlocked = id === 'failed' && error.stage === 'prepare' && !error.retry
    // (a release that is already there - prepared, or kept from before a roll-back - is switched to, not fetched again)
    const there = [staged, can.switch ? previous : null].some((r) => r && compareVersions(versionOf(r), latest ? latest.version : '') >= 0)
    if (can.prepare && newer && retried !== 'prepare' && !prepareBlocked && !there) {
      actions.push({ id: 'prepare', does: 'prepare', target: latest })
    }
    if (can.switch && staged && retried !== 'switch') actions.push({ id: 'switch', does: 'switch', target: staged })
  }
  // one main action, the last of the row: retry, else switching in what is ready, else fetching what is new
  const main = actions.find((a) => a.id === 'retry') || actions.find((a) => a.id === 'switch') || actions.find((a) => a.id === 'prepare')
  for (const a of actions) a.primary = a === main
  if (main) actions.push(...actions.splice(actions.indexOf(main), 1))
  // a release named in an action by its version alone, unless that is the version that runs (two builds of 2.0.2)
  for (const a of actions) a.qualify = !!a.target && (!a.target.version || compareVersions(a.target.version, current) === 0)

  const facts = [{ id: 'running', release: build && build.local ? build : null, version: current }]
  if (st.checked_at || latest) facts.push({ id: 'latest', release: latest, newer })
  if (staged) facts.push({ id: 'staged', release: staged })
  if (switching) facts.push({ id: 'switching', release: switching })
  else if (pending) facts.push({ id: 'pending', release: pending })
  if (st.when_idle && can.switch && !switching && compareVersions(st.when_idle, current) > 0) facts.push({ id: 'whenIdle', version: st.when_idle })
  if (previous) facts.push({ id: 'previous', release: previous })
  if (st.checked_at) facts.push({ id: 'checked', at: st.checked_at })

  // What the overview sets side by side (presentation only): the version that runs, and the one the state is about - the
  // release being switched to, the one prepared, else the newest out. `moves`: the right one is ahead of what runs (or
  // a switch is under way), so an arrow goes between them; `known`: a check has said something about the right one;
  // `others`: the facts said beside the two, without the ones the two already show.
  const toId = switching ? 'switching' : staged && (id === 'ready' || (id === 'failed' && error.stage === 'switch')) ? 'staged' : 'latest'
  const to = { id: toId, release: { switching, staged, latest }[toId], known: toId !== 'latest' || !!(st.checked_at || latest) }
  const compare = {
    from: facts[0],
    to,
    moves: toId !== 'latest' || newer,
    others: facts.filter((f) => f.id !== 'running' && f.id !== toId && !(f.release && to.release && f.release.name === to.release.name)),
  }

  const TONE = { current: 'ok', ready: 'ok', newer: 'info', checking: 'info', downloading: 'info', preparing: 'info', switching: 'warn', failed: 'bad' }
  return {
    id,
    found,
    tone: TONE[found || id] || '',
    kind,
    target,
    progress: id === 'downloading' ? Math.max(0, Math.min(100, Number(st.progress) || 0)) : null,
    error: id === 'failed' ? error : null,
    // a check that did not reach GitHub while something else is the state (a newer release known from before, a
    // release ready): said beside it
    notice: id !== 'failed' && error && error.stage === 'check' ? error : null,
    // how this copy is updated when it does not do it itself, or switched to what it prepared
    how: id === 'unsupported' ? kind : id === 'ready' && !can.switch ? 'unmanaged' : '',
    facts,
    compare,
    actions,
    notes: newer && st.notes ? { version: latest.version, text: st.notes, url: st.url || '' } : null,
    // the page asks again while something goes on by itself
    follow: ['downloading', 'preparing', 'switching'].includes(id),
    policy: {
      mode: st.mode || 'notify',
      channel: st.channel || 'stable',
      window: { from: (st.window && st.window.from) || '03:00', to: (st.window && st.window.to) || '05:00' },
      // fetching by itself needs a copy that can prepare; a checkout or a container only looks (`reason`, for the page's
      // words: why an option cannot be chosen - "install": it needs an installed copy)
      modes: ['off', 'notify', 'download', 'auto'].map((value) => {
        const disabled = (value === 'download' || value === 'auto') && !can.prepare
        return { value, disabled, reason: disabled ? 'install' : '' }
      }),
      windowApplies: (st.mode || 'notify') === 'auto',
    },
  }
}

// A release as a person reads it: "2.0.2", "2.0.2 (local build, Nov 22)". The folder's own name is never the label.
// (`t` and `day` are the page's: the words and how a day is written.)
export function releaseText(rel, t, day) {
  if (!rel) return ''
  const v = versionOf(rel)
  if (!rel.local) return v
  return rel.date ? t('about.rel.local', { v, d: day(rel.date) }) : t('about.rel.localNoDate', { v })
}
// The same in an action: the version alone, unless it is the version that runs.
export const actionTarget = (a, t, day) => (a.target ? (a.qualify ? releaseText(a.target, t, day) : versionOf(a.target)) : '')

// Where "What's new in 2.0.3" leads (a link, never the notes on the overview): that version's entry in this copy's own
// changelog when it has one - a checkout that is behind, a release folder newer than the program - else the release's
// page; a version that came out after this copy was built is in no changelog of its own. `notes` is updateState's
// `notes`, `versions` the versions of GET /api/about/changelog. null: nothing to link to.
export function whatsNew(notes, versions = []) {
  if (!notes) return null
  if (versions.some((v) => compareVersions(v, notes.version) === 0)) return { version: notes.version, to: { path: '/about/changelog', query: { v: notes.version } } }
  return notes.url ? { version: notes.version, href: notes.url } : null
}

// What "copy diagnostics" puts on the clipboard: the facts of this copy as plain text, for an issue report. Nothing but
// what the about page shows - no setting's value beyond the update ones, no account, no key; the one personal thing is
// the data folder's path.
export function diagnosticsText(about, st, t, day) {
  const lines = [`AutoApply ${about.version}`]
  const add = (label, value) => { if (value) lines.push(`${label}: ${value}`) }
  if (about.build) add(t('about.build'), `${about.build} (${releaseText(about.build_release, t, day) || about.version})`)
  add(t('about.commit'), about.commit)
  add(t('about.runs'), about.kind)
  add(t('about.python'), about.python)
  add(t('about.system'), about.system)
  add(t('about.data'), about.data)
  if (st) {
    add(t('about.channel'), st.channel)
    add(t('about.policy'), st.mode)
    add(t('about.fact.latest'), st.latest)
    add(t('about.fact.staged'), st.staged)
    add(t('about.fact.previous'), st.previous)
    add(t('about.fact.switching'), st.switching_to)
    add(t('about.fact.pending'), st.pending)
    add(t('about.fact.checked'), st.checked_at)
    add(t('about.fact.status'), [st.status, st.error].filter(Boolean).join(' · '))
  }
  return lines.join('\n')
}
