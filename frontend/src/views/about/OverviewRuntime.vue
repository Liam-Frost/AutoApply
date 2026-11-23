<script setup>
// The about page's runtime details, closed until opened: Python, the system, how this copy runs, the data folder (with
// a copy button) and what it was built from - the commit of a checkout, or the folder of data/releases it runs from.
// "Copy diagnostics" puts these facts and where updates stand on the clipboard as plain text (diagnosticsText).
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText } from '../../i18n/format'
import { toast } from '../../ui'
import { diagnosticsText, releaseText } from '../../updatestate'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import IconButton from '../../components/IconButton.vue'
import Trunc from '../../components/Trunc.vue'

const props = defineProps({ about: { type: Object, required: true }, status: { type: Object, default: null } })

const KINDS = computed(() => ({ managed: T('about.kind.managed'), unmanaged: T('about.kind.unmanaged'), source: T('about.kind.source'), container: T('about.kind.container') }))
const build = computed(() => releaseText(props.about.build_release, T, dayText))

async function copy(text, done) {
  try { await navigator.clipboard.writeText(text); toast(done) } catch (e) { toast(T('about.copyFailed'), 'bad') }
}
const copyPath = () => copy(props.about.data, T('about.copied'))
const copyDiagnostics = () => copy(diagnosticsText(props.about, props.status, T, dayText), T('about.diagnosticsCopied'))
</script>

<template>
  <details class="card about-runtime">
    <summary><Icon name="chevron_right" class="about-chev" /><span class="card-title">{{ $t('about.runtime') }}</span></summary>
    <dl class="kv about-rt">
      <dt>{{ $t('about.python') }}</dt><dd>{{ about.python }}</dd>
      <dt>{{ $t('about.system') }}</dt><dd>{{ about.system }}</dd>
      <dt>{{ $t('about.runs') }}</dt><dd>{{ KINDS[about.kind] || about.kind }}</dd>
      <dt>{{ $t('about.data') }}</dt>
      <dd class="about-path"><Trunc as="code" :text="about.data" /><IconButton icon="copy" size="sm" :label="$t('about.copyPath')" @click="copyPath" /></dd>
      <template v-if="about.commit"><dt>{{ $t('about.commit') }}</dt><dd><code>{{ about.commit }}</code></dd></template>
      <template v-if="about.build"><dt>{{ $t('about.build') }}</dt><dd><code>{{ about.build }}</code><span v-if="build" class="t-meta about-build">{{ build }}</span></dd></template>
    </dl>
    <div class="actions about-diag">
      <button type="button" @click="copyDiagnostics"><Icon name="copy" />{{ $t('about.copyDiagnostics') }}</button>
      <HelpPop :text="$t('about.diagnosticsHint')" :label="$t('about.copyDiagnostics')" />
    </div>
  </details>
</template>
