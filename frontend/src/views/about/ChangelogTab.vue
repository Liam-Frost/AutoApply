<script>
let live = 0      // a second timeline on the page at once (the lab) gets ids of its own
</script>

<script setup>
// The about page's Changelog tab: every version of CHANGELOG.md on one timeline (backend/autoapply/changelog.py reads
// the file; src/changelog.js decides what shows). A line with a node per version, in runs by year; the latest release
// and the running version open, the others one line each (number, date, how many changes of each kind) that opens.
// A search and category chips narrow it; a version can be gone to (the list beside it on a wide page, a select on a
// narrow one), and the address keeps it: /about/changelog?v=2.0.2. The text of the changelog is English as written;
// what is around it is in the interface's language.
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { t as T } from '../../i18n/catalog'
import { api } from '../../api'
import { dataState } from '../../data'
import { renderMarkdown } from '../../md'
import { dayOf, dayText, localDay } from '../../i18n/format'
import * as cl from '../../changelog'
import DataState from '../../components/DataState.vue'
import EmptyState from '../../components/EmptyState.vue'
import Icon from '../../components/Icon.vue'

// version: the running version (the about page has it). data: { current, versions } given instead of read (the lab).
const props = defineProps({ version: { type: String, default: '' }, data: { type: Object, default: null } })
const route = useRoute()
const router = useRouter()
const prefix = live++ ? 'n' + live + '-' : ''
onUnmounted(() => { live-- })
const idOf = (v) => prefix + cl.anchor(v)

const KIND = {
  added: () => T('about.changelog.kind.added'), changed: () => T('about.changelog.kind.changed'), fixed: () => T('about.changelog.kind.fixed'),
  security: () => T('about.changelog.kind.security'), breaking: () => T('about.changelog.kind.breaking'), removed: () => T('about.changelog.kind.removed'),
  deprecated: () => T('about.changelog.kind.deprecated'), known: () => T('about.changelog.kind.known'), other: () => T('about.changelog.kind.other'),
}
const kindLabel = (k) => (KIND[k] || KIND.other)()
// a section with a heading of its own is named by it (as the file writes it); the standard ones in the page's language
const sectionLabel = (s) => (s.kind === 'other' ? s.title : kindLabel(s.kind))

const raw = ref({ current: '', versions: [] })
const { st, load } = dataState(async () => { raw.value = props.data || (await api.get('/about/changelog')) })
const versions = computed(() => raw.value.versions || [])
const current = computed(() => props.version || raw.value.current || '')

// ── filters ────────────────────────────────────────────────────────────────────────────────────────────────────────
const q = ref('')
const kinds = ref([])
const ws = computed(() => cl.words(q.value))
const filtering = computed(() => kinds.value.length > 0 || ws.value.length > 0)
const totals = computed(() => cl.kindTotals(versions.value))
const shown = computed(() => cl.filterVersions(versions.value, { kinds: kinds.value, q: q.value }))
const groups = computed(() => cl.groupByYear(shown.value))
const hits = computed(() => shown.value.reduce((a, v) => a + v.hits, 0))
const pickKind = (k) => { kinds.value = kinds.value.includes(k) ? kinds.value.filter((x) => x !== k) : [...kinds.value, k] }
const clear = () => { q.value = ''; kinds.value = [] }

// ── what is open ───────────────────────────────────────────────────────────────────────────────────────────────────
// Two sets: the one the reader made, and the one while a filter is on (every version found starts open there, and
// the reader's own is back as it was when the filter is cleared).
const open = ref(new Set())
const openFound = ref(new Set())
watch([q, kinds], () => { if (filtering.value) openFound.value = new Set(shown.value.map((v) => v.version)) })
const mine = () => (filtering.value ? openFound : open)
const isOpen = (v) => mine().value.has(v.version)
function toggle(v) {
  const s = new Set(mine().value)
  if (s.has(v.version)) s.delete(v.version)
  else s.add(v.version)
  mine().value = s
}
const allOpen = computed(() => shown.value.length > 0 && shown.value.every(isOpen))
const toggleAll = () => { mine().value = allOpen.value ? new Set() : new Set(shown.value.map((v) => v.version)) }

// ── going to a version, and the address ────────────────────────────────────────────────────────────────────────────
const wanted = computed(() => cl.versionFromQuery(route.query))
const located = computed(() => cl.findVersion(versions.value, wanted.value))
const notFound = computed(() => !!(st.at && wanted.value && !located.value))
const hrefOf = (v) => router.resolve({ path: route.path, query: cl.queryWith(route.query, v.version), hash: route.hash }).href
const reduced = () => typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

