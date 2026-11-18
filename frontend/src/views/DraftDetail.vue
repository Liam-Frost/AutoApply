<script setup>
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import TechDetails from '../components/TechDetails.vue'
import { decisions, toDecide } from '../draftsum'
import { ask, toast, busy as acting, run } from '../ui'

const props = defineProps({ id: String })
const router = useRouter()
const d = ref(null)
const editing = ref(null)
const editVal = ref('')
const typeOwn = ref(false)      // a choice that is not among the ones the draft lists
const saveRule = ref('')
const remember = ref(false)
const comment = ref('')
const busy = ref(false)
const loadErr = ref('')
let timer

const SENS = { sponsorship: '签证担保', salary: '薪资', ip: '知识产权', noncompete: '竞业/保密', demographic: '人口统计', work_auth: '工作许可', background: '背景调查' }
const KIND = { portfolio: '作品集', research_statement: '研究陈述', teaching_statement: '教学陈述', publications: '发表列表', writing_sample: '作品样本', reference: '推荐信', certificate: '证书', summary_sheet: 'Summary Sheet', tailored_resume: '按这个岗位调整过的简历', resume_site: '简历', resume_portal: '简历', transcript: '成绩单', cover_letter: '求职信', cl_template: '求职信模板', cl_example: '求职信范例' }
const CHECK = {
  enabled: '这个招聘系统开启了自动通过', no_unresolved: '没有答不上的问题', all_high_from_rules: '所有答案都来自你确认过的资料',
  no_new_sensitive: '没有第一次遇到的敏感问题', cover_letter_ok: '没有新写的求职信', tailored_resume_ok: '没有新调整的简历', score_ok: '评分够高',
  driver_proven: '这个招聘系统已连续成功多次', session_ready: '网站已登录', no_unusual_notes: '没有需要留意的备注', revised_by_user: '你改过这份草案',
}

async function load() {
  try { d.value = await api.get('/drafts/' + props.id) } catch (e) { loadErr.value = e.message }
}
const pending = computed(() => d.value && d.value.review_status === 'pending')
// Anything in a draft can be changed for as long as the application has not gone out - before approving and after.
// The server says when it cannot (an old version, already sent, a run in progress) and why.
const editable = computed(() => d.value && !d.value.locked)
const approvedOpen = computed(() => editable.value && d.value.review_status === 'approved')
const filled = computed(() => (d.value ? d.value.answers.filter((a) => a.value !== '' && a.value != null && !(Array.isArray(a.value) && !a.value.length)) : []))
const blank = computed(() => (d.value ? d.value.answers.filter((a) => !filled.value.includes(a)) : []))
const show = (a) => (a.type === 'file' ? String(a.value).split(/[\\/]/).pop() : Array.isArray(a.value) ? a.value.join('，') : a.type === 'checkbox' ? (a.value ? '✓ 勾选' : '不勾选') : a.value)
const onlyDelta = ref(false)
const deltaCount = computed(() => (d.value ? d.value.answers.filter((a) => a.delta).length : 0))
const isUnresolved = (a) => d.value.unresolved.some((u) => u.id === a.id)

// What needs a decision, before the table of everything (draftsum.js); each line leads to its row.
const toLook = computed(() => (pending.value ? decisions(d.value) : []))
const lit = ref('')
const lineOf = (g) => (g.items.length ? g.items.map((i) => i.label).join('；') : '看整个流程')
async function goTo(id, where) {
  if (onlyDelta.value && id && !d.value.answers.some((a) => a.id === id && a.delta)) onlyDelta.value = false      // the row may be filtered out of the table
  await nextTick()
  const el = document.getElementById(id ? 'ans-' + id : 'draft-' + where)
  if (!el) return
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
  lit.value = id || where
  setTimeout(() => { if (lit.value === (id || where)) lit.value = '' }, 2200)
}

