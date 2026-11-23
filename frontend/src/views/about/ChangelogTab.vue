<script>
const slots = new Set()      // a second changelog on the page at once (the lab) gets ids of its own: the first free number
</script>

<script setup>
// The about page's Changelog tab: every release on one line, newest first, in runs by year - one row each (date, node,
// version, its title in the interface's language, Latest / Current), all of them closed when the tab opens. One version
// is open at most (an accordion): up to six of its changes by type, the highlights first, and the way to its full
// notes in a drawer (ChangelogPanel.vue, ChangelogNotes.vue). A press is not written into the address; a deep link
// (/about/changelog?v=2.0.2 - the overview's "What's new") opens its version once and is then taken out of the
// address, so a refresh shows everything closed again. What is not released yet is a block of its own above the line,
// part of the same accordion, closed too. One search and one type filter narrow the versions; neither opens anything.
// backend/autoapply/changelog.py gives the data (releases.json and the pending change fragments: no network), and
// src/changelog.js decides what shows.
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { lang, t as T } from '../../i18n/catalog'
import { api } from '../../api'
import { dataState } from '../../data'
import { dayOf, localDay } from '../../i18n/format'
import * as cl from '../../changelog'
import ChangelogNotes from './ChangelogNotes.vue'
import ChangelogPanel from './ChangelogPanel.vue'
import DataState from '../../components/DataState.vue'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'
import Menu from '../../components/Menu.vue'
import Trunc from '../../components/Trunc.vue'

// version: the running version (the about page has it). data: { current, versions } given instead of read (the lab).
// address: a deep link (?v=) opens its version; the lab's made-up changelog does not read the address.
const props = defineProps({ version: { type: String, default: '' }, data: { type: Object, default: null }, address: { type: Boolean, default: true } })
const route = useRoute()
const router = useRouter()
let slot = 1
while (slots.has(slot)) slot++
slots.add(slot)
onUnmounted(() => slots.delete(slot))
const prefix = slot > 1 ? 'n' + slot + '-' : ''
const idOf = (v) => prefix + cl.anchor(v)

const raw = ref({ current: '', versions: [] })
const { st, load } = dataState(async () => { raw.value = props.data || (await api.get('/about/changelog')) })
const versions = computed(() => raw.value.versions || [])
const current = computed(() => props.version || raw.value.current || '')
const latest = computed(() => cl.latestOf(versions.value))
const typeLabel = (k) => cl.typeLabel(k, T)

// ── search and type ────────────────────────────────────────────────────────────────────────────────────────────────
const q = ref('')
const type = ref('')
const ws = computed(() => cl.words(q.value))
const filtering = computed(() => !!type.value || ws.value.length > 0)
const found = computed(() => cl.filterVersions(versions.value, { type: type.value, q: q.value, lang: lang.value }))
const foundRel = computed(() => found.value.filter((f) => !f.v.unreleased))
const foundUn = computed(() => found.value.find((f) => f.v.unreleased) || null)
const of = computed(() => new Map(found.value.map((f) => [f.v.version, f])))
const groups = computed(() => cl.groupByYear(foundRel.value.map((f) => f.v)))
const typeItems = computed(() => [
  { id: 'all', label: T('about.changelog.allTypes'), icon: type.value ? undefined : 'check' },
  { divider: true },
  ...cl.typeCounts(versions.value, { q: q.value, lang: lang.value }).map((c) => ({
    id: c.type, label: typeLabel(c.type), hint: T('about.changelog.changeCount', { n: c.n }, c.n),
    icon: type.value === c.type ? 'check' : undefined, disabled: !c.n && type.value !== c.type,
  })),
])
const pickType = (id) => { type.value = id === 'all' ? '' : id }
const clear = () => { q.value = ''; type.value = '' }

// ── the open version ───────────────────────────────────────────────────────────────────────────────────────────────
const open = ref(null)
const missing = ref('')          // a deep link named a version the changelog does not have: said until the next press
const same = (a, b) => (a && b ? cl.sameVersion(a, b) : !a && !b)
const isOpen = (v) => same(open.value, v.version)
const reduced = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
// (an opened version grows to its height - a grid row from 0fr to 1fr, styles/changelog.css; for who asked for no motion it is
// there at once, without even the one frame a transition of no length takes)
const still = reduced()

