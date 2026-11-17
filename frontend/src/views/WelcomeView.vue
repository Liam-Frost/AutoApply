<script setup>
// First-run guide. Asks who is using the program, then proposes what to look for; nothing is saved until the last step.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import AiPanel from '../components/AiPanel.vue'
import EmployersPanel from '../components/EmployersPanel.vue'
import FileButton from '../components/FileButton.vue'
import Icon from '../components/Icon.vue'
import { loadPersona, toast } from '../ui'

const router = useRouter()
const STEPS = ['开始', '连接 AI', '你的情况', '简历', '找什么岗位', '从哪里找', '完成', '试一次']
const step = ref(0)
const meta = ref(null)
const p = ref({ stage: '', field: '', targets: [], countries: ['CA'], sponsorship: false, portal: '', strategy: 'volume' })
const portals = ref([])
api.get('/portals').then((d) => (portals.value = d.portals)).catch(() => {})
const targetsText = ref('')
const s = ref({})   // llm settings for the AI panel
const sec = ref({ claude_oauth_token: '' })
const info = ref({ secrets: {} })
const aiOk = ref(null)
const busy = ref('')
const sug = ref(null)
const roles = ref('')
const none = ref('')
const kinds = ref('')
const scoring = ref('')
const tried = ref([])
const resume = ref({ uploaded: false, name: '', profile: false, todos: 0 })
const bigtech = ref({})
const trial = ref({ url: '', state: '', message: '', draft: 0, job: 0 })
let trialTimer
const COUNTRIES = [['CA', '加拿大'], ['US', '美国'], ['GB', '英国'], ['AU', '澳大利亚'], ['DE', '德国'], ['SG', '新加坡'], ['CN', '中国'], ['HK', '中国香港']]
const BIG = [['amazon', 'Amazon'], ['apple', 'Apple'], ['google', 'Google'], ['microsoft', 'Microsoft'], ['meta', 'Meta'], ['nvidia', 'NVIDIA'], ['amd', 'AMD'], ['intel', 'Intel']]
const list = (t) => t.split(/[,，\n]/).map((x) => x.trim().toLowerCase()).filter(Boolean)
const ready = computed(() => p.value.stage && p.value.field && (p.value.field !== 'other' || targetsText.value.trim()))

