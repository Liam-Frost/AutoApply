<script setup>
// How a copy that does not update itself is updated by hand: where to run it, and the commands, one per line, with a
// copy button. Shown from "See the steps" beside the update state (a popover) and under "Advanced" (Manual update).
// (A checkout: as start.sh prepares it - `--inexact` keeps the optional components; start.sh builds the interface only
// when there is none, so a new one is built here.)
import { computed } from 'vue'
import { t as T } from '../../i18n/catalog'
import { toast } from '../../ui'
import IconButton from '../../components/IconButton.vue'

const props = defineProps({ kind: { type: String, required: true } })      // "source" | "container"

const COMMANDS = {
  source: ['git pull', 'uv sync --inexact', 'npm --prefix frontend install', 'npm --prefix frontend run build'],
  container: ['docker compose pull', 'docker compose up -d'],
}
const commands = computed(() => COMMANDS[props.kind] || [])

async function copy() {
  try { await navigator.clipboard.writeText(commands.value.join('\n')); toast(T('about.copied')) } catch (e) { toast(T('about.copyFailed'), 'bad') }
}
</script>

<template>
  <div v-if="commands.length" class="up-steps">
    <p>{{ $t(kind === 'source' ? 'about.howSource' : 'about.howContainer') }}</p>
    <div class="up-cmd">
      <pre><code>{{ commands.join('\n') }}</code></pre>
      <IconButton icon="copy" size="sm" :label="$t('about.copyCommand')" @click="copy" />
    </div>
  </div>
</template>
