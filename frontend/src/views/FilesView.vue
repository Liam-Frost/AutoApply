<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, ROOT } from '../api'
import EmptyState from '../components/EmptyState.vue'
import FileButton from '../components/FileButton.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import PdfView from '../components/PdfView.vue'
import { fmtTime, run, toast, ask, persona } from '../ui'
import { t } from '../i18n/catalog'

const docs = ref([])
const folder = ref('base') // base | generated | all | kind:<k> | job:<id>
const q = ref('')
const showInactive = ref(false)
const cur = ref(null)
const renaming = ref(false)
const newName = ref('')
const upKind = ref('resume_site')
const picked = ref(new Set())

// What a file is used as. `base` kinds are things you upload once; `generated` are written per job.
const KINDS = {
  resume_docx: '简历 Word 原稿（按岗位调整用）', resume_site: '简历（投官网用）', resume_portal: '简历（PD Portal 用）', transcript: '成绩单', summary_sheet: 'Summary Sheet',
  cl_template: '求职信模板', cl_example: '求职信范例', portfolio: '作品集', certificate: '证书 / 证明', reference: '推荐信', research_statement: '研究陈述', teaching_statement: '教学陈述', publications: '发表列表', writing_sample: '写作 / 作品样本', diversity_statement: '多元化陈述', source: '生成个人资料用的素材', other: '其他',
  cover_letter: '求职信', tailored_resume: '定制简历', made: t('files.kind.made'),
}
const GENERATED = ['cover_letter', 'tailored_resume', 'made']
const UPLOADABLE = Object.keys(KINDS).filter((k) => !GENERATED.includes(k) && (!persona.features.doc_kinds || persona.features.doc_kinds.includes(k)))
const GROUPS = [
  ['简历', ['resume_site', 'resume_portal', 'resume_docx']], ['成绩单和证明', ['transcript', 'summary_sheet', 'certificate', 'reference']],
  ['求职信模板和范例', ['cl_template', 'cl_example']], ['作品集和陈述', ['portfolio', 'writing_sample', 'research_statement', 'teaching_statement', 'publications', 'diversity_statement']], ['其他', ['source', 'other']],
]
const isGen = (d) => GENERATED.includes(d.kind)
// What a row's controls are called: two writings of one letter have the same file name, so the version is part of it.
const rowName = (d) => (d.version ? `${d.name}（第 ${d.version} 版）` : d.name)
const openLabel = (d) => `打开 ${rowName(d)}`
const pickLabel = (d) => `选择 ${rowName(d)}`
const base = computed(() => docs.value.filter((d) => !isGen(d)))
const generated = computed(() => docs.value.filter(isGen))
const count = (kinds) => base.value.filter((d) => kinds.includes(d.kind) && d.active).length