async function load() {
  meta.value = await api.get('/persona')
  if (meta.value.persona.stage) { p.value = { ...p.value, ...meta.value.persona }; targetsText.value = (p.value.targets || []).join(', ') }
  resume.value.uploaded = meta.value.resume_uploaded; resume.value.profile = meta.value.has_profile
  const d = await api.get('/settings'); s.value = d.settings; info.value = d
}
async function testAi() {
  busy.value = 'ai'; aiOk.value = null
  try { await api.put('/settings', { settings: { 'llm.model': s.value['llm.model'], 'llm.small_model': s.value['llm.small_model'], 'llm.effort': s.value['llm.effort'] } }); await api.post('/settings/llm-test'); aiOk.value = true } catch (e) { aiOk.value = e.message }
  busy.value = ''
}
function toggleCountry(c) { const cur = new Set(p.value.countries); cur.has(c) ? cur.delete(c) : cur.add(c); p.value.countries = [...cur] }
async function upload(ev) {
  const f = ev.target.files[0]
  if (!f) return
  busy.value = 'up'
  try {
    const word = /\.docx$/i.test(f.name)
    const fd = new FormData(); fd.append('kind', word ? 'resume_docx' : 'resume_site'); fd.append('file', f)
    await api.upload('/documents', fd)
    if (word) { const fd2 = new FormData(); fd2.append('kind', 'source'); fd2.append('file', f); await api.upload('/documents', fd2) }
    resume.value.uploaded = true; resume.value.name = f.name
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''; ev.target.value = ''
}
async function makeProfile() {
  busy.value = 'profile'
  try {
    const r = await api.post('/profile/init', {})
    await api.put('/profile', { markdown: r.draft, note: 'first-run guide' })
    resume.value.profile = true; resume.value.todos = (r.draft.match(/TODO/g) || []).length
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''
}
async function suggest() {
  busy.value = 'sug'
  p.value.targets = targetsText.value.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)
  try {
    sug.value = await api.post('/persona/suggest', { persona: p.value })
    const st = sug.value.settings
    kinds.value = st['intake.title_any'].join(', '); roles.value = st['intake.title_role_any'].join(', '); none.value = st['intake.title_none'].join(', ')
    scoring.value = sug.value.scoring_md; bigtech.value = { ...st['sources.bigtech'] }
    await tryRules()
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''
}
const chosen = () => ({ ...sug.value.settings, 'intake.title_any': list(kinds.value), 'intake.title_role_any': list(roles.value), 'intake.title_none': list(none.value), 'intake.countries': p.value.countries, 'sources.bigtech': bigtech.value })
async function tryRules() {
  if (!sug.value || !sug.value.examples.length) { tried.value = []; return }
  const c = chosen()
  tried.value = (await api.post('/sources/try-rules', { rules: { title_any: c['intake.title_any'], title_role_any: c['intake.title_role_any'], title_none: c['intake.title_none'], countries: c['intake.countries'], max_age_days: 0 }, examples: sug.value.examples })).results
}
async function go(n) {
  if (n === 4 && !sug.value) { step.value = 4; await suggest(); return }
  step.value = n
}
async function finish(scan) {
  busy.value = 'done'
  try {
    await api.post('/persona/apply', { persona: p.value, settings: chosen(), scoring_md: scoring.value, scan })
    await loadPersona()
    toast(scan ? '设置已保存，正在后台扫描岗位' : '设置已保存')
    step.value = 7
  } catch (e) { toast(e.message, 'bad') }
  busy.value = ''
}
async function tryOne() {
  const t = trial.value
  t.state = 'running'; t.message = '正在打开这个岗位的申请页、读取申请表…（一般需要 2–5 分钟）'; t.draft = 0
  try {
    t.job = (await api.post('/jobs', { url: t.url.trim() })).id
    const task = (await api.post(`/jobs/${t.job}/draft`)).task_id
    clearInterval(trialTimer)
    trialTimer = setInterval(async () => {
      const row = (await api.get('/tasks?limit=40')).find((x) => x.id === task)
      if (!row || ['queued', 'running'].includes(row.status)) return
      clearInterval(trialTimer)
      if (row.status === 'done' && row.result && row.result.draft_id) { t.state = 'done'; t.draft = row.result.draft_id; t.message = '草案准备好了。' }
      else if (row.status === 'waiting_human') { t.state = 'needs'; t.message = '这个网站需要你先登录或处理一下，已经放进“需要我处理”。处理完程序会自动继续。' }
      else { t.state = 'failed'; t.message = (row.explained && row.explained.message) || '没有成功，可以换一个岗位再试。' }
    }, 5000)
  } catch (e) { t.state = 'failed'; t.message = e.message }
}
async function skip() { await api.post('/persona/skip'); await loadPersona(); router.push('/home') }
onMounted(load)
</script>

<template>
  <div v-if="meta" class="wiz">
    <ol class="wiz-steps">
      <li v-for="(l, i) in STEPS" :key="l" :class="{ on: i === step, done: i < step }"><span>{{ i < step ? '✓' : i + 1 }}</span>{{ l }}</li>
    </ol>

    <div v-if="step === 0" class="card wiz-card">
      <h2>欢迎使用 AutoApply</h2>
      <p>它帮你找岗位、给岗位打分、把申请表填好，你来决定投不投。用几分钟告诉它你的情况，它就按你的专业和阶段来工作。</p>
      <ul class="wiz-list">
        <li><Icon name="check" /><span><b>不替你编造。</b>申请表和求职信里关于你的内容，只来自你的简历和你确认过的资料。</span></li>
        <li><Icon name="check" /><span><b>先给你看，再投。</b>每份申请先生成草案，你批准后才会填写；最后一下“提交”由谁点，可以设置。</span></li>
        <li><Icon name="check" /><span><b>数据只在这台电脑上。</b>简历、密码、登录状态都存在本机；除了你选的 AI 服务和招聘网站本身，不发给任何人。</span></li>
        <li><Icon name="check" /><span><b>不绕过网站的限制。</b>遇到人机验证或不让程序访问的网站，会停下来请你自己处理。</span></li>
      </ul>
      <div class="row" style="margin-top: 20px"><button class="primary" @click="go(1)">开始设置</button><button class="ghost" @click="skip">先跳过，直接进去看看</button></div>
    </div>

    <div v-else-if="step === 1">
      <div class="card"><div class="card-title">连接 AI</div><p class="muted" style="margin-bottom: 0">读岗位、回答申请表、写求职信都要用 AI。选一种你已经有的；没有的话，Claude 订阅或任意一家的 API key 都可以。这一步可以先跳过，但没有 AI 时后面的建议只能用通用模板。</p></div>
      <AiPanel :s="s" :sec="sec" :secrets="info.secrets" @changed="load" />
      <div class="card">
        <div class="row"><button :disabled="busy === 'ai'" @click="testAi"><Icon name="refresh" />{{ busy === 'ai' ? '正在测试…' : '测试一下能不能用' }}</button>
          <span v-if="aiOk === true" class="badge ok">可以用</span><span v-else-if="aiOk" class="small" style="color: var(--bad)">{{ aiOk }}</span></div>
      </div>
      <div class="row"><button @click="go(0)">上一步</button><button class="primary" @click="go(2)">{{ aiOk === true ? '下一步' : '下一步（先不连接也可以）' }}</button></div>
    </div>

    <div v-else-if="step === 2" class="card wiz-card">
      <h2>你的情况</h2>
      <p class="muted">这些决定程序默认找什么岗位、界面上显示什么、求职信用什么口吻。之后都能改。</p>
      <div class="field"><label>你现在处于哪个阶段</label>
        <div class="wiz-opts"><button v-for="x in meta.stages" :key="x.key" :class="{ on: p.stage === x.key }" @click="p.stage = x.key">{{ x.name }}</button></div></div>
      <div class="field"><label>哪个领域</label>
        <div class="wiz-opts"><button v-for="x in meta.fields" :key="x.key" :class="{ on: p.field === x.key }" @click="p.field = x.key">{{ x.name }}</button></div></div>
      <div class="field"><label>想找的岗位{{ p.field === 'other' ? '（必填）' : '（可选，写了更准）' }}</label>
        <input v-model="targetsText" placeholder="用逗号分开，例如：Financial Analyst, Strategy Consultant" /></div>
      <div class="field"><label>想在哪些国家或地区工作</label>
        <div class="row"><label v-for="[c, n] in COUNTRIES" :key="c" class="nowrap"><input type="checkbox" :checked="p.countries.includes(c)" @change="toggleCountry(c)" /> {{ n }}</label></div>
        <div class="hint">都不选表示不限。</div></div>
      <div class="field"><label><input v-model="p.sponsorship" type="checkbox" /> 我在这些地方工作需要雇主提供签证担保</label></div>
      <div class="field"><label>你更倾向哪种投法</label>
        <div class="choice" style="margin-top: 4px">
          <label :class="{ on: p.strategy === 'volume' }"><input v-model="p.strategy" type="radio" value="volume" /><div><b>多投</b><span>合适的岗位自动准备好草案，我批准就投。适合实习和校招。</span></div></label>
          <label :class="{ on: p.strategy === 'targeted' }"><input v-model="p.strategy" type="radio" value="targeted" /><div><b>精投</b><span>程序只负责找岗位和评分，我自己挑出要投的再让它准备；最后一步提交都由我来点。适合有经验的人。</span></div></label>
        </div></div>
      <div class="row"><button @click="go(1)">上一步</button><button class="primary" :disabled="!ready" @click="go(3)">下一步</button></div>
    </div>

    <div v-else-if="step === 3" class="card wiz-card">
      <h2>上传简历</h2>
      <p class="muted">程序会读你的简历，整理成一份“个人资料”，之后填申请表都从这里取内容。PDF 或 Word 都可以；如果有 Word 版，以后还能按岗位调整简历的顺序。</p>
      <div class="row">
        <FileButton :class="{ primary: !resume.uploaded }" accept=".pdf,.docx,.doc" :disabled="busy === 'up'" @change="upload"><Icon name="inbox" />{{ busy === 'up' ? '正在上传…' : resume.uploaded ? '再传一份' : '选择简历文件' }}</FileButton>
        <span v-if="resume.uploaded" class="badge ok">已上传{{ resume.name ? '：' + resume.name : '' }}</span>
      </div>
      <div v-if="resume.uploaded" style="margin-top: 16px">
        <button :class="{ primary: !resume.profile }" :disabled="busy === 'profile'" @click="makeProfile"><Icon name="edit" />{{ busy === 'profile' ? 'AI 正在读简历，大约一分钟…' : resume.profile ? '重新生成个人资料' : '生成个人资料' }}</button>
        <p v-if="resume.profile" class="callout" style="margin-top: 12px"><Icon name="check" /><span>个人资料已生成。<template v-if="resume.todos">里面有 {{ resume.todos }} 处简历上没有、需要你补充的信息（比如工作许可、称呼），</template>设置完成后到“个人资料”页看一遍、补全即可。</span></p>
      </div>
      <p class="hint" style="margin-top: 14px">没有连接 AI 的话这一步做不了，可以跳过，之后在“个人资料”页手动填写或生成。</p>
      <div class="row" style="margin-top: 8px"><button @click="go(2)">上一步</button><button class="primary" @click="go(4)">{{ resume.profile ? '下一步' : '跳过，下一步' }}</button></div>
    </div>

    <div v-else-if="step === 4" class="card wiz-card">
      <h2>找什么岗位</h2>
      <p v-if="busy === 'sug'" class="muted">正在根据你的情况准备建议…</p>
      <template v-else-if="sug">
        <p class="muted">招聘网站上的岗位绝大多数和你无关。程序先看标题和地点筛一遍，留下的再让 AI 读全文打分。下面是{{ sug.by === 'ai' ? ' AI 根据你的情况' : '按通用模板' }}给的建议，可以直接改。</p>
        <p v-if="sug.note" class="callout warn"><Icon name="alert" /><span>{{ sug.note }}</span></p>
        <div class="field"><label>标题里要有这些词之一（岗位性质）</label><input v-model="kinds" @change="tryRules" /><div class="hint">留空表示不限。</div></div>
        <div class="field"><label>并且有这些词之一（方向）</label><textarea v-model="roles" rows="3" style="font-family: inherit" @change="tryRules"></textarea></div>
        <div class="field"><label>标题里不能有这些词</label><textarea v-model="none" rows="2" style="font-family: inherit" @change="tryRules"></textarea></div>
        <div v-if="tried.length" class="field"><label>按上面的条件，这些岗位会怎么处理</label>
          <div class="list"><div v-for="t in tried" :key="t.title" class="item"><span class="badge" :class="t.kept ? 'ok' : ''">{{ t.kept ? '留下' : '丢掉' }}</span><div><div class="main">{{ t.title }}</div><div class="sub">{{ t.location }}{{ t.why ? ' · ' + t.why : '' }}</div></div></div></div></div>
        <details class="tech"><summary>评分规则（AI 读全文打分时用的标准，可以之后在“个人资料 → 评分规则”里改）</summary><textarea v-model="scoring" rows="14"></textarea></details>
        <div class="row" style="margin-top: 14px"><button @click="go(3)">上一步</button><button :disabled="busy === 'sug'" @click="suggest"><Icon name="refresh" />重新生成建议</button><button class="primary" @click="go(5)">下一步</button></div>
      </template>
    </div>

    <div v-else-if="step === 5" class="card wiz-card">
      <h2>从哪里找</h2>
      <p class="muted">先选几个开始，之后可以在“岗位 → 来源与关注公司”里随时增减，也可以在岗位页粘贴任何岗位的网址手动添加。</p>
      <div class="field"><label>大型科技公司的官网</label>
        <div class="row"><label v-for="[k, n] in BIG" :key="k" class="nowrap"><input type="checkbox" :checked="!!bigtech[k]" @change="bigtech = { ...bigtech, [k]: !bigtech[k] }" /> {{ n }}</label></div>
        <div class="hint">这些公司各种职能的岗位都有，按上一步的条件筛选。{{ ['software', 'engineering', 'design'].includes(p.field) ? '' : '你的领域默认没有勾选，需要的话自己勾。' }}</div></div>
      <div class="field"><label>学校的就业门户</label>
        <AaSelect v-model="p.portal">
          <option value="">没有，或暂时不用</option>
          <option v-for="x in portals.filter((x) => x.status === 'supported')" :key="x.key" :value="x.key">{{ x.school }} · {{ x.name }}</option>
          <option v-for="x in portals.filter((x) => x.status !== 'supported')" :key="x.key" :value="'other:' + x.key" disabled>{{ x.school ? x.school + ' · ' : '' }}{{ x.name }}（{{ x.status === 'same_system' ? '同一套系统，还没适配' : '还没有导入器' }}）</option>
        </AaSelect>
        <div class="hint">学校门户要用你的学校账号登录：在“岗位 → 来源与关注公司”里登录一次，程序扫描时就会自己读；也可以在你自己的浏览器里点一个书签导入。目前实际用过的只有 UBC。
          列表里灰色的是已知但还没适配的门户：可以在门户里打开岗位，把网址粘贴到岗位页的“手动添加”；想帮忙适配，见仓库里的 CONTRIBUTING.md。</div></div>
      <div class="field"><label>你自己想盯住的公司</label>
        <div class="hint">把这家公司招聘页的网址贴进来。这里添加的会马上保存，之后在“岗位 → 来源与关注公司”里管理。</div></div>
      <EmployersPanel :s="s" />
      <div class="row"><button @click="go(4)">上一步</button><button class="primary" @click="go(6)">下一步</button></div>
    </div>

    <div v-else-if="step === 7" class="card wiz-card">
      <h2>试一次</h2>
      <p class="muted">设置已经生效。想马上看看它是怎么工作的，可以贴一个你想投的岗位的网址，程序会去读它的申请表、按你的资料准备一份草案给你看。<b>这一步不会提交任何东西</b>，草案要你批准后才会填写。</p>
      <div class="row" style="margin-top: 14px">
        <input v-model="trial.url" class="grow" placeholder="岗位页面的网址，例如 https://job-boards.greenhouse.io/…/jobs/…" :disabled="trial.state === 'running'" />
        <button class="primary" :disabled="!trial.url.trim() || trial.state === 'running'" @click="tryOne"><Icon name="draft" />{{ trial.state === 'running' ? '正在准备…' : '准备一份草案' }}</button>
      </div>
      <p v-if="trial.message" class="callout" :class="trial.state === 'failed' ? 'warn' : ''" style="margin-top: 12px"><Icon :name="trial.state === 'done' ? 'check' : trial.state === 'failed' ? 'alert' : 'clock'" /><span>{{ trial.message }}</span></p>
      <p v-if="!resume.profile" class="hint">你还没有生成个人资料，草案里很多问题会是“还没有答案”。可以先去“个人资料”页补上再试。</p>
      <div class="row" style="margin-top: 16px">
        <router-link v-if="trial.draft" :to="'/drafts/' + trial.draft" class="btn primary"><Icon name="draft" />看这份草案</router-link>
        <router-link v-if="trial.state === 'needs'" to="/todos" class="btn primary">去“需要我处理”</router-link>
        <router-link to="/home" class="btn">{{ trial.state ? '进入概览' : '先不试，进入概览' }}</router-link>
      </div>
    </div>

    <div v-else class="card wiz-card">
      <h2>设置好了</h2>
      <p class="muted">确认一下，点完成后生效。这些之后都可以在设置里改。</p>
      <div class="facts" style="margin: 12px 0 18px">
        <div><div class="k">阶段</div><div class="v">{{ (meta.stages.find((x) => x.key === p.stage) || {}).name }}</div></div>
        <div><div class="k">领域</div><div class="v">{{ (meta.fields.find((x) => x.key === p.field) || {}).name }}</div></div>
        <div><div class="k">地区</div><div class="v">{{ p.countries.join('、') || '不限' }}</div></div>
        <div><div class="k">投法</div><div class="v">{{ p.strategy === 'targeted' ? '精投：我自己挑，自己点提交' : '多投：自动准备草案，我批准后投' }}</div></div>
        <div><div class="k">岗位来源</div><div class="v">{{ BIG.filter(([k]) => bigtech[k]).map(([, n]) => n).join('、') || '还没选（之后在“岗位 → 来源与关注公司”里加）' }}{{ p.portal ? '、学校门户' : '' }}</div></div>
        <div><div class="k">个人资料</div><div class="v">{{ resume.profile ? '已生成' : '还没有，之后在“个人资料”页填' }}</div></div>
      </div>
      <p class="hint">还可以之后设置：Telegram 通知（设置 → 通知与提醒）、邮箱跟踪（设置 → 账号与连接 → 收件邮箱）、网络代理（设置 → 系统与数据 → 网络连接）。</p>
      <div class="row" style="margin-top: 12px">
        <button @click="go(5)">上一步</button>
        <button class="primary" :disabled="busy === 'done'" @click="finish(BIG.some(([k]) => bigtech[k]))"><Icon name="check" />{{ BIG.some(([k]) => bigtech[k]) ? '完成，并马上扫描一次岗位' : '完成' }}</button>
      </div>
    </div>
  </div>
</template>
