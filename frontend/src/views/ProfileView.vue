<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, fmt } from '../api'
import { renderMarkdown } from '../md'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import { fmtTime, run as runAction, toast, ask } from '../ui'

const tab = ref('sections')
// salary, notice period, referees: a form that keeps two sections of the profile up to date
const st = ref({ compensation: {}, referees: [], suggested: {} })
const CONTACT = [['ask_first', '给出前先问我'], ['after_offer', '拿到录用通知后才能联系'], ['anytime', '随时可以联系']]
const loadSt = async () => {
  const d = await api.get('/profile/structured')
  st.value = { ...d, compensation: { period: 'year', policy: 'state', ...d.compensation }, referees: d.referees.length ? d.referees : [] }
}
const regions = ref({ packs: [] })
const addRef = () => st.value.referees.push({ name: '', title: '', org: '', relation: '', email: '', phone: '', contact: 'ask_first' })
const saveSt = () => run(() => api.put('/profile/structured', { compensation: st.value.compensation, referees: st.value.referees }), '已保存，并写进了个人资料')
const p = ref({ markdown: '', sections: [], versions: [], agent_added: [] })
const scoring = ref('')
const stories = ref('')
const docs = ref([])
const editIdx = ref(-1)
const editBody = ref('')
const md = ref('')
const notes = ref('')
const draft = ref(null)
const busy = ref(false)
const upKind = ref('resume_site')
const mdPreview = ref(true)
const mdDirty = computed(() => md.value !== p.value.markdown)

const KINDS = {
  resume_site: '简历（雇主官网用）', resume_portal: '简历（PD Portal 用）', transcript: '成绩单', cl_template: '求职信模板（Word）',
  cl_example: '求职信范例', source: '其他初始化资料', cover_letter: '生成的求职信', other: '其他',
}
const UPLOADABLE = ['resume_site', 'resume_portal', 'transcript', 'cl_template', 'cl_example', 'source']

async function load() {
  p.value = await api.get('/profile')
  md.value = p.value.markdown
  scoring.value = (await api.get('/profile?doc=scoring')).markdown
  stories.value = (await api.get('/profile?doc=stories')).markdown
  docs.value = await api.get('/documents')
  await loadSt()
  regions.value = await api.get('/regions')
}
const run = (fn, ok) => runAction(fn, ok, load)
const active = computed(() => docs.value.filter((d) => d.active && d.kind !== 'cover_letter'))
const todoCount = computed(() => (p.value.markdown.match(/TODO:/g) || []).length)

function startEdit(i) { editIdx.value = i; editBody.value = p.value.sections[i].body }
const saveSection = () => run(async () => {
  const secs = p.value.sections.map((s, i) => (i === editIdx.value ? { ...s, body: editBody.value } : s))
  await api.put('/profile', { sections: secs, note: '编辑：' + p.value.sections[editIdx.value].title })
  editIdx.value = -1
}, '已保存')
const saveMd = () => run(() => api.put('/profile', { markdown: md.value, note: '直接编辑全文' }), '已保存')
const saveStories = () => run(() => api.put('/profile', { doc: 'stories', markdown: stories.value }), '已保存')
const saveScoring = () => run(() => api.put('/profile', { doc: 'scoring', markdown: scoring.value }), '评分规则已保存')
const restore = async (v) => (await ask('回退到这一版？现在的内容会先存成一个历史版本。')) && run(() => api.post('/profile/restore/' + v.id), '已回退')
const undo = (a) => run(() => api.post('/profile/remove-line', { fragment: a.note.slice(0, 40) }), '已撤销这条规则')

function upload(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('kind', upKind.value); fd.append('file', f)
  run(async () => { const r = await api.upload('/documents', fd); pickAfter = r.id }, `已上传：${f.name}`).then(() => { if (pickAfter) { cur.value = docs.value.find((d) => d.id === pickAfter) || cur.value; docFilter.value = 'active'; pickAfter = null } })
  ev.target.value = ''
}
let pickAfter = null
const docFilter = ref('active')
const cur = ref(null)
const renaming = ref(false)
const newName = ref('')
const shownDocs = computed(() => docs.value.filter((d) => (docFilter.value === 'all' ? true : docFilter.value === 'letters' ? d.kind === 'cover_letter' : d.active && d.kind !== 'cover_letter')))
const sizeText = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')
function pick(d) { cur.value = d; renaming.value = false }
async function docAct(fn, ok) { const id = cur.value && cur.value.id; await run(fn, ok); cur.value = docs.value.find((d) => d.id === id) || null }
const rename = () => docAct(async () => { await api.patch('/documents/' + cur.value.id, { name: newName.value }); renaming.value = false }, '已改名')
const setKind = (k) => docAct(() => api.patch('/documents/' + cur.value.id, { kind: k }), '已更改用途')
const setActive = (on) => docAct(() => api.patch('/documents/' + cur.value.id, { active: on }), on ? '已启用；同类的其他文件已停用' : '已停用，草案不会再用它')
const destroy = async () => (await ask(`彻底删除「${cur.value.name}」？文件会从磁盘上删掉，不能恢复。`)) && docAct(() => api.del('/documents/' + cur.value.id + '?permanent=true'), '已删除')
async function init() {
  busy.value = true; draft.value = null
  try { draft.value = await api.post('/profile/init', { notes: notes.value }) } catch (e) { toast(e.message, 'bad') }
  busy.value = false
}
const adopt = () => run(async () => { await api.put('/profile', { markdown: draft.value.draft, note: '从上传资料初始化' }); draft.value = null }, '已采用起草的个人资料')
onMounted(load)
</script>