// generated files grouped by the job they were written for, newest job first
const jobs = computed(() => {
  const m = new Map()
  for (const d of generated.value) {
    const k = d.job_id || 0
    if (!m.has(k)) m.set(k, { id: k, name: d.for_job || '没有关联岗位', company: d.job_company || '', title: d.job_title || '', where: d.job_where || '', stage: d.job_stage, tone: d.job_tone, archived: d.job_archived, sent: d.job_sent, files: [] })
    m.get(k).files.push(d)
  }
  return [...m.values()].sort((a, b) => b.files[0].id - a.files[0].id)
})
// The jobs in three groups, by where the application stands. What is being prepared is what one looks for; what was
// sent or shelved is kept, folded away, so that the list stays as short as the work in hand.
const SECTIONS = [['open', '正在准备的'], ['sent', '已投递的'], ['old', '已归档的']]
const sectionOf = (j) => (j.archived ? 'old' : j.sent ? 'sent' : 'open')
const bySection = computed(() => Object.fromEntries(SECTIONS.map(([k]) => [k, jobs.value.filter((j) => sectionOf(j) === k)])))
const unfolded = ref(new Set(['open']))
function fold(k) { const s = new Set(unfolded.value); s.has(k) ? s.delete(k) : s.add(k); unfolded.value = s }
const isOpen = (k) => unfolded.value.has(k) || bySection.value[k].some((j) => folder.value === 'job:' + j.id)
// what is narrowed to: files that went out with an application, files an application being prepared still uses; and
// whether the archived ones are shown (archived: put away, kept - a file that went out is what was sent)
const onlySent = ref(false)
const onlyInUse = ref(false)
const showArchived = ref(false)
const archivedCount = computed(() => docs.value.filter((d) => d.archived).length)
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  let rows = docs.value.filter((d) => showArchived.value || !d.archived)
  if (onlySent.value) rows = rows.filter((d) => d.sent)
  if (onlyInUse.value) rows = rows.filter((d) => d.in_use)
  if (folder.value === 'base') rows = rows.filter((d) => !isGen(d))
  else if (folder.value === 'generated') rows = rows.filter(isGen)
  else if (folder.value.startsWith('group:')) rows = rows.filter((d) => !isGen(d) && GROUPS[+folder.value.slice(6)][1].includes(d.kind))
  else if (folder.value.startsWith('job:')) rows = rows.filter((d) => isGen(d) && String(d.job_id || 0) === folder.value.slice(4))
  if (!showInactive.value && !folder.value.startsWith('job:')) rows = rows.filter((d) => d.active)
  if (needle) rows = rows.filter((d) => `${d.name} ${d.for_job} ${KINDS[d.kind] || ''}`.toLowerCase().includes(needle))
  return rows
})
const inactiveCount = computed(() => docs.value.filter((d) => !d.active).length)
const totalSize = computed(() => docs.value.reduce((a, d) => a + (d.size || 0), 0))
const sizeText = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')
const title = computed(() => {
  if (folder.value === 'base') return '我上传的材料'
  if (folder.value === 'generated') return '为岗位生成的文件'
  if (folder.value === 'all') return '全部文件'
  if (folder.value.startsWith('group:')) return GROUPS[+folder.value.slice(6)][0]
  const j = jobs.value.find((x) => String(x.id) === folder.value.slice(4))
  return j ? j.name : ''
})

async function read() { docs.value = await api.get('/documents'); if (cur.value) cur.value = docs.value.find((d) => d.id === cur.value.id) || null }
const act = (fn, ok) => run(fn, ok, load)
function go(f) { folder.value = f; picked.value = new Set(); cur.value = null }
function pick(d) { cur.value = d; renaming.value = false }
function togglePick(id) { const s = new Set(picked.value); s.has(id) ? s.delete(id) : s.add(id); picked.value = s }
function upload(ev) {
  const files = [...ev.target.files]
  if (!files.length) return
  run(async () => {
    let last = null
    for (const f of files) { const fd = new FormData(); fd.append('kind', upKind.value); fd.append('file', f); last = await api.upload('/documents', fd) }
    await load()
    if (last) cur.value = docs.value.find((d) => d.id === last.id) || null
  }, files.length > 1 ? `已上传 ${files.length} 个文件` : `已上传：${files[0].name}`)
  ev.target.value = ''
}
const rename = () => act(async () => { await api.patch('/documents/' + cur.value.id, { name: newName.value }); renaming.value = false }, '已改名')
const setKind = (k) => act(() => api.patch('/documents/' + cur.value.id, { kind: k }), '已更改用途')
const setActive = (on) => act(() => api.patch('/documents/' + cur.value.id, { active: on }), on ? (isGen(cur.value) ? '已改用这一版：之后生成的草案会带上它，已有的草案不变' : '已启用；同类的其他文件已停用') : '已停用，之后的草案不会再用它')
const destroy = async () => (await ask(`彻底删除「${cur.value.name}」？文件会从磁盘上删掉，不能恢复。`)) && act(async () => { await api.del('/documents/' + cur.value.id + '?permanent=true'); cur.value = null }, '已删除')
async function bulk(action) {
  const ids = [...picked.value]
  if (action === 'delete' && !(await ask(t('files.deleteAsk', { n: ids.length }, ids.length)))) return
  await act(() => api.post('/documents/bulk', { action, ids }), (r) => (action === 'delete' ? (r.archived_instead ? t('files.deletedKept', { n: r.done - r.archived_instead, kept: r.archived_instead }) : `已删除 ${ids.length} 个文件`)
    : action === 'archive' ? t('files.archived', { n: ids.length }, ids.length) : `已停用 ${ids.length} 个文件`))
  picked.value = new Set()
}
// Files made for applications that are over (or versions no longer used), that nothing being prepared still uses: put
// away in one go. Archived, never deleted - one that went out is what was sent (the server says which, `cleanable`).
const stale = computed(() => docs.value.filter((d) => d.cleanable))
async function cleanUp() {
  if (!stale.value.length) return toast(t('files.nothingToClean'))
  if (!(await ask(t('files.cleanAsk', { n: stale.value.length }, stale.value.length)))) return
  await act(() => api.post('/documents/bulk', { action: 'archive', ids: stale.value.map((d) => d.id) }), t('files.archived', { n: stale.value.length }, stale.value.length))
}
const setArchived = (on) => act(() => api.post('/documents/bulk', { action: on ? 'archive' : 'unarchive', ids: [cur.value.id] }), on ? t('files.archived', { n: 1 }, 1) : t('files.unarchived'))
const PURPOSE = { mine: 'files.purpose.mine', for_job: 'files.purpose.forJob', made: 'files.purpose.made' }
const previewable = (d) => ['pdf', 'docx', 'doc'].includes(d.ext)
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load)
onMounted(load)
</script>

