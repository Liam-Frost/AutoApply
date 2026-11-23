<script setup>
// The head of the about page's overview: the product, the version that runs (a build of one's own is named as such -
// never by its folder), how this copy runs, and the project's links (from the release repository that is set).
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText } from '../../i18n/format'
import { releaseText } from '../../updatestate'
import BrandLogo from '../../components/BrandLogo.vue'
import Icon from '../../components/Icon.vue'
import Status from '../../components/Status.vue'

const props = defineProps({ about: { type: Object, required: true } })

const version = computed(() => (props.about.build_release && props.about.build_release.local ? releaseText(props.about.build_release, T, dayText) : props.about.version))
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
  <section class="card about-head">
    <div class="about-id">
      <BrandLogo class="about-logo" />
      <div class="about-ver">
        <span class="t-meta">{{ $t('about.version') }}</span>
        <span class="about-ver-v">{{ version }}</span>
      </div>
      <Status class="about-kind" :label="KIND[0]" :tip="KIND[1]" />
    </div>
    <div v-if="links.length" class="about-links">
      <a v-for="[href, words] in links" :key="href" :href="href" target="_blank" rel="noopener"><Icon name="external" />{{ words }}</a>
    </div>
  </section>
</template>