// tailored résumé
const CHANGE = { reorder_bullets: '调整了要点顺序', reorder_entries: '调整了先后顺序', skills: '调整了技能顺序', drop: '去掉了一条要点', rewrite: '改写了措辞', rewrite_rejected: '改写没有通过核对，保留了原文' }
const tailorNote = ref('')
const hasResume = computed(() => d.value && d.value.materials.some((m) => ['resume_site', 'resume_portal', 'tailored_resume'].includes(m.kind)))
const tailored = computed(() => d.value && d.value.materials.find((m) => m.kind === 'tailored_resume'))
async function useResume(which) {
  await run(() => api.post(`/drafts/${props.id}/resume`, { which }), which === 'base' ? '已换回你上传的原版简历' : '已换成调整过的简历', load)
}
async function tailorNow() {
  try {
    await api.post(`/jobs/${d.value.job.id}/tailor`, { instructions: tailorNote.value })
    toast('已开始按这个岗位调整简历，大约一两分钟，完成后会自动放进这份草案')
    tailorNote.value = ''
    const before = tailored.value ? tailored.value.document_id : 0
    let n = 0
    const t = setInterval(async () => { await load(); if (++n > 60 || (tailored.value && tailored.value.document_id !== before)) clearInterval(t) }, 5000)
  } catch (e) { toast(e.message, 'bad') }
}

