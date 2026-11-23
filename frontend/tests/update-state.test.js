// The about page's update state model (src/updatestate.js): from what /api/system/update says, the one state, the facts
// shown and the actions offered - only what updates.py can do. Every status object here is made up, in the shape
// updates.status() gives it.
import { describe, expect, it } from 'vitest'
import { actionTarget, compareVersions, diagnosticsText, direction, errorOf, releaseText, updateState, whatsNew } from '../src/updatestate.js'

const status = (more = {}) => ({
  current: '2.0.2', kind: 'managed', mode: 'notify', channel: 'stable', window: { from: '03:00', to: '05:00' }, latest: '', newer: false, url: '', notes: '',
  published: '', prerelease: false, checked_at: '', status: 'idle', progress: 0, error: '', staged: '', previous: '', history: [],
  staged_release: null, previous_release: null, build: '', build_release: null, switching_to: '', switching_release: null, pending: '', pending_release: null,
  when_idle: '', ...more,
})
const rel = (name, version, date = '', local = name !== version) => ({ name, version, date, local })
const checked = { checked_at: '2026-11-23T10:00', latest: '2.0.2' }
const newer = { checked_at: '2026-11-23T10:00', latest: '2.0.3', newer: true, published: '2026-11-22', notes: '### Added\n- x', url: 'https://example.test/r/2.0.3' }
const ready = { ...newer, status: 'ready', staged: '2.0.3', staged_release: rel('2.0.3', '2.0.3', '2026-11-23') }
const ids = (s) => s.actions.map((a) => a.id)
const primary = (s) => s.actions.filter((a) => a.primary).map((a) => a.id)
const facts = (s) => s.facts.map((f) => f.id)
// the page's words and days, as plain markers
const t = (key, p = {}) => key + (Object.keys(p).length ? JSON.stringify(p) : '')
const day = (d) => 'day:' + d

describe('copies that do not update themselves', () => {
  it('a source checkout: only a check, and how it is updated', () => {
    const s = updateState(status({ kind: 'source', ...newer }))
    expect([s.id, s.found, s.tone, s.target.version]).toEqual(['unsupported', 'newer', 'info', '2.0.3'])      // (the look still says what is out)
    expect(s.how).toBe('source')
    expect(ids(s)).toEqual(['check'])
    expect(facts(s)).toEqual(['running', 'latest', 'checked'])
    expect(s.facts[1]).toMatchObject({ newer: true, release: { version: '2.0.3', date: '2026-11-22' } })
    expect(s.notes).toMatchObject({ version: '2.0.3' })                 // what is new is still said
    expect(s.policy.modes.filter((m) => m.disabled).map((m) => m.value)).toEqual(['download', 'auto'])
  })
  it('a container: the same, told to pull the image', () => {
    const s = updateState(status({ kind: 'container' }))
    expect([s.id, s.found, s.how, ids(s)]).toEqual(['unsupported', 'unchecked', 'container', ['check']])
    const current = updateState(status({ kind: 'container', ...checked }))
    expect([current.found, current.tone, current.target]).toEqual(['current', 'ok', null])
    const off = updateState(status({ kind: 'source', ...checked, error: 'network:ConnectError' }))
    expect([off.found, off.tone, off.notice.key, ids(off)]).toEqual(['failed', 'bad', 'about.error.network', ['check']])
  })
  it('a copy started by hand fetches and prepares, but never offers the switch (that needs the tray)', () => {
    const n = updateState(status({ kind: 'unmanaged', ...newer }))
    expect([n.id, ids(n), primary(n)]).toEqual(['newer', ['check', 'prepare'], ['prepare']])
    const r = updateState(status({ kind: 'unmanaged', ...ready, previous: '2.0.1', previous_release: rel('2.0.1', '2.0.1') }))
    expect([r.id, r.how, ids(r)]).toEqual(['ready', 'unmanaged', ['check']])          // (no switch, no roll-back)
    expect(r.policy.modes.every((m) => !m.disabled)).toBe(true)
  })
})

