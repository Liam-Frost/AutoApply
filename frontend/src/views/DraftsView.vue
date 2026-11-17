<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState } from '../data'
import { ask, toast } from '../ui'

const drafts = ref([])
const picked = ref(new Set())
const showAll = ref(false)
const busy = ref(false)

async function read() {
  drafts.value = await api.get('/drafts' + (showAll.value ? '?all=true' : ''))
  picked.value = new Set([...picked.value].filter((id) => drafts.value.some((d) => d.id === id)))
}
// One state per draft, in the applicant's words: [text, tone]. The draft's own state and the application's are two
// sides of one thing; shown side by side they only repeated each other (and the second came out as an internal name).
function state(d) {
  if (d.review_status === 'pending') {
    if (d.app_status === 'recon') return ['正在读表', 'info']
    if (d.unresolved) return ['等你回答问题', 'bad']
    return ['待审批', 'warn']
  }
  if (d.review_status === 'approved') {
    return { approved: ['已批准，排队中', 'info'], executing: ['正在填写', 'info'], ready_to_submit: ['填好了，等你提交', 'warn'], submit_unknown: ['提交结果待确认', 'warn'], failed: ['填写没成功', 'bad'],
             needs_human: ['需要你处理', 'bad'], submitted: ['已提交', 'ok'], confirmed: ['已确认收到', 'ok'] }[d.app_status] || ['已批准', '']
  }
  return { superseded: ['已被新版本替代', ''], rejected: ['已退回', ''], closed: ['已关闭', ''] }[d.review_status] || ['—', '']
}
const open = (d) => d.review_status === 'pending'                      // can still be acted on
const canApprove = (d) => open(d) && !d.unresolved && d.app_status !== 'recon'
const selectable = computed(() => drafts.value.filter(open))
const chosen = computed(() => drafts.value.filter((d) => picked.value.has(d.id)))
const approvable = computed(() => chosen.value.filter(canApprove))
const allPicked = computed(() => selectable.value.length > 0 && selectable.value.every((d) => picked.value.has(d.id)))
function toggle(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function toggleAll() { picked.value = allPicked.value ? new Set() : new Set(selectable.value.map((d) => d.id)) }
function pickApprovable() { picked.value = new Set(drafts.value.filter(canApprove).map((d) => d.id)) }

async function approvePicked() {
  busy.value = true
  try {
    const r = await api.post('/drafts/approve', { ids: approvable.value.map((d) => d.id) })
    if (r.approved.length) toast(`已批准 ${r.approved.length} 份，开始填写`)
    if (Object.keys(r.errors).length) toast(`有 ${Object.keys(r.errors).length} 份没能批准：` + Object.values(r.errors).join('；'), 'bad')
    picked.value = new Set()
    await load()
  } catch (e) { toast(e.message, 'bad') } finally { busy.value = false }
}
async function batch(action, done) {
  busy.value = true
  try {
    const r = await api.post('/drafts/batch', { action, ids: chosen.value.map((d) => d.id) })
    toast(done(r.done.length) + (Object.keys(r.errors).length ? `；${Object.keys(r.errors).length} 份没成功` : ''), Object.keys(r.errors).length ? 'bad' : undefined)
    picked.value = new Set()
    await load()
  } catch (e) { toast(e.message, 'bad') } finally { busy.value = false }
}
async function dropPicked() {
  if (!(await ask(`不投所选的 ${chosen.value.length} 个岗位了？草案会关掉，岗位记为“不投”。`))) return
  await batch('withdraw', (n) => `已关掉 ${n} 份`)
}
const redoPicked = () => batch('rebuild', (n) => `已开始重新生成 ${n} 份草案`)
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
onMounted(load)
</script>

<template>
  <PageHead title="草案审批" sub="每份草案列出了要填的全部内容和要上传的材料。你批准之后，程序才会去填表；填完会逐项核对，没问题才提交。">
    <label class="small muted"><input v-model="showAll" type="checkbox" @change="load" /> 也显示以前的草案</label>
  </PageHead>
  <DataState :s="st" what="草案列表" @retry="load" />
  <template v-if="st.at">

  <div class="row" style="margin-bottom: 10px; gap: 8px; flex-wrap: wrap">
    <button @click="pickApprovable">选中所有能批准的</button>
    <span class="muted small">已选 {{ chosen.length }} 份<template v-if="chosen.length && approvable.length !== chosen.length">，其中 {{ approvable.length }} 份现在能批准</template></span>
    <span class="grow"></span>
    <button class="primary" :disabled="busy || !approvable.length" @click="approvePicked"><Icon name="check" />批准（{{ approvable.length }}）</button>
    <button :disabled="busy || !chosen.length" @click="redoPicked"><Icon name="refresh" />重新生成（{{ chosen.length }}）</button>
    <button class="ghost" :disabled="busy || !chosen.length" @click="dropPicked">不投这些了（{{ chosen.length }}）</button>
  </div>

  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width: 34px"><input type="checkbox" :checked="allPicked" :disabled="!selectable.length" title="全选 / 全不选" @change="toggleAll" /></th>
        <th>评分</th><th>公司 · 岗位</th><th>版本</th><th>截止时间</th><th>招聘系统</th><th>需要注意</th><th>状态</th>
      </tr></thead>
      <tbody>
        <tr v-for="d in drafts" :key="d.id">
          <td><input type="checkbox" :disabled="!open(d)" :checked="picked.has(d.id)" @change="toggle(d.id)" /></td>
          <td class="score">{{ d.score ?? '—' }}</td>
          <td><router-link :to="'/drafts/' + d.id">{{ d.company }} · {{ d.title }}</router-link></td>
          <td class="small nowrap">第 {{ d.version }} 版</td>
          <td class="small">{{ d.deadline }}</td>
          <td class="small">{{ d.ats_label }}</td>
          <td>
            <span v-if="d.unresolved" class="tag bad">{{ d.unresolved }} 个问题要你回答</span>
            <span v-if="d.sensitive_new" class="tag warn" style="margin-left: 4px">{{ d.sensitive_new }} 个敏感问题第一次遇到</span>
            <span v-if="!d.unresolved && !d.sensitive_new" class="muted small">无</span>
          </td>
          <td><span class="tag" :class="state(d)[1]">{{ state(d)[0] }}</span></td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!drafts.length" icon="draft" title="没有等你审批的草案" text="在“岗位”里打开一个岗位，点“生成申请草案”；评分高的新岗位也会自动准备草案。" />
  </div>
  </template>
</template>
