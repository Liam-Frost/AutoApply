<script setup>
// Lab: the about page's updates card in every state of src/updatestate.js, fed with made-up status objects in the shape
// updates.status() gives (the demo runs from source, so the managed states are only seen here). Pressing an action
// says which one it was; nothing is sent.
import { computed, ref } from 'vue'
import { updateState } from '../../../updatestate'
import UpdatePanel from '../../about/UpdatePanel.vue'

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
const CASES = [
  ['not checked', {}],
  ['checking', { checked_at: now, latest: '2.0.2' }, true],
  ['up to date, previous kept', { checked_at: now, latest: '2.0.2', ...prev }],
  ['newer', newer],
  ['newer pre-release, check failed since', { ...newer, latest: '2.1.0-beta.1', prerelease: true, error: 'network:ConnectError' }],
  ['downloading 40%', { ...newer, status: 'downloading', progress: 40 }],
  ['preparing', { ...newer, status: 'preparing', progress: 100 }],
  ['ready', { ...ready, ...prev }],
  ['ready, staged by hand for the next start', { ...ready, pending: '2026-11-24-mine', pending_release: rel('2026-11-24-mine', '2.0.4', '2026-11-24'), when_idle: '2.0.3' }],
  ['switching', { ...ready, switching_to: '2.0.3', switching_release: rel('2.0.3', '2.0.3', '2026-11-23') }],
  ['failed: checksum', { ...newer, status: 'failed', error: 'checksum' }],
  ['failed: no package', { ...newer, status: 'failed', error: 'no-package' }],
  ['failed: did not start', { ...ready, ...prev, status: 'failed', error: 'did-not-start' }],
  ['failed: check', { checked_at: now, latest: '2.0.2', error: 'network:ReadTimeout' }],
  ['after a roll-back', { checked_at: now, latest: '2.0.3', newer: true, previous: '2.0.3', previous_release: rel('2.0.3', '2.0.3'), current: '2.0.2', build: '', build_release: null }],
  ['started by hand, prepared', { ...ready, kind: 'unmanaged' }],
  ['source checkout, newer out', { ...newer, kind: 'source', build: '', build_release: null }],
  ['container', { checked_at: now, latest: '2.0.2', kind: 'container', build: '', build_release: null }],
]
const shown = computed(() => CASES.map(([name, more, checking]) => ({ name, model: updateState({ ...base, ...more }, { checking: !!checking }) })))
const pressed = ref('')
</script>

<template>
  <p class="lab-note">Each card is one state; only the actions valid in it are offered. Pressed: <b data-t="up-act">{{ pressed || '—' }}</b></p>
  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 420px), 1fr)); gap: 12px; align-items: start">
    <div v-for="c in shown" :key="c.name" :data-up="c.name">
      <p class="lab-note">{{ c.name }} · <code>{{ c.model.id }}</code></p>
      <UpdatePanel :model="c.model" @act="(a) => (pressed = c.name + ': ' + a.id + (a.target ? ' ' + a.target.name : ''))" />
    </div>
  </div>
</template>
