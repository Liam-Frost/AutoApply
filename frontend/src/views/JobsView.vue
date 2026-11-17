<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, fmt } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
import { renderMarkdown } from '../md'
import { run, toast, ask, persona } from '../ui'

const route = useRoute()
const router = useRouter()
const jobs = ref([])
const counts = ref({})
const groups = ref([])
const stages = ref([])
const group = ref('todo')
const sortKey = ref('score')
const sortDir = ref(-1)
const sel = ref(null)
const newUrl = ref('')
const picked = ref(new Set())
const showJd = ref(false)
const showArchived = ref(false)

// Optional columns. The fixed ones (score, job, deadline, status, latest) answer "what is it, how good, how urgent, where does it stand";
// the rest is detail that lives in the drawer unless the user asks for it here.
const COLS = { source: '来源', direction: '方向', salary: '薪资', channel: '在哪里投', posted: '发布日期', first_seen: '发现日期' }
let saved = null
try { saved = JSON.parse(localStorage.getItem('jobs.cols') || 'null') } catch { /* private window */ }
const cols = ref(new Set(Array.isArray(saved) ? saved : persona.features.job_columns || ['source']))
function toggleCol(k) {
  const s = new Set(cols.value); s.has(k) ? s.delete(k) : s.add(k); cols.value = s
  try { localStorage.setItem('jobs.cols', JSON.stringify([...s])) } catch { /* ignore */ }
}

// Filters. Empty string / 0 / false = not filtering on that field.
const f = reactive({ q: '', stage: '', minScore: 0, direction: '', term: '', channel: '', deadline: '', link: false, prio: false })
const DEADLINES = { '': '任何截止时间', 3: '3 天内截止', 7: '7 天内截止', 14: '14 天内截止', none: '没写截止时间' }
const activeFilters = computed(() => ['q', 'stage', 'direction', 'term', 'channel', 'deadline'].filter((k) => f[k]).length + (f.minScore ? 1 : 0) + (f.link ? 1 : 0) + (f.prio ? 1 : 0))
function clearFilters() { Object.assign(f, { q: '', stage: '', minScore: 0, direction: '', term: '', channel: '', deadline: '', link: false, prio: false }) }

const inGroup = (job, g) => (showArchived.value || !job.archived) && (g === 'all' || job.stage_group === g)
const archivedCount = computed(() => jobs.value.filter((j) => j.archived).length)
const inScope = computed(() => jobs.value.filter((j) => inGroup(j, group.value)))
const options = (key) => computed(() => {
  const m = new Map()
  for (const j of inScope.value) { const v = j[key]; if (v) m.set(v, (m.get(v) || 0) + 1) }
  return [...m.entries()].sort((a, b) => b[1] - a[1])
})
const directions = options('direction')
const terms = options('term')
const channels = options('channel_label')
const groupStages = computed(() => stages.value.filter((x) => group.value === 'all' || x.group === group.value))
const groupCount = (g) => jobs.value.filter((j) => inGroup(j, g)).length
function pickGroup(k) { group.value = k; f.stage = ''; picked.value = new Set() }

