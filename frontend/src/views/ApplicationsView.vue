<script setup>
// "My applications": what has gone out, and what waits for its outcome. The jobs list is for finding what to apply
// for; this is for following what was applied for. Each one opens to everything about it (ApplicationDetail).
import { computed, onMounted, ref } from 'vue'
import { api, ROOT } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState } from '../data'
import { fmtTime } from '../ui'

const rows = ref([])
const groups = ref([])
const group = ref('')
const q = ref('')

async function read() {
  const d = await api.get('/applications')
  rows.value = d.applications
  groups.value = d.groups
}
const waiting = computed(() => rows.value.filter((r) => r.unknown || r.status === 'ready_to_submit'))
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  return rows.value.filter((r) => (!group.value || r.group === group.value) && (!needle || `${r.company} ${r.title} ${r.location || ''}`.toLowerCase().includes(needle)))
})
const count = (k) => rows.value.filter((r) => r.group === k).length
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
onMounted(load)
</script>

<template>
  <PageHead title="我的申请" sub="已经投出去的申请，和提交结果还没确认的申请。点开一份，可以看到它的状态、证据、提交的材料、往来邮件和全部经过。">
    <a class="btn" :href="ROOT + '/api/applications.csv'" download><Icon name="download" />导出表格（CSV）</a>
  </PageHead>
  <DataState :s="st" what="申请列表" @retry="load" />
  <template v-if="st.at">

  <div v-if="waiting.length" class="callout warn" style="display: block; margin-bottom: 12px">
    <b>{{ waiting.length }} 份申请的提交还没有结果</b>
    <div class="muted">点过提交但没看到成功页面，或者填好了还没提交。点开处理。</div>
    <div style="margin-top: 6px"><router-link v-for="r in waiting.slice(0, 6)" :key="r.id" :to="'/applications/' + r.id" class="tag warn" style="margin: 0 6px 4px 0">{{ r.company }} · {{ r.title }}</router-link></div>
  </div>

  <div class="row" style="margin-bottom: 10px; gap: 8px; flex-wrap: wrap">
    <div class="seg" role="group" aria-label="按阶段筛选">
      <button :class="{ on: group === '' }" @click="group = ''">全部<span class="n">{{ rows.length }}</span></button>
      <button v-for="g in groups" :key="g.key" :class="{ on: group === g.key }" @click="group = g.key">{{ g.label }}<span class="n">{{ count(g.key) }}</span></button>
    </div>
    <span class="grow"></span>
    <input v-model="q" placeholder="搜索公司或岗位" aria-label="搜索公司或岗位" style="width: 220px" />
  </div>

  <div class="table-wrap">
    <table>
      <thead><tr><th>公司 · 岗位</th><th>状态</th><th>投出日期</th><th>最近进展</th><th>更新</th></tr></thead>
      <tbody>
        <tr v-for="r in shown" :key="r.id">
          <td>
            <router-link :to="'/applications/' + r.id"><b>{{ r.company }}</b> · {{ r.title }}</router-link>
            <div v-if="r.location" class="small muted">{{ r.location }}</div>
          </td>
          <td><span class="tag" :class="r.unknown || r.status === 'ready_to_submit' ? 'warn' : r.tone">{{ r.status_label }}</span></td>
          <td class="small nowrap">{{ r.submitted_at ? r.submitted_at.slice(0, 10) : '—' }}</td>
          <td class="small" style="max-width: 420px">{{ r.last_event || r.next }}</td>
          <td class="small nowrap muted">{{ fmtTime(r.updated_at) }}</td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!rows.length" icon="briefcase" title="还没有投出去的申请" text="批准一份草案后，程序会去填表并提交；投出去的申请会出现在这里。" />
    <EmptyState v-else-if="!shown.length" icon="search" title="没有符合筛选的申请" text="换一个阶段，或清空搜索。" />
  </div>
  </template>
</template>