// A press on a version's row: it opens (and the one that was open closes), or it closes. Only the page changes, not
// the address. The keyboard stays on the row, and the row stays where it can be seen once the one above it has closed.
// (the one that closes because another opens goes at once, and the page is scrolled by what it took away: the row
// pressed stays where it was under the pointer, and its own changes grow below it)
const switching = ref(false)
async function toggle(v) {
  const row = document.getElementById(idOf(v.version) + '-h')
  const was = row ? row.getBoundingClientRect().top : null
  switching.value = !!open.value && !same(open.value, v.version)
  open.value = cl.toggled(open.value, v.version)
  missing.value = ''
  await nextTick()
  if (switching.value && row && was != null) {
    const moved = row.getBoundingClientRect().top - was
    if (Math.abs(moved) > 1) window.scrollBy({ top: moved, behavior: 'instant' })
  }
  switching.value = false
}

// A deep link: the version it names is opened and brought into view (the keyboard left where it is), once - `v` is
// taken out of the address at once, so a refresh, back to it, or another tab and back show everything closed.
// (`v` going away - that replace - is no event: arrival() is null without it)
function arrive() {
  if (!props.address || !st.at) return
  const a = cl.arrival(versions.value, route.query)
  if (!a) return
  if (a.open) { open.value = a.open; reveal(a.open) }
  missing.value = a.missing
  router.replace({ path: route.path, query: a.query, hash: route.hash })
}
async function reveal(name) {
  await nextTick()
  const el = document.getElementById(idOf(name))
  if (el) el.scrollIntoView({ block: 'start', behavior: 'auto' })
}
watch(() => route.query.v, arrive)        // (a link followed while the tab is open)

// Read (and read again after a failure); a deep link is followed once the versions are there.
async function read() {
  await load()
  arrive()
}
onMounted(read)

// ── the full notes (a drawer) ──────────────────────────────────────────────────────────────────────────────────────
const notesOf = ref(null)

// ── words ──────────────────────────────────────────────────────────────────────────────────────────────────────────
const numOf = (v) => (/^\d/.test(v.version) ? 'v' + v.version : v.version)
const dateOf = (v) => dayOf(localDay(v.date))
const yearOf = (g) => (g.year ? g.year : g.key === 'undated' ? T('about.changelog.noDate') : '')
const titleOf = (v) => cl.inLang(v.title, lang.value)
const titleEn = (v) => cl.isEnglish(v.title, lang.value)
const isCurrent = (v) => !v.unreleased && !!current.value && cl.sameVersion(v.version, current.value)
const isLatest = (v) => !!latest.value && latest.value.version === v.version
// (what the filter left of a version: all its changes without one)
const foundOf = (v) => of.value.get(v.version) || { v, changes: [], notes: 0 }
</script>

