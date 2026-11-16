<script setup>
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
import { fmtTime, run as runAction } from '../ui'

const todos = ref([])
const saveCred = ref(true)
const picked = ref({})      // to-do id -> the application chosen for an e-mail that names no posting
const reloadOverview = inject('reloadOverview', () => {})
let timer

// How each kind of to-do is presented: icon, tone, the title and the one-line explanation.
const VIEW = {
  takeover: { icon: 'login', tone: '', title: (t) => `登录 ${t.site ? t.site.name : t.title}`, what: (t) => t.explained.message || '这个网站需要你登录一次，之后程序会记住登录状态。' },
  login: { icon: 'login', tone: '', title: (t) => `登录 ${t.site ? t.site.name : t.title}`, what: (t) => t.explained.message },
  captcha: { icon: 'shield', tone: '', title: (t) => `${t.title}：需要你完成人机验证`, what: () => '网站要确认是真人在操作。请打开页面完成验证，然后回来点“我已完成”。' },
  answer: { icon: 'edit', tone: 'info', title: (t) => t.title, what: (t) => t.body || '草案里有必答题没有答案。' },
  submit: {
    icon: 'send',
    tone: 'info',
    title: (t) => (t.payload && t.payload.incomplete ? `${t.title}：还没填完，需要你接手` : t.title),
    what: (t) =>
      t.payload && t.payload.incomplete
        ? '申请表还没有填完：下面列出的几处，自动填写和 AI 接手都没能解决。请在弹出的浏览器窗口里把它们处理好，再点击提交。窗口会保留约 20 分钟。'
        : t.payload && t.payload.open_items
          ? '申请表已经填好，表单自己没有再报错；有几项程序读不回控件里的值，请在弹出的浏览器窗口里看一眼，然后点击提交。窗口会保留约 20 分钟。'
          : '申请表已经填好，并逐项核对过，表单自己也没有报错。请在弹出的浏览器窗口里看一遍，然后点击提交。窗口会保留约 20 分钟。',
  },
  failed: { icon: 'alert', tone: 'bad', title: (t) => t.title, what: (t) => t.explained.message },
  learned: { icon: 'wrench', tone: '', title: (t) => t.title, what: (t) => t.body || '程序从一次运行里学到了一个新做法，等你决定要不要采用。',
             next: () => '在“数据分析 → 耗时与优化”里可以看到它的内容，决定采用或不采用。' },
  driver_patch: { icon: 'wrench', tone: 'none', title: () => '自动修复了一处填写问题', what: (t) => `填写${t.subject ? '「' + t.subject + '」' : '申请表'}时，有一步没按预期完成，程序已改用另一种方式填完并核对过，这次申请不受影响。这条只是记录，你不需要做什么。` },
  driver: { icon: 'wrench', tone: 'none', title: (t) => t.title, what: (t) => t.explained.message },
  config: { icon: 'settings', tone: '', title: (t) => t.title, what: (t) => t.explained.message },
  mail_unmatched: { icon: 'mail', tone: 'info', title: () => '有一封邮件没对上岗位', what: (t) => `「${t.title}」${t.body ? ' — ' + t.body : ''}` },
}
VIEW.blocked = { icon: 'alert', tone: 'bad', title: (t) => `${t.title}：程序操作不了这个网站的申请页`,
  what: (t) => (t.payload && t.payload.why === 'google') ? '这个岗位要先用 Google 账号登录才能申请。先到“账号”页用 Google 登录一次（浏览器选 nodriver），再让程序重试；也可以自己打开岗位页面投递，投完回来点“我已经提交了”。' : '申请页在程序的浏览器里打不开或点不动（有些网站不对自动化浏览器显示内容）。可以自己打开岗位页面投递，投完回来点“我已经提交了”；也可以让程序再试一次。' }

