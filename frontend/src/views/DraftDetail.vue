<script setup>
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import TechDetails from '../components/TechDetails.vue'
import { decisions, toDecide } from '../draftsum'
import { ask, fmtTime, toast, busy as acting, run } from '../ui'

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
const isUnresolved = (a) => d.value.unresolved.some((u) => u.id === a.id)

// What needs a decision, before the table of everything (draftsum.js); each line leads to its row.
const toLook = computed(() => (pending.value ? decisions(d.value) : []))
const lit = ref('')
const lineOf = (g) => (g.items.length ? g.items.map((i) => i.label).join('；') : '看整个流程')
async function goTo(id, where) {
  await nextTick()
  const el = document.getElementById(id ? 'ans-' + id : 'draft-' + where)
  if (!el) return
  el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
  lit.value = id || where
  setTimeout(() => { if (lit.value === (id || where)) lit.value = '' }, 2200)
}

// The résumé of this application: one rewritten for the posting (when there is one and the applicant has not chosen
// the one they uploaded), or the one they uploaded. The agent's next run on the application uses what is chosen here.
const CHANGE = { reorder_bullets: '调整了要点顺序', reorder_entries: '调整了先后顺序', skills: '调整了技能顺序', drop: '去掉了一条要点', rewrite: '改写了措辞', rewrite_rejected: '改写没有通过核对，保留了原文' }
const tailorNote = ref('')
const written = computed(() => (d.value && d.value.tailor ? d.value.tailor.written : null))
const usesWritten = computed(() => !!written.value && d.value.tailor.use === 'tailored')
async function useResume(which) {
  await run(() => api.post(`/drafts/${props.id}/resume`, { which }), which === 'base' ? '这份申请改用你上传的原版简历；Agent 下次处理时会换上' : '这份申请改用为这个岗位改写的简历；Agent 下次处理时会换上', load)
}
async function tailorNow() {
  try {
    await api.post(`/jobs/${d.value.job.id}/tailor`, { instructions: tailorNote.value })
    toast('已开始按这个岗位改写简历，大约一两分钟；Agent 下次处理这份申请时会用它')
    tailorNote.value = ''
    const before = written.value ? written.value.name : ''
    let n = 0
    const t = setInterval(async () => { await load(); if (++n > 60 || (written.value && written.value.name !== before)) clearInterval(t) }, 5000)
  } catch (e) { toast(e.message, 'bad') }
}

