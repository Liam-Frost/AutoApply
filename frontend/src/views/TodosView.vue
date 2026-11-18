<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import DataState from '../components/DataState.vue'
import { dataState, useRefresh } from '../data'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run as runAction, toast } from '../ui'

const todos = ref([])
const saveCred = ref(true)
const picked = ref({})      // to-do id -> the application chosen for an e-mail that names no posting
const reloadOverview = inject('reloadOverview', () => {})

// How each kind of to-do is presented: icon, tone, the title and the one-line explanation.
const VIEW = {
  takeover: { icon: 'login', tone: '', title: (t) => (t.payload && t.payload.provider ? `重新登录 ${t.payload.provider}` : `登录 ${t.site ? t.site.name : t.title}`),
              what: (t) => (t.payload && t.payload.provider
                ? (t.payload.for
                  ? `处理“${t.payload.for}”时发现保存的 ${t.payload.provider} 登录已经失效。重新登录一次，所有用 ${t.payload.provider} 登录的网站都会恢复，等着它的任务会自动继续。`
                  : `保存的 ${t.payload.provider} 登录已经失效。重新登录一次，所有用 ${t.payload.provider} 登录的网站都会恢复，等着它的任务会自动继续。`)
                : t.explained.message || '这个网站需要你登录一次，之后程序会记住登录状态。') },
  login: { icon: 'login', tone: '', title: (t) => `登录 ${t.site ? t.site.name : t.title}`, what: (t) => t.explained.message },
  captcha: { icon: 'shield', tone: '', title: (t) => `${t.title}：需要你完成人机验证`, what: () => '网站要确认是真人在操作。请打开页面完成验证，然后回来点“我已完成”。' },
  answer: { icon: 'edit', tone: 'info', title: (t) => t.title, what: (t) => t.body || '草案里有必答题没有答案。' },
  submit: {
    icon: 'send',
    tone: 'info',
    title: (t) => (t.payload && t.payload.incomplete ? `${t.title}：还没填完，需要你接手` : t.title),
    what: (t) =>
      t.application && t.application.status === 'submit_unknown'
        ? t.explained.message      // (a submission whose outcome is not known says so in its own words, not "look it over and press submit")
        : t.payload && t.payload.incomplete
        ? '申请表还没有填完：下面列出的几处，自动填写和 AI 接手都没能解决。请在弹出的浏览器窗口里把它们处理好，再点击提交。窗口会保留约 20 分钟。'
        : t.payload && t.payload.open_items
          ? '申请表已经填好，表单自己没有再报错；有几项程序读不回控件里的值，请在弹出的浏览器窗口里看一眼，然后点击提交。窗口会保留约 20 分钟。'
          : '申请表已经填好，并逐项核对过，表单自己也没有报错。请在弹出的浏览器窗口里看一遍，然后点击提交。窗口会保留约 20 分钟。',
  },
  failed: { icon: 'alert', tone: 'bad', title: (t) => t.title, what: (t) => t.explained.message },
  learned: { icon: 'wrench', tone: '', title: (t) => t.title, what: (t) => t.body || '程序从一次运行里学到了一个新做法，等你决定要不要采用。',
             next: () => '在“数据分析 → 耗时与优化”里可以看到它的内容，决定采用或不采用。' },
  share: { icon: 'wrench', tone: 'info', title: (t) => t.title, what: (t) => t.body },
  driver_patch: { icon: 'wrench', tone: 'none', title: () => '自动修复了一处填写问题', what: (t) => `填写${t.subject ? '「' + t.subject + '」' : '申请表'}时，有一步没按预期完成，程序已改用另一种方式填完并核对过，这次申请不受影响。这条只是记录，你不需要做什么。` },
  driver: { icon: 'wrench', tone: 'none', title: (t) => t.title, what: (t) => t.explained.message },
  config: { icon: 'settings', tone: '', title: (t) => t.title, what: (t) => t.explained.message },
  mail_unmatched: { icon: 'mail', tone: 'info', title: () => '有一封邮件没对上岗位', what: (t) => `「${t.title}」${t.body ? ' — ' + t.body : ''}` },
  // something with a date of its own: an interview, an assessment to finish, an offer to answer, a contact to get back to
  followup: { icon: 'bell', tone: 'info', title: (t) => t.title, what: (t) => t.body || '' },
}
VIEW.blocked = { icon: 'alert', tone: 'bad', title: (t) => `${t.title}：程序操作不了这个网站的申请页`,
  what: () => '申请页在程序的浏览器里打不开或点不动（有些网站不对自动化浏览器显示内容）。可以自己打开岗位页面投递，投完回来点“我已经提交了”；也可以让程序再试一次。' }