describe('a managed copy, state by state', () => {
  it('not checked yet', () => {
    const s = updateState(status())
    expect([s.id, s.tone, ids(s), primary(s)]).toEqual(['unchecked', '', ['check'], []])
    expect(facts(s)).toEqual(['running'])
  })
  it('checking: nothing to press while it looks', () => {
    const s = updateState(status(checked), { checking: true })
    expect([s.id, ids(s), s.follow]).toEqual(['checking', [], false])
  })
  it('up to date', () => {
    const s = updateState(status(checked))
    expect([s.id, s.tone, ids(s)]).toEqual(['current', 'ok', ['check']])
    expect(s.facts.find((f) => f.id === 'latest')).toMatchObject({ newer: false, release: { version: '2.0.2' } })
    expect(s.notes).toBe(null)
  })
  it('the channel has no release at all: still up to date, "none found"', () => {
    const s = updateState(status({ checked_at: '2026-11-23T10:00' }))
    expect(s.id).toBe('current')
    expect(s.facts.find((f) => f.id === 'latest').release).toBe(null)
  })
  it('a newer release: fetch and prepare it is the main action', () => {
    const s = updateState(status(newer))
    expect([s.id, s.tone, ids(s), primary(s)]).toEqual(['newer', 'info', ['check', 'prepare'], ['prepare']])
    expect(s.target).toMatchObject({ version: '2.0.3' })
    expect(s.notes).toEqual({ version: '2.0.3', text: '### Added\n- x', url: 'https://example.test/r/2.0.3' })
  })
  it('a pre-release is marked', () => {
    expect(updateState(status({ ...newer, latest: '2.1.0-beta.1', prerelease: true })).target.prerelease).toBe(true)
  })
  it('downloading 40%: its progress, nothing to press, followed', () => {
    const s = updateState(status({ ...newer, status: 'downloading', progress: 40 }))
    expect([s.id, s.progress, ids(s), s.follow]).toEqual(['downloading', 40, [], true])
    expect(s.target.version).toBe('2.0.3')
  })
  it('preparing: nothing to press, followed', () => {
    const s = updateState(status({ ...newer, status: 'preparing', progress: 100 }))
    expect([s.id, s.progress, ids(s), s.follow]).toEqual(['preparing', null, [], true])
  })
  it('ready with a staged version: the switch is the main action', () => {
    const s = updateState(status(ready))
    expect([s.id, s.tone, ids(s), primary(s)]).toEqual(['ready', 'ok', ['check', 'switch'], ['switch']])
    expect(s.target).toEqual(rel('2.0.3', '2.0.3', '2026-11-23'))
    expect(facts(s)).toEqual(['running', 'latest', 'staged', 'checked'])
    expect(s.actions.find((a) => a.id === 'switch').qualify).toBe(false)          // "Switch to 2.0.3"
  })
  it('ready, and a still newer release came out: switch to what is ready, or fetch the newer one', () => {
    const s = updateState(status({ ...ready, latest: '2.0.4' }))
    expect([s.id, ids(s), primary(s)]).toEqual(['ready', ['check', 'prepare', 'switch'], ['switch']])
    expect(s.actions.find((a) => a.id === 'prepare').target.version).toBe('2.0.4')
  })
  it('staged equal to the running version is not offered', () => {
    const same = updateState(status({ ...checked, status: 'ready', staged: '2026-11-23-mine', staged_release: rel('2026-11-23-mine', '2.0.2', '2026-11-23') }))
    expect(same.id).toBe('current')
    expect(ids(same)).toEqual(['check'])
    expect(facts(same)).not.toContain('staged')
    const older = updateState(status({ status: 'ready', staged: '2.0.1', staged_release: rel('2.0.1', '2.0.1') }))
    expect([older.id, ids(older)]).toEqual(['unchecked', ['check']])
  })
  it('switching: the release it restarts into, nothing to press, followed', () => {
    const s = updateState(status({ ...ready, switching_to: '2.0.3', switching_release: rel('2.0.3', '2.0.3') }))
    expect([s.id, s.tone, ids(s), s.follow]).toEqual(['switching', 'warn', [], true])
    expect(s.target.version).toBe('2.0.3')
    expect(facts(s)).toContain('switching')
  })
})