async function dropQuestion(a) {
  if (!(await ask(`“${a.label}”这一项不用填？Agent 会让它保持表单上现在的样子；如果表单不填它就不让往下走，Agent 会回来告诉你。`, { ok: '不用填', danger: false }))) return
  try { d.value = await api.del(`/drafts/${props.id}/answers/${encodeURIComponent(a.id)}`); editing.value = null } catch (e) { toast(e.message, 'bad') }
}
// An answer belongs to this application. "Also from now on" writes it to the profile: offered ticked for a question
// the agent said is about the applicant in general, unticked for one about this job.
function startEdit(a) { typeOwn.value = false; editing.value = a.id; editVal.value = Array.isArray(a.value) ? a.value.join(' || ') : a.value === true ? 'true' : a.value === false ? 'false' : a.value; saveRule.value = ''; remember.value = isUnresolved(a) && a.about === 'applicant' }
async function commitEdit(a) {
  let v = editVal.value
  if (a.type === 'checkbox') v = String(v).toLowerCase() === 'true'
  if (a.type === 'multiselect') v = String(v).split('||').map((x) => x.trim()).filter(Boolean)
  try {
    d.value = await api.patch(`/drafts/${props.id}/answers/${encodeURIComponent(a.id)}`, { value: v, save_rule: remember.value ? saveRule.value : '', remember: remember.value })
    if (remember.value) toast('已保存，并记到个人资料的“标准答案”里')
    else if (approvedOpen.value) toast('已保存。这份记录仍然是批准状态；点“让 Agent 再提交一次”，它会按现在的答案去做')
    editing.value = null
  } catch (e) { toast(e.message, 'bad') }
}
async function sendComment() {
  busy.value = true; 
  try {
    await api.post(`/drafts/${props.id}/comment`, { comment: comment.value })
    toast('Agent 正在按你的意见处理这份申请，完成后会跳到新版本')
    comment.value = ''
    timer = setInterval(async () => {
      const all = await api.get('/drafts?all=true')
      const mine = all.filter((x) => x.company === d.value.job.company && x.title === d.value.job.title).sort((a, b) => b.version - a.version)[0]
      if (mine && mine.id !== Number(props.id)) { clearInterval(timer); busy.value = false; router.push('/drafts/' + mine.id) }
    }, 3000)
  } catch (e) { toast(e.message, 'bad'); busy.value = false }
}
const again = ref(false)
async function workAgain() {
  again.value = true
  try {
    await api.post(`/drafts/${props.id}/reanswer`)
    toast('Agent 会再处理一次这份申请：它会读你现在的资料和这份记录，从网站上现在的样子接着做')
    await load()
  } catch (e) { toast(e.message, 'bad') }
  again.value = false
}
async function runAgain() {
  
  await run(() => api.post(`/drafts/${props.id}/execute`), 'Agent 已重新开始', load, { name: 'execute' })
}
// Submit was pressed and the outcome is not known: what settles it comes first, filling it in again last and on the applicant's word
async function checkMail() {
  await run(() => api.post(`/applications/${d.value.application.id}/check-mail`), '正在查邮箱；有确认邮件的话，这份申请会记为已投出')
}
async function runAgainNotSubmitted() {
  if (!(await ask('确定这份申请没有提交成功吗？如果其实已经提交了，再做一次会向雇主再投一次。', { ok: '确定没提交，再做一次' }))) return
  await run(() => api.post(`/drafts/${props.id}/execute`, { not_submitted: true }), 'Agent 已重新开始', load, { name: 'execute' })
}
async function markSubmitted() {
  
  await run(() => api.post(`/applications/${d.value.application.id}/mark-submitted`), '已记为“投递成功”，稍后会查确认邮件', load)
}
async function approve() {
  
  await run(() => api.post(`/drafts/${props.id}/approve`), '已批准，Agent 开始处理', load, { name: 'approve' })
}
// "Not now" is a link back to the list: the draft stays as it is, waiting. Sending it back is a decision of its own -
// the draft is closed - and says what there is to do afterwards.
async function sendBack() {
  if (!(await ask('退回这份草案？它会作废，岗位回到“未投递”。之后想投这个岗位，在岗位页重新开始（可以写上你的要求）；只是想改几处答案的话，不用退回，直接在这里改或者在下面写修改意见。', { ok: '退回草案' }))) return
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
      <div class="muted small">这些是表单需要、而 Agent 在你的资料里找不到的信息，它不会替你编。在下面的表里点“修改”填上；勾选“以后也这样回答”，下次就不用再问。</div>
      <ul style="margin: 8px 0 0; padding-left: 20px"><li v-for="u in d.unresolved" :key="u.id">{{ u.label }}</li></ul>
      <div v-if="editable" class="row" style="margin-top: 10px"><button :disabled="again" @click="workAgain"><Icon name="refresh" />{{ again ? '正在安排…' : '让 Agent 再做一次' }}</button>
        <span class="muted small">刚补充过个人资料，或觉得这些问题资料里明明有答案时用。</span></div>
    </div>

    <div v-if="d.journal && d.journal.length" class="panel" style="margin-bottom: 16px">
      <div class="row"><h3 class="grow" style="margin: 0">Agent 做了什么</h3>
        <span v-if="d.spent" class="muted small">已用 {{ d.spent.steps }} / {{ d.spent.of_steps }} 步，约 {{ d.spent.minutes }} 分钟，{{ d.spent.runs }} 次运行</span></div>
      <div class="muted small">这份记录是 Agent 自己在网站上做完之后写的：每一项填了什么、依据是什么，都在下面的表里。这里是它途中记下的话。</div>
      <ul class="journal">
        <li v-for="(e, i) in d.journal" :key="i" :class="'j-' + e.kind">
          <span class="muted small nowrap">{{ fmtTime(e.at) }}</span>
          <span v-if="e.kind === 'run'" class="badge">开始一次运行</span>
          <span v-else-if="e.kind === 'ask'" class="j-strong">问你：{{ e.text }}</span>
          <span v-else-if="e.kind === 'waits'" class="j-strong">等你处理：{{ e.text }}</span>
          <span v-else-if="e.kind === 'sending'" class="j-strong">即将点提交：{{ e.text }}</span>
          <span v-else-if="e.kind === 'report'">这次运行结束（{{ e.calls }} 次操作）：{{ e.text }}</span>
          <span v-else-if="e.kind === 'ended'" class="j-strong">这次运行中断（{{ e.calls }} 次操作）：{{ e.text }}</span>
          <span v-else-if="e.kind === 'note'" class="muted">记下了这个网站的一条经验：{{ e.text }}</span>
          <span v-else>{{ e.text }}</span>
        </li>
      </ul>
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

    <div v-if="d.notes_display.length" class="callout" style="display: block">
      <b>Agent 的小结</b>
      <ul style="margin: 6px 0 0; padding-left: 20px"><li v-for="(n, i) in d.notes_display" :key="i">{{ n }}</li></ul>
    </div>

    <div class="row">
      <h3 class="grow">填写的内容（{{ filled.length }} 项）</h3>
    </div>
    <div class="table-wrap" style="max-height: none">
      <table>
        <thead><tr><th style="width: 34%">表单上的问题</th><th>填的答案</th><th style="width: 22%">依据</th><th>把握</th><th></th></tr></thead>
        <tbody>
          <tr v-for="a in d.answers.filter((x) => filled.includes(x) || isUnresolved(x) || x.dropped || editing === x.id)" :id="'ans-' + a.id" :key="a.id" :class="{ lit: lit === a.id }">
            <td>
              {{ a.label }}<span v-if="a.required" style="color: var(--bad)"> *</span>
              <span v-if="isUnresolved(a) && a.about === 'job'" class="tag" style="margin-left: 4px">只和这个岗位有关</span>
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
                  <div class="small muted">这里列出的是表单上的选项；也可以直接输入你的答案。</div>
                </template>
                <AaSelect v-else-if="a.type === 'checkbox'" v-model="editVal"><option value="true">勾选</option><option value="false">不勾选</option></AaSelect>
                <textarea v-else v-model="editVal" rows="3"></textarea>
                <div class="small muted" v-if="a.type === 'multiselect'">多选用 || 分隔；可选：{{ a.options.join(' / ') }}</div>
                <label class="small" style="display: block; margin-top: 8px"><input v-model="remember" type="checkbox" /> 以后别的申请表上遇到这个问题，也这样回答</label>
                <input v-if="remember" v-model="saveRule" placeholder="（可选）补充说明，例如：只对加拿大的岗位这样填" style="width: 100%; margin-top: 6px" />
                <div class="row" style="margin-top: 6px"><button class="primary" @click="commitEdit(a)">保存</button><button @click="editing = null">取消</button>
                  <button v-if="isUnresolved(a) && a.source === 'unresolved'" class="ghost" title="这一项不该由你来填。去掉后，Agent 会让它保持表单上现在的样子。" @click="dropQuestion(a)">不需要填这一项</button></div>
              </template>
              <template v-else>
                <span v-if="isUnresolved(a)" class="tag bad">还没有答案</span>
                <span v-else-if="a.dropped" class="tag">你说这一项不用填</span>
                <pre v-else style="font-family: inherit; font-size: 14px">{{ show(a) }}</pre>
              </template>
            </td>
            <td class="small muted">{{ a.basis_display }}</td>
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
            <span class="tag info">{{ m.slot_label || m.label || m.slot }}</span>
            <a v-if="m.document_id" :href="`api/documents/${m.document_id}/file`" target="_blank" rel="noopener" data-notr>{{ m.name }}</a>
            <span v-else data-notr>{{ m.name }}</span>
            <span v-if="m.overwritten" class="badge warn" title="早先的程序每次重写都写进同一个文件：这里打开的是后来写的那一版，不是这份草案生成时的内容">文件已被后来的版本覆盖</span>
          </div>
          <div v-if="!d.materials.length" class="muted">这份申请没有上传文件。</div>
          <template v-if="written">
            <div class="tailor">
              <div><b>{{ usesWritten ? '这份申请用的是为这个岗位改写的简历' : '有一份为这个岗位改写的简历，这份申请没有用它' }}</b><span v-if="written.focus">：{{ written.focus }}</span></div>
              <div v-if="written.keywords && written.keywords.length" class="row" style="gap: 6px; margin-top: 8px"><span v-for="k in written.keywords" :key="k" class="tag">{{ k }}</span></div>
              <details v-if="written.changes && written.changes.length" class="tech">
                <summary>和原版相比改了什么（{{ written.changes.length }} 处）</summary>
                <div v-for="(c, i) in written.changes" :key="i" class="chg">
                  <div><span class="tag" :class="c.type === 'rewrite_rejected' ? 'warn' : c.type === 'rewrite' || c.type === 'drop' ? 'info' : ''">{{ CHANGE[c.type] || c.type }}</span> <span class="muted small">{{ c.where }}</span></div>
                  <template v-if="Array.isArray(c.after)"><ol><li v-for="x in c.after" :key="x">{{ x }}</li></ol></template>
                  <template v-else>
                    <div v-if="c.before" class="small"><span class="muted">原文：</span>{{ c.before }}</div>
                    <div v-if="c.after" class="small"><span class="muted">{{ c.type === 'rewrite_rejected' ? '被丢掉的改写：' : '现在：' }}</span>{{ c.after }}</div>
                  </template>
                </div>
              </details>
              <div v-if="editable" class="row" style="margin-top: 10px">
                <button v-if="usesWritten" class="sm" @click="useResume('base')">改用原版简历</button>
                <button v-else class="sm" @click="useResume('tailored')">改用为这个岗位改写的简历</button>
              </div>
            </div>
          </template>
          <div v-if="editable && d.tailor && d.tailor.mode !== 'off'" class="tailor">
            <template v-if="d.tailor.available">
              <div class="small muted" style="margin-bottom: 6px">{{ written ? '不满意？可以说明要求，重新改写一次。' : '这份申请用的是原版简历。可以让程序按这个岗位改写一份。' }}</div>
              <div class="row"><input v-model="tailorNote" class="grow" placeholder="可选：有什么要求，例如“突出后端和数据库经验”" /><button class="sm" @click="tailorNow">{{ written ? '重新改写' : '按这个岗位改写简历' }}</button></div>
            </template>
            <div v-else class="small muted">想让程序按岗位改写简历，要先在材料库上传一份 Word 版简历，用途选“简历 Word 原稿”。 <router-link to="/files">打开材料库</router-link></div>
          </div>
        </div>
      </div>
      <div>
        <h3 id="draft-after" :class="{ lit: lit === 'after' }">批准之后会发生什么</h3>
        <div class="panel">
          <p v-if="d.policy === 'hand_over'" style="margin: 0">批准后，Agent 回到这份申请，把网站上现在的内容和这份记录逐项核对（网站自己改过的会改回来），然后停在最后一步，把窗口交给你，由你检查后点提交。</p>
          <p v-else style="margin: 0">批准后，Agent 回到这份申请，把网站上现在的内容和这份记录逐项核对（网站自己改过的会改回来），然后提交，并把确认页的原话和网址存下来作为证据。有它改不回来的差异时不会提交，会带着差异回到你这里。</p>
          <p class="small" style="margin: 8px 0 0"><router-link to="/settings/automation/submit">在设置里改由谁来点提交</router-link></p>
        </div>
      </div>
    </div>

    <div v-if="d.review_status === 'approved' && d.application.status === 'submit_unknown'" class="callout warn" style="display: block">
      <b>点过提交，但还不知道有没有提交成功。</b>
      <div class="muted">{{ d.application.explained.message }}</div>
      <div class="muted" style="margin-top: 6px">如果已经提交成功，雇主的确认邮件会把它记为已投出。先别重新填写：那样可能向雇主投两次。</div>
      <TechDetails :text="d.application.explained.detail" />
      <div class="row" style="margin-top: 10px">
        <button class="primary" @click="checkMail"><Icon name="mail" />现在检查确认邮件</button>
        <button @click="markSubmitted">我已经提交了</button>
        <button class="ghost" :disabled="acting('execute')" @click="runAgainNotSubmitted">没提交成功，让 Agent 再做一次</button>
      </div>
    </div>

    <div v-else-if="d.review_status === 'approved' && ['failed', 'needs_human', 'approved'].includes(d.application.status)" class="callout warn" style="display: block">
      <b>这份草案你已经批准，但申请还没有提交成功。</b>
      <div class="muted">{{ d.application.explained.message }}</div>
      <div v-if="editable" class="muted" style="margin-top: 6px">哪一项答案不对，可以直接在上面点“修改”改掉，不用重新批准；改完点下面的按钮，Agent 按现在的答案再做一次。</div>
      <TechDetails :text="d.application.explained.detail" />
      <div class="row" style="margin-top: 10px">
        <button class="primary" :disabled="acting('execute')" @click="runAgain"><Icon name="refresh" />让 Agent 再提交一次</button>
        <button @click="markSubmitted">我已经自己提交了</button>
      </div>
    </div>

    <div v-if="d.locked && ['pending', 'approved'].includes(d.review_status)" class="callout" style="display: block"><span class="muted">{{ d.locked }}</span></div>
    <div v-if="approvedOpen && d.comments && d.comments.length" class="panel small">
      <div v-for="(c, i) in d.comments" :key="i" class="muted">你：{{ c.comment }}<template v-if="c.result"> → {{ c.result }}</template></div>
    </div>

    <template v-if="pending">
      <h3>想改点什么？直接说</h3>
      <div class="panel">
        <textarea v-model="comment" placeholder="用平常说话的方式写要改什么。例如：求职信第二段改成重点讲我的实习经历；期望薪资填 30 CAD/hour" style="font-family: inherit"></textarea>
        <div class="row" style="margin-top: 8px"><button :disabled="!comment.trim() || busy" @click="sendComment">{{ busy ? 'Agent 正在处理…' : '按这个改' }}</button></div>
        <div v-for="(c, i) in d.comments" :key="i" class="small muted" style="margin-top: 6px">你：{{ c.comment }}<template v-if="c.result"> → {{ c.result }}</template></div>
      </div>
      <div class="row" style="position: sticky; bottom: 0; background: var(--bg); padding: 12px 0">
        <button class="primary" :disabled="!!d.unresolved.length || acting('approve')" @click="approve">{{ acting('approve') ? '正在批准…' : d.policy === 'hand_over' ? '批准，最后一步我来点提交' : '批准，让 Agent 提交' }}</button>
        <router-link to="/drafts" class="btn">稍后再说</router-link>
        <button class="ghost" :disabled="acting('reject') || acting('approve')" @click="sendBack">退回这份草案</button>
        <button class="ghost danger" :disabled="acting('reject') || acting('approve')" @click="reject(true)">不投这个岗位了</button>
        <span v-if="d.unresolved.length" class="muted">回答完上面的问题才能批准</span>
      </div>
    </template>
  </template>
</template>
