<script setup>
// Every instruction text the program gives the AI: read, edit, restore. The fixed rules under each one are shown but cannot be changed.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { ask, fmtTime, toast } from '../ui'
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
  if (dirty.value && !(await ask('这条提示词有没保存的修改，切换后会丢掉。继续吗？', { ok: '丢掉修改' }))) return
  cur.value = r; text.value = r.body; showDefault.value = false
}
async function save() {
  if (cur.value.risk === 'high' && !(await ask('这条提示词指挥 AI 在真实的招聘网站上点击和填写。改得不好，可能读错申请表或卡在半路；固定规则（不提交、不碰密码、不绕过人机验证）不受影响。确定保存吗？', { ok: '保存' }))) return
  try {
    await api.put('/prompts/' + cur.value.key, { body: text.value })
    toast('已保存，下一次用到时生效')
    await load(cur.value.key)
  } catch (e) { toast(e.message, 'bad') }
}
async function reset() {
  if (!(await ask(`把「${cur.value.title}」恢复成程序自带的内容？你改过的版本会留在历史记录里。`, { ok: '恢复默认' }))) return
  try { await api.post(`/prompts/${cur.value.key}/reset`); toast('已恢复默认'); await load(cur.value.key) } catch (e) { toast(e.message, 'bad') }
}
function loadVersion(id) {
  const v = cur.value.history.find((h) => String(h.id) === String(id))
  if (v) { text.value = v.content; toast('已把这个版本放进编辑框，点“保存”才会生效') }
}
onMounted(() => load())
</script>

<template>
  <div class="card">
    <div class="card-title">AI 提示词</div>
    <p class="muted">程序在各个环节交给 AI 的工作说明都在这里，可以按你的习惯改。每条下面的“固定规则”始终会附在后面、不能修改；这些规则同时也由程序本身强制执行（比如 AI 根本没有“提交”这个操作），所以改提示词可能让结果变差，但不会让它替你乱投、编造经历或碰你的密码。</p>
  </div>
  <div v-if="cur" class="pr">
    <div class="card pr-nav">
      <template v-for="[g, list] in groups" :key="g">
        <div class="pr-group">{{ g }}</div>
        <button v-for="r in list" :key="r.key" :class="{ on: cur.key === r.key }" @click="pick(r)">
          <span class="ell">{{ r.title }}</span>
          <span v-if="r.edited" class="badge info">已修改</span>
        </button>
      </template>
    </div>
    <div class="card pr-edit">
      <div class="row">
        <span class="card-title grow">{{ cur.title }}</span>
        <span v-if="cur.risk === 'high'" class="badge warn">会操作真实网站，修改要谨慎</span>
        <span class="badge" :class="cur.edited ? 'info' : ''">{{ cur.edited ? '你改过的版本' : '程序自带的版本' }}</span>
      </div>
      <p class="muted" style="margin: 4px 0 12px">{{ cur.used }}</p>
      <textarea v-model="text" rows="16" spellcheck="false" aria-label="提示词内容"></textarea>
      <div class="row small muted" style="margin-top: 6px">
        <span :style="tooLong ? 'color: var(--bad)' : ''">{{ text.length }} / {{ cur.max }} 个字符</span>
        <span v-if="missing.length" style="color: var(--bad)">不能去掉：{{ missing.join('、') }}（程序靠它接上后面的步骤）</span>
        <span class="grow"></span>
        <span>提示词用英文写效果最稳定；也可以用中文。</span>
      </div>

      <div class="pr-guard">
        <div class="row"><Icon name="shield" /><b>固定规则</b><span class="muted small">始终附在上面的内容之后，优先于它，不能修改</span></div>
        <ul><li v-for="g in cur.guard" :key="g">{{ g }}</li></ul>
      </div>

      <div class="row" style="margin-top: 14px">
        <button class="primary" :disabled="!dirty || tooLong || missing.length > 0" @click="save"><Icon name="check" />保存</button>
        <button :disabled="!dirty" @click="text = cur.body">撤销修改</button>
        <button :disabled="!cur.edited && isDefault" @click="cur.edited ? reset() : (text = cur.default)">恢复默认</button>
        <span class="grow"></span>
        <AaSelect v-if="cur.history.length" small :model-value="''" placeholder="历史版本" aria-label="历史版本" @update:model-value="loadVersion">
          <option v-for="h in cur.history" :key="h.id" :value="h.id">{{ fmtTime(h.created_at) }}{{ h.note ? ' · ' + h.note : '' }}</option>
        </AaSelect>
        <button class="ghost sm" @click="showDefault = !showDefault">{{ showDefault ? '收起自带版本' : '对照程序自带的版本' }}</button>
      </div>
      <pre v-if="showDefault" class="pr-default">{{ cur.default }}</pre>
    </div>
  </div>
</template>
