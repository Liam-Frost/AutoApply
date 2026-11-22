<script setup>
import { t as T } from '../i18n/catalog'
// Every instruction text the program gives the AI: read, edit, restore. The fixed rules under each one are shown but cannot be changed.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { ask, fmtTime, toast } from '../ui'
import { mayLeave, useUnsaved } from '../dirty'
import CardHead from './CardHead.vue'
import HelpPop from './HelpPop.vue'
import Icon from './Icon.vue'
import Menu from './Menu.vue'
import Status from './Status.vue'

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
  if (tooLong.value || missing.value.length) { toast(tooLong.value ? T('settings.prompts.thisPromptIsToo') : T('settings.prompts.cannotBeRemovedNot', { p0: missing.value.join(', ') }), 'bad'); return false }
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
  if (!(await ask(T('settings.prompts.restoreToTheBuilt', { p0: cur.value.title }), { ok: T('settings.prompts.restoreDefaults'), danger: true }))) return
  try { await api.post(`/prompts/${cur.value.key}/reset`); toast(T('settings.prompts.defaultsRestored')); await load(cur.value.key) } catch (e) { toast(e.message, 'bad') }
}
function loadVersion(id) {
  const v = cur.value.history.find((h) => String(h.id) === String(id))
  if (v) { text.value = v.content; toast(T('settings.prompts.thisVersionIsNow')) }
}
// the menu beside the buttons: compare with the built-in text; go back to it (asked first when a version of yours is stored)
function more(id) {
  if (id === 'compare') showDefault.value = !showDefault.value
  else if (id === 'restore') { if (cur.value.edited) reset(); else text.value = cur.value.default }
}
onMounted(() => load())
</script>

<template>
  <CardHead class="pr-head" :title="$t('settings.prompts.aiPrompts')" :help="$t('settings.prompts.theInstructionsTheProgram')" />
  <div v-if="cur" class="pr">
    <div class="card pr-nav">
      <template v-for="[g, list] in groups" :key="g">
        <div class="pr-group">{{ g }}</div>
        <button v-for="r in list" :key="r.key" :class="{ on: cur.key === r.key }" :aria-pressed="cur.key === r.key" @click="pick(r)">
          <span class="ell">{{ r.title }}</span>
          <span v-if="r.edited" class="meta small">{{ $t('settings.prompts.edited') }}</span>
        </button>
      </template>
    </div>
    <div class="card pr-edit">
      <CardHead :title="cur.title">
        <template #after>
          <span v-if="cur.risk === 'high'" class="tag warn">{{ $t('settings.prompts.actsOnRealSites') }}</span>
          <Status :tone="cur.edited ? 'info' : ''" :label="cur.edited ? $t('settings.prompts.yourEditedVersion') : $t('settings.prompts.builtInVersion')" />
        </template>
      </CardHead>
      <p class="pr-used">{{ cur.used }}</p>
      <textarea v-model="text" rows="16" spellcheck="false" :aria-label="$t('settings.prompts.promptText')"></textarea>
      <div class="pr-foot">
        <span class="num" :class="{ bad: tooLong }">{{ $t('settings.prompts.characters', { p0: text.length, p1: cur.max }) }}</span>
        <span v-if="missing.length" class="bad">{{ $t('settings.prompts.cantRemoveTheApp', { p0: missing.join(', ') }) }}</span>
        <span class="grow"></span>
        <span>{{ $t('settings.prompts.promptsWorkMostReliably') }}</span>
      </div>

      <div class="pr-guard">
        <div class="chain-name"><Icon name="shield" /><span class="t-primary">{{ $t('settings.prompts.fixedRules') }}</span><HelpPop :text="$t('settings.prompts.alwaysAddedAfterThe')" /></div>
        <ul><li v-for="g in cur.guard" :key="g">{{ g }}</li></ul>
      </div>

      <div class="set-actions">
        <button :disabled="!dirty" @click="text = cur.body">{{ $t('settings.prompts.undoChanges') }}</button>
        <button class="primary" :disabled="!dirty || tooLong || missing.length > 0" @click="save"><Icon name="check" />{{ $t('settings.prompts.save') }}</button>
        <Status v-if="dirty" tone="warn" :label="$t('settings.prompts.unsavedChanges')" />
        <span class="grow"></span>
        <AaSelect v-if="cur.history.length" class="pr-history" :model-value="''" :placeholder="$t('settings.prompts.versionHistory')" :aria-label="$t('settings.prompts.versionHistory')" @update:model-value="loadVersion">
          <option v-for="h in cur.history" :key="h.id" :value="h.id">{{ fmtTime(h.created_at) }}{{ h.note ? ' · ' + h.note : '' }}</option>
        </AaSelect>
        <Menu :label="$t('common.more')" :items="[
          { id: 'compare', label: showDefault ? $t('settings.prompts.hideBuiltInVersion') : $t('settings.prompts.compareWithTheBuilt'), icon: 'eye' },
          { divider: true },
          { id: 'restore', label: $t('settings.prompts.restoreDefaults'), icon: 'refresh', danger: true, disabled: !cur.edited && isDefault },
        ]" @pick="more" />
      </div>
      <pre v-if="showDefault" class="pr-default">{{ cur.default }}</pre>
    </div>
  </div>
</template>
