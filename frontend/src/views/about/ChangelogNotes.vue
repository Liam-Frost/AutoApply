<script setup>
// The full release notes of one version, in a side drawer (views/about/ChangelogTab.vue): its intro, every change by
// type - its summary in bold, in the interface's language (English where it has none yet, said so), and its details as
// written - then its known limits, and the version's page on GitHub. Never cut; markdown rendered by md.js. Everything
// is in the data the page already has: it works offline (only the GitHub link needs the network). The intro, the
// details and the known limits are written in English; in another interface language one line says so.
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

const typeLabel = (k) => cl.typeLabel(k, T)
const title = computed(() => (props.version.unreleased ? T('about.changelog.unreleased') : T('about.changelog.notesTitle', { v: props.version.version })))
const sub = computed(() => (props.version.unreleased ? T('about.changelog.notReleased') : props.version.date ? dayText(props.version.date) : T('about.changelog.noDate')))
const link = computed(() => cl.linkOf(props.version, T))
const groups = computed(() => cl.byType(props.version.changes))
const limits = computed(() => (props.version.known_limits || []).filter(Boolean))
const empty = computed(() => !props.version.intro && !groups.value.length && !limits.value.length)
// (said only when there is English text to read: the intro, a change's details, a known limit)
const english = computed(() => lang.value !== 'en' && (!!props.version.intro || limits.value.length > 0 || (props.version.changes || []).some((c) => c.details)))

const made = new Map()
function html(md) {
  if (!made.has(md)) made.set(md, renderMarkdown(md))
  return props.ws.length ? cl.mark(made.get(md), props.ws) : made.get(md)
}
const inline = (md) => html(md).replace(/^<p>([\s\S]*)<\/p>$/, '$1')
const said = (words) => ({ html: inline(cl.inLang(words, lang.value)), en: cl.isEnglish(words, lang.value) })
</script>

<template>
  <SideDrawer :title="title" :sub="sub" @close="emit('close')">
    <div v-if="english || link" class="cl-notes-top">
      <p v-if="english" class="cl-note">{{ $t('about.changelog.notesEnglish') }}</p>
      <a v-if="link" v-tip="link.tip" class="cl-link" :href="link.url" target="_blank" rel="noopener noreferrer"><Icon name="external" />{{ link.label }}</a>
    </div>
    <div class="cl-notes">
      <div v-if="version.intro" class="md cl-summary" lang="en" v-html="html(version.intro)"></div>
      <section v-for="g in groups" :key="g.type" class="cl-sec">
        <h4 class="cl-sec-head"><span class="cl-dot" :class="'tone-' + (cl.TONE[g.type] || 'plain')" aria-hidden="true"></span>{{ typeLabel(g.type) }}</h4>
        <ul class="cl-items cl-changes">
          <li v-for="c in g.items" :key="c.id" class="cl-item">
            <p class="cl-item-sum"><strong :lang="said(c.summary).en ? 'en' : undefined" v-html="said(c.summary).html"></strong><span v-if="said(c.summary).en" class="cl-en">{{ $t('about.changelog.english') }}</span></p>
            <div v-if="c.details" class="md cl-item-details" lang="en" v-html="html(c.details)"></div>
          </li>
        </ul>
      </section>
      <section v-if="limits.length" class="cl-sec">
        <h4 class="cl-sec-head">{{ $t('about.changelog.knownLimits') }}</h4>
        <ul class="cl-items" lang="en">
          <li v-for="(k, i) in limits" :key="i" class="md cl-item" v-html="html(k)"></li>
        </ul>
      </section>
      <p v-if="empty" class="t-meta">{{ $t('about.changelog.noNotes') }}</p>
    </div>
  </SideDrawer>
</template>
