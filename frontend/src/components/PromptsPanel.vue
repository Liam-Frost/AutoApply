<script setup>
import { t as T } from '../i18n/catalog'
// Every instruction text the program gives the AI: read, edit, restore. The fixed rules under each one are shown but cannot be changed.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { ask, fmtTime, toast } from '../ui'
import { mayLeave, useUnsaved } from '../dirty'
import Icon from './Icon.vue'

const rows = ref([])
const cur = ref(null)
const text = ref('')
const showDefault = ref(false)

const groups = computed(() => {
  const m = new Map()
  for (const r of rows.value) { if (!m.has(r.group)) m.set(r.group, []); m.get(r.group).push(r) }
  return [...m.entries()]
})
const dirty = computed(() => cur.value && text.value.trim() !== cur.value.body.trim())
const isDefault = computed(() => cur.value && text.value.trim() === cur.value.default.trim())
const missing = computed(() => (cur.value ? cur.value.requires.filter((r) => !text.value.includes(r)) : []))
const tooLong = computed(() => cur.value && text.value.length > cur.value.max)

async function load(keep) {
  rows.value = await api.get('/prompts')
  const k = keep || (cur.value && cur.value.key) || rows.value[0]?.key
  const r = rows.value.find((x) => x.key === k)
  if (r) { cur.value = r; text.value = r.body; showDefault.value = false }
}
async function pick(r) {
  if (r.key === cur.value.key || !(await mayLeave(['prompt']))) return
  cur.value = r; text.value = r.body; showDefault.value = false
}
async function save() {
  if (tooLong.value || missing.value.length) { toast(tooLong.value ? T('settings.prompts.thisPromptIsToo') : T('settings.prompts.cannotBeRemovedNot', { p0: missing.value.join('、') }), 'bad'); return false }
  if (cur.value.risk === 'high' && !(await ask(T('settings.prompts.thisPromptDirectsThe'), { ok: T('settings.prompts.save') }))) return false
  try {
    await api.put('/prompts/' + cur.value.key, { body: text.value })
    toast(T('settings.prompts.savedTakesEffectNext'))
    await load(cur.value.key)
    return true
  } catch (e) { toast(e.message, 'bad'); return false }
}
useUnsaved({ id: 'prompt', get label() { return cur.value ? T('settings.prompts.prompt', { p0: cur.value.title }) : T('settings.prompts.aiPrompts') }, dirty: () => !!dirty.value, save, discard: () => { text.value = cur.value.body } })
async function reset() {
  if (!(await ask(T('settings.prompts.restoreToTheBuilt', { p0: cur.value.title }), { ok: T('settings.prompts.restoreDefaults') }))) return
  try { await api.post(`/prompts/${cur.value.key}/reset`); toast(T('settings.prompts.defaultsRestored')); await load(cur.value.key) } catch (e) { toast(e.message, 'bad') }
}
function loadVersion(id) {
  const v = cur.value.history.find((h) => String(h.id) === String(id))
  if (v) { text.value = v.content; toast(T('settings.prompts.thisVersionIsNow')) }
}
onMounted(() => load())
</script>

<template>
  <div class="card">
    <div class="card-title">{{ $t('settings.prompts.aiPrompts') }}</div>
    <p class="muted">{{ $t('settings.prompts.theInstructionsTheProgram') }}</p>
  </div>
  <div v-if="cur" class="pr">
    <div class="card pr-nav">
      <template v-for="[g, list] in groups" :key="g">
        <div class="pr-group">{{ g }}</div>
        <button v-for="r in list" :key="r.key" :class="{ on: cur.key === r.key }" @click="pick(r)">
          <span class="ell">{{ r.title }}</span>
          <span v-if="r.edited" class="badge info">{{ $t('settings.prompts.edited') }}</span>
        </button>
      </template>
    </div>
    <div class="card pr-edit">
      <div class="row">
        <span class="card-title grow">{{ cur.title }}</span>
        <span v-if="cur.risk === 'high'" class="badge warn">{{ $t('settings.prompts.actsOnRealSites') }}</span>
        <span v-if="dirty" class="badge warn">{{ $t('settings.prompts.unsavedChanges') }}</span>
        <span class="badge" :class="cur.edited ? 'info' : ''">{{ cur.edited ? $t('settings.prompts.yourEditedVersion') : $t('settings.prompts.builtInVersion') }}</span>
      </div>
      <p class="muted" style="margin: 4px 0 12px">{{ cur.used }}</p>
      <textarea v-model="text" rows="16" spellcheck="false" :aria-label="$t('settings.prompts.promptText')"></textarea>
      <div class="row small muted" style="margin-top: 6px">
        <span :style="tooLong ? 'color: var(--bad)' : ''">{{ $t('settings.prompts.characters', { p0: text.length, p1: cur.max }) }}</span>
        <span v-if="missing.length" style="color: var(--bad)">{{ $t('settings.prompts.cantRemoveTheApp', { p0: missing.join('、') }) }}</span>
        <span class="grow"></span>
        <span>{{ $t('settings.prompts.promptsWorkMostReliably') }}</span>
      </div>

      <div class="pr-guard">
        <div class="row"><Icon name="shield" /><b>{{ $t('settings.prompts.fixedRules') }}</b><span class="muted small">{{ $t('settings.prompts.alwaysAddedAfterThe') }}</span></div>
        <ul><li v-for="g in cur.guard" :key="g">{{ g }}</li></ul>
      </div>

      <div class="row" style="margin-top: 14px">
        <button class="primary" :disabled="!dirty || tooLong || missing.length > 0" @click="save"><Icon name="check" />{{ $t('settings.prompts.save') }}</button>
        <button :disabled="!dirty" @click="text = cur.body">{{ $t('settings.prompts.undoChanges') }}</button>
        <button :disabled="!cur.edited && isDefault" @click="cur.edited ? reset() : (text = cur.default)">{{ $t('settings.prompts.restoreDefaults') }}</button>
        <span class="grow"></span>
        <AaSelect v-if="cur.history.length" small :model-value="''" :placeholder="$t('settings.prompts.versionHistory')" :aria-label="$t('settings.prompts.versionHistory')" @update:model-value="loadVersion">
          <option v-for="h in cur.history" :key="h.id" :value="h.id">{{ fmtTime(h.created_at) }}{{ h.note ? ' · ' + h.note : '' }}</option>
        </AaSelect>
        <button class="ghost sm" @click="showDefault = !showDefault">{{ showDefault ? $t('settings.prompts.hideBuiltInVersion') : $t('settings.prompts.compareWithTheBuilt') }}</button>
      </div>
      <pre v-if="showDefault" class="pr-default">{{ cur.default }}</pre>
    </div>
  </div>
</template>
