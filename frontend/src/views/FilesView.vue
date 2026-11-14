<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import PdfView from '../components/PdfView.vue'
import { fmtTime, run, toast, ask, persona } from '../ui'

const docs = ref([])
const folder = ref('base') // base | generated | all | kind:<k> | job:<id>
const q = ref('')
const showInactive = ref(false)
const cur = ref(null)
const renaming = ref(false)
const newName = ref('')
const upKind = ref('resume_site')
const picked = ref(new Set())
const openJobs = ref(new Set())

// What a file is used as. `base` kinds are things you upload once; `generated` are written per job.
const KINDS = {
  resume_docx: '简历 Word 原稿（按岗位调整用）', resume_site: '简历（投官网用）', resume_portal: '简历（PD Portal 用）', transcript: '成绩单', summary_sheet: 'Summary Sheet',
  cl_template: '求职信模板', cl_example: '求职信范例', portfolio: '作品集', certificate: '证书 / 证明', reference: '推荐信', research_statement: '研究陈述', teaching_statement: '教学陈述', publications: '发表列表', writing_sample: '写作 / 作品样本', diversity_statement: '多元化陈述', source: '生成个人资料用的素材', other: '其他',
  cover_letter: '求职信', tailored_resume: '定制简历',
}
const GENERATED = ['cover_letter', 'tailored_resume']
const UPLOADABLE = Object.keys(KINDS).filter((k) => !GENERATED.includes(k) && (!persona.features.doc_kinds || persona.features.doc_kinds.includes(k)))
const GROUPS = [
  ['简历', ['resume_site', 'resume_portal', 'resume_docx']], ['成绩单和证明', ['transcript', 'summary_sheet', 'certificate', 'reference']],
  ['求职信模板和范例', ['cl_template', 'cl_example']], ['作品集和陈述', ['portfolio', 'writing_sample', 'research_statement', 'teaching_statement', 'publications', 'diversity_statement']], ['其他', ['source', 'other']],
]
const isGen = (d) => GENERATED.includes(d.kind)
const base = computed(() => docs.value.filter((d) => !isGen(d)))
const generated = computed(() => docs.value.filter(isGen))
const count = (kinds) => base.value.filter((d) => kinds.includes(d.kind) && d.active).length

// generated files grouped by the job they were written for, newest job first
const jobs = computed(() => {
  const m = new Map()
  for (const d of generated.value) {
    const k = d.job_id || 0
    if (!m.has(k)) m.set(k, { id: k, name: d.for_job || '没有关联岗位', stage: d.job_stage, tone: d.job_tone, archived: d.job_archived, files: [] })
    m.get(k).files.push(d)
  }
  return [...m.values()].sort((a, b) => b.files[0].id - a.files[0].id)
})
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  let rows = docs.value
  if (folder.value === 'base') rows = base.value
  else if (folder.value === 'generated') rows = generated.value
  else if (folder.value.startsWith('group:')) rows = base.value.filter((d) => GROUPS[+folder.value.slice(6)][1].includes(d.kind))
  else if (folder.value.startsWith('job:')) rows = generated.value.filter((d) => String(d.job_id || 0) === folder.value.slice(4))
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

async function load() { docs.value = await api.get('/documents'); if (cur.value) cur.value = docs.value.find((d) => d.id === cur.value.id) || null }
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
const setActive = (on) => act(() => api.patch('/documents/' + cur.value.id, { active: on }), on ? '已启用；同类的其他文件已停用' : '已停用，之后的草案不会再用它')
const destroy = async () => (await ask(`彻底删除「${cur.value.name}」？文件会从磁盘上删掉，不能恢复。`)) && act(async () => { await api.del('/documents/' + cur.value.id + '?permanent=true'); cur.value = null }, '已删除')
async function bulk(action) {
  const ids = [...picked.value]
  if (action === 'delete' && !(await ask(`彻底删除选中的 ${ids.length} 个文件？不能恢复。`))) return
  await act(() => api.post('/documents/bulk', { action, ids }), action === 'delete' ? `已删除 ${ids.length} 个文件` : `已停用 ${ids.length} 个文件`)
  picked.value = new Set()
}
// old versions of generated files, and files written for jobs that are over
const stale = computed(() => generated.value.filter((d) => !d.active || d.job_archived))
async function cleanUp() {
  if (!stale.value.length) return toast('没有可以清理的文件')
  if (!(await ask(`清理 ${stale.value.length} 个文件（生成文件的旧版本，以及已归档岗位的文件）？会从磁盘上删除，不能恢复。`))) return
  await act(() => api.post('/documents/bulk', { action: 'delete', ids: stale.value.map((d) => d.id) }), `已清理 ${stale.value.length} 个文件`)
}
const previewable = (d) => ['pdf', 'docx', 'doc'].includes(d.ext)
onMounted(load)
</script>

