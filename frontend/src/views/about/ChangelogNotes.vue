<script setup>
// The full release notes of one version, in a side drawer (views/about/ChangelogTab.vue): its summary and every section
// of CHANGELOG.md as written - never cut - rendered by md.js, with the version's page on GitHub. The notes are English;
// in another interface language one line says so (they are not translated).
import { computed } from 'vue'
import { lang, t as T } from '../../i18n/catalog'
import { renderMarkdown } from '../../md'
import { dayText } from '../../i18n/format'
import * as cl from '../../changelog'
import Icon from '../../components/Icon.vue'
import SideDrawer from '../../components/SideDrawer.vue'

const props = defineProps({
  version: { type: Object, required: true },
  ws: { type: Array, default: () => [] },           // the words searched for, marked in the notes
})
const emit = defineEmits(['close'])

// a section with a heading of its own is named by it (as the file writes it); the standard ones in the page's language
const sectionLabel = (s) => (s.kind === 'other' ? s.title : cl.kindLabel(s.kind, T))

const title = computed(() => (props.version.unreleased ? T('about.changelog.unreleased') : T('about.changelog.notesTitle', { v: props.version.version })))
const sub = computed(() => (props.version.unreleased ? T('about.changelog.notReleased') : props.version.date ? dayText(props.version.date) : T('about.changelog.noDate')))
const link = computed(() => cl.linkOf(props.version, T))

const made = new Map()
function html(md) {
  if (!made.has(md)) made.set(md, renderMarkdown(md))
  return props.ws.length ? cl.mark(made.get(md), props.ws) : made.get(md)
}
</script>

<template>
  <SideDrawer :title="title" :sub="sub" @close="emit('close')">
    <div class="cl-notes-top">
      <p v-if="lang.value !== 'en'" class="cl-derived">{{ $t('about.changelog.notesEnglish') }}</p>
      <a v-if="link" v-tip="link.tip || undefined" class="cl-link" :href="link.url" target="_blank" rel="noopener noreferrer"><Icon name="external" />{{ link.label }}</a>
    </div>
    <div class="cl-notes">
      <div v-if="version.summary" class="md cl-summary" lang="en" v-html="html(version.summary)"></div>
      <section v-for="(s, i) in version.sections" :key="i" class="cl-sec">
        <h4 class="cl-sec-head" :lang="s.kind === 'other' && lang.value !== 'en' ? 'en' : undefined">{{ sectionLabel(s) }}</h4>
        <div v-if="s.text" class="md cl-text" lang="en" v-html="html(s.text)"></div>
        <ul v-if="s.items.length" class="cl-items" lang="en">
          <li v-for="(it, j) in s.items" :key="j" class="md cl-item" v-html="html(it)"></li>
        </ul>
      </section>
      <p v-if="!version.summary && !version.sections.length" class="t-meta">{{ $t('about.changelog.noNotes') }}</p>
    </div>
  </SideDrawer>
</template>