<template>
  <div class="cl">
    <DataState :s="st" :what="$t('about.changelog.title')" @retry="read" />
    <template v-if="st.at">
      <EmptyState v-if="!versions.length" icon="info" :title="$t('about.changelog.noneTitle')" :text="$t('about.changelog.noneText')" />
      <template v-else>
        <div class="filters cl-bar">
          <input v-model="q" class="search" type="search" :placeholder="$t('about.changelog.search')" :aria-label="$t('about.changelog.search')" />
          <span v-if="filtering" class="count" role="status">{{ $t('about.changelog.versionCount', { n: found.length }, found.length) }}</span>
          <span class="grow"></span>
          <span v-if="type" class="fchip lg cl-chip">{{ typeLabel(type) }}<button type="button" v-tip="$t('about.changelog.removeFilter', { what: typeLabel(type) })"
            :aria-label="$t('about.changelog.removeFilter', { what: typeLabel(type) })" @click="type = ''"><Icon name="x" /></button></span>
          <Menu :label="$t('about.changelog.type')" :items="typeItems" align="end" @pick="pickType">
            <template #trigger="{ toggle: flip, attrs }">
              <button type="button" class="cl-type" :class="{ on: !!type }" v-bind="attrs" @click="flip"><Icon name="filter" />{{ $t('about.changelog.type') }}<Icon name="chevron" class="cl-type-chev" /></button>
            </template>
          </Menu>
        </div>
        <p v-if="missing" class="callout warn cl-missing" role="status"><Icon name="alert" />{{ $t('about.changelog.notFound', { v: missing }) }}</p>

        <EmptyState v-if="!found.length" icon="search" :title="$t('about.changelog.noMatch')" :text="$t('about.changelog.noMatchText')">
          <button class="sm" @click="clear">{{ $t('about.changelog.clear') }}</button>
        </EmptyState>
        <template v-else>
          <!-- what is not released yet: a block of its own, not on the line of releases -->
          <section v-if="foundUn" :id="idOf(foundUn.v.version)" class="cl-un" :class="{ open: isOpen(foundUn.v) }">
            <h3 class="cl-h">
              <button :id="idOf(foundUn.v.version) + '-h'" type="button" class="cl-row" :aria-expanded="isOpen(foundUn.v) ? 'true' : 'false'"
                      :aria-controls="idOf(foundUn.v.version) + '-b'" @click="toggle(foundUn.v)">
                <span class="cl-num">{{ $t('about.changelog.unreleased') }}</span>
                <span class="cl-mid"><Trunc v-if="titleOf(foundUn.v)" class="cl-name" :text="titleOf(foundUn.v)" :lang="titleEn(foundUn.v) ? 'en' : undefined" /></span>
                <Icon name="chevron_right" class="cl-chev" />
              </button>
            </h3>
            <div :id="idOf(foundUn.v.version) + '-b'" class="cl-slot">
              <Transition name="cl-open" :css="!still && !(switching && !isOpen(foundUn.v))">
                <div v-if="isOpen(foundUn.v)" class="cl-grow"><div class="cl-grow-in">
                  <ChangelogPanel :found="foundUn" :filtering="filtering" :ws="ws" @notes="notesOf = foundUn.v" />
                </div></div>
              </Transition>
            </div>
          </section>

          <ol v-if="groups.length" class="cl-line" :aria-label="$t('about.changelog.title')">
            <li v-for="g in groups" :key="g.key + g.versions[0].version" class="cl-run">
              <h3 v-if="yearOf(g)" class="cl-year"><span>{{ yearOf(g) }}</span></h3>
              <ol class="cl-versions">
                <li v-for="v in g.versions" :id="idOf(v.version)" :key="v.version" class="cl-ver" :class="{ open: isOpen(v), current: isCurrent(v) }">
                  <h4 class="cl-h">
                    <button :id="idOf(v.version) + '-h'" type="button" class="cl-row" :aria-expanded="isOpen(v) ? 'true' : 'false'" :aria-controls="idOf(v.version) + '-b'" @click="toggle(v)">
                      <time v-if="v.date" class="cl-date" :datetime="v.date">{{ dateOf(v) }}</time>
                      <span v-else class="cl-date"><span aria-hidden="true">–</span><span class="cl-sr">{{ $t('about.changelog.noDate') }}</span></span>
                      <span class="cl-node" aria-hidden="true"></span>
                      <span class="cl-num">{{ numOf(v) }}</span>
                      <span class="cl-mid">
                        <Trunc v-if="titleOf(v)" class="cl-name" :text="titleOf(v)" :lang="titleEn(v) ? 'en' : undefined" />
                        <span v-if="titleOf(v) && titleEn(v)" class="cl-en">{{ $t('about.changelog.english') }}</span>
                        <span v-if="isLatest(v)" class="tag cl-tag">{{ $t('about.changelog.latest') }}</span>
                        <span v-if="isCurrent(v)" class="tag info cl-tag">{{ $t('about.changelog.current') }}</span>
                      </span>
                      <Icon name="chevron_right" class="cl-chev" />
                    </button>
                  </h4>
                  <div :id="idOf(v.version) + '-b'" class="cl-slot">
                    <Transition name="cl-open" :css="!still && !(switching && !isOpen(v))">
                      <div v-if="isOpen(v)" class="cl-grow"><div class="cl-grow-in">
                        <ChangelogPanel :found="foundOf(v)" :filtering="filtering" :ws="ws" @notes="notesOf = v" />
                      </div></div>
                    </Transition>
                  </div>
                </li>
              </ol>
            </li>
          </ol>
        </template>
      </template>
    </template>
    <ChangelogNotes v-if="notesOf" :version="notesOf" :ws="ws" @close="notesOf = null" />
  </div>
</template>
