<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import { toast } from '../ui'

const drafts = ref([])
const picked = ref(new Set())
const showAll = ref(false)

async function load() {
  drafts.value = await api.get('/drafts' + (showAll.value ? '?all=true' : ''))
  picked.value = new Set()
}
const APP = { draft_ready: '', needs_input: '有问题待回答', approved: '', executing: '', ready_to_submit: '填好了但没有提交', failed: '执行失败', needs_human: '需要你处理', submitted: '已提交', confirmed: '已确认' }
const canApprove = (d) => d.review_status === 'pending' && !d.unresolved
function toggle(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function pickAll() { picked.value = new Set(drafts.value.filter(canApprove).map((d) => d.id)) }
async function approvePicked() {
  try {
    const r = await api.post('/drafts/approve', { ids: [...picked.value] })
    if (r.approved.length) toast(`已批准 ${r.approved.length} 份，开始填写`)
    if (Object.keys(r.errors).length) toast(`有 ${Object.keys(r.errors).length} 份没能批准：` + Object.values(r.errors).join('；'), 'bad')
    await load()
  } catch (e) { toast(e.message, 'bad') }
}
onMounted(load)
</script>

<template>
  <PageHead title="草案审批" sub="每份草案列出了要填的全部内容和要上传的材料。你批准之后，程序才会去填表；填完会逐项核对，没问题才提交。">
    <label class="small muted"><input v-model="showAll" type="checkbox" @change="load" /> 也显示以前的草案</label>
    <button @click="pickAll">全选能批准的</button>
    <button class="primary" :disabled="!picked.size" @click="approvePicked"><Icon name="check" />批准所选（{{ picked.size }}）</button>
  </PageHead>
  <div class="table-wrap">
    <table>
      <thead><tr><th></th><th>评分</th><th>公司 · 岗位</th><th>截止时间</th><th>招聘系统</th><th>需要注意</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="d in drafts" :key="d.id">
          <td><input type="checkbox" :disabled="!canApprove(d)" :checked="picked.has(d.id)" @change="toggle(d.id)" /></td>
          <td class="score">{{ d.score ?? '—' }}</td>
          <td><router-link :to="'/drafts/' + d.id">{{ d.company }} · {{ d.title }}</router-link> <span class="muted small">v{{ d.version }}</span></td>
          <td class="small">{{ d.deadline }}</td>
          <td class="small">{{ d.ats_label }}</td>
          <td>
            <span v-if="d.unresolved" class="tag bad">{{ d.unresolved }} 个问题要你回答</span>
            <span v-if="d.sensitive_new" class="tag warn" style="margin-left: 4px">{{ d.sensitive_new }} 个敏感问题第一次遇到</span>
            <span v-if="!d.unresolved && !d.sensitive_new" class="muted small">无</span>
          </td>
          <td>
            <span v-if="d.review_status === 'pending'" class="tag warn">待审批</span>
            <span v-else-if="d.review_status === 'approved' && ['approved', 'executing'].includes(d.app_status)" class="tag info">已批准，执行中</span>
            <span v-else-if="d.review_status === 'approved'" class="tag bad">已批准，未提交</span>
            <span v-else class="tag">{{ d.review_status }}</span>
            <span class="muted small"> {{ APP[d.app_status] || d.app_status }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!drafts.length" icon="draft" title="没有等你审批的草案" text="在“岗位”里打开一个岗位，点“生成申请草案”；评分高的新岗位也会自动准备草案。" />
  </div>
</template>