describe('failures, code by code', () => {
  const failed = (error, more = {}) => updateState(status({ ...newer, status: 'failed', error, ...more }))
  it.each(['checksum', 'incomplete', 'interrupted', 'CalledProcessError'])('%s: retry is fetching and preparing again', (code) => {
    const s = failed(code)
    expect([s.id, s.tone, s.error.stage, ids(s), primary(s)]).toEqual(['failed', 'bad', 'prepare', ['check', 'retry'], ['retry']])
    expect(s.actions.find((a) => a.id === 'retry')).toMatchObject({ does: 'prepare', target: { version: '2.0.3' } })
  })
  it('an exception of its own is said with its name', () => {
    expect(failed('CalledProcessError').error).toMatchObject({ key: 'about.error.other', params: { code: 'CalledProcessError' } })
  })
  it.each([['no-package', 'about.error.noPackage'], ['no-uv', 'about.error.noUv'], ['not-here', 'about.error.notHere']])('%s: trying again cannot help - no retry, no prepare', (code, key) => {
    const s = failed(code)
    expect([s.id, s.error.key, ids(s)]).toEqual(['failed', key, ['check']])
  })
  it('did-not-start: retry is the switch again, and going back stays possible', () => {
    const s = updateState(status({ ...ready, status: 'failed', error: 'did-not-start', previous: '2.0.1', previous_release: rel('2.0.1', '2.0.1') }))
    expect([s.id, s.error.stage, ids(s), primary(s)]).toEqual(['failed', 'switch', ['check', 'rollback', 'retry'], ['retry']])
    expect(s.actions.find((a) => a.id === 'retry')).toMatchObject({ does: 'switch', target: { version: '2.0.3' } })
  })
  it('a check that did not reach GitHub, nothing newer known: retry is the check', () => {
    const s = updateState(status({ ...checked, error: 'network:ConnectError' }))
    expect([s.id, s.error.stage, s.error.key, ids(s), primary(s)]).toEqual(['failed', 'check', 'about.error.network', ['retry'], ['retry']])
    expect(s.actions[0]).toMatchObject({ does: 'check', target: null })
  })
  it('no release repository set: said, and only a plain check', () => {
    const s = updateState(status({ error: 'no-repo', checked_at: '2026-11-23T10:00' }))
    expect([s.id, s.error.key, ids(s)]).toEqual(['failed', 'about.error.noRepo', ['check']])
  })
  it('a failed check while a newer release is known: still "newer", the failure said beside it', () => {
    const s = updateState(status({ ...newer, error: 'network:ReadTimeout' }))
    expect([s.id, s.error, s.notice.key]).toEqual(['newer', null, 'about.error.network'])
    const r = updateState(status({ ...ready, error: 'network:ReadTimeout' }))
    expect([r.id, r.notice.stage]).toEqual(['ready', 'check'])
  })
  it('"failed" with its error cleared by a later check is no longer a failure', () => {
    expect(updateState(status({ ...newer, status: 'failed', error: '' })).id).toBe('newer')
  })
  it('the switch endpoint refusals have their words', () => {
    expect(errorOf('nothing prepared').key).toBe('about.error.nothingPrepared')
    expect(errorOf('not-managed').key).toBe('about.error.notManaged')
    expect(errorOf('no-previous').key).toBe('about.error.noPrevious')
    expect(errorOf('')).toBe(null)
  })
})