<template>
  <PageHead title="材料库" sub="申请时会用到的所有文件：你上传的简历、成绩单这类材料，以及程序为每个岗位写的求职信。">
    <AaSelect v-model="upKind" title="上传的文件用作什么"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect>
    <FileButton class="primary" multiple @change="upload"><Icon name="draft" />上传</FileButton>
  </PageHead>
  <DataState :s="st" what="材料库" @retry="load" />
  <template v-if="st.at">

  <div class="fm">
    <!-- folders -->
    <nav class="card fm-nav">
      <button :class="{ on: folder === 'base' }" @click="go('base')"><Icon name="user" />我上传的材料<span class="n">{{ base.filter((d) => d.active).length }}</span></button>
      <button v-for="(g, i) in GROUPS" :key="i" class="sub" :class="{ on: folder === 'group:' + i }" @click="go('group:' + i)">{{ g[0] }}<span class="n">{{ count(g[1]) }}</span></button>

      <button style="margin-top: 10px" :class="{ on: folder === 'generated' }" @click="go('generated')"><Icon name="briefcase" />为岗位生成的<span class="n">{{ generated.length }}</span></button>
      <template v-for="[k, label] in SECTIONS" :key="k">
        <template v-if="bySection[k].length">
          <button class="sub fold" :aria-expanded="isOpen(k)" @click="fold(k)"><Icon :name="isOpen(k) ? 'chevron_up' : 'chevron'" />{{ label }}<span class="n">{{ bySection[k].length }}</span></button>
          <template v-if="isOpen(k)">
            <button v-for="j in bySection[k]" :key="j.id" class="sub deep" :class="{ on: folder === 'job:' + j.id }" :title="j.name" @click="go('job:' + j.id)">
              <span v-if="j.company" class="fm-job"><b class="ell">{{ j.company }}</b><span class="ell">{{ j.title }}<template v-if="j.where"> · {{ j.where }}</template></span></span>
              <span v-else class="ell">{{ j.name }}</span><span class="n">{{ j.files.length }}</span>
            </button>
          </template>
        </template>
      </template>
      <div v-if="!jobs.length" class="hint" style="padding: 4px 12px 0 34px">生成求职信后会出现在这里，每个岗位一组。</div>

      <button style="margin-top: 10px" :class="{ on: folder === 'all' }" @click="go('all')"><Icon name="inbox" />全部文件<span class="n">{{ docs.length }}</span></button>
      <div class="fm-foot">
        <div>共 {{ docs.length }} 个文件，{{ sizeText(totalSize) }}</div>
        <button v-if="stale.length" class="sm ghost" style="margin-top: 6px; padding-left: 0" @click="cleanUp">{{ $t('files.clean', { n: stale.length }, stale.length) }}</button>
      </div>
    </nav>

    <!-- list -->
    <div class="card fm-list">
      <div class="row" style="padding: 4px 6px 10px">
        <b class="grow ell">{{ title }}</b>
        <input v-model="q" placeholder="搜索文件名或岗位" style="width: 170px" />
      </div>
      <div class="row small muted" style="padding: 0 8px 8px; flex-wrap: wrap; gap: 10px">
        <label><input v-model="onlySent" type="checkbox" /> {{ $t('files.filter.sent') }}</label>
        <label><input v-model="onlyInUse" type="checkbox" /> {{ $t('files.filter.inUse') }}</label>
        <label v-if="archivedCount"><input v-model="showArchived" type="checkbox" /> {{ $t('files.filter.archived', { n: archivedCount }) }}</label>
      </div>
      <label v-if="inactiveCount && !folder.startsWith('job:')" class="small muted" style="padding: 0 8px 8px; display: block"><input v-model="showInactive" type="checkbox" /> 也显示没在用的（{{ inactiveCount }}）</label>
      <div class="fm-rows">
        <div v-for="d in shown" :key="d.id" class="mat-item" :class="{ on: cur && cur.id === d.id }" @click="pick(d)">
          <input type="checkbox" :checked="picked.has(d.id)" :aria-label="pickLabel(d)" @click.stop @change="togglePick(d.id)" />
          <span class="ext" :class="d.ext">{{ (d.ext || '?').toUpperCase().slice(0, 4) }}</span>
          <span class="grow" style="min-width: 0">
            <button type="button" class="name mat-open" :aria-current="cur && cur.id === d.id ? 'true' : undefined" :aria-label="openLabel(d)" @click.stop="pick(d)">{{ d.name }}</button>
            <span class="sub">{{ KINDS[d.kind] || d.kind }}<template v-if="d.version"> · 第 {{ d.version }} 版</template><template v-if="d.for_job && !folder.startsWith('job:')"> · {{ d.for_job }}</template> · {{ fmtTime(d.created_at) }}</span>
          </span>
          <span v-if="d.archived" class="badge">{{ $t('files.archivedBadge') }}</span>
          <span v-else-if="d.sent" class="badge ok">{{ $t('files.sentBadge') }}</span>
          <span v-if="d.missing" class="badge bad">文件丢失</span>
          <span v-else-if="d.problems.length" class="badge warn" title="自检发现了问题">有问题</span>
          <span v-else-if="d.overwritten" class="badge warn" title="这一版的文件被后来写的那一版覆盖了">已被覆盖</span>
          <span v-else-if="!d.active" class="badge">{{ isGen(d) ? '没在用的版本' : '没在用' }}</span>
        </div>
        <EmptyState v-if="!shown.length" icon="draft" :title="q ? '没有找到' : '这里还没有文件'" :text="folder === 'base' && !q ? '先上传一份简历，草案里才有文件可交。' : ''" />
      </div>
      <div v-if="picked.size" class="row fm-bulk">
        <b>已选 {{ picked.size }} 个</b><span class="grow"></span>
        <button class="sm" @click="bulk('archive')">{{ $t('files.archive') }}</button>
        <button class="sm" @click="bulk('stop')">停用</button>
        <button class="sm danger" @click="bulk('delete')">彻底删除</button>
        <button class="sm ghost" @click="picked = new Set()">取消</button>
      </div>
    </div>

    <!-- preview -->
    <div class="card fm-view">
      <template v-if="cur">
        <div class="row" style="align-items: flex-start">
          <div class="grow" style="min-width: 0">
            <div v-if="renaming" class="row"><input v-model="newName" class="grow" @keyup.enter="rename" /><button class="primary sm" @click="rename">保存</button><button class="sm ghost" @click="renaming = false">取消</button></div>
            <div v-else class="card-title" style="overflow-wrap: anywhere">{{ cur.name }}</div>
            <div class="muted small">{{ KINDS[cur.kind] || cur.kind }} · {{ fmtTime(cur.created_at) }} · {{ sizeText(cur.size) }}<template v-if="cur.pages"> · {{ cur.pages }} 页</template><template v-if="cur.version"> · 第 {{ cur.version }} 版</template></div>
            <div v-if="cur.for_job" class="small" style="margin-top: 2px">为 <router-link :to="{ path: '/jobs', query: { open: cur.job_id } }">{{ cur.for_job }}</router-link> 写的 <span v-if="cur.job_stage" class="badge" :class="cur.job_tone">{{ cur.job_stage }}</span></div>
          </div>
          <span class="badge" :class="cur.active ? 'ok' : ''">{{ cur.active ? '在用' : isGen(cur) ? '没在用的版本' : '没在用' }}</span>
        </div>
        <div class="small" style="margin-top: 8px">
          <div><span class="muted">{{ $t('files.purpose.label') }}</span> {{ $t(PURPOSE[cur.purpose] || 'files.purpose.mine') }}</div>
          <div v-if="cur.made_from.length" class="muted">{{ $t('files.madeFrom') }} {{ cur.made_from.join('；') }}</div>
          <div v-if="cur.application"><span class="muted">{{ $t('files.belongs') }}</span> <router-link :to="`/applications/${cur.application.id}`">{{ cur.for_job }}</router-link>
            <span class="tag" style="margin-left: 4px">{{ cur.application.label }}</span><span v-if="cur.application.ended" class="tag" style="margin-left: 4px">{{ $t('files.ended') }}</span></div>
          <div style="margin-top: 4px"><span class="muted">{{ $t('files.went') }}</span>
            <span v-if="!cur.went.length">{{ $t('files.wentNowhere') }}</span>
            <div v-for="(w, k) in cur.went" :key="k" style="margin: 2px 0 0 12px">
              <span class="tag" :class="w.sent ? 'ok' : ''">{{ w.how === 'mail' ? $t('files.how.mail') : w.sent ? $t('files.how.sent') : $t('files.how.record') }}</span>
              <router-link v-if="w.application_id" :to="`/applications/${w.application_id}`">{{ w.company }} · {{ w.title }}</router-link>
              <span v-if="w.field" class="muted"> · {{ w.field }}</span>
            </div>
          </div>
        </div>
        <div v-if="cur.in_draft && !cur.active" class="callout" style="margin-top: 10px; display: block"><span class="small">这个岗位现有的草案带的还是这一版。之后新生成的草案会用“在用”的那一版。</span></div>
        <div v-if="cur.overwritten" class="callout warn" style="margin-top: 10px; display: block"><b>这一版的文件已经被覆盖</b><div class="small">早先的程序每次重写都写进同一个文件，所以这里打开的是后来写的那一版，不是当时的内容。现在每次重写都单独保存，不会再发生。</div></div>
        <div v-if="cur.problems.length" class="callout warn" style="margin-top: 10px; display: block"><b>自检发现的问题</b><div v-for="(x, k) in cur.problems" :key="k" class="small">{{ x }}</div></div>
        <div class="row" style="margin: 12px 0 8px">
          <a :href="`api/documents/${cur.id}/file`" :download="cur.name" class="btn sm"><Icon name="external" />下载</a>
          <button v-if="!renaming" class="sm" @click="renaming = true; newName = cur.name"><Icon name="edit" />改名</button>
          <AaSelect v-if="!isGen(cur)" small :value="cur.kind" title="这个文件用作什么" @change="setKind($event.target.value)"><option v-for="k in UPLOADABLE" :key="k" :value="k">用作：{{ KINDS[k] }}</option></AaSelect>
          <button v-if="cur.active" class="sm" @click="setActive(false)">停用</button>
          <button v-else class="sm" :disabled="cur.missing || cur.overwritten" @click="setActive(true)">{{ isGen(cur) ? '改用这一版' : '重新启用' }}</button>
          <button class="sm" @click="setArchived(!cur.archived)">{{ cur.archived ? $t('files.unarchive') : $t('files.archive') }}</button>
          <button v-if="!cur.sent" class="sm ghost danger" @click="destroy">彻底删除</button>
        </div>
        <div v-if="cur.missing" class="empty"><div class="t">文件已经不在磁盘上了</div><div>只剩一条记录，可以直接删除。</div></div>
        <PdfView v-else-if="previewable(cur)" :key="cur.id" :src="`${ROOT}/api/documents/${cur.id}/bytes`" />
        <div v-else class="empty"><div class="t">这种文件不能在页面里预览</div><div>请点“下载”后查看。</div></div>
      </template>
      <EmptyState v-else icon="search" title="点一个文件来预览" text="PDF 和 Word 文件可以直接在这里看。" />
    </div>
  </div>
  </template>
</template>
