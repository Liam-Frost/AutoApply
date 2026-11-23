<script setup>
// "Advanced", the last part of the about page's "Software update": closed until opened (the page holds `open`, so it
// is closed again on every load and every return to the tab). In it, one under the other: the runtime details - Python,
// the system, how this copy runs, the data folder (with a copy button), the commit or the release folder it runs from -
// with "Copy diagnostics", which puts these facts and where updates stand on the clipboard as plain text; how to update
// a checkout or a container by hand (UpdateSteps, as "See the steps" shows it); how updates work and what is sent where.
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText } from '../../i18n/format'
import { toast } from '../../ui'
import { diagnosticsText, releaseText } from '../../updatestate'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import IconButton from '../../components/IconButton.vue'
import Trunc from '../../components/Trunc.vue'
import UpdateSteps from './UpdateSteps.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  about: { type: Object, required: true },        // GET /api/about
  status: { type: Object, default: null },        // GET /api/system/update, for the diagnostics
})
const emit = defineEmits(['update:open'])

const KINDS = computed(() => ({ managed: T('about.kind.managed'), unmanaged: T('about.kind.unmanaged'), source: T('about.kind.source'), container: T('about.kind.container') }))
const build = computed(() => releaseText(props.about.build_release, T, dayText))
const byHand = computed(() => props.about.kind === 'source' || props.about.kind === 'container')

async function copy(text, done) {
  try { await navigator.clipboard.writeText(text); toast(done) } catch (e) { toast(T('about.copyFailed'), 'bad') }
}
const copyPath = () => copy(props.about.data, T('about.copied'))
const copyDiagnostics = () => copy(diagnosticsText(props.about, props.status, T, dayText), T('about.diagnosticsCopied'))
</script>

<template>
  <div class="up-adv" :class="{ open }">
    <button type="button" class="up-adv-toggle" :aria-expanded="open ? 'true' : 'false'" aria-controls="up-adv-body" @click="emit('update:open', !open)">
      <Icon name="chevron_right" class="up-adv-chev" /><span>{{ $t('about.advanced') }}</span>
    </button>
    <div v-show="open" id="up-adv-body" class="up-adv-body">
      <section class="up-adv-part" aria-labelledby="up-adv-rt">
        <h4 id="up-adv-rt">{{ $t('about.runtime') }}</h4>
        <dl class="up-rt">
          <div><dt>{{ $t('about.python') }}</dt><dd>{{ about.python }}</dd></div>
          <div><dt>{{ $t('about.system') }}</dt><dd>{{ about.system }}</dd></div>
          <div><dt>{{ $t('about.runs') }}</dt><dd>{{ KINDS[about.kind] || about.kind }}</dd></div>
          <div><dt>{{ $t('about.data') }}</dt><dd class="up-path"><Trunc as="code" :text="about.data" /><IconButton icon="copy" size="sm" :label="$t('about.copyPath')" @click="copyPath" /></dd></div>
          <div v-if="about.commit"><dt>{{ $t('about.commit') }}</dt><dd><code>{{ about.commit }}</code></dd></div>
          <div v-if="about.build"><dt>{{ $t('about.build') }}</dt><dd><code>{{ about.build }}</code><span v-if="build" class="t-meta">{{ build }}</span></dd></div>
        </dl>
        <div class="actions up-diag">
          <button type="button" class="sm" @click="copyDiagnostics"><Icon name="copy" />{{ $t('about.copyDiagnostics') }}</button>
          <HelpPop :text="$t('about.diagnosticsHint')" :label="$t('about.copyDiagnostics')" />
        </div>
      </section>

      <section v-if="byHand" class="up-adv-part" aria-labelledby="up-adv-hand">
        <h4 id="up-adv-hand">{{ $t('about.byHand.title') }}</h4>
        <UpdateSteps :kind="about.kind" />
      </section>

      <section class="up-adv-part" aria-labelledby="up-adv-how">
        <h4 id="up-adv-how">{{ $t('about.howItWorks') }}</h4>
        <p>{{ $t('about.privacy') }}</p>
        <p>{{ $t('about.howSwitch') }}</p>
        <p>{{ $t('about.idleHow') }}</p>
      </section>
    </div>
  </div>
</template>