// Sorting and filtering. Urgency comes from the server: 0 a window is waiting for you now, 1 the deadline is within 3 days, 2 when you can, 3 just so you know.
const CATS = [['all', '全部'], ['login', '要登录'], ['answer', '要回答'], ['submit', '要提交'], ['problem', '出了问题'], ['info', '仅通知']]
const URGENCY = ['现在处理', '快截止了', '有空时处理', '仅通知，不需要操作']
const SORTS = { urgency: '按轻重缓急', newest: '最新的在前', deadline: '按截止时间', score: '按岗位评分' }
const cat = ref('all')
const sort = ref(localStorage.getItem('todos.sort') || 'urgency')
const q = ref('')
const count = (c) => todos.value.filter((t) => c === 'all' || t.category === c).length
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase()
  const rows = todos.value.filter((t) => (cat.value === 'all' || t.category === cat.value)
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
const scoreCls = (x) => (x == null ? '' : x >= 9 ? 'hi' : x >= 7.5 ? 'mid' : '')

const view = (t) => VIEW[t.kind] || { icon: 'bell', tone: '', title: (x) => x.title, what: (x) => x.explained.message }

async function load() { todos.value = await api.get('/todos'); reloadOverview() }
const act = (fn, ok) => runAction(fn, ok, load)
const takeover = (t) => act(() => api.post('/accounts/takeover', { tenant_key: t.payload.tenant_key, url: t.payload.url, job_url: t.payload.job_url, save_credentials: saveCred.value }),
  '已打开一个浏览器窗口，请在里面登录。登录好之后直接关掉窗口，程序会保存登录状态并继续。')
const useSso = (t, p) => act(() => api.post('/accounts/sign-in-choice', { tenant_key: t.payload.tenant_key, provider: p.key }), `好的，这个网站以后用 ${p.name} 账号登录，任务已重新排队`)
const letRegister = (t) => act(() => api.post('/accounts/allow-register', { tenant_key: t.payload.tenant_key }), '好的，程序会自己注册账号，任务已重新排队')
const done = (t) => act(() => api.post(`/todos/${t.id}/done`, {}), '已继续')
const dismiss = (t) => act(() => api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }), '已关闭')
const runAgain = (t) => act(async () => { await api.post(`/drafts/${t.payload.draft_id}/execute`); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }).catch(() => {}) }, '已重新开始填写')
const linkMail = (t) => act(() => api.post(`/todos/${t.id}/link`, { application_id: picked.value[t.id] }), '已关联，这个申请的状态已按邮件更新')
const ackAll = () => act(() => api.post('/todos/bulk', { ids: infoIds.value }), `已关闭 ${infoIds.value.length} 条通知`)
const appliedMyself = (t) => act(() => api.post(`/jobs/${t.payload.job_id}/mark-submitted`), '已记为“投递成功”，稍后会查确认邮件')
const skipJob = (t) => act(async () => { await api.patch(`/jobs/${t.payload.job_id}`, { status: 'skipped' }); await api.post(`/todos/${t.id}/done`, { status: 'dismissed', resume: false }) }, '已标为不投递')
const markSubmitted = (t) => act(() => api.post(`/applications/${t.payload.application_id}/mark-submitted`), '已记为“投递成功”，稍后会查确认邮件')
onMounted(() => { load(); timer = setInterval(load, 6000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <PageHead title="需要我处理" sub="程序自己做不了、需要你出面的事。处理完，相关任务会自动继续。" />

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
          <button :class="{ primary: !(t.sso && t.sso.length) }" @click="takeover(t)"><Icon name="login" />{{ t.sso && t.sso.length ? '我自己登录' : '我有账号，去登录' }}</button>
          <button v-if="t.payload.can_register" @click="letRegister(t)">我没注册过，帮我注册</button>
          <button class="ghost" @click="dismiss(t)">先不处理</button>
          <label class="small muted" style="margin-left: 8px"><input v-model="saveCred" type="checkbox" /> 记住我输入的密码，下次自动登录</label>
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
        <template v-else-if="['failed', 'submit'].includes(t.kind) && t.payload && t.payload.draft_id">
          <button v-if="t.payload.maybe_submitted" class="primary" @click="markSubmitted(t)"><Icon name="check" />我已经提交了</button>
          <button :class="{ primary: !t.payload.maybe_submitted }" @click="runAgain(t)"><Icon name="refresh" />重新填写并提交</button>
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
        <template v-else-if="['driver_patch', 'driver'].includes(t.kind)">
          <button @click="dismiss(t)">知道了</button>
        </template>
        <template v-else>
          <a v-if="t.payload && t.payload.url" :href="t.payload.url" target="_blank" rel="noopener" class="btn"><Icon name="external" />打开页面</a>
          <router-link v-if="t.payload && t.payload.draft_id" :to="'/drafts/' + t.payload.draft_id" class="btn">查看草案</router-link>
          <button @click="done(t)">我处理好了，继续</button>
          <button class="ghost" @click="dismiss(t)">关闭</button>
        </template>
      </div>
      <TechDetails :text="t.explained.detail || (t.kind === 'driver_patch' ? t.body : '')" />
    </div>
  </div>
  </template>
  <div v-if="todos.length && !shown.length" class="card"><EmptyState icon="search" title="没有符合条件的待办" text="换一个分类，或清空搜索。" /></div>

  <div v-if="!todos.length" class="card"><EmptyState icon="check" title="没有需要你处理的事" text="需要登录、回答问题或确认提交时，会出现在这里，同时发到 Telegram。" /></div>
</template>