// A search looks in the group that is open. What it would find in the other groups is counted, so that "one result"
// does not read as "this posting is not in the library" when it sits under "not applying" or "applied".
const elsewhere = computed(() => {
  const needle = f.q.trim().toLowerCase()
  if (!needle || group.value === 'all') return 0
  return jobs.value.filter((j) => !inGroup(j, group.value) && (showArchived.value || !j.archived)
    && `${j.company} ${j.title} ${j.source_id} ${j.direction} ${j.summary} ${j.location}`.toLowerCase().includes(needle)).length
})
function daysTo(dl) { return dl ? Math.ceil((new Date(dl.replace(' ', 'T')).getTime() - Date.now()) / 86400000) : null }
const rows = computed(() => {
  const needle = f.q.trim().toLowerCase()
  const out = inScope.value.filter((j) => {
    if (f.stage && j.stage !== f.stage) return false
    if (f.minScore && (j.score ?? -1) < f.minScore) return false
    if (f.direction && j.direction !== f.direction) return false
    if (f.term && j.term !== f.term) return false
    if (f.channel && j.channel_label !== f.channel) return false
    if (f.link && !j.apply_url) return false
    if (f.prio && !j.priority) return false
    if (f.deadline === 'none' && j.deadline) return false
    if (f.deadline && f.deadline !== 'none') { const d = daysTo(j.deadline); if (d == null || d < 0 || d > +f.deadline) return false }
    return !needle || `${j.company} ${j.title} ${j.source_id} ${j.direction} ${j.summary} ${j.location}`.toLowerCase().includes(needle)
  })
  const k = sortKey.value
  return out.sort((a, b) => {
    const x = a[k] ?? (k === 'score' ? -1 : ''), y = b[k] ?? (k === 'score' ? -1 : '')
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir.value || Number(b.priority) - Number(a.priority) || (b.score ?? -1) - (a.score ?? -1)
  })
})
function sortBy(k) { if (sortKey.value === k) sortDir.value *= -1; else { sortKey.value = k; sortDir.value = k === 'score' ? -1 : 1 } }
const arrow = (k) => (sortKey.value === k ? (sortDir.value > 0 ? ' ↑' : ' ↓') : '')
const scoreCls = (s) => (s == null ? '' : s >= 9 ? 'hi' : s >= 7.5 ? 'mid' : s < 6 ? 'lo' : '')

