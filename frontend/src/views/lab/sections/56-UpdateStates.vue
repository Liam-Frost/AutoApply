<script setup>
// Lab: the about page's "Software update" in every state of src/updatestate.js, fed with made-up status objects in the
// shape updates.status() gives (the demo runs from source, so the managed states are only seen here). At the top the
// whole card as the page shows it, for the state chosen; under it the state part (UpdateStatus) of every state.
// Pressing an action or changing a setting says what it was; nothing is sent.
import { computed, ref } from 'vue'
import { updateState } from '../../../updatestate'
import UpdateSection from '../../about/UpdateSection.vue'
import UpdateStatus from '../../about/UpdateStatus.vue'

const rel = (name, version, date = '', local = name !== version) => ({ name, version, date, local })
const base = {
  current: '2.0.2', kind: 'managed', mode: 'notify', channel: 'stable', window: { from: '03:00', to: '05:00' }, latest: '', newer: false, url: '', notes: '',
  published: '', prerelease: false, checked_at: '', status: 'idle', progress: 0, error: '', staged: '', previous: '', history: [], staged_release: null,
  previous_release: null, build: '2026-11-23-design-system', build_release: rel('2026-11-23-design-system', '2.0.2', '2026-11-23'), switching_to: '',
  switching_release: null, pending: '', pending_release: null, when_idle: '',
}
// an hour ago on this computer's clock, written as the server writes checked_at (local wall clock, no zone)
const hourAgo = new Date(Date.now() - 3600e3)
const now = new Date(hourAgo.getTime() - hourAgo.getTimezoneOffset() * 60e3).toISOString().slice(0, 16)
const newer = { checked_at: now, latest: '2.0.3', newer: true, published: '2026-11-22', url: 'https://example.test/releases/2.0.3', notes: '### Added\n\n- A made-up change for the lab\n- Another one' }
const ready = { ...newer, status: 'ready', staged: '2.0.3', staged_release: rel('2.0.3', '2.0.3', '2026-11-23') }
const prev = { previous: '2026-11-22-calendar', previous_release: rel('2026-11-22-calendar', '2.0.2', '2026-11-22') }
const plain = { build: '', build_release: null }
// [name, status, checking?, the versions the copy's own changelog has (a checkout that is behind has the newer one)]
const CASES = [
  ['not checked', {}],
  ['checking', { checked_at: now, latest: '2.0.2' }, true],
  ['up to date, previous kept', { checked_at: now, latest: '2.0.2', ...prev }],
  ['newer', newer],
  ['newer pre-release, check failed since', { ...newer, latest: '2.1.0-beta.1', prerelease: true, error: 'network:ConnectError' }],
  ['downloading 40%', { ...newer, status: 'downloading', progress: 40 }],
  ['preparing', { ...newer, status: 'preparing', progress: 100 }],
  ['ready', { ...ready, ...prev, mode: 'auto', window: { from: '02:00', to: '04:30' } }],      // (updating by itself: the switch window is shown)
  ['ready, staged by hand for the next start', { ...ready, pending: '2026-11-24-mine', pending_release: rel('2026-11-24-mine', '2.0.4', '2026-11-24'), when_idle: '2.0.3' }],
  ['switching', { ...ready, switching_to: '2.0.3', switching_release: rel('2.0.3', '2.0.3', '2026-11-23') }],
  ['failed: checksum', { ...newer, status: 'failed', error: 'checksum' }],
  ['failed: no package', { ...newer, status: 'failed', error: 'no-package' }],
  ['failed: did not start', { ...ready, ...prev, status: 'failed', error: 'did-not-start' }],
  ['failed: check', { checked_at: now, latest: '2.0.2', error: 'network:ReadTimeout' }],
  ['rollback available (after a roll-back)', { checked_at: now, latest: '2.0.3', newer: true, previous: '2.0.3', previous_release: rel('2.0.3', '2.0.3'), current: '2.0.2', ...plain }],
  ['started by hand, prepared', { ...ready, kind: 'unmanaged' }],
  ['source checkout, newer out', { ...newer, kind: 'source', ...plain }, false, ['2.0.3', '2.0.2']],
  ['container', { checked_at: now, latest: '2.0.2', kind: 'container', ...plain }],
]
const LOG = ['2.0.2', '2.0.1']
const shown = computed(() => CASES.map(([name, more, checking, log]) => ({ name, st: { ...base, ...more }, model: updateState({ ...base, ...more }, { checking: !!checking }), log: log || LOG })))
const pressed = ref('')
const say = (c, a) => (pressed.value = c.name + ': ' + a.id + (a.target ? ' ' + a.target.name : ''))

// the whole card, for one state; its settings changes are said here, not saved
const whole = ref('ready')
const one = computed(() => shown.value.find((c) => c.name === whole.value) || shown.value[0])
const about = computed(() => ({ version: one.value.st.current, commit: one.value.st.kind === 'source' ? 'abc1234' : '', kind: one.value.st.kind, python: '3.14.2', system: 'Windows-11',
  data: 'C:/Users/someone/AutoApply/data', repo: 'someone/project', build: one.value.st.build, build_release: one.value.st.build_release }))
</script>

<template>
  <p class="lab-note">The whole card as the page shows it, for the state chosen here. Pressed / changed: <b data-t="up-act">{{ pressed || '—' }}</b></p>
  <div class="lab-row">
    <AaSelect v-model="whole" aria-label="Lab: the state the whole card shows" data-t="up-whole">
      <option v-for="c in shown" :key="c.name" :value="c.name">{{ c.name }}</option>
    </AaSelect>
  </div>
  <div data-up-whole>
    <UpdateSection :model="one.model" :about="about" :status="one.st" :changelog="one.log" @act="(a) => say(one, a)" @save="(k, v) => (pressed = 'saved ' + k + ' = ' + JSON.stringify(v))" />
  </div>

  <p class="lab-note">The state part of every state; only the actions valid in it are offered</p>
  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr)); gap: 12px; align-items: start">
    <div v-for="c in shown" :key="c.name" :data-up="c.name">
      <p class="lab-note">{{ c.name }} · <code>{{ c.model.id }}</code></p>
      <div class="card up-sec" style="margin: 0"><UpdateStatus :model="c.model" :changelog="c.log" @act="(a) => say(c, a)" @show-command="pressed = c.name + ': show the command'" /></div>
    </div>
  </div>
</template>