async function dropQuestion(a) {
  if (!(await ask(`去掉“${a.label}”这个问题？它是填表时遇到的，不是你的资料里的问题。去掉后，如果表单仍然要求填它，AI 会在下次填表时按你的资料处理（例如删掉网站自己生成的那一条）。`, { ok: '去掉', danger: false }))) return
  try { d.value = await api.del(`/drafts/${props.id}/answers/${encodeURIComponent(a.id)}`); editing.value = null } catch (e) { toast(e.message, 'bad') }
}
function startEdit(a) { typeOwn.value = false; editing.value = a.id; editVal.value = Array.isArray(a.value) ? a.value.join(' || ') : a.value === true ? 'true' : a.value === false ? 'false' : a.value; saveRule.value = ''; remember.value = false }
async function commitEdit(a) {
  let v = editVal.value
  if (a.type === 'checkbox') v = String(v).toLowerCase() === 'true'
  if (a.type === 'multiselect') v = String(v).split('||').map((x) => x.trim()).filter(Boolean)
  try {
    d.value = await api.patch(`/drafts/${props.id}/answers/${encodeURIComponent(a.id)}`, { value: v, save_rule: remember.value ? saveRule.value : '', remember: remember.value })
    if (remember.value) toast('已保存，并记到个人资料的“标准答案”里')
    else if (approvedOpen.value) toast('已保存。这份草案仍然是批准状态；点“重新填写并提交”，程序会按现在的答案再填一次')
    editing.value = null
  } catch (e) { toast(e.message, 'bad') }
}
async function sendComment() {
  busy.value = true; 
  try {
    await api.post(`/drafts/${props.id}/comment`, { comment: comment.value })
    toast('正在按你的意见修改，完成后会跳到新版本')
    comment.value = ''
    timer = setInterval(async () => {
      const all = await api.get('/drafts?all=true')
      const mine = all.filter((x) => x.company === d.value.job.company && x.title === d.value.job.title).sort((a, b) => b.version - a.version)[0]
      if (mine && mine.id !== Number(props.id)) { clearInterval(timer); busy.value = false; router.push('/drafts/' + mine.id) }
    }, 3000)
  } catch (e) { toast(e.message, 'bad'); busy.value = false }
}
const scouting = ref(false)
async function scout() {
  scouting.value = true
  try {
    const { task_id } = await api.post(`/drafts/${props.id}/scout`)
    for (let i = 0; i < 400; i++) {       // a walk through a form takes a few minutes
      await new Promise((r) => setTimeout(r, 3000))
      const t = (await api.get('/tasks?limit=30')).find((x) => x.id === task_id)
      if (t && ['done', 'failed', 'waiting_human'].includes(t.status)) {
        await load()
        if (t.status !== 'done') toast(t.explained && t.explained.message ? t.explained.message : '没有读成，请稍后再试', 'bad')
        else toast(t.result && t.result.reached_review ? '后面的步骤读完了，新问到的内容已经加进草案' : '读到一处需要你回答的问题，已经加进草案')
        break
      }
    }
  } catch (e) { toast(e.message, 'bad') } finally { scouting.value = false }
}
const reasking = ref(false)
async function reanswer() {
  reasking.value = true
  try {
    const { task_id } = await api.post(`/drafts/${props.id}/reanswer`)
    for (let i = 0; i < 120; i++) {       // a single AI call: usually well under a minute
      await new Promise((r) => setTimeout(r, 2500))
      const t = (await api.get('/tasks?limit=30')).find((x) => x.id === task_id)
      if (t && ['done', 'failed'].includes(t.status)) {
        await load()
        if (t.status === 'failed') toast(t.explained && t.explained.message ? t.explained.message : '没有成功，请稍后再试', 'bad')
        else toast(t.result && t.result.answered ? `答上了 ${t.result.answered} 个，还剩 ${t.result.left} 个需要你回答` : '资料里确实没有这些问题的答案，需要你来回答')
        break
      }
    }
  } catch (e) { toast(e.message, 'bad') }
  reasking.value = false
}
async function runAgain() {
  
  await run(() => api.post(`/drafts/${props.id}/execute`), '已重新开始填写', load, { name: 'execute' })
}
// Submit was pressed and the outcome is not known: what settles it comes first, filling it in again last and on the applicant's word
async function checkMail() {
  await run(() => api.post(`/applications/${d.value.application.id}/check-mail`), '正在查邮箱；有确认邮件的话，这份申请会记为已投出')
}
async function runAgainNotSubmitted() {
  if (!(await ask('确定这份申请没有提交成功吗？如果其实已经提交了，重新填写会向雇主再投一次。', { ok: '确定没提交，重新填写' }))) return
  await run(() => api.post(`/drafts/${props.id}/execute`, { not_submitted: true }), '已重新开始填写', load, { name: 'execute' })
}
async function markSubmitted() {
  
  await run(() => api.post(`/applications/${d.value.application.id}/mark-submitted`), '已记为“投递成功”，稍后会查确认邮件', load)
}
async function approve() {
  
  await run(() => api.post(`/drafts/${props.id}/approve`), '已批准，开始填写', load, { name: 'approve' })
}
// "Not now" is a link back to the list: the draft stays as it is, waiting. Sending it back is a decision of its own -
// the draft is closed - and says what there is to do afterwards.
async function sendBack() {
  if (!(await ask('退回这份草案？它会作废，岗位回到“未投递”。之后想投这个岗位，在岗位页重新生成草案（可以写上你的要求）；只是想改几处答案的话，不用退回，直接在这里改或者在下面写修改意见。', { ok: '退回草案' }))) return
  await reject(false)
}
async function reject(withdraw) {
  if (await run(() => api.post(`/drafts/${props.id}/reject`, { withdraw }), '', null, { name: 'reject' })) router.push('/drafts')
}
watch(() => props.id, load)
onMounted(load)
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div v-if="!d" class="muted">{{ loadErr || '加载中…' }}</div>
  <template v-else>
    <header class="page-head">
      <div>
        <router-link to="/drafts" class="small muted">← 草案审批</router-link>
        <h2>{{ d.job.company }}</h2>
        <div class="sub" style="font-size: 16px">{{ d.job.title }}</div>
      </div>
      <div class="actions">
        <span class="badge" :class="{ ok: d.review_status === 'approved', warn: pending }">第 {{ d.version }} 版 · {{ d.review_label }}</span>
        <a :href="d.job.apply_url" target="_blank" rel="noopener" class="btn sm"><Icon name="external" />看原岗位</a>
      </div>
    </header>
    <p class="muted small">
      评分 {{ d.job.score ?? '—' }} · 截止 {{ d.job.deadline || '未知' }} · 在 {{ d.job.ats_label }} 上投 · 现在：{{ d.application.status_label }}
    </p>
    <p v-if="d.job.score_reason" class="small">{{ d.job.score_reason }}</p>

    <div v-if="d.unresolved.length" class="callout bad" style="display: block">
      <b>有 {{ d.unresolved.length }} 个问题需要你回答</b>
      <div class="muted small">在你的个人资料里找不到这些问题的答案。在下面的表里点“修改”填上；顺手存成规则，下次就不用再问。</div>
      <ul style="margin: 8px 0 0; padding-left: 20px"><li v-for="u in d.unresolved" :key="u.id">{{ u.label }}</li></ul>
    
      <div class="row" style="margin-top: 10px"><button :disabled="reasking" @click="reanswer"><Icon name="refresh" />{{ reasking ? '正在重新回答…' : '让 AI 按我的资料再答一次' }}</button>
        <span class="muted small">刚补充过个人资料，或觉得这些问题资料里明明有答案时用。已经有答案的不会动。</span></div>
    </div>

    <div v-if="d.review_status === 'pending' && ((d.unseen && d.unseen.length) || d.walk_open)" class="callout" style="display: block">
      <b v-if="d.unseen && d.unseen.length">这张表还有 {{ d.unseen.length }} 步没读到</b><b v-else>上一次往下读没有走到确认页</b>
      <div class="small" style="margin-top: 4px">这些步骤要先填完前面的才打得开。程序会带着这份草案的答案在隐藏窗口里一步步往下填，把后面问到的问题读回来加进草案；不会提交，也不用你点什么，几分钟内自己开始。
        填进去的内容雇主网站可能会自动保存为未完成的申请。</div>
      <div class="row" style="margin-top: 8px">
        <span v-if="scouting || d.application.status === 'recon'" class="muted small">正在往下读…</span>
        <button v-else class="ghost sm" @click="scout"><Icon name="play" />现在就读</button>
      </div>
    </div>

    <div v-if="toLook.length" class="panel look" aria-labelledby="look-h">
      <h3 id="look-h" style="margin-top: 0">先看这几项<span v-if="toDecide(toLook)" class="muted small" style="font-weight: 400">　{{ toDecide(toLook) }} 项需要你过目，其余的是资料里写明的事实</span>
        <span v-else class="muted small" style="font-weight: 400">　没有需要你特别过目的答案</span></h3>
      <div v-for="g in toLook" :key="g.key" class="look-group">
        <span class="tag" :class="g.tone">{{ g.label }}</span>
        <template v-if="g.to">
          <button class="look-item" @click="goTo('', g.to)">{{ lineOf(g) }}</button>
        </template>
        <template v-else>
          <button v-for="i in g.items" :key="i.id" class="look-item" @click="goTo(i.id)">{{ i.label }}<span v-if="i.note" class="muted">（{{ i.note }}）</span></button>
        </template>
      </div>
    </div>

    <div v-if="d.notes_display.length" class="callout warn" style="display: block">
      <b>请留意</b>
      <ul style="margin: 6px 0 0; padding-left: 20px"><li v-for="(n, i) in d.notes_display" :key="i">{{ n }}</li></ul>
    </div>

    <div class="row">
      <h3 class="grow">要填写的内容（{{ filled.length }} 项）</h3>
      <label v-if="deltaCount" class="small"><input v-model="onlyDelta" type="checkbox" /> 只看表单变化的 {{ deltaCount }} 项（其余沿用上次审批的答案）</label>
    </div>
    <div class="table-wrap" style="max-height: none">
      <table>
        <thead><tr><th style="width: 34%">表单上的问题</th><th>准备填的答案</th><th style="width: 22%">为什么这么填</th><th>把握</th><th></th></tr></thead>
        <tbody>
          <tr v-for="a in d.answers.filter((x) => (filled.includes(x) || isUnresolved(x) || editing === x.id) && (!onlyDelta || x.delta))" :id="'ans-' + a.id" :key="a.id" :class="{ lit: lit === a.id }">
            <td>
              {{ a.label }}<span v-if="a.required" style="color: var(--bad)"> *</span>
              <div v-if="a.entry" class="small muted" data-notr>{{ a.entry }}</div>
              <span v-if="a.delta" class="tag warn" style="margin-left: 4px">{{ a.delta === 'new' ? '新增' : '有变化' }}</span>
              <span v-if="a.held" class="tag" style="margin-left: 4px" title="这个答案已经存在雇主网站上，程序不会改动它。你在这里修改后，程序会按你改的去填。">网站上已有</span>
              <span v-if="a.conflict" class="tag warn" style="margin-left: 4px">和你的资料不一致</span>
              <div v-if="a.sensitive" class="small"><span class="tag" :class="a.sensitive_confirmed ? '' : 'warn'">{{ SENS[a.sensitive] || a.sensitive }}{{ a.sensitive_confirmed ? '（已确认过）' : '（第一次遇到，请确认）' }}</span></div>
              <div v-if="d.pages.length > 1" class="muted small">第 {{ a.page + 1 }} 页 · {{ d.pages[a.page] }}</div>
            </td>
            <td>
              <template v-if="editing === a.id">
                <template v-if="a.options && a.options.length && a.type !== 'multiselect' && !a.searchable && !typeOwn">
                  <AaSelect v-model="editVal" style="max-width: 100%"><option v-for="o in a.options" :key="o">{{ o }}</option></AaSelect>
                  <div><button class="ghost sm" @click="typeOwn = true">列表里没有？直接输入</button></div>
                </template>
                <template v-else-if="a.options && a.options.length && a.type !== 'multiselect'">
                  <input v-model="editVal" :list="'opts-' + a.page + '-' + a.label.length" style="width: 100%" />
                  <datalist :id="'opts-' + a.page + '-' + a.label.length"><option v-for="o in a.options" :key="o" :value="o"></option></datalist>
                  <div class="small muted">这个列表在表单上是可以搜索的，这里只列出了其中几项。直接输入你的答案，填表时程序会在列表里搜它。</div>
                </template>
                <AaSelect v-else-if="a.type === 'checkbox'" v-model="editVal"><option value="true">勾选</option><option value="false">不勾选</option></AaSelect>
                <textarea v-else v-model="editVal" rows="3"></textarea>
                <div class="small muted" v-if="a.type === 'multiselect'">多选用 || 分隔；可选：{{ a.options.join(' / ') }}</div>
                <label class="small" style="display: block; margin-top: 8px"><input v-model="remember" type="checkbox" /> 以后别的申请表上遇到这个问题，也这样回答</label>
                <input v-if="remember" v-model="saveRule" placeholder="（可选）补充说明，例如：只对加拿大的岗位这样填" style="width: 100%; margin-top: 6px" />
                <div class="row" style="margin-top: 6px"><button class="primary" @click="commitEdit(a)">保存</button><button @click="editing = null">取消</button>
                  <button v-if="isUnresolved(a) && a.source === 'unresolved'" class="ghost" title="这一项不该由你来填（例如网站自己生成了一条不该有的内容）。去掉后，下次填表时 AI 会按你的资料处理它。" @click="dropQuestion(a)">不需要填这一项</button></div>
              </template>
              <template v-else>
                <span v-if="isUnresolved(a)" class="tag bad">还没有答案</span>
                <pre v-else style="font-family: inherit; font-size: 14px">{{ show(a) }}</pre>
              </template>
            </td>
            <td class="small muted">{{ a.basis_display }}<div v-if="a.source === 'cache'" class="tag" style="margin-top: 2px">以前回答过</div><div v-if="a.source === 'agent_added'" class="tag" style="margin-top: 2px">填表时 AI 补填</div></td>
            <td><span class="tag" :class="{ ok: a.confidence === 'high', warn: a.confidence === 'medium', bad: a.confidence === 'low' }">{{ { high: '高', medium: '中', low: '低' }[a.confidence] }}</span></td>
            <td><button v-if="editable && a.type !== 'file' && editing !== a.id" class="sm" @click="startEdit(a)">修改</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <details v-if="blank.length" style="margin: 8px 0">
      <summary class="muted">没有填的选答题（{{ blank.filter((b) => !isUnresolved(b)).length }}）</summary>
      <ul class="small"><li v-for="b in blank.filter((b) => !isUnresolved(b))" :key="b.id">{{ b.label }} <button v-if="editable && b.type !== 'file'" @click="startEdit(b)">填写</button></li></ul>
    </details>

    <div class="cols">
      <div>
        <h3 id="draft-materials" :class="{ lit: lit === 'materials' }">要上传的文件</h3>
        <div class="panel">
          <div v-for="m in d.materials" :key="m.slot" class="row" style="margin-bottom: 6px">
            <span class="tag info">{{ m.slot_label }}</span>
            <a :href="`api/documents/${m.document_id}/file`" target="_blank" rel="noopener">{{ m.name }}</a>
            <span class="muted small">{{ KIND[m.kind] || '' }}</span>
          </div>
          <div v-if="!d.materials.length" class="muted">这张申请表不需要上传文件。</div>
          <template v-if="tailored && tailored.tailor">
            <div class="tailor">
              <div><b>这份简历针对这个岗位做了调整</b><span v-if="tailored.tailor.focus">：{{ tailored.tailor.focus }}</span></div>
              <div v-if="tailored.tailor.keywords && tailored.tailor.keywords.length" class="row" style="gap: 6px; margin-top: 8px"><span v-for="k in tailored.tailor.keywords" :key="k" class="tag">{{ k }}</span></div>
              <details class="tech" open>
                <summary>和原版相比改了什么（{{ tailored.tailor.changes.length }} 处）</summary>
                <div v-for="(c, i) in tailored.tailor.changes" :key="i" class="chg">
                  <div><span class="tag" :class="c.type === 'rewrite_rejected' ? 'warn' : c.type === 'rewrite' || c.type === 'drop' ? 'info' : ''">{{ CHANGE[c.type] || c.type }}</span> <span class="muted small">{{ c.where }}</span></div>
                  <template v-if="Array.isArray(c.after)"><ol><li v-for="x in c.after" :key="x">{{ x }}</li></ol></template>
                  <template v-else>
                    <div v-if="c.before" class="small"><span class="muted">原文：</span>{{ c.before }}</div>
                    <div v-if="c.after" class="small"><span class="muted">{{ c.type === 'rewrite_rejected' ? '被丢掉的改写：' : '现在：' }}</span>{{ c.after }}</div>
                  </template>
                </div>
              </details>
              <div v-if="editable" class="row" style="margin-top: 10px"><button class="sm" @click="useResume('base')">改用原版简历</button></div>
            </div>
          </template>
          <div v-if="pending && hasResume && d.tailor && d.tailor.mode !== 'off'" class="tailor">
            <template v-if="d.tailor.available">
              <div class="small muted" style="margin-bottom: 6px">{{ tailored ? '不满意？可以说明要求，重新调整一次。' : '这份草案用的是原版简历。可以让程序按这个岗位调整一份。' }}</div>
              <div class="row"><input v-model="tailorNote" class="grow" placeholder="可选：有什么要求，例如“突出后端和数据库经验”" /><button class="sm" @click="tailorNow">{{ tailored ? '重新调整' : '按这个岗位调整简历' }}</button></div>
            </template>
            <div v-else class="small muted">想让程序按岗位调整简历？先在<router-link to="/files">材料库</router-link>上传一份 Word 版简历，用途选“简历 Word 原稿”。</div>
          </div>
        </div>
      </div>
      <div>
        <h3 id="draft-after" :class="{ lit: lit === 'after' }">批准之后会发生什么</h3>
        <div class="panel">
          <p v-if="d.submit_mode" style="margin-top: 0">
            <b>批准后：</b>
            <span v-if="d.submit_mode.mode === 'auto'">填写并核对无误后<b>自动提交</b>，不需要你再操作。</span>
            <span v-else>填好后停下，<b>由你检查并点击提交</b>。<span>原因：</span><template v-for="(w, i) in d.submit_mode.why || d.submit_mode.reasons.map((text) => ({ text }))" :key="i"><template v-if="i">；</template><router-link v-if="w.where" :to="w.where" title="打开决定这一条的设置">{{ w.text }}</router-link><template v-else>{{ w.text }}</template></template></span>
          </p>
          <ol style="margin: 0; padding-left: 18px"><li v-for="(s, i) in d.plan" :key="i">{{ s.text }}</li></ol>
        </div>
      </div>
    </div>

    <details class="tech" style="margin: 4px 0 16px">
      <summary>为什么这份草案需要我审批（没有自动通过）</summary>
      <div class="panel small" style="margin-top: 8px">
        <span v-for="(v, k) in d.auto_approve_check.checks" :key="k" class="tag" :class="v ? 'ok' : 'bad'" style="margin: 0 6px 6px 0">{{ v ? '✓' : '✗' }} {{ CHECK[k] || k }}</span>
        <span v-if="!Object.keys(d.auto_approve_check.checks || {}).length" class="muted">{{ (d.auto_approve_check.failed || []).map((k) => CHECK[k] || k).join('，') || '没有评估' }}</span>
      </div>
    </details>

    <div v-if="d.review_status === 'approved' && d.application.status === 'submit_unknown'" class="callout warn" style="display: block">
      <b>点过提交，但还不知道有没有提交成功。</b>
      <div class="muted">{{ d.application.explained.message }}</div>
      <div class="muted" style="margin-top: 6px">如果已经提交成功，雇主的确认邮件会把它记为已投出。先别重新填写：那样可能向雇主投两次。</div>
      <TechDetails :text="d.application.explained.detail" />
      <div class="row" style="margin-top: 10px">
        <button class="primary" @click="checkMail"><Icon name="mail" />现在检查确认邮件</button>
        <button @click="markSubmitted">我已经提交了</button>
        <button class="ghost" :disabled="acting('execute')" @click="runAgainNotSubmitted">没提交成功，重新填写</button>
      </div>
    </div>

    <div v-else-if="d.review_status === 'approved' && ['ready_to_submit', 'failed', 'needs_human', 'approved'].includes(d.application.status)" class="callout warn" style="display: block">
      <b>这份草案你已经批准，但申请还没有提交成功。</b>
      <div class="muted">{{ d.application.explained.message }}</div>
      <div v-if="editable" class="muted" style="margin-top: 6px">哪一项答案不对，可以直接在上面点“修改”改掉，不用重新批准；改完点下面的按钮，程序按现在的答案再填一次。</div>
      <TechDetails :text="d.application.explained.detail" />
      <div class="row" style="margin-top: 10px">
        <button class="primary" :disabled="acting('execute')" @click="runAgain"><Icon name="refresh" />{{ d.application.status === 'ready_to_submit' ? '重新打开窗口，由我提交' : '重新填写并提交' }}</button>
        <button v-if="d.application.status === 'ready_to_submit'" @click="markSubmitted">我已经提交了</button>
      </div>
    </div>

    <div v-if="d.locked && ['pending', 'approved'].includes(d.review_status)" class="callout" style="display: block"><span class="muted">{{ d.locked }}</span></div>
    <div v-if="approvedOpen && d.comments && d.comments.length" class="panel small">
      <div v-for="(c, i) in d.comments" :key="i" class="muted">你：{{ c.comment }} → {{ c.result }}</div>
    </div>

    <template v-if="pending">
      <h3>想改点什么？直接说</h3>
      <div class="panel">
        <textarea v-model="comment" placeholder="用平常说话的方式写要改什么。例如：求职信第二段改成重点讲我的实习经历；期望薪资填 30 CAD/hour" style="font-family: inherit"></textarea>
        <div class="row" style="margin-top: 8px"><button :disabled="!comment.trim() || busy" @click="sendComment">{{ busy ? '正在修改…' : '按这个改' }}</button></div>
        <div v-for="(c, i) in d.comments" :key="i" class="small muted" style="margin-top: 6px">你：{{ c.comment }} → {{ c.result }}</div>
      </div>
      <div class="row" style="position: sticky; bottom: 0; background: var(--bg); padding: 12px 0">
        <button class="primary" :disabled="!!d.unresolved.length || acting('approve')" @click="approve">{{ acting('approve') ? '正在批准…' : d.submit_mode && d.submit_mode.mode === 'manual' ? '批准，填好后我来点提交' : '批准，自动填写并提交' }}</button>
        <router-link to="/drafts" class="btn">稍后再说</router-link>
        <button class="ghost" :disabled="acting('reject') || acting('approve')" @click="sendBack">退回这份草案</button>
        <button class="ghost danger" :disabled="acting('reject') || acting('approve')" @click="reject(true)">不投这个岗位了</button>
        <span v-if="d.unresolved.length" class="muted">回答完上面的问题才能批准</span>
      </div>
    </template>
  </template>
</template>
