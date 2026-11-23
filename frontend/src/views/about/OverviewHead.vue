<script setup>
// The head of the about page's overview, one compact block without a card: the mark and the product's name, under the
// name the version that runs (a build of one's own reads as such - its folder's name is under Advanced, never the
// version) and how this copy runs, with an (i) on what that means for updates; under both, the project's links (from
// the release repository that is set) as a row of small buttons.
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText } from '../../i18n/format'
import { releaseText } from '../../updatestate'
import InfoTip from '../../components/InfoTip.vue'

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
      <h3 id="about-name" class="about-name">AutoApply</h3>
      <p class="about-line">
        <span class="about-v" data-version>{{ $t('about.vVersion', { v: version }) }}</span>
        <span class="about-kind">{{ KIND[0] }}<InfoTip v-if="KIND[1]" :text="KIND[1]" :label="KIND[0]" /></span>
      </p>
    </div>
    <nav v-if="links.length" class="about-links" :aria-label="$t('about.links')">
      <a v-for="[href, words] in links" :key="href" class="btn sm" :href="href" target="_blank" rel="noopener">{{ words }}</a>
    </nav>
  </section>
</template>