async function locate(name, { focus = true, write = true } = {}) {
  const v = cl.findVersion(versions.value, name)
  if (!v) return
  if (filtering.value && !shown.value.some((x) => x.version === v.version)) clear()      // (it is not among those found: show them all again)
  open.value = new Set(open.value).add(v.version)
  if (filtering.value) openFound.value = new Set(openFound.value).add(v.version)
  if (write && !cl.sameVersion(wanted.value, v.version)) router.replace({ path: route.path, query: cl.queryWith(route.query, v.version), hash: route.hash })
  await nextTick()
  const el = document.getElementById(idOf(v.version))
  if (!el) return
  el.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' })
  if (focus) el.querySelector('.cl-toggle')?.focus({ preventScroll: true })
}
// another address (back, forward, a link): go to what it names
watch(wanted, (v) => { if (v && located.value) locate(v, { focus: false, write: false }) })

// Read (and read again after a failure): what starts open is decided once, when the versions are first there.
let seeded = false
async function read() {
  await load()
  if (seeded || !st.at) return
  seeded = true
  open.value = cl.initialOpen(versions.value, current.value, wanted.value)
  if (located.value) locate(located.value.version, { focus: false, write: false })
}
onMounted(read)

// ── words ──────────────────────────────────────────────────────────────────────────────────────────────────────────
const made = new Map()
function html(md) {
  if (!made.has(md)) made.set(md, renderMarkdown(md))
  return ws.value.length ? cl.mark(made.get(md), ws.value) : made.get(md)
}
const titleOf = (v) => (v.unreleased ? T('about.changelog.unreleased') : v.version)
const dateOf = (v) => (v.unreleased ? T('about.changelog.notReleased') : v.date ? dayOf(localDay(v.date)) : T('about.changelog.noDate'))
const yearOf = (g) => (g.year ? g.year : g.key === 'undated' ? T('about.changelog.noDate') : '')
const linkOf = (v) => {
  const url = cl.safeUrl(v.url)
  if (!url) return null
  const kind = cl.linkKind(url)
  if (kind === 'compare') return { url, label: T('about.changelog.compare'), tip: v.unreleased ? T('about.changelog.compareUnreleased') : T('about.changelog.compareTip', { v: v.version }) }
  if (kind === 'release') return { url, label: T('about.changelog.release'), tip: T('about.changelog.releaseTip', { v: v.version }) }
  return { url, label: T('about.changelog.link'), tip: '' }
}
const isCurrent = (v) => !v.unreleased && cl.sameVersion(v.version, current.value)
</script>

