<script setup>
// The employers to watch: the user's own list. Paste a careers-page address; the program works out how to read it.
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { ask, run, toast } from '../ui'
import Icon from './Icon.vue'

const rows = ref([])
const form = ref({ name: '', url: '', priority: true })
const hint = ref(null)
const cat = ref({ field: '', employers: [] })
const moreCat = ref(false)
const shownCat = computed(() => (moreCat.value ? cat.value.employers : cat.value.employers.filter((e) => e.match || !cat.value.field).slice(0, 14)))
let t

const sorted = computed(() => [...rows.value].sort((a, b) => Number(b.priority) - Number(a.priority) || a.name.localeCompare(b.name)))
async function load() { rows.value = (await api.get('/employers')).employers; cat.value = await api.get('/employers/catalog') }
const quick = (e) => run(() => api.post('/employers', { name: e.name, url: e.url, priority: false }), `已添加 ${e.name}`, load)
watch(() => form.value.url, (u) => {
  clearTimeout(t); hint.value = null
  if (u.trim().length > 8) t = setTimeout(async () => { try { hint.value = await api.post('/employers/detect', { url: u }) } catch (e) { /* ignore */ } }, 350)
})
const add = () => run(async () => { const r = await api.post('/employers', form.value); form.value = { name: '', url: '', priority: true }; hint.value = null; return r }, (r) => `已添加 ${r.name}（${r.kind_label}），下次扫描时开始读取`, load)
const patch = (e, body) => run(() => api.patch('/employers/' + e.id, body), '', load)
const remove = async (e) => (await ask(`不再关注 ${e.name}？已经找到的岗位会保留，只是不再读取新的。`, { ok: '移除', danger: true })) && run(() => api.del('/employers/' + e.id), `已移除 ${e.name}`, load)
const scan = () => run(() => api.post('/tasks', { kind: 'discover' }), '开始扫描，完成后会通知你')
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="row"><span class="card-title grow">关注的雇主</span><button @click="scan"><Icon name="search" />现在扫描一次</button></div>
    <p class="muted">你想盯住的公司。把它招聘页的网址贴进来就行：用常见招聘系统的公司会直接读它的岗位列表；其他网站由 AI 打开招聘页，从里面找出岗位。读到的岗位只有符合“入库条件”的才会留下。</p>

    <div class="emp-add">
      <input v-model="form.url" class="grow" placeholder="招聘页网址，例如 https://www.mckinsey.com/careers/search-jobs" @keyup.enter="form.url && add()" />
      <input v-model="form.name" style="width: 190px" placeholder="公司名称（可不填）" @keyup.enter="form.url && add()" />
      <label class="nowrap" title="重点雇主的岗位会加星标、排在前面，并且在更低的分数就准备草案"><input v-model="form.priority" type="checkbox" /> 重点</label>
      <button class="primary" :disabled="!form.url.trim()" @click="add"><Icon name="check" />添加</button>
    </div>
    <p v-if="hint" class="hint" style="margin: 6px 0 0">识别为：<b>{{ hint.kind_label }}</b>{{ hint.kind === 'page' ? '。每次扫描会用一次 AI 来读这个页面；需要登录才能看的招聘页读不了。' : hint.kind === 'feed' ? '。这是一个职位站的订阅源，里面是很多雇主的最新岗位，可以直接读取，不用 AI。' : '，可以直接读取它的岗位列表。' }}</p>

    <div v-if="cat.employers.length" class="emp-cat">
      <div class="small muted">可以直接添加的（地址已验证能读取{{ cat.field ? '；先列出和你的领域相关的' : '' }}）：</div>
      <div class="row" style="gap: 6px; margin-top: 6px">
        <button v-for="e in shownCat" :key="e.url" class="sm chip" :title="e.kind_label + ' · ' + e.url" @click="quick(e)">+ {{ e.name }}</button>
        <button v-if="cat.employers.length > shownCat.length || moreCat" class="sm ghost" @click="moreCat = !moreCat">{{ moreCat ? '收起' : `全部 ${cat.employers.length} 个…` }}</button>
      </div>
    </div>

    <table v-if="rows.length" style="margin-top: 14px">
      <thead><tr><th style="width: 54px">重点</th><th>公司</th><th>怎么读取</th><th>在招岗位</th><th style="width: 70px">启用</th><th></th></tr></thead>
      <tbody>
        <tr v-for="e in sorted" :key="e.id" :style="e.enabled ? '' : 'opacity: 0.55'">
          <td><button class="star" :class="{ on: e.priority }" :aria-label="e.priority ? '取消重点' : '设为重点'" :title="e.priority ? '重点雇主，点一下取消' : '点一下设为重点雇主'" @click="patch(e, { priority: !e.priority })">★</button></td>
          <td><b>{{ e.name }}</b><div class="small muted ell" style="max-width: 360px"><a :href="e.url" target="_blank" rel="noopener">{{ e.url.replace(/^https?:\/\//, '') }}</a></div></td>
          <td class="small">{{ e.kind_label }}</td>
          <td class="small">{{ e.open_jobs || '—' }}</td>
          <td><input type="checkbox" :checked="e.enabled" :aria-label="'启用 ' + e.name" @change="patch(e, { enabled: !e.enabled })" /></td>
          <td style="text-align: right"><button class="sm ghost danger" @click="remove(e)">移除</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted" style="margin-top: 14px">还没有添加任何雇主。</p>

    <p class="hint" style="margin-top: 14px">添加、移除和这里的开关改了就生效。重点雇主的岗位评分到多少就准备草案，在<router-link to="/settings/automation/prepare">设置 → 自动准备草案</router-link>；在大型官网上搜什么词，在<router-link to="/settings/goals/search">设置 → 在大型官网上搜什么</router-link>。</p>
  </div>
</template>
