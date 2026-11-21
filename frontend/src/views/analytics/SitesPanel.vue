<script setup>
// What the agent wrote down about the sites it worked: the notes it left for the next application there, and what
// is known about how the site signs in. One row a site; a row opened shows its notes. Clearing a site takes its
// notes and leaves its sign-in.
import { computed, ref } from 'vue'
import { api } from '../../api'
import { ask, toast } from '../../ui'
import { stampDay } from '../../i18n/format'
import EmptyState from '../../components/EmptyState.vue'

const props = defineProps({ d: { type: Array, required: true } })
const emit = defineEmits(['reload'])

// a recruiting system's notes hold for every employer on it; a sign-in provider has no notes of its own
const rows = computed(() => props.d.filter((r) => r.notes && !r.key.startsWith('idp:')))
const shown = (r) => r.employer || r.name
const site = ref(null)
async function show(row) {
  if (site.value && site.value.key === row.key) { site.value = null; return }
  try { site.value = await api.get(`/sites/${encodeURIComponent(row.key)}`) } catch (e) { toast(e.message, 'bad') }
}
async function forget(row) {
  if (!(await ask({ title: '清除这个网站的笔记？', text: 'Agent 下次到这个网站时会重新摸索。登录状态和已保存的账号不受影响。', ok: '清除', danger: true }))) return
  try { await api.post(`/sites/${encodeURIComponent(row.key)}/forget`); site.value = null; emit('reload') } catch (e) { toast(e.message, 'bad') }
}
</script>

<template>
  <div class="card">
    <div class="card-title">Agent 记下的网站笔记</div>
    <p class="muted">Agent 每做一份申请，都会把这个网站值得下一次知道的事记下来：控件怎么用、简历解析会弄错什么、下一步藏在哪里。下次到同一个网站时它先读这些。写给整个招聘系统的笔记，对这个系统上的所有雇主都有效。点一行查看内容。</p>
    <EmptyState v-if="!rows.length" icon="wrench" title="还没有笔记" text="Agent 做过申请之后，这里会列出它对各个网站记下的内容。" />
    <div v-else class="an-scroll">
      <table class="an-table">
        <thead><tr><th>网站</th><th>范围</th><th class="num">笔记</th><th>最近更新</th><th></th></tr></thead>
        <tbody>
          <template v-for="row in rows" :key="row.key">
            <tr style="cursor: pointer" @click="show(row)">
              <td class="name" data-notr>{{ shown(row) }}</td>
              <td class="small muted">{{ row.key.startsWith('system:') ? '整个招聘系统' : '这一个网站' }}</td>
              <td class="num">{{ row.notes }}</td>
              <td class="small muted nowrap">{{ stampDay(row.updated) }}</td>
              <td class="nowrap" @click.stop><button class="sm ghost danger" @click="forget(row)">清除</button></td>
            </tr>
            <tr v-if="site && site.key === row.key">
              <td colspan="5" style="background: var(--surface-2)">
                <div v-if="site.signs_in_on" class="small muted">登录状态来自：<span data-notr>{{ site.signs_in_on.replace(/^(generic:|idp:)/, '') }}</span></div>
                <ul class="small" style="margin: 4px 0 0 18px"><li v-for="(n, i) in site.notes" :key="i" data-notr>{{ n.at ? '（' + n.at + '）' : '' }}{{ n.text }}</li></ul>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