<template>
  <div class="cl">
    <DataState :s="st" :what="$t('about.changelog.title')" @retry="read" />
    <template v-if="st.at">
      <EmptyState v-if="!versions.length" icon="info" :title="$t('about.changelog.noneTitle')" :text="$t('about.changelog.noneText')" />
      <template v-else>
        <div class="filters cl-bar">
          <input v-model="q" class="search" type="search" :placeholder="$t('about.changelog.search')" :aria-label="$t('about.changelog.search')" />
          <span v-if="filtering" class="count" role="status">{{ $t('about.changelog.matches', { n: hits }, hits) }}</span>
          <button v-if="filtering" class="ghost sm" @click="clear"><Icon name="x" />{{ $t('about.changelog.clear') }}</button>
          <span class="grow"></span>
          <AaSelect class="cl-jump" small :model-value="located ? located.version : ''" :placeholder="$t('about.changelog.goTo')" :aria-label="$t('about.changelog.goTo')"
                    @update:model-value="locate($event)">
            <option v-for="v in versions" :key="v.version" :value="v.version">{{ titleOf(v) }} · {{ v.date ? dayText(v.date) : dateOf(v) }}</option>
          </AaSelect>
        </div>
        <div class="cl-kinds">
          <div class="cl-chips" role="group" :aria-label="$t('about.changelog.category')">
            <button v-for="k in totals" :key="k.kind" class="chip sm cl-chip" :aria-pressed="kinds.includes(k.kind) ? 'true' : 'false'" @click="pickKind(k.kind)">
              <span class="cl-dot" :class="'tone-' + (cl.TONE[k.kind] || 'plain')" aria-hidden="true"></span>{{ kindLabel(k.kind) }}<span class="n">{{ k.n }}</span>
            </button>
          </div>
          <span class="grow"></span>
          <button class="ghost sm cl-all" :disabled="!shown.length" @click="toggleAll"><Icon :name="allOpen ? 'chevron_up' : 'chevron'" />{{ allOpen ? $t('about.changelog.collapseAll') : $t('about.changelog.expandAll') }}</button>
        </div>
        <p v-if="notFound" class="callout warn cl-missing" role="status"><Icon name="alert" />{{ $t('about.changelog.notFound', { v: wanted }) }}</p>

        <div class="cl-body">
          <EmptyState v-if="!shown.length" icon="search" :title="$t('about.changelog.noMatch')" :text="$t('about.changelog.noMatchText')">
            <button class="sm" @click="clear">{{ $t('about.changelog.clear') }}</button>
          </EmptyState>
          <ol v-else class="cl-line" :aria-label="$t('about.changelog.title')">
            <li v-for="g in groups" :key="g.key + g.versions[0].version" class="cl-group" :class="'g-' + g.key">
              <h3 v-if="yearOf(g)" class="cl-year"><span>{{ yearOf(g) }}</span></h3>
              <ol class="cl-versions">
                <li v-for="v in g.versions" :id="idOf(v.version)" :key="v.version" class="cl-ver"
                    :class="{ open: isOpen(v), current: isCurrent(v), unreleased: v.unreleased, located: located && located.version === v.version }">
                  <time class="cl-date" :datetime="v.date || null">{{ dateOf(v) }}</time>
                  <span class="cl-node" aria-hidden="true"></span>
                  <div class="cl-main">
                    <div class="cl-head">
                      <h4 class="cl-title">
                        <button class="cl-toggle" :aria-expanded="isOpen(v) ? 'true' : 'false'" :aria-controls="idOf(v.version) + '-b'" @click="toggle(v)">
                          <Icon name="chevron_right" class="cl-chev" />
                          <span class="cl-num">{{ titleOf(v) }}</span>
                        </button>
                      </h4>
                      <span v-if="isCurrent(v)" class="tag info">{{ $t('about.changelog.current') }}</span>
                      <span v-if="!isOpen(v)" class="cl-counts">
                        <span v-for="c in cl.counts(v)" :key="c.kind" class="cl-count"><span class="cl-dot" :class="'tone-' + (cl.TONE[c.kind] || 'plain')" aria-hidden="true"></span>{{ kindLabel(c.kind) }} <span class="num">{{ c.n }}</span></span>
                      </span>
                      <span class="grow"></span>
                      <a v-if="linkOf(v)" v-tip="linkOf(v).tip" class="cl-link" :href="linkOf(v).url" target="_blank" rel="noopener noreferrer"><Icon name="external" />{{ linkOf(v).label }}</a>
                    </div>
                    <div v-if="isOpen(v)" :id="idOf(v.version) + '-b'" class="cl-content">
                      <div v-if="v.summary" class="md cl-summary" v-html="html(v.summary)"></div>
                      <section v-for="(s, i) in v.sections" :key="i" class="cl-sec">
                        <h5 class="cl-sec-head"><span class="tag" :class="cl.TONE[s.kind]">{{ sectionLabel(s) }}</span><span v-if="s.items.length" class="t-meta num">{{ s.items.length }}</span></h5>
                        <div v-if="s.text" class="md cl-text" v-html="html(s.text)"></div>
                        <ul v-if="s.items.length" class="cl-items">
                          <li v-for="(it, j) in s.items" :key="j" class="md cl-item" v-html="html(it)"></li>
                        </ul>
                      </section>
                      <p v-if="!v.summary && !v.sections.length" class="t-meta">{{ $t('about.changelog.noNotes') }}</p>
                    </div>
                  </div>
                </li>
              </ol>
            </li>
          </ol>

          <nav class="cl-index" :aria-label="$t('about.changelog.versions')">
            <div class="cl-index-title t-meta">{{ $t('about.changelog.versions') }}</div>
            <template v-for="g in cl.groupByYear(versions)" :key="'i' + g.key + g.versions[0].version">
              <div v-if="yearOf(g)" class="cl-index-year t-meta">{{ yearOf(g) }}</div>
              <a v-for="v in g.versions" :key="v.version" :href="hrefOf(v)" class="cl-index-v" :class="{ on: located && located.version === v.version }"
                 :aria-current="located && located.version === v.version ? 'location' : null" @click.prevent="locate(v.version)">
                <span class="cut">{{ titleOf(v) }}</span><template v-if="isCurrent(v)"><span class="cl-dot tone-info" aria-hidden="true"></span><span class="cl-sr">{{ $t('about.changelog.current') }}</span></template><span class="grow"></span><span v-if="v.date" class="t-meta num">{{ dateOf(v) }}</span>
              </a>
            </template>
          </nav>
        </div>
        <p class="hint cl-source">{{ $t('about.changelog.source') }}</p>
      </template>
    </template>
  </div>
</template>