// selection
const allPicked = computed(() => rows.value.length > 0 && rows.value.every((j) => picked.value.has(j.id)))
function togglePick(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function toggleAll() { picked.value = allPicked.value ? new Set() : new Set(rows.value.map((j) => j.id)) }
const BULK = {
  draft: ['生成申请草案', (r) => `${r.done} 个岗位已排队生成草案` + (r.skipped ? `；${r.skipped} 个跳过（没有链接、已下线或已投过）` : '')],
  score: ['重新评分', (r) => `${r.done} 个岗位已排队评分` + (r.skipped ? `；${r.skipped} 个没有岗位说明，没法评分` : '')],
  skip: ['不投这些', (r) => `${r.done} 个岗位已标为不投递` + (r.skipped ? `；${r.skipped} 个已经投出，没有改动` : '')],
  archive: ['归档', (r) => `${r.done} 个岗位已归档，在“显示已归档”里还能找到`],
  unarchive: ['取消归档', (r) => `${r.done} 个岗位已放回列表`],
  restore: ['恢复为未投递', (r) => `${r.done} 个岗位已恢复` + (r.skipped ? `；${r.skipped} 个本来就不是“不投递”` : '')],
}
async function bulk(action) {
  const ids = [...picked.value]
  if (action === 'draft' && ids.length > 5 && !(await ask(`要为 ${ids.length} 个岗位生成草案吗？每个需要一两分钟，会占用 AI 额度。`))) return
  await run(() => api.post('/jobs/bulk', { action, ids }), BULK[action][1], load)
  picked.value = new Set()
}

async function load() {
  const d = await api.get('/jobs')
  jobs.value = d.jobs; counts.value = d.counts; groups.value = d.groups; stages.value = d.stages
}
async function open(j) { sel.value = await api.get('/jobs/' + j.id); showJd.value = false; if (route.query.open) router.replace({ path: '/jobs' }) }
const refreshSel = async () => { if (sel.value) sel.value = await api.get('/jobs/' + sel.value.id) }
const briefing = ref(false)
async function writeBrief() {
  briefing.value = true
  try { const r = await api.post(`/jobs/${sel.value.id}/brief`); if (r.brief) sel.value = { ...sel.value, brief: r.brief }; else toast('没有写出来：这个岗位没有可读的说明', 'bad') } catch (e) { toast(e.message, 'bad') } finally { briefing.value = false }
}
const act = (fn, ok) => run(fn, ok, async () => { await load(); await refreshSel() })
const makeDraft = () => act(() => api.post(`/jobs/${sel.value.id}/draft`), '已开始：读取申请表并生成草案，完成后会通知你')
const rescore = () => act(() => api.post(`/jobs/${sel.value.id}/score`), '已开始重新评分')
const setStatus = (s) => act(() => api.patch(`/jobs/${sel.value.id}`, { status: s }), s === 'skipped' ? '已标为不投递' : '已恢复为未投递')
const setArchived = (on) => act(() => api.post('/jobs/bulk', { action: on ? 'archive' : 'unarchive', ids: [sel.value.id] }), on ? '已归档' : '已放回列表')
const saveUrl = () => act(() => api.patch(`/jobs/${sel.value.id}`, { apply_url: sel.value.apply_url }), '申请链接已保存')
const addJob = () => run(async () => { await api.post('/jobs', { url: newUrl.value }); newUrl.value = '' }, '岗位已添加，稍后会评分', load)
const scan = () => run(() => api.post('/tasks', { kind: 'discover' }), '开始扫描新岗位，完成后会通知你')
const mail = () => run(() => api.post('/tasks', { kind: 'mail' }), '开始检查邮箱')
const sent = computed(() => sel.value && ['submitted', 'confirmed', 'rejected', 'interview', 'assessment', 'offer'].includes(sel.value.app_status))
const facts = computed(() => {
  const j = sel.value
  if (!j) return []
  return [['学期', j.term], ['时长', j.months ? j.months + ' 个月' : ''], ['薪资', j.salary], ['地点 / 形式', j.location || j.work_type], ['截止时间', j.deadline], ['在哪里投', j.channel_label],
    ['要交的材料', j.docs_required], ['方向', j.direction], ['来源', j.source_label], ['发布日期', j.posted], ['岗位编号', j.source_id && j.source_id.length <= 12 ? j.source_id : '']].filter((x) => x[1])
})
watch(() => route.query.open, (id) => { if (id) open({ id }) })
if (route.query.q) f.q = String(route.query.q)
onMounted(async () => { await load(); if (route.query.open) open({ id: route.query.open }) })
</script>

<template>
  <PageHead title="岗位" sub="所有找到的岗位，以及每个申请进行到哪一步。点一行看详情，勾选多行可以批量操作。">
    <button @click="mail"><Icon name="mail" />检查邮箱</button>
    <button @click="scan"><Icon name="search" />扫描新岗位</button>
  </PageHead>

  <div class="seg" style="margin-bottom: 12px">
    <button v-for="g in groups" :key="g.key" :class="{ on: group === g.key }" @click="pickGroup(g.key)">{{ g.label }}<span class="n">{{ groupCount(g.key) }}</span></button>
  </div>

  <div class="filters">
    <input v-model="f.q" placeholder="搜索公司、岗位、地点或编号" style="width: 240px" />
    <AaSelect v-if="groupStages.length > 1" v-model="f.stage"><option value="">全部状态</option><option v-for="x in groupStages" :key="x.key" :value="x.key">{{ x.label }}（{{ counts[x.key] || 0 }}）</option></AaSelect>
    <AaSelect v-model="f.direction"><option value="">全部方向</option><option v-for="[v, n] in directions" :key="v" :value="v">{{ v }}（{{ n }}）</option></AaSelect>
    <AaSelect v-if="persona.features.term" v-model="f.term"><option value="">全部学期</option><option v-for="[v, n] in terms" :key="v" :value="v">{{ v }}（{{ n }}）</option></AaSelect>
    <AaSelect v-model="f.channel"><option value="">在哪里投都行</option><option v-for="[v, n] in channels" :key="v" :value="v">{{ v }}（{{ n }}）</option></AaSelect>
    <AaSelect v-model="f.deadline"><option v-for="(l, k) in DEADLINES" :key="k" :value="k">{{ l }}</option></AaSelect>
    <label class="muted nowrap">评分至少 <input v-model.number="f.minScore" type="number" min="0" max="10" step="0.5" style="width: 68px" /></label>
    <label class="muted nowrap"><input v-model="f.link" type="checkbox" /> 只看有申请链接的</label>
    <label v-if="jobs.some((j) => j.priority)" class="muted nowrap"><input v-model="f.prio" type="checkbox" /> 只看重点雇主</label>
    <label v-if="archivedCount" class="muted nowrap"><input v-model="showArchived" type="checkbox" /> 显示已归档（{{ archivedCount }}）</label>
    <button v-if="activeFilters" class="ghost sm" @click="clearFilters"><Icon name="x" />清空筛选</button>
    <span class="grow"></span>
    <span class="muted small nowrap">{{ rows.length }} 个岗位</span>
    <details class="colpick">
      <summary class="btn sm ghost">显示的列</summary>
      <div class="menu"><label v-for="(l, k) in COLS" :key="k"><input type="checkbox" :checked="cols.has(k)" @change="toggleCol(k)" /> {{ l }}</label></div>
    </details>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th style="width: 36px"><input type="checkbox" :checked="allPicked" aria-label="全选" @change="toggleAll" /></th>
          <th class="sortable" @click="sortBy('score')">评分{{ arrow('score') }}</th>
          <th class="sortable" @click="sortBy('company')">岗位{{ arrow('company') }}</th>
          <th v-if="cols.has('source')">来源</th>
          <th v-if="cols.has('direction')">方向</th>
          <th v-if="cols.has('salary')">薪资</th>
          <th v-if="cols.has('channel')">在哪里投</th>
          <th v-if="cols.has('posted')" class="sortable" @click="sortBy('posted')">发布{{ arrow('posted') }}</th>
          <th v-if="cols.has('first_seen')" class="sortable" @click="sortBy('first_seen')">发现{{ arrow('first_seen') }}</th>
          <th class="sortable" @click="sortBy('deadline')">截止{{ arrow('deadline') }}</th>
          <th>状态</th>
          <th>最新情况</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="j in rows" :key="j.id" class="clickable" @click="open(j)">
          <td @click.stop><input type="checkbox" :checked="picked.has(j.id)" :aria-label="'选择 ' + j.company" @change="togglePick(j.id)" /></td>
          <td><span class="score" :class="scoreCls(j.score)">{{ j.score == null ? '—' : j.score.toFixed(1) }}</span></td>
          <td class="jobcell">
            <div><span v-if="j.priority" class="star on" title="你标为重点的雇主" style="cursor: default">★</span><b>{{ j.company }}</b> <span v-if="j.also_listed" class="tag" title="同一个岗位在别的来源也出现了，已合并">+{{ j.also_listed }} 处</span></div>
            <div>{{ j.title }} <a v-if="j.apply_url" :href="j.apply_url" target="_blank" rel="noopener" title="打开岗位链接" @click.stop>↗</a></div>
            <div class="small muted">{{ [j.location, persona.features.term ? j.term : '', persona.features.term && j.months ? j.months + ' 个月' : ''].filter(Boolean).join(' · ') }}</div>
          </td>
          <td v-if="cols.has('source')" class="small nowrap">{{ j.source_label }}</td>
          <td v-if="cols.has('direction')" class="small">{{ j.direction }}</td>
          <td v-if="cols.has('salary')" class="small">{{ j.salary }}</td>
          <td v-if="cols.has('channel')" class="small nowrap">{{ j.channel_label }}</td>
          <td v-if="cols.has('posted')" class="small nowrap">{{ (j.posted || '').slice(0, 10) || '—' }}</td>
          <td v-if="cols.has('first_seen')" class="small nowrap">{{ j.first_seen || '—' }}</td>
          <td class="small nowrap">{{ (j.deadline || '').slice(5, 10) || '—' }}</td>
          <td class="nowrap"><span class="tag" :class="j.stage_tone">{{ j.stage_label }}</span><span v-if="j.archived" class="tag" style="margin-left: 4px">已归档</span><span v-if="!j.online && j.stage !== 'offline'" class="tag" style="margin-left: 4px">已下线</span></td>
          <td class="small muted" style="min-width: 200px; max-width: 340px"><div class="clamp2">{{ j.app_detail || j.exclusion || j.note }}</div></td>
        </tr>
      </tbody>
    </table>
    <div v-if="elsewhere" class="callout" style="margin: 10px 0 0">
      <Icon name="info" /><div>另有 {{ elsewhere }} 个符合搜索的岗位在别的分组里（已投递、不投递等）。 <button class="ghost sm" @click="pickGroup('all')">在全部岗位里看</button></div>
    </div>
    <EmptyState v-if="!rows.length" icon="briefcase" title="没有符合条件的岗位" :text="activeFilters ? '试试清空筛选条件。' : '换一个分组看看，或者扫描新岗位。'">
      <button v-if="activeFilters" @click="clearFilters">清空筛选</button>
    </EmptyState>
  </div>

  <div class="row" style="margin-top: 12px">
    <input v-model="newUrl" placeholder="粘贴一个岗位的网址来添加" style="width: 360px" />
    <button :disabled="!newUrl" @click="addJob">添加岗位</button>
  </div>

  <div v-if="picked.size" class="bulkbar">
    <b>已选 {{ picked.size }} 个</b>
    <button class="sm" @click="bulk('draft')">{{ BULK.draft[0] }}</button>
    <button class="sm" @click="bulk('score')">{{ BULK.score[0] }}</button>
    <button class="sm" @click="bulk('skip')">{{ BULK.skip[0] }}</button>
    <button class="sm" @click="bulk('restore')">{{ BULK.restore[0] }}</button>
    <button class="sm" @click="bulk('archive')">{{ BULK.archive[0] }}</button>
    <button v-if="showArchived" class="sm" @click="bulk('unarchive')">{{ BULK.unarchive[0] }}</button>
    <button class="sm ghost" style="border-color: transparent" @click="picked = new Set()">取消选择</button>
  </div>

  <!-- detail drawer -->
  <div v-if="sel" class="overlay" @click="sel = null"></div>
  <div v-if="sel" class="drawer">
    <div class="row" style="align-items: flex-start">
      <div class="grow">
        <h2 style="margin: 0">{{ sel.company }}</h2>
        <div style="font-size: 16px; color: var(--text-2)">{{ sel.title }}</div>
      </div>
      <button class="ghost" aria-label="关闭" @click="sel = null"><Icon name="x" /></button>
    </div>
    <div class="row" style="margin: 12px 0">
      <span class="tag" :class="sel.stage_tone">{{ sel.stage_label }}</span>
      <span v-if="!sel.online && sel.stage !== 'offline'" class="tag">岗位已下线</span>
      <span class="score" :class="scoreCls(sel.score)">{{ sel.score == null ? '还没评分' : '评分 ' + sel.score }}</span>
      <span v-if="sel.exclusion" class="tag bad">{{ sel.exclusion }}</span>
      <span v-if="sel.archived" class="tag">已归档</span>
    </div>

    <div class="row" style="margin-bottom: 16px">
      <button class="primary" :disabled="!sel.apply_url || sent" @click="makeDraft"><Icon name="draft" />生成申请草案</button>
      <a v-if="sel.apply_url" :href="sel.apply_url" target="_blank" rel="noopener" class="btn"><Icon name="external" />看原岗位</a>
      <button :disabled="!sel.has_jd" :title="sel.has_jd ? '' : '没有岗位说明全文，没法评分'" @click="rescore">重新评分</button>
      <button v-if="sel.status !== 'skipped'" :disabled="sent" @click="setStatus('skipped')">不投这个</button>
      <button v-else @click="setStatus('scored')">恢复为未投递</button>
      <button v-if="!sel.archived" title="从日常列表里收起来，记录保留" @click="setArchived(true)">归档</button>
      <button v-else @click="setArchived(false)">取消归档</button>
      <router-link v-if="sel.drafts.length" :to="'/drafts/' + sel.drafts[sel.drafts.length - 1].id" class="btn"><Icon name="draft" />查看草案<span v-if="sel.drafts.length > 1" class="muted">（第 {{ sel.drafts[sel.drafts.length - 1].version }} 版）</span></router-link>
    </div>
    <p v-if="!sel.apply_url" class="callout warn"><Icon name="alert" /><span>这个岗位还没有申请链接，所以没法生成草案。把雇主官网上这个岗位的网址贴到下面保存即可。</span></p>

    <div class="card">
      <div class="facts">
        <div v-for="[k, v] in facts" :key="k"><div class="k">{{ k }}</div><div class="v">{{ v }}</div></div>
      </div>
      <div class="row" style="margin-top: 14px">
        <input v-model="sel.apply_url" class="grow" placeholder="申请链接（雇主官网上这个岗位的网址）" />
        <button class="sm" @click="saveUrl">保存链接</button>
      </div>
    </div>

    <div v-if="sel.contacts && sel.contacts.length" class="callout">
      <Icon name="user" />
      <div>
        <b>这家公司你认识 {{ sel.contacts.length }} 个人</b>
        <div v-for="c in sel.contacts" :key="c.id" class="small" style="margin-top: 4px">{{ c.name }}<span v-if="c.role" class="muted">（{{ c.role }}）</span><span v-if="c.relation"> · {{ c.relation }}</span><span v-if="c.status === 'referred'" class="tag ok" style="margin-left: 6px">已帮你内推</span></div>
        <router-link to="/contacts" class="small">去“人脉与内推”查看 →</router-link>
      </div>
    </div>

    <div v-if="sel.duplicates && sel.duplicates.length" class="callout">
      <Icon name="link" />
      <div>
        <b>这个岗位在别处也出现了，已合并成这一条</b>（来自 {{ sel.source_label }}）
        <div v-for="d in sel.duplicates" :key="d.id" class="small" style="margin-top: 4px">
          {{ d.source_label }}：<a v-if="d.apply_url" :href="d.apply_url" target="_blank" rel="noopener">{{ d.title }}</a><span v-else>{{ d.title }}</span><span v-if="!d.online" class="muted">（已下线）</span>
        </div>
      </div>
    </div>

    <div v-if="sel.history && sel.history.length" class="callout">
      <Icon name="activity" />
      <div>
        <b>这家公司以前出现过相同或相近的岗位</b>
        <div v-for="h in sel.history" :key="h.id" class="small" style="margin-top: 4px">
          {{ h.first_seen.slice(0, 7) }} · <a href="#" @click.prevent="open(h)">{{ h.title }}</a><span v-if="h.term" class="muted">（{{ h.term }}）</span>
          <span class="tag" :class="h.stage_tone" style="margin-left: 6px">{{ h.applied ? '投过 · ' : '' }}{{ h.stage_label }}</span>
        </div>
      </div>
    </div>

    <template v-if="sel.app_status">
      <h3>申请进展</h3>
      <div class="card">
        <div>{{ sel.app_explained.message || sel.stage_label }}</div>
        <div v-if="sel.submitted_at" class="muted small" style="margin-top: 4px">提交于 {{ fmt(sel.submitted_at) }}</div>
        <TechDetails :text="sel.app_explained.detail" />
        <template v-if="sel.evidence && (sel.evidence.text || sel.evidence.url)">
          <details class="tech"><summary>提交成功时网站显示的内容</summary><pre>{{ sel.evidence.url }}
{{ sel.evidence.text }}</pre></details>
        </template>
      </div>
    </template>

    <template v-if="sel.score_reason">
      <h3>为什么是这个分数</h3>
      <div class="card">{{ sel.score_reason }}</div>
    </template>

    <template v-if="sel.brief">
      <h3>岗位概况</h3>
      <div class="card md" v-html="renderMarkdown(sel.brief)"></div>
    </template>
    <p v-else-if="sel.has_jd !== false && sel.score != null" class="small muted">
      这个岗位的评分不高，程序没有为它写详细的概况。
      <button class="sm ghost" :disabled="briefing" @click="writeBrief">{{ briefing ? '正在写…' : '现在写一份' }}</button>
    </p>

    <h3>岗位说明原文</h3>
    <div class="card">
      <template v-if="sel.jd_text && sel.jd_text.length >= 200">
        <pre style="font-family: inherit; font-size: 13.5px; line-height: 1.6" :style="showJd || sel.jd_text.length < 900 ? '' : 'max-height: 200px; overflow: hidden; -webkit-mask-image: linear-gradient(#000 60%, transparent)'">{{ sel.jd_text }}</pre>
        <button v-if="sel.jd_text.length >= 900" class="ghost sm" style="margin-top: 6px" @click="showJd = !showJd">{{ showJd ? '收起' : '展开全文' }}</button>
      </template>
      <template v-else>
        <p v-if="sel.summary || sel.note || sel.jd_text" style="margin-bottom: 8px">{{ sel.jd_text || sel.summary || sel.note }}</p>
        <p class="muted small" style="margin: 0">这个岗位是从旧表格导入的，只有一句简介，没有岗位说明全文，所以没有详细概况，也没法重新评分。可以点“看原岗位”到官网查看。</p>
      </template>
    </div>
  </div>
</template>
