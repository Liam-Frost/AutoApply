<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import AiPanel from '../components/AiPanel.vue'
import EmployersPanel from '../components/EmployersPanel.vue'
import MailboxPanel from '../components/MailboxPanel.vue'
import Icon from '../components/Icon.vue'
import NetworkPanel from '../components/NetworkPanel.vue'
import PromptsPanel from '../components/PromptsPanel.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
import { useRouter } from 'vue-router'
import { fmtTime, persona, run as runAction, toast } from '../ui'

const s = ref(null)
const info = ref({ secrets: {}, gmail: {}, drivers: [] })
const sec = ref({ anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' })
const netPanel = ref(null)
const claude = ref(null)
const lists = ref({ greenhouse: '', lever: '', ashby: '', workday: '' })
const tab = ref('apply')
const router = useRouter()
const rerun = async () => { await api.post('/persona/restart'); persona.done = false; router.push('/welcome') }
const SYSTEMS = [
  ['greenhouse', 'Greenhouse'], ['ashby', 'Ashby'], ['workday', 'Workday'], ['pdportal', 'UBC PD Portal'], ['generic', '其他网站'],
]
const sys = ref({})
const exported = ref(null)
const upd = ref(null)
api.get('/system').then((d) => (sys.value = d)).catch(() => {})
const exportData = async (sessions) => {
  try { exported.value = await api.post('/system/export', { sessions }) } catch (e) { toast(e.message, 'bad') }
}
const checkUpdate = async () => {
  try { upd.value = await api.get('/system/update') } catch (e) { toast(e.message, 'bad') }
}
const TABS = { apply: '投递方式', materials: '申请材料', sources: '岗位来源', intake: '入库条件', notify: '通知与邮箱', ai: 'AI 模型', prompts: 'AI 提示词', network: '网络', advanced: '高级' }
const BIGTECH = [['amazon', 'Amazon'], ['apple', 'Apple'], ['google', 'Google'], ['microsoft', 'Microsoft'], ['meta', 'Meta'], ['nvidia', 'NVIDIA'], ['amd', 'AMD'], ['intel', 'Intel']]
const COUNTRIES = [['CA', '加拿大'], ['US', '美国']]
const scan = ref({ at: null, sources: [] })
const bm = ref({ href: '' })
const examples = ref('Software Engineering Intern, Summer 2027 | Seattle, WA, US\nSenior Software Engineer | Toronto, ON, CA\nSoftware Developer Co-op | Vancouver, BC, Canada\nMBA Intern | New York, NY, US\nSoftware Engineering Intern | Singapore')
const tried = ref([])
const csv = (key) => (s.value[key] || []).join(', ')
const setCsv = (key, v) => { s.value[key] = v.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean) }
function toggleCountry(c) { const cur = new Set(s.value['intake.countries'] || []); cur.has(c) ? cur.delete(c) : cur.add(c); s.value['intake.countries'] = [...cur] }
function toggleSite(k) { s.value['sources.bigtech'] = { ...s.value['sources.bigtech'], [k]: !s.value['sources.bigtech'][k] } }
async function tryRules() {
  const rules = { title_any: s.value['intake.title_any'], title_role_any: s.value['intake.title_role_any'], title_none: s.value['intake.title_none'], countries: s.value['intake.countries'], max_age_days: s.value['intake.max_age_days'] }
  try { tried.value = (await api.post('/sources/try-rules', { rules, examples: examples.value.split('\n').filter((x) => x.trim()) })).results } catch (e) { toast(e.message, 'bad') }
}
const scanNow = () => act(() => api.post('/tasks', { kind: 'discover' }), '开始扫描，完成后会通知你；大厂官网全部读一遍大约需要十几分钟')

async function load() {
  const d = await api.get('/settings')
  s.value = d.settings
  info.value = d
  api.get('/settings/claude-status').then((c) => (claude.value = c)).catch(() => {})
  api.get('/sources/last-scan').then((c) => (scan.value = c)).catch(() => {})
  api.get('/import/pdportal/bookmarklet').then((c) => (bm.value = c)).catch(() => {})
  lists.value = {
    greenhouse: d.settings['sources.greenhouse'].join('\n'), lever: d.settings['sources.lever'].join('\n'), ashby: d.settings['sources.ashby'].join('\n'),
    workday: d.settings['sources.workday'].map((w) => `${w.host} ${w.tenant} ${w.site}${w.search ? ' ' + w.search : ''}`).join('\n'),
  }
}
const lines = (t) => t.split('\n').map((x) => x.trim()).filter(Boolean)
async function save() {
  try {
    const st = { ...s.value }
    for (const k of ['employers', 'employers.migrated', 'mail.kind', 'mail.imap', 'llm.provider', 'llm.providers', 'persona', 'onboarding.done', 'sso.sites', 'sso.offered',
      'sources.greenhouse', 'sources.lever', 'sources.ashby', 'sources.workday', 'sources.bigtech']) delete st[k]  // owned by their own panels / endpoints
    const secrets = {}
    for (const k in sec.value) if (sec.value[k]) secrets[k] = sec.value[k]
    await api.put('/settings', { settings: st, secrets })
    sec.value = { anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' }
    toast('设置已保存')
    await load()
    if (netPanel.value) netPanel.value.load()
  } catch (e) { toast(e.message, 'bad') }
}
const act = (fn, ok) => runAction(fn, ok, load)
const llmTest = () => act(() => api.post('/settings/llm-test'), 'AI 模型可以正常使用')
const tgTest = () => act(() => api.post('/settings/telegram-test'), '测试消息已发送，请查看 Telegram')
function gmailClient(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f)
  act(() => api.upload('/settings/gmail-client', fd), '文件已保存，接着点“授权”')
}
const gmailAuth = () => act(() => api.post('/settings/gmail-authorize'), '已打开浏览器，请在里面完成 Google 授权（只读）')
function toggle(key, sys) { s.value[key] = { ...s.value[key], [sys]: !s.value[key][sys] } }
function setRegister(sys, on) { const p = { ...s.value['register.per_ats'] }; if (on) delete p[sys]; else p[sys] = false; s.value['register.per_ats'] = p }
function setPolicy(sys, v) { const p = { ...s.value['policy.per_ats'] }; if (v) p[sys] = v; else delete p[sys]; s.value['policy.per_ats'] = p }
onMounted(load)
</script>

<template>
  <div v-if="s">
    <PageHead title="设置" sub="改完记得点右上角的“保存”。">
      <button v-if="tab !== 'prompts'" class="primary" @click="save"><Icon name="check" />保存</button>
    </PageHead>
    <div class="seg" style="margin-bottom: 16px">
      <button v-for="(l, k) in TABS" :key="k" :class="{ on: tab === k }" @click="tab = k">{{ l }}</button>
    </div>

    <!-- 投递方式 -->
    <template v-if="tab === 'apply'">
      <div class="card">
        <div class="row"><span class="card-title grow">使用档案</span><button class="sm" @click="rerun">重新走一遍设置向导</button></div>
        <p class="muted" style="margin: 4px 0 0">{{ persona.features.summary || '还没有填。程序现在按最初的默认方式工作，所有功能都显示。走一遍向导可以让它按你的专业和阶段来设置。' }}</p>
        <p class="hint" style="margin-top: 6px">档案决定界面显示哪些内容、求职信用什么口吻。重新走向导时，最后一步确认前不会改动你现在的设置。</p>
      </div>
      <div class="card">
        <div class="card-title">草案批准之后</div>
        <p class="muted">每个申请都会先生成草案给你看。这里决定你批准之后，最后那一下“提交”由谁来点。</p>
        <div class="kv">
          <label>默认</label>
          <AaSelect v-model="s['policy.default']"><option value="approve_then_submit">程序填好、核对无误后自动提交</option><option value="manual">程序填好后停下，我检查后自己点提交</option></AaSelect>
          <label>这些公司始终由我提交</label>
          <div><input style="width: 100%" :value="(s['policy.manual_companies'] || []).join(', ')" placeholder="例如：Google, Apple（用逗号分开）" @change="s['policy.manual_companies'] = $event.target.value.split(/[,，]/).map((x) => x.trim()).filter(Boolean)" /></div>
          <label>遇到挡住表单的“数据隐私声明”</label>
          <div><input v-model="s['consent.acknowledge_notices']" type="checkbox" /> <span class="hint">自动点“I understand / Accept”后继续。这类声明是申请的前提条件；只处理纯告知性质的弹窗，不会碰申请表里的任何选项。不勾的话，遇到就停下来等你。</span></div>
          <label>答案没把握时由我提交</label>
          <AaSelect v-model="s['policy.manual_confidence']"><option value="none">不因此停下</option><option value="low">草案里有“把握低”的答案时</option><option value="medium">有“把握中等”或“把握低”的答案时</option></AaSelect>
        </div>
        <p class="hint" style="margin-top: 12px">另外两种情况也一定会停下等你：这个网站程序还不熟（没有专门适配）；或者填写中途出过错、由 AI 接手填完。</p>
      </div>

      <div class="card">
        <div class="card-title">哪些岗位自动生成草案</div>
        <div class="kv" style="margin-top: 12px">
          <label>评分达到多少分</label><div><input v-model.number="s['queue.min_score_for_draft']" type="number" step="0.5" style="width: 100px" /> <span class="hint">满分 10。新岗位评分达到这个分数就自动准备草案。</span></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">没有账号的网站</div>
        <p class="muted">需要登录的招聘网站：你以前投过的公司，会请你登录一次并记住；没投过的，由程序自己注册账号（密码存在本机的系统凭据管理器里）。</p>
        <div class="kv">
          <label>允许程序自己注册账号</label><div><input v-model="s['register.auto']" type="checkbox" /></div>
          <label>网站支持“用第三方账号登录”时</label>
          <div><AaSelect v-model="s['sso.mode']"><option value="ask">每个网站第一次先问我用哪种方式</option><option value="auto">直接用我已登录的第三方账号</option><option value="never">不用第三方账号，用邮箱注册</option></AaSelect>
            <div class="hint">指 Google / LinkedIn / Microsoft / Apple 等，需要先在<router-link to="/accounts">网站账号</router-link>里登录。用第三方账号登录时，对方会把你的姓名和邮箱提供给招聘网站；好处是不用多一个密码，也不用收验证邮件。网站上已经有账号的，始终用原来的账号。</div></div>
          <label>第三方账号的优先顺序</label>
          <div><input :value="(s['sso.order'] || []).join(', ')" style="width: 260px" @change="s['sso.order'] = $event.target.value.split(/[,，\s]+/).map((x) => x.trim().toLowerCase()).filter(Boolean)" />
            <span class="hint"> 一个网站同时支持几种时，用排在前面的。</span></div>
          <label>注册和登录用的邮箱</label><input v-model="s['account.email']" />
        </div>
      </div>
    </template>

    <!-- 申请材料 -->
    <template v-if="tab === 'materials'">
      <div class="card">
        <div class="card-title">按岗位调整简历</div>
        <p class="muted">程序可以针对每个岗位，把你简历里最相关的经历排到前面。它只用你 Word 简历里已有的内容，不会写出简历里没有的东西。需要先在<router-link to="/files">材料库</router-link>上传一份 Word 版简历，用途选“简历 Word 原稿”。</p>
        <div class="choice">
          <label :class="{ on: s['tailor.mode'] === 'off' }"><input v-model="s['tailor.mode']" type="radio" value="off" /><div><b>不调整</b><span>所有岗位都用你上传的简历。</span></div></label>
          <label :class="{ on: s['tailor.mode'] === 'select' }"><input v-model="s['tailor.mode']" type="radio" value="select" /><div><b>只调顺序</b><span>调整要点、项目和技能的先后顺序，一个字都不改。最稳妥。</span></div></label>
          <label :class="{ on: s['tailor.mode'] === 'rephrase' }"><input v-model="s['tailor.mode']" type="radio" value="rephrase" /><div><b>调顺序，并允许改写措辞</b><span>可以把要点改成更贴近岗位说明的说法。事实、数字、技术名称必须和原文一致，程序会逐条核对，不一致的改写会被丢掉。</span></div></label>
        </div>
        <div v-if="s['tailor.mode'] !== 'off'" class="kv" style="margin-top: 16px">
          <label>什么时候调整</label>
          <AaSelect :model-value="s['tailor.auto'] ? 'auto' : 'ask'" @update:model-value="s['tailor.auto'] = $event === 'auto'"><option value="auto">生成草案时自动调整</option><option value="ask">只在我点“按这个岗位调整简历”时</option></AaSelect>
          <template v-if="s['tailor.auto']">
            <label>评分达到多少分才调整</label>
            <div><input v-model.number="s['tailor.min_score']" type="number" step="0.5" min="0" max="10" style="width: 100px" /> <span class="hint">低于这个分数的岗位直接用原版简历，省时间也省 AI 额度。</span></div>
          </template>
          <label>可以调整哪些经历的先后</label>
          <AaSelect v-model="s['tailor.reorder_entries']"><option value="projects">只调项目，工作经历和教育保持时间顺序</option><option value="all">所有部分都可以调</option><option value="none">都不调，只调每段经历里要点的顺序</option></AaSelect>
          <label>调整技能的先后</label>
          <div><input v-model="s['tailor.reorder_skills']" type="checkbox" /> <span class="hint">把岗位要求的技能排到每一行的前面，不增不减。</span></div>
          <label>可以去掉不相关的要点</label>
          <div><input v-model="s['tailor.allow_drop']" type="checkbox" /> <span class="hint">适合内容比较多的简历。不勾选时所有要点都保留。</span></div>
          <label>每段经历至少留几条要点</label>
          <div><input v-model.number="s['tailor.min_bullets']" type="number" min="1" max="10" style="width: 100px" /> 条</div>
          <label>页数上限</label>
          <div><input v-model.number="s['tailor.target_pages']" type="number" min="0" max="5" style="width: 100px" /> 页 <span class="hint">填 0 表示和原版一样。如果你上传的是内容更全的多页“母版”简历，填 1，程序会按相关程度去掉排在最后的要点，直到剩一页。</span></div>
          <label>调整过的简历要我看过才能投</label>
          <div><input v-model="s['tailor.review']" type="checkbox" /> <span class="hint">勾选后，用了新调整简历的草案不会自动通过，一定等你批准。</span></div>
        </div>
      </div>
    </template>

    <PromptsPanel v-if="tab === 'prompts'" />
    <NetworkPanel v-if="tab === 'network'" ref="netPanel" :s="s" :sec="sec" :has-password="!!info.secrets.proxy_password" />

    <!-- 通知与邮箱 -->
    <template v-if="tab === 'notify'">
      <div class="card">
        <div class="row"><span class="card-title grow">Telegram 通知</span><span class="badge" :class="info.secrets.telegram_bot_token && s['notify.telegram_chat_id'] ? 'ok' : 'warn'">{{ info.secrets.telegram_bot_token && s['notify.telegram_chat_id'] ? '已接通' : '还没配置' }}</span></div>
        <p class="muted">进展、需要你处理的事和结果，都会发到你的 Telegram。</p>
        <div class="kv">
          <label>机器人令牌</label><input v-model="sec.telegram_bot_token" type="password" autocomplete="off" :placeholder="info.secrets.telegram_bot_token ? '已保存；要更换时在这里填新的' : '从 @BotFather 创建机器人后得到'" />
          <label>聊天 ID</label><input v-model="s['notify.telegram_chat_id']" placeholder="给机器人发一条消息后可以查到" />
          <label>发哪些通知</label>
          <div class="row">
            <label><input v-model="s['notify.todo']" type="checkbox" /> 需要我处理的事</label>
            <label><input v-model="s['notify.task_result']" type="checkbox" /> 结果（投出、没成功）</label>
            <label><input v-model="s['notify.status_update']" type="checkbox" /> 申请进展</label>
            <label><input v-model="s['notify.task_started']" type="checkbox" /> 开始做某件事</label>
          </div>
        </div>
        <div class="row" style="margin-top: 12px"><button @click="tgTest"><Icon name="send" />发一条测试消息</button><span class="hint">先保存再测试。面试和测评邀请不受开关影响，一定会发。</span></div>
      </div>

      <MailboxPanel />
    </template>

    <!-- 岗位来源 -->
    <template v-if="tab === 'sources'">
      <EmployersPanel :s="s" />

      <div class="card">
        <div class="card-title">上次扫描</div>
        <p v-if="!scan.at" class="muted">还没有扫描过。</p>
        <template v-else>
          <p class="muted">{{ fmtTime(scan.at) }}<span v-if="scan.duplicates"> · 合并了 {{ scan.duplicates }} 个重复的岗位</span></p>
          <table>
            <thead><tr><th>来源</th><th>读到</th><th>符合条件</th><th>新增</th><th>没留下的原因</th></tr></thead>
            <tbody>
              <tr v-for="r in scan.sources" :key="r.name">
                <td><b>{{ r.name }}</b></td>
                <td>{{ r.error ? '—' : r.read }}</td><td>{{ r.error ? '—' : r.kept }}</td><td>{{ r.error ? '—' : r.new }}</td>
                <td class="small muted">
                  <template v-if="r.error"><span style="color: var(--bad)">{{ r.error }}</span><TechDetails :text="r.error_detail" /></template>
                  <template v-else>{{ Object.entries(r.dropped).map(([k, v]) => `${k} ${v}`).join(' · ') || '—' }}</template>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>

      <div v-if="persona.features.portal === 'ubc'" class="card">
        <div class="card-title">UBC PD Portal</div>
        <p class="muted">门户不允许程序自动访问，所以改成在你自己的浏览器里导入：你登录门户后点一下书签，它在你的浏览器里读岗位，发给本机的 AutoApply。只读新出现的岗位，一般一两分钟。</p>
        <ol class="small" style="margin: 0 0 10px; padding-left: 20px; line-height: 1.9">
          <li>把这个按钮<b>拖到浏览器的书签栏</b>：<a v-if="bm.href" :href="bm.href" class="btn sm primary" @click.prevent="toast('把它拖到书签栏，不是点击')">导入到 AutoApply</a></li>
          <li>在 Chrome 里登录 PD Portal，打开 Job Postings 页面。</li>
          <li>点书签栏里的“导入到 AutoApply”。第一次会先列出全部岗位，列表出来后再点一次；右下角会显示进度。</li>
        </ol>
        <details class="tech"><summary>书签栏用不了？改用控制台</summary><pre>在门户页面按 F12 打开控制台，粘贴下面这行并回车：

var s=document.createElement('script');s.src='{{ s['app.base_url'] }}/pdportal-import.js';document.body.appendChild(s)</pre></details>
      </div>

      <div class="card">
        <div class="card-title">多久看一次</div>
        <div class="kv" style="margin-top: 12px">
          <label>扫描新岗位</label><div>每 <input v-model.number="s['schedule.discover_minutes']" type="number" style="width: 90px" /> 分钟 <span class="hint">填 0 关闭</span></div>
          <label>检查邮箱</label><div>每 <input v-model.number="s['schedule.mail_minutes']" type="number" style="width: 90px" /> 分钟 <span class="hint">填 0 关闭</span></div>
        </div>
      </div>
    </template>

    <!-- 入库条件 -->
    <template v-if="tab === 'intake'">
      <div class="card">
        <div class="row"><span class="card-title grow">什么样的岗位才入库</span><label><input v-model="s['intake.enabled']" type="checkbox" /> 启用</label></div>
        <p class="muted">招聘网站上的岗位绝大多数和你无关。每读到一个岗位，先按下面的条件看标题和地点，不符合的直接丢掉，不入库、不评分，也不占 AI 额度。留下来的再由 AI 读全文评分。UBC PD Portal 和你手动添加的岗位不受这些条件限制。</p>
        <div class="field"><label>标题里要有这些词之一（岗位类型）</label>
          <input :value="csv('intake.title_any')" @change="setCsv('intake.title_any', $event.target.value)" />
          <span class="hint">用逗号分开。按整词匹配，会自动认复数：“intern” 能匹配 Interns、Internship，但不会匹配 Internal。留空表示不限制。</span></div>
        <div class="field"><label>并且要有这些词之一（方向）</label>
          <textarea rows="3" style="font-family: inherit" :value="csv('intake.title_role_any')" @change="setCsv('intake.title_role_any', $event.target.value)"></textarea></div>
        <div class="field"><label>标题里不能有这些词</label>
          <input :value="csv('intake.title_none')" @change="setCsv('intake.title_none', $event.target.value)" /></div>
        <div class="kv">
          <label>工作地点在</label>
          <div class="row"><label v-for="[c, name] in COUNTRIES" :key="c"><input type="checkbox" :checked="(s['intake.countries'] || []).includes(c)" @change="toggleCountry(c)" /> {{ name }}</label>
            <span class="hint">都不勾表示不限地点。岗位没写地点时不会因此被丢掉。</span></div>
          <label>只要最近多少天内发布的</label>
          <div><input v-model.number="s['intake.max_age_days']" type="number" style="width: 100px" /> 天 <span class="hint">填 0 表示不限。网站没写发布日期时不会因此被丢掉。</span></div>
          <label>岗位结束后多久归档</label>
          <div><input v-model.number="s['archive.closed_after_days']" type="number" style="width: 100px" /> 天 <span class="hint">已下线、过了截止时间、标为不投或被拒的岗位，过这么久就从日常列表里收起来。记录不会删除。</span></div>
          <label>投出后多久没回音就归档</label>
          <div><input v-model.number="s['archive.silent_after_days']" type="number" style="width: 100px" /> 天</div>
          <label>相隔多久算新一轮招聘</label>
          <div><input v-model.number="s['dedupe.window_days']" type="number" style="width: 100px" /> 天 <span class="hint">同一家公司同名的岗位，如果两次出现相隔超过这么久，就当成新的岗位，而不是和旧的合并。</span></div>
          <label>每次最多让 AI 评分多少个</label>
          <div><input v-model.number="s['scoring.max_per_run']" type="number" style="width: 100px" /> 个 <span class="hint">超出的留到下一次扫描后再评，避免一次用掉太多额度。</span></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">试一下</div>
        <p class="muted">每行写一个标题，可以在后面用竖线加地点。点“试一下”看按当前填写的条件（不用先保存）哪些会留下。</p>
        <textarea v-model="examples" rows="5" style="font-family: inherit"></textarea>
        <div class="row" style="margin-top: 8px"><button @click="tryRules">试一下</button></div>
        <div v-if="tried.length" class="list" style="margin-top: 8px">
          <div v-for="(t, i) in tried" :key="i" class="item">
            <span class="badge" :class="t.kept ? 'ok' : ''" style="min-width: 56px; justify-content: center">{{ t.kept ? '留下' : '丢掉' }}</span>
            <div><div class="main">{{ t.title }}</div><div class="sub">{{ t.location }}</div></div>
            <span class="small muted">{{ t.why }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- AI 模型 -->
    <AiPanel v-if="tab === 'ai'" :s="s" :sec="sec" :secrets="info.secrets" @changed="load" />

    <!-- 高级 -->
    <template v-if="tab === 'advanced'">
      <div class="card">
        <div class="card-title">免审批直接投（自动通过）</div>
        <p class="muted">默认每份草案都要你批准。打开后，同时满足下面所有条件的草案不用你看，直接填写提交。建议用熟了再开。</p>
        <div class="kv">
          <label>开启自动通过</label><div><input v-model="s['auto_approve.enabled']" type="checkbox" /></div>
          <label>岗位评分至少</label><input v-model.number="s['auto_approve.min_score']" type="number" step="0.5" style="width: 100px" />
          <label>这个招聘系统已连续成功提交</label><div><input v-model.number="s['auto_approve.min_driver_successes']" type="number" style="width: 100px" /> 次以上</div>
          <label>新写的求职信也不用我看</label><div><input v-model="s['auto_approve.allow_new_cover_letter']" type="checkbox" /></div>
        </div>
        <p class="hint" style="margin-top: 12px">还必须同时满足：没有答不上的问题；所有答案都来自你确认过的资料，把握高；没有第一次遇到的敏感问题；网站已登录；草案里没有需要留意的备注。</p>
      </div>

      <div class="card">
        <div class="card-title">按招聘系统分别设置</div>
        <table style="margin-top: 8px">
          <thead><tr><th>招聘系统</th><th>批准之后</th><th>允许自动通过</th><th>允许自己注册账号</th></tr></thead>
          <tbody>
            <tr v-for="[k, name] in SYSTEMS" :key="k">
              <td><b>{{ name }}</b></td>
              <td><AaSelect :value="s['policy.per_ats'][k] || ''" @change="setPolicy(k, $event.target.value)"><option value="">跟默认一样</option><option value="approve_then_submit">自动提交</option><option value="manual">我自己点提交</option></AaSelect></td>
              <td><input type="checkbox" :checked="!!s['auto_approve.per_ats'][k]" @change="toggle('auto_approve.per_ats', k)" /></td>
              <td><input type="checkbox" :checked="s['register.per_ats'][k] !== false" @change="setRegister(k, $event.target.checked)" /></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-title">数据与更新</div>
        <p class="muted">你的数据都在这台电脑上：<code>{{ sys.data_dir }}</code> 和 <code>{{ sys.knowledge_dir }}</code>。升级程序不会动这两个文件夹。</p>
        <div class="row" style="gap: 8px; flex-wrap: wrap; margin-top: 8px">
          <button @click="exportData(false)"><Icon name="download" />导出全部数据</button>
          <button class="ghost" @click="exportData(true)">连同登录状态一起导出</button>
          <button @click="checkUpdate"><Icon name="refresh" />检查更新</button>
          <span class="muted small">当前版本 {{ sys.version }}</span>
        </div>
        <p v-if="exported" class="small" style="margin-top: 8px">已导出 {{ exported.files }} 个文件（{{ (exported.size / 1e6).toFixed(1) }} MB）：<a :href="'/api/system/export/' + exported.name">下载 {{ exported.name }}</a>
          <span class="muted">，也保存在 {{ exported.path }}</span></p>
        <p v-if="upd" class="small" style="margin-top: 8px">
          <template v-if="upd.error">{{ upd.error }}</template>
          <template v-else-if="upd.newer">有新版本 <b>{{ upd.latest }}</b>（{{ upd.published }}）：<a :href="upd.url" target="_blank" rel="noopener">查看发布说明并下载</a>。程序不会自动更新，下载后解压覆盖程序文件即可，数据不受影响。</template>
          <template v-else>{{ upd.note || '已经是最新版本。' }}</template>
        </p>
        <p class="hint" style="margin-top: 8px">导出的压缩包里有数据库、你上传和程序生成的文件、个人资料和规则；不含历次运行的截图，不含密码和 API key（它们在系统的密码库里）。登录状态是加密保存的，只能在这台电脑上用。
          恢复：先退出程序，然后在程序文件夹里运行 <code>uv run autoapply restore 导出文件.zip</code>，原来的数据会另存一份。</p>
      </div>

      <div class="card">
        <div class="card-title">其他</div>
        <div class="kv" style="margin-top: 12px">
          <label>填写出错时让 AI 接手</label><div><input v-model="s['repair.enabled']" type="checkbox" /> <span class="hint">AI 只能把你批准过的内容填进去，不能编新答案，也不能点提交；表单限制字数或格式时，它会把批准过的答案改写到符合要求，提交前给你看改写前后的内容。</span></div>
          <label>非必填项也填上</label><div><input v-model="s['fill.optional']" type="checkbox" /> <span class="hint">表单上不带星号的问题和整段可选内容（工作经历、教育经历、语言、链接等），只要你的资料或简历里有，就填上。关掉后只填必填项。</span></div>
          <label>审批前先把分步表单读完</label><div><input v-model="s['recon.walk']" type="checkbox" /> <span class="hint">有些表单要填完前一步才打得开后一步。打开后，程序会带着草案的答案在隐藏窗口里一步步填到确认页，把后面问到的问题加进草案，不会提交；填进去的内容雇主网站可能会存成未完成的申请。</span></div>
          <label>自检间隔</label><div>每 <input v-model.number="s['schedule.canary_minutes']" type="number" style="width: 90px" /> 分钟 <span class="hint">定期检查各招聘系统的适配是否还正常，填 0 关闭</span></div>
          <label>UBC PD Portal</label><div><input v-model="s['sources.pdportal']" type="checkbox" /> <span class="hint">目前门户不允许程序自动访问，这一项暂时不起作用</span></div>
          <label>通知里的链接指向</label><input v-model="s['app.base_url']" />
        </div>
      </div>
    </template>
  </div>
</template>