<template>
  <PageHead title="个人资料" sub="填申请表、写求职信用的全部依据。这里没有写的事，程序不会替你编。">
    <span v-if="todoCount" class="badge warn">还有 {{ todoCount }} 处没填</span>
  </PageHead>
  <div class="seg" style="margin-bottom: 16px">
    <router-link to="/files" class="btn ghost sm" style="order: 9; margin-left: 6px">简历和材料在“材料库” →</router-link>
    <button v-for="(l, k) in { sections: '我的资料', pay: '薪资与推荐人', stories: '我的经历故事', init: '从简历生成', scoring: '岗位评分规则', markdown: '原文编辑', history: '历史版本' }" :key="k" :class="{ on: tab === k }" @click="tab = k">{{ l }}</button>
  </div>

  <template v-if="tab === 'sections'">
    <div v-if="p.agent_added.length" class="panel" style="border-color: var(--info)">
      <h3 style="margin-top: 0">程序最近帮你记下的内容</h3>
      <div v-for="a in p.agent_added" :key="a.id" class="row small" style="margin-bottom: 4px">
        <span class="grow">{{ a.note }}</span><span class="muted">{{ fmt(a.created_at) }}</span><button @click="undo(a)">撤销</button>
      </div>
    </div>
    <details v-if="regions.packs.length" class="panel">
      <summary><b>你投递的地区，申请表通常还会问这些</b> <span class="muted small">（{{ regions.packs.map((r) => r.name).join('、') }}；资料里写清楚，程序才答得上来）</span></summary>
      <div v-for="r in regions.packs" :key="r.code" style="margin-top: 10px">
        <b>{{ r.name }}</b>
        <ul style="margin: 4px 0 4px 18px"><li v-for="x in r.profile" :key="x" class="small">{{ x }}</li></ul>
        <div v-if="r.diversity" class="small muted">多元化 / 平等就业调查：{{ r.diversity }}</div>
        <div v-if="r.consents" class="small muted">同意项：{{ r.consents }}</div>
        <div v-if="r.never" class="small muted">程序不会替你填：{{ r.never }}</div>
      </div>
    </details>
    <div v-for="(s, i) in p.sections" :key="i" class="panel">
      <div class="row"><h3 class="grow" style="margin: 0">{{ s.title === 'preamble' ? '说明' : s.title }}</h3><button v-if="editIdx !== i" @click="startEdit(i)">编辑</button></div>
      <template v-if="editIdx === i">
        <textarea v-model="editBody" :rows="Math.min(30, Math.max(6, editBody.split('\n').length + 1))" style="margin-top: 8px"></textarea>
        <div class="row" style="margin-top: 8px"><button class="primary" @click="saveSection">保存</button><button @click="editIdx = -1">取消</button></div>
      </template>
      <div v-else-if="s.body" class="md" style="margin-top: 8px" v-html="renderMarkdown(s.body)"></div>
      <p v-else class="muted">（空）</p>
    </div>
  </template>

  <template v-if="tab === 'pay'">
    <div class="panel">
      <h3 style="margin-top: 0">期望薪资</h3>
      <p class="muted small">申请表问到薪资时用这里的内容。薪资题属于敏感问题：每种问法第一次出现时，草案都会停下来等你确认。</p>
      <div class="row" style="gap: 16px; flex-wrap: wrap; margin-bottom: 10px">
        <label><input v-model="st.compensation.policy" type="radio" value="state" /> 按下面的范围回答</label>
        <label><input v-model="st.compensation.policy" type="radio" value="ask" /> 不要替我填数字，每次都留给我自己答</label>
      </div>
      <div v-if="st.compensation.policy !== 'ask'" class="row" style="gap: 8px; flex-wrap: wrap; align-items: end">
        <label class="small">最低<input v-model="st.compensation.min" placeholder="70000" style="width: 110px; display: block" /></label>
        <label class="small">最高<input v-model="st.compensation.max" placeholder="85000" style="width: 110px; display: block" /></label>
        <label class="small">货币<input v-model="st.compensation.currency" placeholder="CAD" style="width: 80px; display: block" /></label>
        <label class="small">按
          <select v-model="st.compensation.period" style="display: block"><option value="year">年</option><option value="month">月</option><option value="hour">小时</option></select>
        </label>
        <label class="small"><input v-model="st.compensation.negotiable" type="checkbox" /> 可以商量</label>
      </div>
      <div class="row" style="gap: 8px; flex-wrap: wrap; align-items: end; margin-top: 12px">
        <label class="small">目前薪资（可不填）<input v-model="st.compensation.current" placeholder="例如 62000 CAD / 年" style="width: 220px; display: block" /></label>
        <label class="small"><input v-model="st.compensation.share_current" type="checkbox" /> 表单要求时可以填写目前薪资</label>
      </div>
      <h3>离职通知期与到岗时间</h3>
      <div class="row" style="gap: 8px; flex-wrap: wrap">
        <label class="small">通知期<input v-model="st.compensation.notice" placeholder="例如 2 weeks / 一个月 / 不适用" style="width: 240px; display: block" /></label>
        <label class="small">最早到岗<input v-model="st.compensation.start" placeholder="例如 2027-01-05 / 录用后两周" style="width: 240px; display: block" /></label>
      </div>
      <label class="small" style="display: block; margin-top: 12px">补充说明（可不填）<input v-model="st.compensation.notes" placeholder="例如：时薪制岗位按 35–40 CAD 每小时" style="display: block; width: 100%" /></label>
    </div>
    <div class="panel">
      <div class="row"><h3 class="grow" style="margin: 0">推荐人</h3><button @click="addRef"><Icon name="plus" />添加一位</button></div>
      <p class="muted small">只有表单里有专门的“推荐人”栏时才会填写，而且只填这里列出的人。推荐人的联系方式是别人的个人信息：每种问法第一次出现时，草案都会停下来等你确认。</p>
      <p v-if="!st.referees.length" class="muted">还没有添加推荐人。{{ st.suggested.referees ? '你这类岗位的申请表经常要求提供推荐人。' : '' }}</p>
      <div v-for="(r, i) in st.referees" :key="i" class="panel" style="background: var(--bg2)">
        <div class="row" style="gap: 8px; flex-wrap: wrap; align-items: end">
          <label class="small">姓名<input v-model="r.name" style="width: 170px; display: block" /></label>
          <label class="small">职位<input v-model="r.title" style="width: 170px; display: block" /></label>
          <label class="small">单位<input v-model="r.org" style="width: 190px; display: block" /></label>
          <label class="small">和你的关系<input v-model="r.relation" placeholder="例如 直属上司 / 导师" style="width: 170px; display: block" /></label>
          <label class="small">邮箱<input v-model="r.email" style="width: 210px; display: block" /></label>
          <label class="small">电话<input v-model="r.phone" style="width: 150px; display: block" /></label>
          <label class="small">什么时候可以联系
            <select v-model="r.contact" style="display: block"><option v-for="[k, l] in CONTACT" :key="k" :value="k">{{ l }}</option></select>
          </label>
          <button class="ghost" @click="st.referees.splice(i, 1)">删除</button>
        </div>
      </div>
    </div>
    <div class="row"><button class="primary" @click="saveSt">保存</button><span class="muted small">保存后会写进个人资料的“Compensation and notice period”和“Referees”两节，这两节由这里管理，手动改动会在下次保存时被覆盖。</span></div>
  </template>

  <template v-if="tab === 'init'">
    <div class="card">
      <h3 style="margin-top: 0">1. 上传资料</h3>
      <div class="row">
        <AaSelect v-model="upKind"><option v-for="k in UPLOADABLE" :key="k" :value="k">{{ KINDS[k] }}</option></AaSelect>
        <label class="btn"><Icon name="inbox" />选择文件<input type="file" hidden @change="upload" /></label>
      </div>
      <ul class="small"><li v-for="d in active" :key="d.id">{{ KINDS[d.kind] }}：<a :href="`/api/documents/${d.id}/file`" target="_blank" rel="noopener">{{ d.name }}</a></li></ul>
      <h3>2. 补充说明（可选）</h3>
      <textarea v-model="notes" style="font-family: inherit" placeholder="简历上没有但申请表常问的信息：法定姓名和常用名、工作许可、是否需要签证担保、可工作时间、GPA、地址……"></textarea>
      <div class="row" style="margin-top: 8px"><button class="primary" :disabled="busy" @click="init">{{ busy ? '正在阅读你的资料…' : '3. 生成个人资料草稿' }}</button></div>
      <p class="muted small">程序只照抄资料里写明的事实；资料里没有而申请表需要的信息会标成“待填” 让你填，不会猜。</p>
    </div>
    <div v-if="draft" class="cols">
      <div class="panel"><h3 style="margin-top: 0">当前个人资料</h3><pre>{{ draft.current }}</pre></div>
      <div class="panel" style="border-color: var(--ok)">
        <div class="row"><h3 class="grow" style="margin: 0">生成的草稿</h3><button class="primary" @click="adopt">采用</button></div>
        <textarea v-model="draft.draft" rows="40" style="margin-top: 8px"></textarea>
      </div>
    </div>
  </template>

  <template v-if="tab === 'markdown'">
    <div class="card">
      <div class="row">
        <div class="grow"><div class="card-title">直接编辑全文</div><div class="muted small">用 Markdown 写。一般在“我的资料”里按段落改就够了，这里适合大段调整。</div></div>
        <label class="small muted"><input v-model="mdPreview" type="checkbox" /> 同时预览</label>
        <span v-if="mdDirty" class="badge warn">有改动还没保存</span>
        <button :disabled="!mdDirty" @click="md = p.markdown">放弃改动</button>
        <button class="primary" :disabled="!mdDirty" @click="saveMd"><Icon name="check" />保存</button>
      </div>
      <div :class="mdPreview ? 'cols' : ''" style="margin-top: 14px">
        <textarea v-model="md" style="height: 68vh; resize: vertical"></textarea>
        <div v-if="mdPreview" class="md" style="height: 68vh; overflow: auto; border: 1px solid var(--border); border-radius: var(--r-sm); padding: 12px 16px" v-html="renderMarkdown(md)"></div>
      </div>
    </div>
  </template>

  <template v-if="tab === 'stories'">
    <div class="card">
      <div class="row">
        <div class="grow"><div class="card-title">我的经历故事</div><div class="muted small">申请表上常有开放题：“讲一次你解决冲突的经历”“说一个你引以为傲的项目”。把你真实的经历写在这里，每个故事一个“## 标题”，写清楚当时的情况、你做了什么、结果如何。程序回答这类问题时只会从这里（和你的经历）取材、改写和压缩；这里没有合适的故事，它会把问题留给你，不会替你编。</div></div>
        <button class="primary" @click="saveStories"><Icon name="check" />保存</button>
      </div>
      <textarea v-model="stories" style="height: 60vh; margin-top: 14px; resize: vertical; font-family: inherit; font-size: 14px"></textarea>
      <p class="hint" style="margin-top: 8px">用中文或英文写都可以，程序会按申请表的语言来回答。写 4–6 个覆盖不同主题的故事（团队合作、解决难题、领导、失败与学习、主动性）基本够用。</p>
    </div>
  </template>

  <template v-if="tab === 'scoring'">
    <div class="card">
      <div class="row">
        <div class="grow"><div class="card-title">岗位评分规则</div><div class="muted small">用平常的话写：什么样的岗位该高分、什么情况直接排除。程序读完岗位说明全文后按这些规则评分；没有岗位说明的不评分。</div></div>
        <button class="primary" @click="saveScoring"><Icon name="check" />保存</button>
      </div>
      <textarea v-model="scoring" style="height: 60vh; margin-top: 14px; resize: vertical"></textarea>
    </div>
  </template>

  <template v-if="tab === 'history'">
    <div class="card">
      <div class="card-title">历史版本</div>
      <p class="muted">每次保存都会留一份。回退不会丢东西：当前内容也会先存成一个版本。</p>
      <div class="list">
        <div v-for="(v, i) in p.versions" :key="v.id" class="item">
          <span class="badge" :class="v.source === 'agent' ? 'info' : ''" style="min-width: 76px; justify-content: center">{{ { user: '你改的', agent: '程序记的', init: '从简历生成' }[v.source] || v.source }}</span>
          <div><div class="main">{{ v.note || '保存' }}</div><div class="sub">{{ fmtTime(v.created_at) }} · {{ v.size }} 字</div></div>
          <div><span v-if="i === 0" class="small muted">最近一次</span><button class="sm" style="margin-left: 8px" @click="restore(v)">回退到这一版</button></div>
        </div>
      </div>
      <EmptyState v-if="!p.versions.length" icon="clock" title="还没有历史版本" text="保存过一次之后，这里会开始记录。" />
    </div>
  </template>
</template>