// Sorting and filtering. Urgency comes from the server: 0 a window is waiting for you now, 1 the deadline is within 3 days, 2 when you can, 3 just so you know.
const CATS = [['all', '全部'], ['dated', '有日期的'], ['login', '要登录'], ['answer', '要回答'], ['submit', '要提交'], ['problem', '出了问题'], ['info', '仅通知']]
const URGENCY = ['现在处理', '快截止了', '有空时处理', '仅通知，不需要操作']
const SORTS = { urgency: '按轻重缓急', newest: '最新的在前', deadline: '按截止时间', score: '按岗位评分' }
const cat = ref('all')
const sort = ref(localStorage.getItem('todos.sort') || 'urgency')
const q = ref('')
// What the applicant put off until later is out of the way until then - and can be looked at, and brought back, below.
const active = computed(() => todos.value.filter((t) => !t.snoozed_until))
const later = computed(() => todos.value.filter((t) => t.snoozed_until).sort((a, b) => (a.snoozed_until < b.snoozed_until ? -1 : 1)))
const showLater = ref(false)
const count = (c) => active.value.filter((t) => c === 'all' || t.category === c).length
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  const rows = active.value.filter((t) => (cat.value === 'all' || t.category === cat.value)
    && (!needle || `${t.title} ${t.body} ${t.job ? t.job.company + ' ' + t.job.title : ''} ${t.site ? t.site.name : ''}`.toLowerCase().includes(needle)))
  const big = 1e9
  const key = { urgency: (t) => [t.urgency, t.days_left ?? big, -(t.job?.score ?? 0), -t.id], newest: (t) => [-t.id], deadline: (t) => [t.days_left ?? big, t.urgency, -t.id],
    score: (t) => [-(t.job?.score ?? -1), t.urgency, -t.id] }[sort.value]
  return rows.sort((a, b) => { const x = key(a), y = key(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0 })
})
// with the default order the list is cut into sections, so "what first" is visible without reading every card
const sections = computed(() => {
  if (sort.value !== 'urgency') return [{ label: '', rows: shown.value }]
  return URGENCY.map((label, u) => ({ label, u, rows: shown.value.filter((t) => t.urgency === u) })).filter((x) => x.rows.length)
})
const setSort = (v) => { sort.value = v; try { localStorage.setItem('todos.sort', v) } catch { /* ignore */ } }
const infoIds = computed(() => shown.value.filter((t) => t.category === 'info').map((t) => t.id))
const left = (t) => (t.days_left == null ? '' : t.days_left < 0 ? '已过截止时间' : t.days_left === 0 ? '今天截止' : `还剩 ${t.days_left} 天`)
// a card's own date, in words: the day (and the time, when the mail gave one)
const dueText = (t) => (t.due_at ? (t.date_only ? t.due_at.slice(0, 10) : t.due_at.slice(0, 16).replace('T', ' ')) : '')
const dueTone = (t) => (t.days_left == null ? '' : t.days_left < 0 ? 'bad' : t.days_left <= 1 ? 'warn' : '')
// "show me this again": tomorrow morning, in three days, next Monday - or a day of the applicant's choosing
const menu = ref(0)          // the card whose "later" choices are open
const day = ref('')
function at9(d) { d.setHours(9, 0, 0, 0); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T09:00` }
function inDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return at9(d) }
function nextMonday() { const d = new Date(); d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); return at9(d) }
const snooze = (t, until) => { menu.value = 0; return act(() => api.post(`/todos/${t.id}/snooze`, { until }), until ? `好的，${until.slice(0, 10)} 再提醒你` : '已放回待办') }
const snoozeDay = (t) => (day.value ? snooze(t, day.value + 'T09:00') : null)
const dueEdit = ref({ id: 0, value: '' })
const openDue = (t) => { dueEdit.value = { id: t.id, value: t.due_at ? t.due_at.slice(0, 16) : '' } }
const saveDue = (t) => act(async () => { await api.post(`/todos/${t.id}/due`, { due: dueEdit.value.value || null }); dueEdit.value = { id: 0, value: '' } }, '日期已更新，到时会提醒你')
const scoreCls = (x) => (x == null ? '' : x >= 9 ? 'hi' : x >= 7.5 ? 'mid' : '')

// a card that says something is not set up (or no longer works): where that is put right
const FIX = {
  'config:gmail': ['/settings/accounts/mailbox', '打开邮箱设置'], 'config:resume': ['/files', '打开材料库'], 'config:pdportal-blocked': ['/settings/system/browser', '打开浏览器兼容设置'],
  'config:llm-limit': ['/settings/accounts/ai', '查看 AI 服务和额度'], 'config:llm': ['/settings/accounts/ai', '打开 AI 服务设置'],
  'config:profile': ['/profile?tab=init', '生成或填写个人资料'],
}
const view = (t) => VIEW[t.kind] || { icon: 'bell', tone: '', title: (x) => x.title, what: (x) => x.explained.message }

async function read() { todos.value = await api.get('/todos'); reloadOverview() }
const act = (fn, ok) => runAction(fn, ok, load)
const takeover = (t) => act(() => api.post('/accounts/takeover', { tenant_key: t.payload.tenant_key, url: t.payload.url, job_url: t.payload.job_url, save_credentials: !!t.remembers && saveCred.value }),
  '已打开一个浏览器窗口，请在里面登录。登录好之后直接关掉窗口，程序会保存登录状态并继续。')
const useSso = (t, p) => act(() => api.post('/accounts/sign-in-choice', { tenant_key: t.payload.tenant_key, provider: p.key }), `好的，这个网站以后用 ${p.name} 账号登录，任务已重新排队`)
const letRegister = (t) => act(() => api.post('/accounts/allow-register', { tenant_key: t.payload.tenant_key }), '好的，程序会自己注册账号，任务已重新排队')
const done = (t) => act(() => api.post(`/todos/${t.id}/done`, {}), '已继续')
const dismiss = (t) => act(() => api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }), '已关闭')
const runAgain = (t) => act(async () => { await api.post(`/drafts/${t.payload.draft_id}/execute`); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }, '已重新开始填写')
// What a card about an application offers follows from where the application stands, not from the card.
// Submit was pressed and the outcome is not known: filling it in again would be a second application if the first went through.
const unknown = (t) => !!(t.application && t.application.status === 'submit_unknown')
const checkMail = (t) => act(() => api.post(`/applications/${t.application.id}/check-mail`), '正在查邮箱；有确认邮件的话，这份申请会记为已投出，这张卡片会自己关闭')
async function runAgainNotSubmitted(t) {
  if (!(await ask('确定这份申请没有提交成功吗？如果其实已经提交了，重新填写会向雇主再投一次。', { ok: '确定没提交，重新填写' }))) return
  await act(async () => { await api.post(`/drafts/${t.payload.draft_id}/execute`, { not_submitted: true }); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }, '已重新开始填写')
}
const linkMail = (t) => act(() => api.post(`/todos/${t.id}/link`, { application_id: picked.value[t.id] }), '已关联，这个申请的状态已按邮件更新')
const ackAll = () => act(() => api.post('/todos/bulk', { ids: infoIds.value }), `已关闭 ${infoIds.value.length} 条通知`)
const moreBudget = (t) => act(() => api.post(`/applications/${t.payload.application_id}/budget`), '已追加一份预算，Agent 接着做')
const tryAgain = (t) => act(async () => { await api.post(`/jobs/${t.payload.job_id}/draft`); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }, 'Agent 已重新开始')
const appliedMyself = (t) => act(() => api.post(`/jobs/${t.payload.job_id}/mark-submitted`), '已记为“投递成功”，稍后会查确认邮件')
const skipJob = (t) => act(async () => { await api.patch(`/jobs/${t.payload.job_id}`, { status: 'skipped' }); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }) }, '已标为不投递')
// a driver the program wrote: the issue opens in the applicant's own browser, filled in, for them to read and submit
async function share(t, choice) {
  const tab = ['once', 'always'].includes(choice) ? window.open('', '_blank') : null      // opened in the click itself, or the browser blocks it
  try {
    const r = await api.post(`/learned/${t.payload.id}/share`, { choice })
    if (tab && r.url) tab.location = r.url
    else if (tab) tab.close()
    if (r.url && !r.whole) { try { await navigator.clipboard.writeText(r.body) } catch { /* the page shows what fits */ } }
    toast(choice === 'once' || choice === 'always'
      ? (r.whole ? '已在浏览器里打开 GitHub，内容已填好，确认后点提交即可' : '已打开 GitHub。驱动内容太长没放全，完整内容已复制到剪贴板，请粘贴到正文里再提交')
      : choice === 'never' ? '好的，以后不再询问。可以在“数据分析 → 耗时与优化”里改回来' : '好的，这次不提')
    load()
  } catch (e) { if (tab) tab.close(); toast(e.message, 'bad') }
}
const markSubmitted = (t) => act(() => api.post(`/applications/${(t.application && t.application.id) || t.payload.application_id}/mark-submitted`), '已记为“投递成功”，稍后会查确认邮件')
// (data.js: what is shown is being read, could not be read, or was read earlier - the page says which)
const { st, load } = dataState(read)
useRefresh(load, { every: 15000 })
onMounted(load)
</script>

<template>
  <PageHead title="需要我处理" sub="程序自己做不了、需要你出面的事。处理完，相关任务会自动继续。" />
  <DataState :s="st" what="待办" @retry="load" />
  <template v-if="st.at">

  <template v-if="todos.length">
    <div class="seg" style="margin-bottom: 12px">
      <button v-for="[k, l] in CATS" :key="k" :class="{ on: cat === k }" :disabled="k !== 'all' && !count(k)" @click="cat = k">{{ l }}<span class="n">{{ count(k) }}</span></button>
    </div>
    <div class="filters">
      <input v-model="q" placeholder="搜索公司、岗位或网站" style="width: 240px" />
      <AaSelect :model-value="sort" aria-label="排序方式" @update:model-value="setSort"><option v-for="(l, k) in SORTS" :key="k" :value="k">{{ l }}</option></AaSelect>
      <span class="grow"></span>
      <button v-if="infoIds.length > 1" class="sm" @click="ackAll"><Icon name="check" />{{ infoIds.length }} 条通知全部知道了</button>
      <span class="muted small nowrap">{{ shown.length }} 件</span>
    </div>
  </template>

  <template v-for="sec in sections" :key="sec.label">
  <div v-if="sec.label" class="todo-sec" :class="'u' + sec.u">{{ sec.label }}<span>{{ sec.rows.length }}</span></div>
  <div v-for="t in sec.rows" :key="t.id" class="card todo" :class="'u' + t.urgency">
    <div class="ico" :class="view(t).tone"><Icon :name="view(t).icon" /></div>
    <div>
      <div class="head">
        <span class="title grow">{{ view(t).title(t) }}</span>
        <span v-if="t.due_at" class="tag" :class="dueTone(t)" :title="t.payload && t.payload.due_text ? '邮件里写的：' + t.payload.due_text : ''">{{ dueText(t) }}<template v-if="left(t)"> · {{ left(t).replace('截止', '') }}</template></span>
        <span v-if="t.site && t.site.system" class="badge">{{ t.site.system }}</span>
        <span class="small muted">{{ fmtTime(t.created_at) }}</span>
      </div>
      <router-link v-if="t.job" :to="{ path: '/jobs', query: { open: t.job.id } }" class="todo-job">
        <span v-if="t.job.score != null" class="score" :class="scoreCls(t.job.score)">{{ t.job.score.toFixed(1) }}</span>
        <span class="ell">{{ t.job.company }} · {{ t.job.title }}</span>
        <span v-if="left(t)" class="tag" :class="t.days_left <= 3 ? 'warn' : ''">{{ left(t) }}</span>
      </router-link>
      <p class="what" style="white-space: pre-line">{{ view(t).what(t) }}</p>
      <p v-if="t.kind === 'mail_unmatched' && t.payload && t.payload.site && t.payload.site.length" class="callout"><Icon name="info" /><span>程序到雇主网站上查过，没能确定是哪一个。网站上显示：{{ t.payload.site.join('；') }}</span></p>
      <p v-else-if="t.kind === 'mail_unmatched' && t.candidates && !t.candidates_near" class="small muted">没认出是哪家雇主发的，下面列的是所有已投递的申请。</p>
      <p v-if="t.sso && t.sso.length" class="callout"><Icon name="info" /><span>这个网站支持用 {{ t.sso.map((p) => p.name).join(' / ') }} 账号登录，而你已经在这里登录过。选它的话，程序会替你点“用 {{ t.sso[0].name }} 登录”，不需要新密码；对方会把你的姓名和邮箱提供给这个网站。你的选择会记住，这个网站以后不再问。</span></p>
      <p v-else-if="t.sso_offered && t.sso_offered.length" class="callout"><Icon name="info" /><span>这个网站也支持用 {{ t.sso_offered.join(' / ') }} 账号登录。想用的话，先到<router-link to="/accounts">网站账号</router-link>里登录一次那个账号，再回来。</span></p>
      <p v-if="t.payload && t.payload.trying" class="callout"><Icon name="clock" /><span>登录窗口已打开，正在等你登录。大型网站第一次打开可能要半分钟到一分钟，请稍等。登录完成后直接关掉窗口即可。</span></p>
      <p v-else-if="t.payload && t.payload.last_try" class="callout warn"><Icon name="alert" /><span>上次没有登录成功：{{ t.payload.last_try }}。可以再点一次“去登录”。</span></p>
      <div v-if="t.payload && t.payload.open_items && t.payload.open_items.some((m) => m.kind === 'fix')" class="callout warn" style="display: block">
        <b>这几项没能填好，请在窗口里自己填上，再点提交：</b>
        <div v-for="m in t.payload.open_items.filter((m) => m.kind === 'fix')" :key="m.label" style="margin-top: 4px">「{{ m.label }}」<template v-if="m.expected">草案里的答案是 <b>{{ m.expected }}</b></template><span class="muted">（{{ m.why }}）</span></div>
      </div>
      <div v-if="t.payload && t.payload.open_items && t.payload.open_items.some((m) => m.kind === 'form')" class="callout warn" style="display: block">
        <b>表单自己还在提示这些问题，AI 接手后也没能解决，请在窗口里处理：</b>
        <div v-for="m in t.payload.open_items.filter((m) => m.kind === 'form')" :key="m.label" style="margin-top: 4px">{{ m.label }}</div>
      </div>
      <div v-if="t.payload && t.payload.open_items && t.payload.open_items.some((m) => m.kind !== 'fix' && m.kind !== 'form')" class="callout" style="display: block">
        <b>这几项应该已经填上了，但程序读不回控件的值、没法自己确认，提交前请看一眼：</b>
        <div v-for="m in t.payload.open_items.filter((m) => m.kind !== 'fix' && m.kind !== 'form')" :key="m.label" style="margin-top: 4px">「{{ m.label }}」应为 <b>{{ m.expected }}</b></div>
      </div>
      <div v-if="t.payload && t.payload.added" class="callout" style="display: block">
        <b>这几项草案里没有（选了某个答案之后才出现），AI 按你的个人资料填上了，请确认：</b>
        <div v-for="m in t.payload.added" :key="m.label" style="margin-top: 4px">「{{ m.label }}」填了 <b>{{ m.value }}</b><span v-if="m.basis" class="muted">（依据：{{ m.basis }}）</span></div>
      </div>
      <div v-if="t.payload && t.payload.adapted" class="callout" style="display: block">
        <b>这几项答案按表单的限制改写过，提交前请过目</b>
        <div v-for="m in t.payload.adapted" :key="m.label" style="margin-top: 6px">「{{ m.label }}」<span v-if="m.max_chars" class="muted">（表单最多收 {{ m.max_chars }} 个字符）</span>
          <div style="margin-top: 2px" data-notr>{{ m.entered }}</div>
          <details class="tech"><summary>改写前的答案</summary><pre data-notr>{{ m.approved }}</pre></details>
        </div>
      </div>
      <div v-if="t.payload && t.payload.mapped" class="callout" style="display: block">
        <b>这几项按表单上的实际选项填了，请确认意思没变：</b>
        <div v-for="m in t.payload.mapped" :key="m.label" style="margin-top: 4px">「{{ m.label }}」你的答案 <b>{{ m.approved }}</b> → 表单选项 <b>{{ m.chosen }}</b></div>
      </div>
      <div v-if="t.payload && t.payload.mismatches" class="callout warn" style="display: block">
        <div v-for="m in t.payload.mismatches" :key="m.id">「{{ m.label }}」草案里是 <b>{{ m.expected }}</b>，页面上是 <b>{{ m.actual || '空的' }}</b></div>
      </div>

      <div class="acts">
        <template v-if="['takeover', 'login'].includes(t.kind) && t.payload && t.payload.tenant_key">
          <button v-for="p in t.sso || []" :key="p.key" class="primary" @click="useSso(t, p)"><Icon name="login" />用我的 {{ p.name }} 账号登录</button>
          <button :class="{ primary: !(t.sso && t.sso.length) }" @click="takeover(t)"><Icon name="login" />{{ t.payload.provider ? `去登录 ${t.payload.provider}` : t.sso && t.sso.length ? '我自己登录' : '我有账号，去登录' }}</button>
          <button v-if="t.payload.can_register" @click="letRegister(t)">我没注册过，帮我注册</button>
          <button class="ghost" @click="dismiss(t)">先不处理</button>
          <label v-if="t.remembers" class="small muted" style="margin-left: 8px"><input v-model="saveCred" type="checkbox" /> 记住我输入的密码，下次自动登录</label>
          <span v-else-if="t.payload.tenant_key.startsWith('idp:')" class="small muted" style="margin-left: 8px">只保存登录状态，不保存这个账号的密码</span>
          <span v-else class="small muted" style="margin-left: 8px">这个登录窗口里程序看不到你输入的内容。想让程序以后自己登录，到“账号”页给这个网站保存登录名和密码。</span>
        </template>
        <template v-else-if="t.kind === 'blocked'">
          <a v-if="t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />打开岗位页面，自己投</a>
          <button @click="appliedMyself(t)"><Icon name="check" />我已经提交了</button>
          <button @click="done(t)"><Icon name="refresh" />让程序再试一次</button>
          <button class="ghost" @click="skipJob(t)">不投这个了</button>
        </template>
        <template v-else-if="t.kind === 'answer'">
          <router-link v-if="t.payload && t.payload.draft_id" :to="'/drafts/' + t.payload.draft_id" class="btn primary"><Icon name="edit" />去回答</router-link>
          <button class="ghost" @click="dismiss(t)">关闭</button>
        </template>
        <template v-else-if="t.kind === 'followup'">
          <button class="primary" @click="done(t)"><Icon name="check" />已完成</button>
          <button @click="openDue(t)"><Icon name="edit" />{{ t.due_at ? '改日期' : '加上日期' }}</button>
          <router-link v-if="t.payload && t.payload.application_id" :to="'/applications/' + t.payload.application_id" class="btn">查看这份申请和原邮件</router-link>
          <router-link v-else-if="t.payload && t.payload.contact_id" to="/contacts" class="btn">打开人脉</router-link>
        </template>
        <template v-else-if="['failed', 'submit'].includes(t.kind) && t.payload && t.payload.application_id && !t.payload.draft_id">
          <template v-if="unknown(t)">
            <button class="primary" @click="checkMail(t)"><Icon name="mail" />现在检查确认邮件</button>
            <button @click="markSubmitted(t)"><Icon name="check" />我已经提交了</button>
          </template>
          <button v-else-if="t.payload.budget" class="primary" @click="moreBudget(t)"><Icon name="refresh" />再给一份预算，接着做</button>
          <button v-else class="primary" @click="tryAgain(t)"><Icon name="refresh" />让 Agent 再试一次</button>
          <router-link :to="'/applications/' + t.payload.application_id" class="btn">查看这份申请</router-link>
          <button v-if="!unknown(t)" class="ghost" @click="dismiss(t)">不投了，关闭</button>
        </template>
        <template v-else-if="['failed', 'submit'].includes(t.kind) && t.payload && t.payload.draft_id">
          <template v-if="unknown(t)">
            <button class="primary" @click="checkMail(t)"><Icon name="mail" />现在检查确认邮件</button>
            <button @click="markSubmitted(t)"><Icon name="check" />我已经提交了</button>
            <button class="ghost" @click="runAgainNotSubmitted(t)">没提交成功，重新填写</button>
          </template>
          <template v-else>
            <button class="primary" @click="runAgain(t)"><Icon name="refresh" />{{ t.application && t.application.status === 'ready_to_submit' ? '重新打开窗口，由我提交' : '重新填写并提交' }}</button>
            <button v-if="t.application && t.application.status === 'ready_to_submit'" @click="markSubmitted(t)"><Icon name="check" />我已经提交了</button>
          </template>
          <router-link v-if="t.application" :to="'/applications/' + t.application.id" class="btn">查看这份申请</router-link>
          <router-link :to="'/drafts/' + t.payload.draft_id" class="btn">查看草案</router-link>
          <button class="ghost" @click="dismiss(t)">不投了，关闭</button>
        </template>
        <template v-else-if="t.kind === 'captcha'">
          <a v-if="t.payload && t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn primary"><Icon name="external" />打开页面</a>
          <button @click="done(t)">我已完成，继续</button>
          <button class="ghost" @click="dismiss(t)">关闭</button>
        </template>
        <template v-else-if="t.kind === 'mail_unmatched'">
          <AaSelect v-model="picked[t.id]" placeholder="这封邮件是哪个申请的？" style="max-width: 460px">
            <option v-for="c in t.candidates || []" :key="c.id" :value="c.id">{{ c.label }}{{ c.site_status ? '（网站上：' + c.site_status + '）' : '' }}</option>
          </AaSelect>
          <button class="primary" :disabled="!picked[t.id]" @click="linkMail(t)"><Icon name="check" />关联到这个申请</button>
          <button class="ghost" @click="dismiss(t)">和申请无关，关闭</button>
        </template>
        <template v-else-if="t.kind === 'share'">
          <button class="primary" @click="share(t, 'once')"><Icon name="external" />{{ t.payload.ready ? '打开并提交' : '提这一次' }}</button>
          <button v-if="!t.payload.ready" @click="share(t, 'always')">以后都提</button>
          <button class="ghost" @click="share(t, 'skip')">这次不提</button>
          <button class="ghost" @click="share(t, 'never')">永久不提</button>
        </template>
        <template v-else-if="['driver_patch', 'driver'].includes(t.kind)">
          <button @click="dismiss(t)">知道了</button>
        </template>
        <template v-else-if="t.kind === 'config' && FIX[t.ref]">
          <router-link :to="FIX[t.ref][0]" class="btn primary"><Icon name="settings" />{{ FIX[t.ref][1] }}</router-link>
          <button @click="done(t)">已经处理了</button>
        </template>
        <template v-else>
          <a v-if="t.payload && t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn"><Icon name="external" />打开页面</a>
          <router-link v-if="t.payload && t.payload.draft_id" :to="'/drafts/' + t.payload.draft_id" class="btn">查看草案</router-link>
          <button @click="done(t)">我处理好了，继续</button>
          <button class="ghost" @click="dismiss(t)">关闭</button>
        </template>
      </div>
      <div v-if="dueEdit.id === t.id" class="row" style="margin-top: 8px; flex-wrap: wrap">
        <label :for="'due-' + t.id" class="small muted">这件事的时间</label>
        <input :id="'due-' + t.id" v-model="dueEdit.value" type="datetime-local" style="width: 220px" />
        <button class="sm primary" @click="saveDue(t)">保存</button>
        <button v-if="t.due_at" class="sm ghost" @click="dueEdit.value = ''; saveDue(t)">去掉日期</button>
        <button class="sm ghost" @click="dueEdit = { id: 0, value: '' }">取消</button>
      </div>
      <!-- "not now": out of the way until a day of the applicant's choosing, then shown and said again -->
      <div class="row" style="margin-top: 8px; flex-wrap: wrap">
        <button v-if="menu !== t.id" class="sm ghost" @click="menu = t.id; day = ''"><Icon name="clock" />稍后提醒</button>
        <template v-else>
          <span class="small muted">什么时候再提醒：</span>
          <button class="sm" @click="snooze(t, inDays(1))">明天</button>
          <button class="sm" @click="snooze(t, inDays(3))">3 天后</button>
          <button class="sm" @click="snooze(t, nextMonday())">下周一</button>
          <input v-model="day" type="date" aria-label="选一天" style="width: 150px" />
          <button class="sm" :disabled="!day" @click="snoozeDay(t)">这一天</button>
          <button class="sm ghost" @click="menu = 0">取消</button>
        </template>
      </div>
      <TechDetails :text="t.explained.detail || (t.kind === 'driver_patch' ? t.body : '')" />
    </div>
  </div>
  </template>

  <div v-if="later.length" class="card">
    <button class="ghost" @click="showLater = !showLater">稍后提醒的（{{ later.length }}）{{ showLater ? '收起' : '展开' }}</button>
    <div v-if="showLater" class="list" style="margin-top: 8px">
      <div v-for="t in later" :key="t.id" class="item">
        <span class="badge" style="min-width: 96px; justify-content: center">{{ t.snoozed_until.slice(0, 10) }}</span>
        <div><div class="main">{{ view(t).title(t) }}</div><div v-if="t.due_at" class="sub">时间：{{ dueText(t) }}</div></div>
        <div class="right"><button class="sm" @click="snooze(t, null)">现在就看</button></div>
      </div>
    </div>
  </div>
  <div v-if="active.length && !shown.length" class="card"><EmptyState icon="search" title="没有符合条件的待办" text="换一个分类，或清空搜索。" /></div>

  <div v-if="!active.length" class="card"><EmptyState icon="check" title="没有需要你处理的事" text="需要登录、回答问题或确认提交时，会出现在这里，同时发到 Telegram。" /></div>
  </template>
</template>
