<script setup>
// The head of the about page's overview, one compact block: the mark, the product and the version that runs (a build
// of one's own reads as such - its folder's name is secondary text, never the version), how this copy runs on the line
// under it, and the project's links (from the release repository that is set) as one quiet row under that.
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText } from '../../i18n/format'
import { releaseText } from '../../updatestate'
import Status from '../../components/Status.vue'

const props = defineProps({ about: { type: Object, required: true } })

const local = computed(() => !!(props.about.build_release && props.about.build_release.local))
const version = computed(() => (local.value ? releaseText(props.about.build_release, T, dayText) : props.about.version))
const KIND = computed(() => ({
  managed: [T('about.kind.managed'), T('about.kindTip.managed')],
  unmanaged: [T('about.kind.unmanaged'), T('about.kindTip.unmanaged')],
  source: [T('about.kind.source'), T('about.kindTip.source')],
  container: [T('about.kind.container'), T('about.kindTip.container')],
}[props.about.kind] || [props.about.kind, '']))
const links = computed(() => {
  const repo = props.about.repo ? 'https://github.com/' + props.about.repo : ''
  return repo ? [[repo, T('about.source')], [repo + '/releases', T('about.releases')], [repo + '/issues', T('about.issues')], [repo + '/blob/master/LICENSE', T('about.license')]] : []
})
</script>

<template>
  <section class="about-head" aria-labelledby="about-name">
    <img class="about-mark" :src="'logo-mark.svg'" alt="" />
    <div class="about-id">
      <!-- (the product's name: a name, not words to translate - as in the sidebar) -->
      <h3 id="about-name" class="about-name">AutoApply <span class="about-v">{{ version }}</span><span v-if="local" class="about-build">{{ about.build }}</span></h3>
      <Status class="about-kind" :label="KIND[0]" :tip="KIND[1]" />
      <div v-if="links.length" class="about-links">
        <a v-for="[href, words] in links" :key="href" :href="href" target="_blank" rel="noopener">{{ words }}</a>
      </div>
    </div>
  </section>
</template>