<template>
  <PageHead title="材料库" sub="申请时会用到的所有文件：你上传的简历、成绩单这类材料，以及程序为每个岗位写的求职信。">
    <AaSelect v-model="upKind" title="上传的文件用作什么"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect>
    <label class="btn primary" style="cursor: pointer"><Icon name="draft" />上传<input type="file" multiple style="display: none" @change="upload" /></label>
  </PageHead>

  <div class="fm">
    <!-- folders -->
    <nav class="card fm-nav">
      <button :class="{ on: folder === 'base' }" @click="go('base')"><Icon name="user" />我上传的材料<span class="n">{{ base.filter((d) => d.active).length }}</span></button>
      <button v-for="(g, i) in GROUPS" :key="i" class="sub" :class="{ on: folder === 'group:' + i }" @click="go('group:' + i)">{{ g[0] }}<span class="n">{{ count(g[1]) }}</span></button>

      <button style="margin-top: 10px" :class="{ on: folder === 'generated' }" @click="go('generated')"><Icon name="briefcase" />为岗位生成的<span class="n">{{ generated.length }}</span></button>
      <button v-for="j in jobs" :key="j.id" class="sub" :class="{ on: folder === 'job:' + j.id }" :title="j.name" @click="go('job:' + j.id)">
        <span class="ell">{{ j.name }}</span><span class="n">{{ j.files.length }}</span>
      </button>
      <div v-if="!jobs.length" class="hint" style="padding: 4px 12px 0 34px">生成求职信后会出现在这里，每个岗位一组。</div>

      <button style="margin-top: 10px" :class="{ on: folder === 'all' }" @click="go('all')"><Icon name="inbox" />全部文件<span class="n">{{ docs.length }}</span></button>
      <div class="fm-foot">
        <div>共 {{ docs.length }} 个文件，{{ sizeText(totalSize) }}</div>
        <button v-if="stale.length" class="sm ghost" style="margin-top: 6px; padding-left: 0" @click="cleanUp">清理 {{ stale.length }} 个旧文件</button>
      </div>
    </nav>

    <!-- list -->
    <div class="card fm-list">
      <div class="row" style="padding: 4px 6px 10px">
        <b class="grow ell">{{ title }}</b>
        <input v-model="q" placeholder="搜索文件名或岗位" style="width: 170px" />
      </div>
      <label v-if="inactiveCount && !folder.startsWith('job:')" class="small muted" style="padding: 0 8px 8px; display: block"><input v-model="showInactive" type="checkbox" /> 也显示没在用的（{{ inactiveCount }}）</label>
      <div class="fm-rows">
        <div v-for="d in shown" :key="d.id" class="mat-item" :class="{ on: cur && cur.id === d.id }" role="button" tabindex="0" @click="pick(d)" @keyup.enter="pick(d)">
          <input type="checkbox" :checked="picked.has(d.id)" :aria-label="'选择 ' + d.name" @click.stop @change="togglePick(d.id)" />
          <span class="ext" :class="d.ext">{{ (d.ext || '?').toUpperCase().slice(0, 4) }}</span>
          <span class="grow" style="min-width: 0">
            <span class="name">{{ d.name }}</span>
            <span class="sub">{{ KINDS[d.kind] || d.kind }}<template v-if="d.for_job && !folder.startsWith('job:')"> · {{ d.for_job }}</template> · {{ fmtTime(d.created_at) }}</span>
          </span>
          <span v-if="d.missing" class="badge bad">文件丢失</span>
          <span v-else-if="d.problems.length" class="badge warn" title="自检发现了问题">有问题</span>
          <span v-else-if="!d.active" class="badge">{{ isGen(d) ? '旧版本' : '没在用' }}</span>
        </div>
        <EmptyState v-if="!shown.length" icon="draft" :title="q ? '没有找到' : '这里还没有文件'" :text="folder === 'base' && !q ? '先上传一份简历，草案里才有文件可交。' : ''" />
      </div>
      <div v-if="picked.size" class="row fm-bulk">
        <b>已选 {{ picked.size }} 个</b><span class="grow"></span>
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
            <div class="muted small">{{ KINDS[cur.kind] || cur.kind }} · {{ fmtTime(cur.created_at) }} · {{ sizeText(cur.size) }}<template v-if="cur.pages"> · {{ cur.pages }} 页</template></div>
            <div v-if="cur.for_job" class="small" style="margin-top: 2px">为 <router-link :to="{ path: '/jobs', query: { open: cur.job_id } }">{{ cur.for_job }}</router-link> 写的 <span v-if="cur.job_stage" class="badge" :class="cur.job_tone">{{ cur.job_stage }}</span></div>
          </div>
          <span class="badge" :class="cur.active ? 'ok' : ''">{{ cur.active ? '在用' : isGen(cur) ? '旧版本' : '没在用' }}</span>
        </div>
        <div v-if="cur.problems.length" class="callout warn" style="margin-top: 10px; display: block"><b>自检发现的问题</b><div v-for="(x, k) in cur.problems" :key="k" class="small">{{ x }}</div></div>
        <div class="row" style="margin: 12px 0 8px">
          <a :href="`/api/documents/${cur.id}/file`" :download="cur.name" class="btn sm"><Icon name="external" />下载</a>
          <button v-if="!renaming" class="sm" @click="renaming = true; newName = cur.name"><Icon name="edit" />改名</button>
          <AaSelect v-if="!isGen(cur)" small :value="cur.kind" title="这个文件用作什么" @change="setKind($event.target.value)"><option v-for="k in UPLOADABLE" :key="k" :value="k">用作：{{ KINDS[k] }}</option></AaSelect>
          <button v-if="cur.active" class="sm" @click="setActive(false)">停用</button>
          <button v-else class="sm" :disabled="cur.missing" @click="setActive(true)">{{ isGen(cur) ? '改用这一版' : '重新启用' }}</button>
          <button class="sm ghost danger" @click="destroy">彻底删除</button>
        </div>
        <div v-if="cur.missing" class="empty"><div class="t">文件已经不在磁盘上了</div><div>只剩一条记录，可以直接删除。</div></div>
        <PdfView v-else-if="previewable(cur)" :key="cur.id" :src="`/api/documents/${cur.id}/bytes`" />
        <div v-else class="empty"><div class="t">这种文件不能在页面里预览</div><div>请点“下载”后查看。</div></div>
      </template>
      <EmptyState v-else icon="search" title="点一个文件来预览" text="PDF 和 Word 文件可以直接在这里看。" />
    </div>
  </div>
</template>
