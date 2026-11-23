<script setup>
// "Advanced", the last part of the about page's "Software update": closed until opened (the page holds `open`, so it
// is closed again on every load and every return to the tab). In it: how to update a checkout or a container by hand
// (the command, with a copy button), how updates work and what is sent where, and the runtime details - Python, the
// system, how this copy runs, the data folder (with a copy button), the commit or the release folder it runs from -
// with "Copy diagnostics", which puts these facts and where updates stand on the clipboard as plain text.
import { computed, nextTick, ref } from 'vue'
import { t as T } from '../../i18n/catalog'
import { dayText } from '../../i18n/format'
import { toast } from '../../ui'
import { diagnosticsText, releaseText } from '../../updatestate'
import HelpPop from '../../components/HelpPop.vue'
import Icon from '../../components/Icon.vue'
import IconButton from '../../components/IconButton.vue'
import Trunc from '../../components/Trunc.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  about: { type: Object, required: true },        // GET /api/about
  status: { type: Object, default: null },        // GET /api/system/update, for the diagnostics
})
const emit = defineEmits(['update:open'])

const KINDS = computed(() => ({ managed: T('about.kind.managed'), unmanaged: T('about.kind.unmanaged'), source: T('about.kind.source'), container: T('about.kind.container') }))
const build = computed(() => releaseText(props.about.build_release, T, dayText))
// how a copy that does not update itself is updated: the commands, one per line, run where the words say. (A checkout:
// as start.sh prepares it - `--inexact` keeps the optional components; start.sh builds the interface only when there is
// none, so a new one is built here.)
const COMMANDS = {
  source: ['git pull', 'uv sync --inexact', 'npm --prefix frontend install', 'npm --prefix frontend run build'],
  container: ['docker compose pull', 'docker compose up -d'],
}
const commands = computed(() => COMMANDS[props.about.kind] || null)

async function copy(text, done) {
  try { await navigator.clipboard.writeText(text); toast(done) } catch (e) { toast(T('about.copyFailed'), 'bad') }
}
const copyPath = () => copy(props.about.data, T('about.copied'))
const copyCommand = () => copy(commands.value.join('\n'), T('about.copied'))
const copyDiagnostics = () => copy(diagnosticsText(props.about, props.status, T, dayText), T('about.diagnosticsCopied'))

// "Show the command" (beside the state of a copy that does not update itself): open, and go to it
const hand = ref(null)
async function showCommand() {
  emit('update:open', true)
  await nextTick()
  if (!hand.value) return
  hand.value.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  hand.value.focus({ preventScroll: true })
}
defineExpose({ showCommand })
</script>

<template>
  <div class="up-adv" :class="{ open }">
    <button type="button" class="up-adv-toggle" :aria-expanded="open ? 'true' : 'false'" aria-controls="up-adv-body" @click="emit('update:open', !open)">
      <Icon name="chevron_right" class="up-adv-chev" /><span>{{ $t('about.advanced') }}</span>
    </button>
    <div v-show="open" id="up-adv-body" class="up-adv-body">
      <section v-if="commands" ref="hand" class="up-adv-part" tabindex="-1" aria-labelledby="up-adv-hand">
        <h4 id="up-adv-hand">{{ $t('about.byHand.title') }}</h4>
        <p>{{ $t(about.kind === 'source' ? 'about.howSource' : 'about.howContainer') }}</p>
        <div class="up-cmd">
          <pre><code>{{ commands.join('\n') }}</code></pre>
          <IconButton icon="copy" size="sm" :label="$t('about.copyCommand')" @click="copyCommand" />
        </div>
      </section>

      <section class="up-adv-part" aria-labelledby="up-adv-how">
        <h4 id="up-adv-how">{{ $t('about.howItWorks') }}</h4>
        <p>{{ $t('about.privacy') }}</p>
        <p>{{ $t('about.howSwitch') }}</p>
        <p>{{ $t('about.idleHow') }}</p>
      </section>

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
          <button type="button" @click="copyDiagnostics"><Icon name="copy" />{{ $t('about.copyDiagnostics') }}</button>
          <HelpPop :text="$t('about.diagnosticsHint')" :label="$t('about.copyDiagnostics')" />
        </div>
      </section>
    </div>
  </div>
</template>
