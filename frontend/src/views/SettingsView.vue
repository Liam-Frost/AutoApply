<script setup>
// The settings, in six groups by what they are about. Every section has an address (/settings/<group>/<section>), so
// a card, a notice or another page can lead to the very thing that needs changing.
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import AiPanel from '../components/AiPanel.vue'
import MailboxPanel from '../components/MailboxPanel.vue'
import AccessPanel from '../components/AccessPanel.vue'
import Icon from '../components/Icon.vue'
import NetworkPanel from '../components/NetworkPanel.vue'
import BrowserPanel from '../components/BrowserPanel.vue'
import DoctorPanel from '../components/DoctorPanel.vue'
import PromptsPanel from '../components/PromptsPanel.vue'
import PageHead from '../components/PageHead.vue'
import SetSection from '../components/SetSection.vue'
import FormError from '../components/FormError.vue'
import { useRoute, useRouter } from 'vue-router'
import { fmtTime, persona, run as runAction, toast } from '../ui'
import { absorb, changed, clone, unsaved, useUnsaved } from '../dirty'

const s = ref(null)
const info = ref({ secrets: {}, gmail: {} })
const sec = ref({ anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' })
const netPanel = ref(null)
const route = useRoute()
const router = useRouter()
const rerun = async () => { await api.post('/persona/restart'); persona.done = false; router.push('/welcome') }
const sys = ref({})
const exported = ref(null)
const upd = ref(null)
const docs = ref([])
api.get('/system').then((d) => (sys.value = d)).catch(() => {})
api.get('/documents').then((d) => (docs.value = d)).catch(() => {})
const exportData = async (sessions) => {
  try {
    exported.value = await api.post('/system/export', { sessions })
    sys.value = await api.get('/system')        // "last exported" is read from the exports themselves
  } catch (e) { toast(e.message, 'bad') }
}
const lastExport = computed(() => sys.value.last_export || null)
// (one sentence for each of the two cases: the parts are not put together from pieces)
const lastExportLine = computed(() => {
  const e = lastExport.value
  if (!e) return ''
  const when = fmtTime(e.created), mb = (e.size / 1e6).toFixed(1)
  return e.sessions ? `上次导出：${when}，${e.files} 个文件，${mb} MB，含登录状态。这台电脑上保留最近 5 份。` : `上次导出：${when}，${e.files} 个文件，${mb} MB，不含登录状态。这台电脑上保留最近 5 份。`
})
const checkUpdate = async () => {
  try { upd.value = await api.get('/system/update') } catch (e) { toast(e.message, 'bad') }
}

// --- where everything is ---------------------------------------------------------------------------------------------
// [group, its name, what it is for, [[section, its name], ...]]. The sections of a group are on one page, in this order.
const GROUPS = [
  ['overview', '总览', '这些设置合起来是什么意思：你会投什么，程序现在自己能做到哪一步。只读；每一条都能点到改它的地方。', []],
  ['goals', '求职目标与匹配', '想找什么样的岗位：哪些根本不看，哪些优先。', [['profile', '求职档案'], ['filters', '入库前的硬条件'], ['search', '在大型官网上搜什么'], ['sources', '来源与关注公司']]],
  ['automation', '自动化与工作计划', '程序自己能做到哪一步，什么时候做。', [['prepare', '自动开始申请'], ['submit', '怎么提交'], ['limits', 'Agent 怎么工作'], ['schedule', '工作计划']]],
  ['materials', '材料', '简历怎么调、求职信怎么写。', [['resume', '简历'], ['cover', '求职信']]],
  ['accounts', '账号与连接', '招聘网站的登录、收信的邮箱、用哪家 AI。', [['logins', '招聘网站的登录'], ['mailbox', '收件邮箱'], ['ai', 'AI 服务']]],
  ['notify', '通知与提醒', '什么事告诉你，发到哪里，什么时候不打扰。', [['channel', '发到哪里'], ['events', '通知什么、什么时候']]],
  ['system', '系统与数据', '网络、浏览器、远程访问、备份，和平时用不到的专家工具。', [['network', '网络连接（出站）'], ['browser', '浏览器兼容'], ['remote', '远程访问（入站）'], ['security', '账号安全'], ['retention', '数据保留'], ['backup', '备份与更新'], ['diagnose', '诊断'], ['expert', '专家工具']]],
]
const group = computed(() => (GROUPS.some((g) => g[0] === route.params.group) ? route.params.group : 'overview'))
// what the settings come to, as the server reads them (rules.py): asked for when the overview is opened, and again after a save
const rules = ref(null)
const loadRules = () => api.get('/rules').then((d) => (rules.value = d)).catch((e) => toast(e.message, 'bad'))
watch(group, (g) => { if (g === 'overview') loadRules() }, { immediate: true })
const WHO = { auto: ['程序自己做', 'ok'], you: ['等你', 'warn'], mixed: ['看情况', 'info'], off: ['不做', ''] }
const KIND_TONE = { fact: 'info', filter: 'warn', preference: '', threshold: 'ok', source: '' }
const here = computed(() => GROUPS.find((g) => g[0] === group.value))
function settle() {
  // an address that names no group, or one that is not there (an old link): the first group
  if (route.params.group !== group.value) { router.replace('/settings/' + group.value); return }
  const sec = route.params.section
  if (sec) nextTick(() => { const el = document.getElementById('set-' + sec); if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' }) })
}
watch(() => [route.params.group, route.params.section, !!s.value], settle)

const COUNTRIES = [['CA', '加拿大'], ['US', '美国']]
const examples = ref('Software Engineering Intern, Summer 2027 | Seattle, WA, US\nSenior Software Engineer | Toronto, ON, CA\nSoftware Developer Co-op | Vancouver, BC, Canada\nMBA Intern | New York, NY, US\nSoftware Engineering Intern | Singapore')
const tried = ref([])
const csv = (key) => (s.value[key] || []).join(', ')
const setCsv = (key, v) => { s.value[key] = v.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean) }
function toggleCountry(c) { const cur = new Set(s.value['intake.countries'] || []); cur.has(c) ? cur.delete(c) : cur.add(c); s.value['intake.countries'] = [...cur] }
async function tryRules() {
  const rules = { title_any: s.value['intake.title_any'], title_role_any: s.value['intake.title_role_any'], title_none: s.value['intake.title_none'], countries: s.value['intake.countries'], max_age_days: s.value['intake.max_age_days'] }
  try { tried.value = (await api.post('/sources/try-rules', { rules, examples: examples.value.split('\n').filter((x) => x.trim()) })).results } catch (e) { toast(e.message, 'bad') }
}

// --- how what is on this page gets saved -------------------------------------------------------------------------------
// Three ways, and each section says which of them it uses: the button at the top right (most settings), a part's own
// button (a mailbox, an AI service, a prompt, the access settings), and at once. The button at the top saves what was
// changed and says how much that is; nothing reads the settings afresh over what is being edited.
// settings that belong to their own panels / endpoints / pages: the button at the top does not send them
const ELSEWHERE = ['employers', 'employers.migrated', 'mail.kind', 'mail.imap', 'llm.provider', 'llm.providers', 'persona', 'onboarding.done', 'sso.sites', 'sso.offered',
  'sources.greenhouse', 'sources.lever', 'sources.ashby', 'sources.workday', 'sources.bigtech', 'sources.pdportal', 'schedule.paused']
const saved = ref({})         // the settings as they were last read or saved
const saving = ref(false)
const dirtyKeys = computed(() => (s.value ? changed(saved.value, s.value).filter((k) => !ELSEWHERE.includes(k)) : []))
const typedSecrets = computed(() => Object.keys(sec.value).filter((k) => sec.value[k]))
const pending = computed(() => dirtyKeys.value.length + typedSecrets.value.length)
// in which group each change was made (a change is made in the group that is open): the groups with something unsaved are marked
const madeIn = reactive({})
watch(() => [...dirtyKeys.value, ...typedSecrets.value.map((k) => 'secret:' + k)], (now) => {
  for (const k of now) if (!madeIn[k]) madeIn[k] = group.value
  for (const k of Object.keys(madeIn)) if (!now.includes(k)) delete madeIn[k]
})
const marked = (g) => Object.values(madeIn).includes(g) || (g === group.value && unsaved.value.some((a) => a.id !== 'settings' && a.scope === '/settings/' + g))

async function load() {
  const d = await api.get('/settings')
  if (!s.value) { s.value = d.settings; saved.value = clone(d.settings) } else absorb(s.value, saved.value, d.settings)      // (dirty.absorb: what is being edited stays)
  info.value = d
}
async function save() {
  const keys = dirtyKeys.value
  const n = pending.value
  if (!n) { toast('没有需要保存的改动'); return true }
  if (saving.value) return false
  saving.value = true
  try {
    // (ui.run: what the server refused stays on the page, next to the button, until it is saved again)
    const done = await runAction(async () => {
      const st = {}
      for (const k of keys) st[k] = s.value[k]       // what was changed, and only that: a setting another part saved meanwhile is not sent back as it was
      const secrets = {}
      for (const k in sec.value) if (sec.value[k]) secrets[k] = sec.value[k]
      await api.put('/settings', { settings: st, secrets })
      for (const k of keys) saved.value[k] = clone(s.value[k])
      sec.value = { anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' }
    }, `已保存 ${n} 项改动`, async () => {
      await load()
      if (group.value === 'overview') loadRules()
      if (netPanel.value) netPanel.value.load()
    }, { form: 'settings' })
    return done !== false
  } finally { saving.value = false }
}
function discard() {
  for (const k of dirtyKeys.value) s.value[k] = clone(saved.value[k])
  sec.value = { anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' }
}
useUnsaved({ id: 'settings', label: '设置', dirty: () => pending.value > 0, save, discard, scope: '/settings' })
// (after an action of this page - a test message, a part saved by its own button - the settings are read afresh;
// load takes what is new and leaves what is being edited)
const act = (fn, ok) => runAction(fn, ok, load)
const tgTest = () => act(() => api.post('/settings/telegram-test'), '测试消息已发送，请查看 Telegram')
const hasWord = computed(() => docs.value.some((d) => d.kind === 'resume_docx' && d.active))
const template = computed(() => docs.value.find((d) => d.kind === 'cl_template' && d.active))
// the conventions of the applicant's own letter template, one per line
const pairs = (key, a, b) => (s.value[key] || []).map((x) => `${x[a]} | ${x[b]}`).join('\n')
const setPairs = (key, a, b, text) => { s.value[key] = text.split('\n').map((l) => l.split('|').map((x) => x.trim())).filter((p) => p.length >= 2 && p[0] && p[1]).map((p) => ({ [a]: p[0], [b]: p.slice(1).join('|').trim() })) }
onMounted(load)
</script>

<template>
  <div v-if="s">
    <PageHead title="设置">
      <span v-if="pending" class="badge warn" role="status">有 {{ pending }} 项改动还没保存</span>
      <button v-if="pending" class="ghost" :disabled="saving" @click="discard">放弃改动</button>
      <button class="primary" :disabled="!pending || saving" @click="save"><Icon name="check" />{{ saving ? '正在保存…' : pending ? '保存' : '已保存' }}</button>
    </PageHead>
    <FormError name="settings" />
    <nav class="seg" style="margin-bottom: 8px" aria-label="设置的分组">
      <router-link v-for="[g, name] in GROUPS" :key="g" :to="'/settings/' + g" class="seg-link" :class="{ on: group === g }">{{ name }}<span v-if="marked(g)" class="unsaved-dot" title="有改动还没保存" aria-label="有改动还没保存"></span></router-link>
    </nav>
    <p class="muted" style="margin: 0 0 6px">{{ here[2] }}</p>
    <nav v-if="here[3].length" class="set-toc" aria-label="这一组里的各节">
      <router-link v-for="[k, name] in here[3]" :key="k" :to="`/settings/${group}/${k}`" :class="{ on: route.params.section === k }">{{ name }}</router-link>
    </nav>

    <!-- 总览：这些设置合起来是什么意思 -->
    <template v-if="group === 'overview'">
      <p v-if="pending" class="callout warn"><Icon name="alert" /><span>下面写的是已经保存的设置。你还有 {{ pending }} 项改动没保存，保存后这里才会变。</span></p>
      <div v-if="rules" class="cols">
        <div class="card">
          <div class="card-title">我会投什么</div>
          <p class="muted">从上到下是一个岗位要过的几关：先是硬条件（不符合的不入库），再按评分偏好打分，够分数线的 Agent 才去做申请。</p>
          <ul class="rule-list">
            <li v-for="(r, i) in rules.apply" :key="i">
              <span class="tag" :class="KIND_TONE[r.kind]">{{ r.label }}</span>
              <div class="grow"><router-link :to="r.where">{{ r.text }}</router-link><div v-if="r.note" class="small muted">{{ r.note }}</div></div>
            </li>
          </ul>
        </div>
        <div class="card">
          <div class="card-title">程序现在被允许做什么</div>
          <p class="muted">一份申请从发现到提交的每一步，现在由谁来做。<template v-if="rules.paused"><b>自动运行已暂停</b>：程序自己发起的事都停着。</template></p>
          <ul class="rule-list">
            <li v-for="st in rules.allowed" :key="st.key">
              <span class="tag" :class="WHO[st.who][1]">{{ WHO[st.who][0] }}</span>
              <div class="grow"><b>{{ st.name }}</b>：<router-link :to="st.where">{{ st.text }}</router-link>
                <ul v-if="st.more.length" class="small muted" style="margin: 4px 0 0 18px"><li v-for="(m, i) in st.more" :key="i">{{ m }}</li></ul></div>
            </li>
          </ul>
          <p class="hint" style="margin-top: 10px">具体到每一份申请，它的记录页上写着 Agent 做了什么、填了什么、批准之后由谁提交。</p>
        </div>
      </div>
    </template>

    <!-- 求职目标与匹配 -->
    <template v-if="group === 'goals'">
      <SetSection id="profile" title="求职档案" how="">
        <div class="card">
          <div class="row"><span class="card-title grow">你告诉过程序的</span><button class="sm" @click="rerun">重新规划（走一遍设置向导）</button></div>
          <p class="muted" style="margin: 4px 0 0">{{ persona.features.summary || '还没有填。程序现在按最初的默认方式工作，所有功能都显示。走一遍向导可以让它按你的专业和阶段来设置。' }}</p>
          <p class="hint" style="margin-top: 6px">档案决定界面显示哪些内容、求职信用什么口吻。重新走向导时，最后一步确认前不会改动你现在的设置。</p>
          <p class="small" style="margin: 10px 0 0">岗位怎么打分写在<router-link :to="{ path: '/profile', query: { tab: 'scoring' } }">个人资料 → 岗位评分规则</router-link>里；分数到多少才准备草案在<router-link to="/settings/automation/prepare">自动准备草案</router-link>里。</p>
        </div>
      </SetSection>

      <SetSection id="filters" title="入库前的硬条件">
        <div class="card">
          <div class="row"><span class="card-title grow">什么样的岗位才入库</span><label><input v-model="s['intake.enabled']" type="checkbox" /> 启用</label></div>
          <p class="muted">这是评分之前的一道筛子，不是偏好：招聘网站上的岗位绝大多数和你无关。每读到一个岗位，先按下面的条件看标题和地点，不符合的直接丢掉，不入库、不评分，也不占 AI 额度。留下来的再由 AI 读全文评分。UBC PD Portal 和你手动添加的岗位不受这些条件限制。</p>
          <div class="field"><label for="f-title-any">标题里要有这些词之一（岗位类型）</label>
            <input id="f-title-any" :value="csv('intake.title_any')" @change="setCsv('intake.title_any', $event.target.value)" />
            <span class="hint">用逗号分开。按整词匹配，会自动认复数：“intern” 能匹配 Interns、Internship，但不会匹配 Internal。留空表示不限制。</span></div>
          <div class="field"><label for="f-role-any">并且要有这些词之一（方向）</label>
            <textarea id="f-role-any" rows="3" style="font-family: inherit" :value="csv('intake.title_role_any')" @change="setCsv('intake.title_role_any', $event.target.value)"></textarea></div>
          <div class="field"><label for="f-title-none">标题里不能有这些词</label>
            <input id="f-title-none" :value="csv('intake.title_none')" @change="setCsv('intake.title_none', $event.target.value)" /></div>
          <div class="field"><label for="f-programs">你的专业（用于按专业筛选）</label>
            <input id="f-programs" :value="csv('intake.programs')" placeholder="例如：Computer" @change="setCsv('intake.programs', $event.target.value)" />
            <span class="hint">有些来源（学校的 co-op 平台）的岗位会写明面向哪些专业。面向的专业名里不含这里任何一个词的岗位会被直接标为不投，不交给 AI 评分；写明“所有专业均可”或没写专业的岗位不受影响。留空时取你的资料“Education”一节第一条里的专业。</span></div>
          <div class="kv">
            <label>工作地点在</label>
            <div class="row"><label v-for="[c, name] in COUNTRIES" :key="c"><input type="checkbox" :checked="(s['intake.countries'] || []).includes(c)" @change="toggleCountry(c)" /> {{ name }}</label>
              <span class="hint">都不勾表示不限地点。岗位没写地点时不会因此被丢掉。</span></div>
            <label for="f-age">只要最近多少天内发布的</label>
            <div><input id="f-age" v-model.number="s['intake.max_age_days']" type="number" style="width: 100px" /> 天 <span class="hint">填 0 表示不限。网站没写发布日期时不会因此被丢掉。</span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title">试一下</div>
          <p class="muted">每行写一个标题，可以在后面用竖线加地点。点“试一下”看按当前填写的条件（不用先保存）哪些会留下。</p>
          <textarea v-model="examples" rows="5" style="font-family: inherit" aria-label="用来试的岗位标题"></textarea>
          <div class="row" style="margin-top: 8px"><button @click="tryRules">试一下</button></div>
          <div v-if="tried.length" class="list" style="margin-top: 8px">
            <div v-for="(t, i) in tried" :key="i" class="item">
              <span class="badge" :class="t.kept ? 'ok' : ''" style="min-width: 56px; justify-content: center">{{ t.kept ? '留下' : '丢掉' }}</span>
              <div><div class="main">{{ t.title }}</div><div class="sub">{{ t.location }}</div></div>
              <span class="small muted">{{ t.why }}</span>
            </div>
          </div>
        </div>
      </SetSection>

      <SetSection id="search" title="在大型官网上搜什么">
        <div class="card">
          <div class="field" style="margin: 0"><label for="f-terms">搜索词</label>
            <input id="f-terms" :value="csv('sources.search_terms')" placeholder="例如：intern, co-op 或 analyst, graduate" @change="setCsv('sources.search_terms', $event.target.value)" />
            <span class="hint">Amazon、Microsoft 这类官网岗位成千上万，程序是用搜索框去搜的；每个词各搜一遍，词越多越慢。</span></div>
        </div>
      </SetSection>

      <SetSection id="sources" title="来源与关注公司" how="">
        <div class="card">
          <p class="muted" style="margin: 0">关注哪些公司、上次扫描读到了什么、学校门户的开关和登录，都在岗位页的<router-link to="/jobs/sources">来源与关注公司</router-link>里：那是平时要看的东西，不是设置。多久扫描一次在<router-link to="/settings/automation/schedule">工作计划</router-link>里。</p>
        </div>
      </SetSection>
    </template>

    <!-- 自动化与工作计划 -->
    <template v-if="group === 'automation'">
      <SetSection id="prepare" title="自动开始申请">
        <div class="card">
          <p class="muted" style="margin-top: 0">新岗位评完分，够分的 Agent 就自己去做申请。两条分数线放在一起比较：</p>
          <div class="kv" style="margin-top: 12px">
            <label for="f-min">一般岗位，评分达到多少分</label><div><input id="f-min" v-model.number="s['queue.min_score_for_draft']" type="number" step="0.5" style="width: 100px" /> <span class="hint">满分 10。</span></div>
            <label for="f-pmin">重点雇主的岗位，评分达到多少分</label><div><input id="f-pmin" v-model.number="s['employers.priority_min_score']" type="number" step="0.5" min="0" max="10" style="width: 100px" /> <span class="hint">哪些是重点雇主，在<router-link to="/jobs/sources">来源与关注公司</router-link>里标。</span></div>
            <label for="f-cap">最多同时有多少份申请等你</label><div><input id="f-cap" v-model.number="s['drafts.max_pending']" type="number" min="0" step="1" style="width: 100px" /> <span class="hint">正在做、或者等你回答和批准的申请到了这个数，程序就不再自己开始新的，等你处理掉一些再继续（先做评分最高的）。填 0 表示不限。你亲手点“申请”的不受这个限制。</span></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="submit" title="怎么提交">
        <div class="card">
          <div class="card-title">申请怎么提交</div>
          <p class="muted">每份申请由 Agent 在雇主的网站上一直做到最后一步。这里决定最后那一下“提交”怎么办。</p>
          <div class="kv">
            <label for="f-submit-policy">提交方式</label>
            <AaSelect id="f-submit-policy" v-model="s['submit.policy']">
              <option value="auto">没有未决问题就直接提交</option>
              <option value="approve">每份都先给我看，我批准后再提交</option>
              <option value="hand_over">做到最后一步，把窗口交给我自己点</option>
            </AaSelect>
            <label for="f-manual">这些公司始终由我自己点提交</label>
            <div><input id="f-manual" style="width: 100%" :value="(s['policy.manual_companies'] || []).join(', ')" placeholder="例如：Google, Apple（用逗号分开）" @change="s['policy.manual_companies'] = $event.target.value.split(/[,，]/).map((x) => x.trim()).filter(Boolean)" />
              <div class="hint">不管上面选的是什么，这些公司的申请 Agent 都做到最后一步停下，把窗口交给你。</div></div>
          </div>
          <p v-if="s['submit.policy'] === 'auto'" class="hint">资料里都有答案、Agent 也没有拿不准的地方时，它直接提交，然后把记录和确认页交给你。有问题要你回答，或者它拿不准时，它停在提交之前。</p>
          <p v-else-if="s['submit.policy'] === 'approve'" class="hint">Agent 做到提交之前停下，把它填的每一项和依据给你看。你批准之后，它回去核对一遍再提交。</p>
          <p v-else class="hint">Agent 被要求停在最后一步，把窗口交给你。这是给它的一条指令，不是一把锁：程序不靠识别按钮来拦它。</p>
          <p class="hint">表单怎么填（可选项填不填、隐私声明怎么处理、要不要订阅职位提醒）不是这里的开关：Agent 按你个人资料里写的规则做，没有写的按通常的做法。想改，就在个人资料里写一句。 <router-link to="/profile">打开个人资料</router-link></p>
        </div>
      </SetSection>

      <SetSection id="limits" title="Agent 怎么工作">
        <div class="card">
          <div class="card-title">一份申请最多做多少</div>
          <p class="muted">一份申请从岗位页到确认页，所有运行加在一起最多用多少步（每调用一次工具算一步）、最多用多久。用完了 Agent 会停下来，问你要不要再给一份。表单很长的网站可以调高。</p>
          <div class="kv">
            <label for="f-budget-steps">最多多少步</label>
            <div><input id="f-budget-steps" v-model.number="s['agent.budgets'].apply.steps" type="number" min="1" max="2000" style="width: 90px" /></div>
            <label for="f-budget-minutes">最多多少分钟</label>
            <div><input id="f-budget-minutes" v-model.number="s['agent.budgets'].apply.minutes" type="number" min="1" max="240" style="width: 90px" /></div>
          </div>
        </div>
        <div class="card">
          <div class="card-title">同时做几份、看不看得到</div>
          <div class="kv">
            <label for="f-parallel">同时做几份申请</label>
            <div><input id="f-parallel" v-model.number="s['agent.parallel']" type="number" min="1" max="6" style="width: 90px" />
              <div class="hint">每份申请各用各的浏览器，最多 6 份。同一个网站上的申请一次只做一份，因为那里的账号和登录只有一份。</div></div>
            <label for="f-mail-send">程序替你写的邮件</label>
            <div><AaSelect id="f-mail-send" v-model="s['mail.send']" style="max-width: 320px">
                <option value="review">我看一遍再发</option>
                <option value="auto">没有要我填的内容就直接发</option>
              </AaSelect>
              <div class="hint">指用邮件投递的申请，和回复雇主来信的邮件。都从你自己的邮箱发出，发出后收不回来。有需要你本人回答的内容时，不管选哪个都会先给你看。</div></div>
            <label for="f-show-window">Agent 工作时的浏览器窗口</label>
            <div><label><input id="f-show-window" v-model="s['agent.show_window']" type="checkbox" /> 显示在屏幕上</label>
              <div class="hint">打开后，Agent 做申请时浏览器窗口在屏幕上：你可以看着它做，也可以叫停之后自己接着操作。不需要看就关着，它在后台做。最后一步交给你自己点的申请，窗口总是会显示。</div></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="schedule" title="工作计划">
        <div class="card">
          <div class="kv">
            <label for="f-scan">扫描新岗位</label><div>每 <input id="f-scan" v-model.number="s['schedule.discover_minutes']" type="number" style="width: 90px" /> 分钟 <span class="hint">填 0 关闭</span></div>
            <label for="f-mail">检查邮箱</label><div>每 <input id="f-mail" v-model.number="s['schedule.mail_minutes']" type="number" style="width: 90px" /> 分钟 <span class="hint">填 0 关闭。读哪个邮箱在<router-link to="/settings/accounts/mailbox">收件邮箱</router-link>里。</span></div>
          </div>
          <p class="hint" style="margin-top: 12px"><b>暂停</b>在侧栏下方（“暂停自动运行”）。暂停只停程序自己发起的事：定时扫描、评分、自动准备草案、自动重试；你亲手点的照常执行，已经在做的那一件会做完。现在排着什么、能不能调顺序，在<router-link :to="{ path: '/runs', query: { tab: 'plan' } }">活动记录 → 工作计划</router-link>里。</p>
          <details class="tech" style="margin-top: 10px"><summary>用量与节奏（高级）</summary>
            <div class="kv" style="margin-top: 10px">
              <label for="f-batch">每次最多让 AI 评分多少个</label>
              <div><input id="f-batch" v-model.number="s['scoring.max_per_run']" type="number" style="width: 100px" /> 个 <span class="hint">超出的留到下一次扫描后再评，避免一次用掉太多额度。额度快用完时提醒不提醒、用到多少算“快用完”，在<router-link to="/settings/accounts/ai">AI 服务</router-link>的“额度提醒”里。</span></div>
            </div>
          </details>
        </div>
      </SetSection>
    </template>

    <!-- 材料与回答 -->
    <template v-if="group === 'materials'">
      <SetSection id="resume" title="简历">
        <div class="card">
          <div class="card-title">按岗位调整简历</div>
          <p class="muted">程序可以针对每个岗位，把你简历里最相关的经历排到前面。它只用你 Word 简历里已有的内容，不会写出简历里没有的东西。</p>
          <div v-if="s['tailor.mode'] !== 'off' && !hasWord" class="callout warn"><Icon name="alert" /><span>还没有 Word 版简历，调整做不了：每个岗位仍然会用你上传的原版。<router-link to="/files">到材料库上传一份</router-link>，用途选“简历 Word 原稿”。</span></div>
          <div class="choice">
            <label :class="{ on: s['tailor.mode'] === 'off' }"><input v-model="s['tailor.mode']" type="radio" value="off" /><div><b>不调整</b><span>所有岗位都用你上传的简历。</span></div></label>
            <label :class="{ on: s['tailor.mode'] === 'select' }"><input v-model="s['tailor.mode']" type="radio" value="select" /><div><b>只调顺序</b><span>调整要点、项目和技能的先后顺序，一个字都不改。最稳妥。</span></div></label>
            <label :class="{ on: s['tailor.mode'] === 'rephrase' }"><input v-model="s['tailor.mode']" type="radio" value="rephrase" /><div><b>调顺序，并允许改写措辞</b><span>可以把要点改成更贴近岗位说明的说法。事实、数字、技术名称必须和原文一致，程序会逐条核对，不一致的改写会被丢掉。</span></div></label>
          </div>
          <div v-if="s['tailor.mode'] !== 'off'" class="kv" style="margin-top: 16px">
            <label>什么时候调整</label>
            <AaSelect :model-value="s['tailor.auto'] ? 'auto' : 'ask'" @update:model-value="s['tailor.auto'] = $event === 'auto'"><option value="auto">生成草案时自动调整</option><option value="ask">只在我点“按这个岗位调整简历”时</option></AaSelect>
            <template v-if="s['tailor.auto']">
              <label for="f-tmin">评分达到多少分才调整</label>
              <div><input id="f-tmin" v-model.number="s['tailor.min_score']" type="number" step="0.5" min="0" max="10" style="width: 100px" /> <span class="hint">低于这个分数的岗位直接用原版简历，省时间也省 AI 额度。</span></div>
            </template>
            <label>可以调整哪些经历的先后</label>
            <AaSelect v-model="s['tailor.reorder_entries']"><option value="projects">只调项目，工作经历和教育保持时间顺序</option><option value="all">所有部分都可以调</option><option value="none">都不调，只调每段经历里要点的顺序</option></AaSelect>
            <label for="f-tskills">调整技能的先后</label>
            <div><input id="f-tskills" v-model="s['tailor.reorder_skills']" type="checkbox" /> <span class="hint">把岗位要求的技能排到每一行的前面，不增不减。</span></div>
            <label for="f-tdrop">可以去掉不相关的要点</label>
            <div><input id="f-tdrop" v-model="s['tailor.allow_drop']" type="checkbox" /> <span class="hint">适合内容比较多的简历。不勾选时所有要点都保留。</span></div>
            <label for="f-tbul">每段经历至少留几条要点</label>
            <div><input id="f-tbul" v-model.number="s['tailor.min_bullets']" type="number" min="1" max="10" style="width: 100px" /> 条</div>
            <label for="f-tpages">页数上限</label>
            <div><input id="f-tpages" v-model.number="s['tailor.target_pages']" type="number" min="0" max="5" style="width: 100px" /> 页 <span class="hint">填 0 表示和原版一样。如果你上传的是内容更全的多页“母版”简历，填 1，程序会按相关程度去掉排在最后的要点，直到剩一页。</span></div>
            <label for="f-trev">调整过的简历要我看过才能投</label>
            <div><input id="f-trev" v-model="s['tailor.review']" type="checkbox" /> <span class="hint">勾选后，用了刚改写的简历的申请不会直接提交，先等你批准。</span></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="cover" title="求职信">
        <div class="card">
          <p class="muted" style="margin-top: 0">求职信按你自己的 Word 模板来写：版式、抬头、落款都跟模板走。
            <template v-if="template">现在用的模板是「{{ template.name }}」，</template><template v-else>还没有上传模板，</template>在<router-link to="/files">材料库</router-link>里换（用途选“求职信模板”）。下面是模板里几样固定的写法，生成时照着做：</p>
          <div class="field"><label for="f-bold">这些名字第一次出现时加粗</label>
            <input id="f-bold" :value="csv('cover_letter.bold_terms')" placeholder="例如：项目名、雇主名（用逗号分开）" @change="setCsv('cover_letter.bold_terms', $event.target.value)" /></div>
          <div class="field"><label for="f-links">结尾段里要保留的链接</label>
            <textarea id="f-links" rows="2" style="font-family: inherit" :value="pairs('cover_letter.links', 'text', 'url')" placeholder="每行一个：显示的文字 | 链接，例如 careers@school.example | mailto:careers@school.example" @change="setPairs('cover_letter.links', 'text', 'url', $event.target.value)"></textarea></div>
          <div class="field" style="margin-bottom: 0"><label for="f-repl">模板里要改掉的固定文字</label>
            <textarea id="f-repl" rows="2" style="font-family: inherit" :value="pairs('cover_letter.replace', 'find', 'with')" placeholder="每行一个：原来的文字 | 改成的文字" @change="setPairs('cover_letter.replace', 'find', 'with', $event.target.value)"></textarea></div>
        </div>
      </SetSection>

    </template>

    <!-- 账号与连接 -->
    <template v-if="group === 'accounts'">
      <SetSection id="logins" title="招聘网站的登录">
        <div class="card">
          <p class="muted" style="margin-top: 0">网站需要账号时，Agent 用已经保存的账号登录；没有账号就用下面的邮箱注册一个，密码由程序生成、存在本机的系统凭据管理器里，Agent 自己看不到。验证码、手机上的二次验证、没有保存密码的账号，会请你来处理。 <router-link to="/accounts">查看每个网站的登录状态</router-link></p>
          <div class="kv">
            <label for="f-email">注册和登录用的邮箱</label><input id="f-email" v-model="s['account.email']" />
          </div>
          <p class="hint" style="margin-top: 12px">想让某个网站用 Google / LinkedIn 等第三方账号登录，或者不想让 Agent 自己注册账号，在个人资料里写一句就行，例如“不要替我注册新账号，需要账号时来问我”。 <router-link to="/profile">打开个人资料</router-link></p>
        </div>
      </SetSection>

      <SetSection id="mailbox" title="收件邮箱" how="own">
        <MailboxPanel />
        <p class="hint" style="margin: -6px 0 16px">多久检查一次邮箱，在<router-link to="/settings/automation/schedule">工作计划</router-link>里。</p>
      </SetSection>

      <SetSection id="ai" title="AI 服务" how="own">
        <p class="hint" style="margin: 0 0 10px">换了服务或模型之后，之后开始的任务用新的；正在进行的那一个任务用它开始时的，不会中途换。每家服务的地址、key 和模型用它下面的按钮保存，备用顺序用“保存备用顺序”；Claude 的模型、思考深度和长期令牌由右上角的“保存”保存。</p>
        <AiPanel :s="s" :sec="sec" :secrets="info.secrets" @changed="load" />
      </SetSection>
    </template>

    <!-- 通知与提醒 -->
    <template v-if="group === 'notify'">
      <SetSection id="channel" title="发到哪里">
        <div class="card">
          <div class="row"><span class="card-title grow">Telegram</span><span class="badge" :class="info.secrets.telegram_bot_token && s['notify.telegram_chat_id'] ? 'ok' : 'warn'">{{ info.secrets.telegram_bot_token && s['notify.telegram_chat_id'] ? '已接通' : '还没配置' }}</span></div>
          <p class="muted">进展、需要你处理的事和结果，都会发到你的 Telegram。不接也可以：所有通知在页面上都看得到（<router-link :to="{ path: '/runs', query: { tab: 'notes' } }">活动记录 → 发出的通知</router-link>）。</p>
          <div class="kv">
            <label for="f-tg">机器人令牌</label><input id="f-tg" v-model="sec.telegram_bot_token" type="password" autocomplete="off" :placeholder="info.secrets.telegram_bot_token ? '已保存；要更换时在这里填新的' : '从 @BotFather 创建机器人后得到'" />
            <label for="f-chat">聊天 ID</label><input id="f-chat" v-model="s['notify.telegram_chat_id']" placeholder="给机器人发一条消息后可以查到" />
            <label for="f-base">通知里的链接指向</label><div><input id="f-base" v-model="s['app.base_url']" style="width: 100%" /><div class="hint">手机上点通知里的链接时打开的地址。要从别的设备打开，这里得是那台设备够得着的地址（见<router-link to="/settings/system/remote">远程访问</router-link>）。</div></div>
          </div>
          <div class="row" style="margin-top: 12px"><button @click="tgTest"><Icon name="send" />发一条测试消息</button><span class="hint">先保存再测试。</span></div>
        </div>
      </SetSection>

      <SetSection id="events" title="通知什么、什么时候">
        <div class="card">
          <div class="kv">
            <label>发哪些通知</label>
            <div class="row" style="flex-wrap: wrap">
              <label><input v-model="s['notify.todo']" type="checkbox" /> 需要我处理的事</label>
              <label><input v-model="s['notify.task_result']" type="checkbox" /> 结果（投出、没成功）</label>
              <label><input v-model="s['notify.status_update']" type="checkbox" /> 申请进展</label>
              <label><input v-model="s['notify.task_started']" type="checkbox" /> 开始做某件事</label>
            </div>
            <label for="quiet-on">静默时段</label>
            <div v-if="s['notify.quiet']">
              <div class="row" style="flex-wrap: wrap">
                <label><input id="quiet-on" v-model="s['notify.quiet'].on" type="checkbox" /> 这段时间不往手机上发通知</label>
                <span>从 <input v-model="s['notify.quiet'].from" type="time" :disabled="!s['notify.quiet'].on" aria-label="静默开始时间" style="width: 110px" />
                  到 <input v-model="s['notify.quiet'].to" type="time" :disabled="!s['notify.quiet'].on" aria-label="静默结束时间" style="width: 110px" /></span>
              </div>
              <p class="hint" style="margin: 6px 0 0">这段时间里的通知不会丢：先记下来，时段结束时合成一条发给你，页面上随时能看到。程序自己发起的、需要你在手机上确认的登录（比如学校的 Duo）在这段时间不会开始，会留一条待办等你。只有一种通知不受影响：你亲手点开始的登录需要的手机确认。</p>
            </div>
          </div>
          <p class="hint" style="margin-top: 12px">面试和测评邀请不受开关影响，一定会发。待办卡上的“稍后提醒”和到期提醒在<router-link to="/todos">需要你处理</router-link>里逐条设。</p>
        </div>
      </SetSection>
    </template>

    <!-- 系统与数据 -->
    <template v-if="group === 'system'">
      <SetSection id="network" title="网络连接（出站）">
        <p class="hint" style="margin: 0 0 10px">程序去访问招聘网站、邮箱和 AI 服务时怎么走。别的设备怎么打开这个程序，是下面的“远程访问（入站）”。</p>
        <NetworkPanel ref="netPanel" :s="s" :sec="sec" :has-password="!!info.secrets.proxy_password" />
      </SetSection>
      <SetSection id="browser" title="浏览器兼容">
        <p class="hint" style="margin: 0 0 10px">默认用程序自带的浏览器。个别网站不对它显示内容时，对那个网站改用普通浏览器（nodriver）。和代理是两回事：打不开看上面，打开了但被挡住看这里。</p>
        <BrowserPanel :s="s" />
      </SetSection>
      <AccessPanel />
      <SetSection id="retention" title="数据保留">
        <div class="card">
          <p class="muted" style="margin-top: 0">这三项只决定岗位什么时候从日常列表里收起来、什么时候算同一个岗位。收起来只是归档：记录不删，申请的状态也不会因此改变。</p>
          <div class="kv">
            <label for="f-arch">岗位结束后多久归档</label>
            <div><input id="f-arch" v-model.number="s['archive.closed_after_days']" type="number" style="width: 100px" /> 天 <span class="hint">已下线、过了截止时间、标为不投或被拒的岗位。</span></div>
            <label for="f-silent">投出后多久没回音就归档</label>
            <div><input id="f-silent" v-model.number="s['archive.silent_after_days']" type="number" style="width: 100px" /> 天 <span class="hint">申请仍然记为“已提交”，之后收到回信照样会更新。</span></div>
            <label for="f-dedupe">相隔多久算新一轮招聘</label>
            <div><input id="f-dedupe" v-model.number="s['dedupe.window_days']" type="number" style="width: 100px" /> 天 <span class="hint">同一家公司同名的岗位，如果两次出现相隔超过这么久，就当成新的岗位，而不是和旧的合并。</span></div>
          </div>
        </div>
      </SetSection>
      <SetSection id="backup" title="备份与更新" how="">
        <div class="card">
          <p class="muted" style="margin-top: 0">你的数据都在这台电脑上：<code>{{ sys.data_dir }}</code> 和 <code>{{ sys.knowledge_dir }}</code>。升级程序不会动这两个文件夹。</p>
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
          <p class="small" style="margin: 10px 0 0">
            <template v-if="lastExport">{{ lastExportLine }} <a :href="'/api/system/export/' + lastExport.name">下载这一份</a></template>
            <template v-else>还没有导出过。数据只在这台电脑上：硬盘坏了或者换电脑之前，先导出一份放到别处。</template>
          </p>
          <div class="backup-notes">
            <div>
              <h4>导出里有什么</h4>
              <ul>
                <li>全部记录：岗位、申请、草案和答过的问题、邮件的归类、设置、运行历史。</li>
                <li>你上传的文件，和程序为各个岗位写的简历、求职信。</li>
                <li>个人资料、评分规则、各网站的笔记、你改过的提示词，以及程序学到的做法。</li>
                <li>选“连同登录状态一起导出”时，还有各网站保存的登录状态（加密的）。</li>
              </ul>
            </div>
            <div>
              <h4>导出里没有什么</h4>
              <ul>
                <li v-if="sys.secrets === 'file'">密码和 API key：它们在数据文件夹里单独加密的密码文件里，不进压缩包。</li>
                <li v-else>密码和 API key：它们在系统的密码库里（Windows 凭据管理器、macOS 钥匙串），不在数据文件夹里。</li>
                <li>历次运行的截图和页面记录：很大，也不需要带走。</li>
                <li>普通浏览器的用户资料文件夹：在普通浏览器里登录过的网站，登录是留在那里的。</li>
                <li>远程访问的设置和登录密码。</li>
              </ul>
            </div>
            <div>
              <h4>在这台电脑上恢复</h4>
              <ul>
                <li>先退出程序：到“工作计划”里点“做完手上的就停”，等它停下后退出。 <router-link :to="{ path: '/runs', query: { tab: 'plan' } }">打开工作计划</router-link></li>
                <li>在程序文件夹里运行下面这条命令；原来的数据会另存一份，不会丢。<div><code>uv run autoapply restore 导出文件.zip</code></div></li>
                <li>密码和 API key 还在原处，恢复后照常能用；导出时带了登录状态的，登录也一起回来。</li>
              </ul>
            </div>
            <div>
              <h4>搬到另一台电脑</h4>
              <ul>
                <li>在新电脑上装好程序，用同样的命令恢复：记录、文件、资料和规则都跟过去。</li>
                <li>密码和 API key 不会跟过去：在新电脑上重新填（设置里的“账号与连接”；各网站的密码在“网站账号”里）。</li>
                <li>登录状态不会跟过去：它是用这台电脑上的密钥加密的，换了电脑打不开。要么在新电脑上重新登录，要么在“网站账号”的“高级”里把某个登录单独导出（设一个口令），到新电脑上导入。 <router-link to="/accounts">打开网站账号</router-link></li>
              </ul>
            </div>
          </div>
          <p class="hint" style="margin: 10px 0 0">更新程序也是先“做完手上的就停”再退出，覆盖程序文件后重新启动；数据文件夹不受影响。</p>
        </div>
      </SetSection>
      <SetSection id="diagnose" title="诊断" how="">
        <DoctorPanel />
      </SetSection>
      <SetSection id="expert" title="专家工具" how="own">
        <p class="hint" style="margin: 0 0 10px">平时用不到。想让程序换一种口吻、偏好或答法，改<router-link to="/profile">个人资料</router-link>和评分规则就够了，不需要改这里的提示词。</p>
        <PromptsPanel />
      </SetSection>
    </template>
  </div>
</template>