describe('going back', () => {
  const running = { build: '2026-11-23-design-system', build_release: rel('2026-11-23-design-system', '2.0.2', '2026-11-23') }
  it('previous available: offered in every state where nothing goes on, named by its version and day', () => {
    const s = updateState(status({ ...checked, ...running, previous: '2026-11-22-calendar', previous_release: rel('2026-11-22-calendar', '2.0.2', '2026-11-22') }))
    expect([s.id, ids(s)]).toEqual(['current', ['check', 'rollback']])
    const back = s.actions[1]
    expect([back.direction, back.qualify]).toEqual(['back', true])            // (same version as the one that runs: the day tells them apart)
    expect(actionTarget(back, t, day)).toBe('about.rel.local{"v":"2.0.2","d":"day:2026-11-22"}')
    expect(actionTarget(back, t, day)).not.toContain('2026-11-22-calendar')
    expect(s.facts.find((f) => f.id === 'running').release.name).toBe('2026-11-23-design-system')
    expect(facts(s)).toEqual(['running', 'latest', 'previous', 'checked'])
  })
  it('previous gone: no roll-back', () => {
    expect(ids(updateState(status({ ...checked, previous: '' })))).toEqual(['check'])
  })
  it('not while something goes on', () => {
    const s = updateState(status({ ...newer, status: 'downloading', progress: 5, previous: '2.0.1', previous_release: rel('2.0.1', '2.0.1') }))
    expect(ids(s)).toEqual([])
  })
  it('after a roll-back the release kept is the newer one: "switch back to", by its version alone', () => {
    const s = updateState(status({ ...checked, previous: '2.0.3', previous_release: rel('2.0.3', '2.0.3') }))
    const a = s.actions.find((x) => x.id === 'rollback')
    expect([a.direction, a.qualify, actionTarget(a, t, day)]).toEqual(['forward', false, '2.0.3'])
    // that release is the newest out: switched back to, not fetched again
    const n = updateState(status({ ...newer, previous: '2.0.3', previous_release: rel('2.0.3', '2.0.3') }))
    expect([n.id, ids(n)]).toEqual(['newer', ['check', 'rollback']])
  })
  it('two builds of one version: the later day is forward', () => {
    expect(direction(rel('b', '2.0.2', '2026-11-24'), '2.0.2', rel('a', '2.0.2', '2026-11-23'))).toBe('forward')
    expect(direction(rel('b', '2.0.2', '2026-11-22'), '2.0.2', rel('a', '2.0.2', '2026-11-23'))).toBe('back')
    expect(direction(rel('2.0.1', '2.0.1'), '2.0.2', null)).toBe('back')
  })
})

describe('what is shown besides', () => {
  it('a release staged for the next start, and a switch asked for from a notification', () => {
    const s = updateState(status({ ...checked, pending: '2026-11-24-mine', pending_release: rel('2026-11-24-mine', '2.0.4', '2026-11-24'), when_idle: '2.0.3' }))
    expect(facts(s)).toEqual(['running', 'latest', 'pending', 'whenIdle', 'checked'])
    expect(s.facts.find((f) => f.id === 'pending').release.version).toBe('2.0.4')
  })
  it('the policy: mode, channel, the window only for "auto"', () => {
    expect(updateState(status({ mode: 'auto', channel: 'beta', window: { from: '23:00', to: '02:00' } })).policy)
      .toMatchObject({ mode: 'auto', channel: 'beta', window: { from: '23:00', to: '02:00' }, windowApplies: true })
    expect(updateState(status({ window: {} })).policy).toMatchObject({ windowApplies: false, window: { from: '03:00', to: '05:00' } })
  })
  it('a release reads as its version, a local build with its day - never its folder name', () => {
    expect(releaseText(rel('2.0.3', '2.0.3'), t, day)).toBe('2.0.3')
    expect(releaseText(rel('2026-11-22-calendar', '2.0.2', '2026-11-22'), t, day)).toBe('about.rel.local{"v":"2.0.2","d":"day:2026-11-22"}')
    expect(releaseText(rel('mine', '2.0.2', ''), t, day)).toBe('about.rel.localNoDate{"v":"2.0.2"}')
    expect(releaseText(null, t, day)).toBe('')
  })
  it('an older server without the release descriptions: the folder name stands for the version', () => {
    const s = updateState({ ...status(ready), staged_release: undefined })
    expect([s.id, s.target]).toEqual(['ready', { name: '2.0.3', version: '2.0.3', date: '', local: false }])
  })
})

