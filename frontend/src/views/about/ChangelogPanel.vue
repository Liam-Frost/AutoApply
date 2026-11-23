<script setup>
// What an opened version of the changelog shows (views/about/ChangelogTab.vue): at most six of its changes - the
// release's highlights first, then the others in the release's order - by type, each its one-line summary in the
// interface's language (English where it has none yet, said so); then the way to the full release notes (a side
// drawer) and the version's page on GitHub. No details here: they are in the drawer. While a search or a type is on,
// only the changes that match, and how many more the full notes have.
import { computed } from 'vue'
import { lang, t as T } from '../../i18n/catalog'
import { renderMarkdown } from '../../md'
import * as cl from '../../changelog'
import Icon from '../../components/Icon.vue'

const props = defineProps({
  found: { type: Object, required: true },          // { v, changes, notes }: the version and what the filter left of it (changelog.js filterVersions)
  filtering: Boolean,
  ws: { type: Array, default: () => [] },           // the words searched for, to mark
})
const emit = defineEmits(['notes'])

const typeLabel = (k) => cl.typeLabel(k, T)
const shown = computed(() => cl.shownOf(props.found))
const groups = computed(() => cl.byType(shown.value.changes))

// A summary may carry inline markdown (`code`, *emphasis*): rendered as md.js does, without the paragraph around it;
// the words searched for marked.
const made = new Map()
function inline(s) {
  if (!made.has(s)) made.set(s, renderMarkdown(s).replace(/^<p>([\s\S]*)<\/p>$/, '$1'))
  return props.ws.length ? cl.mark(made.get(s), props.ws) : made.get(s)
}
const said = (words) => ({ html: inline(cl.inLang(words, lang.value)), en: cl.isEnglish(words, lang.value) })

const link = computed(() => cl.linkOf(props.found.v, T))
</script>

<template>
  <div class="cl-panel">
    <template v-if="shown.changes.length">
      <section v-for="g in groups" :key="g.type" class="cl-group-k">
        <h5 class="cl-kind"><span class="cl-dot" :class="'tone-' + (cl.TONE[g.type] || 'plain')" aria-hidden="true"></span>{{ typeLabel(g.type) }}</h5>
        <ul class="cl-hl">
          <li v-for="c in g.items" :key="c.id">
            <span class="cl-hl-title" :lang="said(c.summary).en ? 'en' : undefined" v-html="said(c.summary).html"></span>
            <span v-if="said(c.summary).en" class="cl-en">{{ $t('about.changelog.english') }}</span>
          </li>
        </ul>
      </section>
    </template>
    <p v-else-if="!filtering" class="cl-note">{{ $t('about.changelog.noNotes') }}</p>
    <div class="cl-acts">
      <button type="button" class="sm" aria-haspopup="dialog" @click="emit('notes')">{{ $t('about.changelog.fullNotes') }}</button>
      <span v-if="!shown.changes.length && found.notes" class="cl-more">{{ $t('about.changelog.inNotes', { n: found.notes }, found.notes) }}</span>
      <span v-else-if="shown.more" class="cl-more">{{ $t('about.changelog.moreInNotes', { n: shown.more }) }}</span>
      <a v-if="link" v-tip="link.tip" class="cl-link" :href="link.url" target="_blank" rel="noopener noreferrer"><Icon name="external" />{{ link.label }}</a>
    </div>
  </div>
</template>
