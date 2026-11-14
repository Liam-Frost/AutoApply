<script setup>
// People you know at employers: who can refer you, who you talked to, when to follow up. Shown next to that employer's postings.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import { ask, run } from '../ui'

const rows = ref([])
const blank = () => ({ id: 0, name: '', company: '', role: '', relation: '', how: '', status: 'none', follow_up: '', note: '' })
const form = ref(blank())
const editing = ref(false)
const q = ref('')
const STATUS = { none: ['还没联系', ''], asked: ['已联系，等回复', 'warn'], referred: ['已帮我内推', 'ok'], talked: ['聊过了', 'info'], declined: ['不方便', ''] }
const today = new Date().toISOString().slice(0, 10)

const shown = computed(() => {
  const n = q.value.trim().toLowerCase()
  return rows.value.filter((r) => !n || `${r.name} ${r.company} ${r.role} ${r.note}`.toLowerCase().includes(n))
})
const due = computed(() => rows.value.filter((r) => r.follow_up && r.follow_up <= today).length)
async function load() { rows.value = await api.get('/contacts') }
const save = () => run(async () => { await (form.value.id ? api.put('/contacts/' + form.value.id, form.value) : api.post('/contacts', form.value)); form.value = blank(); editing.value = false }, '已保存', load)
const edit = (r) => { form.value = { ...r }; editing.value = true; window.scrollTo({ top: 0, behavior: 'smooth' }) }
const remove = async (r) => (await ask(`删除联系人「${r.name}」？`)) && run(() => api.del('/contacts/' + r.id), '已删除', load)
onMounted(load)
</script>

<template>
  <PageHead title="人脉与内推" sub="在目标公司认识的人：谁能帮你内推、和谁聊过、什么时候该跟进。岗位详情里会提示“这家公司你认识谁”。这里只是你的记录，程序不会替你联系任何人。">
    <button class="primary" @click="form = blank(); editing = !editing"><Icon name="edit" />{{ editing ? '收起' : '添加联系人' }}</button>
  </PageHead>

  <div v-if="editing" class="card">
    <div class="card-title">{{ form.id ? '修改联系人' : '添加联系人' }}</div>
    <div class="kv" style="margin-top: 12px">
      <label>姓名</label><input v-model="form.name" />
      <label>公司</label><input v-model="form.company" placeholder="和岗位表里的公司名一致，才能对上" />
      <label>职位</label><input v-model="form.role" placeholder="可不填" />
      <label>怎么认识的</label><input v-model="form.relation" placeholder="例如：校友、前同事、朋友介绍、LinkedIn 上联系的" />
      <label>联系方式</label><input v-model="form.how" placeholder="邮箱、LinkedIn 链接等，可不填" />
      <label>进展</label><AaSelect v-model="form.status"><option v-for="(v, k) in STATUS" :key="k" :value="k">{{ v[0] }}</option></AaSelect>
      <label>哪天跟进</label><div><input v-model="form.follow_up" type="date" style="width: 180px" /> <span class="hint">到了这天，概览页和这里会提醒你。</span></div>
      <label>备注</label><textarea v-model="form.note" rows="3" style="font-family: inherit; min-height: 0"></textarea>
    </div>
    <div class="row" style="margin-top: 12px"><button class="primary" :disabled="!form.name.trim() || !form.company.trim()" @click="save"><Icon name="check" />保存</button><button @click="editing = false">取消</button></div>
  </div>

  <div v-if="rows.length" class="filters">
    <input v-model="q" placeholder="搜索姓名、公司或备注" style="width: 260px" />
    <span v-if="due" class="badge warn">{{ due }} 位该跟进了</span>
    <span class="grow"></span><span class="muted small">{{ shown.length }} 位</span>
  </div>
  <div class="table-wrap" style="max-height: none">
    <table v-if="rows.length">
      <thead><tr><th>姓名</th><th>公司</th><th>怎么认识的</th><th>进展</th><th>跟进</th><th>备注</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in shown" :key="r.id">
          <td><b>{{ r.name }}</b><div class="small muted">{{ r.role }}</div></td>
          <td>{{ r.company }}<div v-if="r.open_jobs" class="small"><router-link :to="{ path: '/jobs', query: { q: r.company } }">{{ r.open_jobs }} 个在招岗位</router-link></div></td>
          <td class="small">{{ r.relation }}<div v-if="r.how" class="muted ell" style="max-width: 200px">{{ r.how }}</div></td>
          <td><span class="badge" :class="(STATUS[r.status] || [])[1]">{{ (STATUS[r.status] || [r.status])[0] }}</span></td>
          <td class="small nowrap"><span v-if="r.follow_up" :style="r.follow_up <= today ? 'color: var(--warn); font-weight: 600' : ''">{{ r.follow_up }}</span><span v-else class="muted">—</span></td>
          <td class="small muted" style="max-width: 320px"><div class="clamp2">{{ r.note }}</div></td>
          <td><div class="row" style="flex-wrap: nowrap"><button class="sm" @click="edit(r)">修改</button><button class="sm ghost danger" @click="remove(r)">删除</button></div></td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-else icon="user" title="还没有记录联系人" text="有经验的求职者，很大一部分机会来自内推。把目标公司里认识的人记在这里，看岗位时就能想起来该找谁。" />
  </div>
</template>