describe('"What\'s new in X" on the overview: a link, never the notes', () => {
  const notes = updateState(status(newer)).notes
  it("this copy's own changelog has that version (a checkout that is behind): its entry in the changelog", () => {
    expect(whatsNew(notes, ['2.0.3', '2.0.2'])).toEqual({ version: '2.0.3', to: { path: '/about/changelog', query: { v: '2.0.3' } } })
    expect(whatsNew(notes, ['v2.0.3'])).toMatchObject({ to: { query: { v: '2.0.3' } } })          // (read as the server compares versions)
  })
  it('it has not (the usual case: the version came out after this copy was built): the release page', () => {
    expect(whatsNew(notes, ['2.0.2', '2.0.1'])).toEqual({ version: '2.0.3', href: 'https://example.test/r/2.0.3' })
    expect(whatsNew(notes)).toEqual({ version: '2.0.3', href: 'https://example.test/r/2.0.3' })
  })
  it('nothing newer, or nowhere to link to: no link', () => {
    expect(whatsNew(updateState(status(checked)).notes, ['2.0.2'])).toBe(null)
    expect(whatsNew({ version: '2.0.3', text: 'x', url: '' }, ['2.0.2'])).toBe(null)
  })
})

describe('versions', () => {
  it('compare as the server does (backup._key)', () => {
    expect(compareVersions('2.0.10', '2.0.9')).toBe(1)
    expect(compareVersions('2.1.0-beta.1', '2.1.0')).toBe(-1)
    expect(compareVersions('2.1.0-beta.2', '2.1.0-beta.1')).toBe(1)
    expect(compareVersions('v2.0.2', '2.0.2')).toBe(0)
    expect(compareVersions('2.0', '2.0.0')).toBe(0)
  })
})

describe('diagnostics', () => {
  const about = { version: '2.0.2', commit: '', kind: 'managed', python: '3.14.2', system: 'Windows-11', data: 'C:/AutoApply/data', repo: 'someone/project',
    components: [{ name: 'fastapi', version: '1', license: 'MIT' }], changes: 'secret-looking text', build: '2026-11-23-design-system',
    build_release: rel('2026-11-23-design-system', '2.0.2', '2026-11-23') }
  it('the facts of this copy and where updates stand, one per line - nothing else', () => {
    const text = diagnosticsText(about, status({ ...ready, previous: '2026-11-22-calendar' }), t, day)
    const lines = text.split('\n')
    expect(lines[0]).toBe('AutoApply 2.0.2')
    expect(text).toContain('about.build: 2026-11-23-design-system (about.rel.local{"v":"2.0.2","d":"day:2026-11-23"})')
    expect(text).toContain('about.data: C:/AutoApply/data')
    expect(text).toContain('about.fact.staged: 2.0.3')
    expect(text).toContain('about.fact.status: ready')
    expect(text).not.toContain('someone/project')
    expect(text).not.toContain('secret-looking')
    expect(text).not.toContain('Added')                                     // (no release notes)
    expect(lines.every((l) => l === lines[0] || /^[\w.]+(\{.*\})?: \S/.test(l))).toBe(true)
  })
  it('without the update status (it could not be read): the copy alone', () => {
    expect(diagnosticsText({ ...about, build: '', build_release: null, commit: 'abc1234' }, null, t, day).split('\n'))
      .toEqual(['AutoApply 2.0.2', 'about.commit: abc1234', 'about.runs: managed', 'about.python: 3.14.2', 'about.system: Windows-11', 'about.data: C:/AutoApply/data'])
  })
})
