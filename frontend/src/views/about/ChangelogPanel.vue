<script setup>
// What an opened version of the changelog shows (views/about/ChangelogTab.vue): its highlights by kind - a short title
// and, when there is one, its sentence - then the way to the full release notes (a side drawer) and the version's page
// on GitHub. Nothing of the notes themselves: no long paragraph is shown here. While a search or a type is on, only the
// highlights that match, and how many more the full notes have.
import { computed } from 'vue'
import { lang, t as T } from '../../i18n/catalog'
import { renderMarkdown } from '../../md'
import * as cl from '../../changelog'
import Icon from '../../components/Icon.vue'

const props = defineProps({
  version: { type: Object, required: true },        // the version, as the server gives it
  highlights: { type: Array, required: true },      // those to show (all of them, or those a filter left)
  filtering: Boolean,
  notes: { type: Number, default: 0 },              // while filtering: how many entries of the full notes match
  more: { type: Number, default: 0 },               // ... more than the highlights shown
  ws: { type: Array, default: () => [] },           // the words searched for, to mark
})
const emit = defineEmits(['notes'])

const kindLabel = (k) => cl.kindLabel(k, T)
const groups = computed(() => cl.byKind(props.highlights))
const derived = computed(() => props.highlights.some((h) => h.derived))

// A highlight's words may carry inline markdown (`code`, *emphasis*): rendered as md.js does, without the paragraph
// around it; the words searched for marked.
const made = new Map()
function inline(s) {
  if (!made.has(s)) made.set(s, renderMarkdown(s).replace(/^<p>([\s\S]*)<\/p>$/, '$1'))
  return props.ws.length ? cl.mark(made.get(s), props.ws) : made.get(s)
}
const said = (words) => ({ html: inline(cl.inLang(words, lang.value)), lang: cl.isEnglish(words, lang.value) ? 'en' : undefined })

const link = computed(() => cl.linkOf(props.version, T))
</script>

<template>
  <div class="cl-panel">
    <template v-if="highlights.length">
      <section v-for="g in groups" :key="g.kind" class="cl-group-k">
        <h5 class="cl-kind"><span class="cl-dot" :class="'tone-' + (cl.TONE[g.kind] || 'plain')" aria-hidden="true"></span>{{ kindLabel(g.kind) }}</h5>
        <ul class="cl-hl">
          <li v-for="(h, i) in g.items" :key="i">
            <span class="cl-hl-title" :lang="said(h.title).lang" v-html="said(h.title).html"></span>
            <span v-if="h.text" class="cl-hl-text" :lang="said(h.text).lang" v-html="said(h.text).html"></span>
          </li>
        </ul>
      </section>
      <p v-if="derived" class="cl-derived">{{ $t('about.changelog.derived') }}</p>
    </template>
    <p v-else-if="!filtering" class="cl-derived">{{ $t('about.changelog.noHighlights') }}</p>
    <div class="cl-acts">
      <button type="button" class="sm" aria-haspopup="dialog" @click="emit('notes')">{{ $t('about.changelog.fullNotes') }}</button>
      <span v-if="filtering && more" class="cl-more">{{ highlights.length ? $t('about.changelog.moreInNotes', { n: more }) : $t('about.changelog.inNotes', { n: notes }, notes) }}</span>
      <a v-if="link" v-tip="link.tip || undefined" class="cl-link" :href="link.url" target="_blank" rel="noopener noreferrer"><Icon name="external" />{{ link.label }}</a>
    </div>
  </div>
</template>
