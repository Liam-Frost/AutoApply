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
import { useRoute, useRouter } from 'vue-router'
import { persona, run as runAction, toast } from '../ui'
import { absorb, changed, clone, unsaved, useUnsaved } from '../dirty'

const s = ref(null)
const info = ref({ secrets: {}, gmail: {}, drivers: [] })
const sec = ref({ anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' })
const netPanel = ref(null)
const route = useRoute()
const router = useRouter()
const rerun = async () => { await api.post('/persona/restart'); persona.done = false; router.push('/welcome') }
const SYSTEMS = [
  ['greenhouse', 'Greenhouse'], ['ashby', 'Ashby'], ['workday', 'Workday'], ['pdportal', 'UBC PD Portal'], ['generic', '其他网站'],
]
const sys = ref({})
const exported = ref(null)
const upd = ref(null)
const docs = ref([])
api.get('/system').then((d) => (sys.value = d)).catch(() => {})
api.get('/documents').then((d) => (docs.value = d)).catch(() => {})
const exportData = async (sessions) => {
  try { exported.value = await api.post('/system/export', { sessions }) } catch (e) { toast(e.message, 'bad') }
}
const checkUpdate = async () => {
  try { upd.value = await api.get('/system/update') } catch (e) { toast(e.message, 'bad') }
}

// --- where everything is ---------------------------------------------------------------------------------------------
// [group, its name, what it is for, [[section, its name], ...]]. The sections of a group are on one page, in this order.
const GROUPS = [
  ['overview', '总览', '这些设置合起来是什么意思：你会投什么，程序现在自己能做到哪一步。只读；每一条都能点到改它的地方。', []],
  ['goals', '求职目标与匹配', '想找什么样的岗位：哪些根本不看，哪些优先。', [['profile', '求职档案'], ['filters', '入库前的硬条件'], ['search', '在大型官网上搜什么'], ['sources', '来源与关注公司']]],
  ['automation', '自动化与工作计划', '程序自己能做到哪一步，什么时候做。', [['prepare', '自动准备草案'], ['submit', '审批与提交'], ['permissions', '操作权限'], ['adaptive', '出问题时自己调整'], ['schedule', '工作计划']]],
  ['materials', '材料与回答', '简历怎么调、求职信怎么写、答过的问题怎么再用。', [['resume', '简历'], ['cover', '求职信'], ['answers', '回答的复用']]],
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
  saving.value = true
  try {
    const st = {}
    for (const k of keys) st[k] = s.value[k]       // what was changed, and only that: a setting another part saved meanwhile is not sent back as it was
    const secrets = {}
    for (const k in sec.value) if (sec.value[k]) secrets[k] = sec.value[k]
    await api.put('/settings', { settings: st, secrets })
    for (const k of keys) saved.value[k] = clone(s.value[k])
    sec.value = { anthropic_api_key: '', telegram_bot_token: '', claude_oauth_token: '', proxy_password: '' }
    toast(`已保存 ${n} 项改动`)
    await load()
    if (group.value === 'overview') loadRules()
    if (netPanel.value) netPanel.value.load()
    return true
  } catch (e) { toast(e.message, 'bad'); return false } finally { saving.value = false }
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
// (a table of the systems that are ticked: unticking takes the system out, as it is when it was never ticked - so that
// ticking and unticking leaves nothing to save)
function toggle(key, sys) { const p = { ...s.value[key] }; if (p[sys]) delete p[sys]; else p[sys] = true; s.value[key] = p }
function setRegister(sys, on) { const p = { ...s.value['register.per_ats'] }; if (on) delete p[sys]; else p[sys] = false; s.value['register.per_ats'] = p }
function setPolicy(sys, v) { const p = { ...s.value['policy.per_ats'] }; if (v) p[sys] = v; else delete p[sys]; s.value['policy.per_ats'] = p }

// --- what the rules on the page come to (as they stand on the page, saved or not) ----------------------------------------
const sysName = (k) => (SYSTEMS.find((x) => x[0] === k) || [k, k])[1]
const submitNow = computed(() => {
  const st = s.value
  const out = []
  const auto = st['policy.default'] !== 'manual'
  out.push(auto ? '你批准之后，程序填好、核对无误就自己提交。' : '你批准之后，程序填好就停下，由你检查后点提交。')
  const other = Object.entries(st['policy.per_ats'] || {}).filter(([, v]) => v && v !== st['policy.default'])
  for (const [k, v] of other) out.push(v === 'manual' ? `${sysName(k)}：由你点提交。` : `${sysName(k)}：程序自己提交。`)
  if ((st['policy.manual_companies'] || []).length) out.push(`这些公司始终由你点提交：${st['policy.manual_companies'].join('、')}。`)
  if (st['policy.manual_confidence'] === 'low') out.push('草案里有“把握低”的答案时，由你点提交。')
  if (st['policy.manual_confidence'] === 'medium') out.push('草案里有“把握中等”或“把握低”的答案时，由你点提交。')
  const systems = SYSTEMS.filter(([k]) => (st['auto_approve.per_ats'] || {})[k]).map(([, n]) => n)
  out.push(!st['auto_approve.enabled'] ? '每份草案都要你批准。'
    : systems.length ? `同时满足下面条件的草案不用你批准（只限这些招聘系统：${systems.join('、')}）；其余的都要你批准。` : '自动批准已打开，但没有一个招聘系统被允许，所以每份草案仍然要你批准。')
  return out
})
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
      <button class="primary" :disabled="!pending || saving" @click="save"><Icon name="check" />{{ pending ? '保存' : '已保存' }}</button>
    </PageHead>
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
          <p class="muted">从上到下是一个岗位要过的几关：先是硬条件（不符合的不入库），再按评分偏好打分，够分数线的才准备草案。</p>
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
          <p class="hint" style="margin-top: 10px">具体到每一份草案，草案页上写着它由谁提交、为什么，每条原因都能点到决定它的设置。</p>
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
      <SetSection id="prepare" title="自动准备草案">
        <div class="card">
          <p class="muted" style="margin-top: 0">新岗位评完分，够分的就自动准备草案给你看。两条分数线放在一起比较：</p>
          <div class="kv" style="margin-top: 12px">
            <label for="f-min">一般岗位，评分达到多少分</label><div><input id="f-min" v-model.number="s['queue.min_score_for_draft']" type="number" step="0.5" style="width: 100px" /> <span class="hint">满分 10。</span></div>
            <label for="f-pmin">重点雇主的岗位，评分达到多少分</label><div><input id="f-pmin" v-model.number="s['employers.priority_min_score']" type="number" step="0.5" min="0" max="10" style="width: 100px" /> <span class="hint">哪些是重点雇主，在<router-link to="/jobs/sources">来源与关注公司</router-link>里标。</span></div>
            <label for="f-cap">最多同时有多少份草案等你</label><div><input id="f-cap" v-model.number="s['drafts.max_pending']" type="number" min="0" step="1" style="width: 100px" /> <span class="hint">正在生成或等你审批的草案到了这个数，程序就不再自己开始新的，等你处理掉一些再继续（先做评分最高的）；填 0 不限制。你亲手点“生成草案”的不受限制。</span></div>
          </div>
        </div>
      </SetSection>

      <SetSection id="submit" title="审批与提交">
        <div class="card">
          <div class="card-title">草案批准之后</div>
          <p class="muted">每个申请都会先生成草案给你看。这里决定你批准之后，最后那一下“提交”由谁来点。</p>
          <div class="kv">
            <label>默认</label>
            <AaSelect v-model="s['policy.default']"><option value="approve_then_submit">程序填好、核对无误后自动提交</option><option value="manual">程序填好后停下，我检查后自己点提交</option></AaSelect>
            <label for="f-manual">这些公司始终由我提交</label>
            <div><input id="f-manual" style="width: 100%" :value="(s['policy.manual_companies'] || []).join(', ')" placeholder="例如：Google, Apple（用逗号分开）" @change="s['policy.manual_companies'] = $event.target.value.split(/[,，]/).map((x) => x.trim()).filter(Boolean)" /></div>
            <label>答案没把握时由我提交</label>
            <AaSelect v-model="s['policy.manual_confidence']"><option value="none">不因此停下</option><option value="low">草案里有“把握低”的答案时</option><option value="medium">有“把握中等”或“把握低”的答案时</option></AaSelect>
          </div>
          <table style="margin-top: 14px">
            <thead><tr><th>招聘系统</th><th>批准之后</th></tr></thead>
            <tbody>
              <tr v-for="[k, name] in SYSTEMS" :key="k">
                <td><b>{{ name }}</b></td>
                <td><AaSelect :value="s['policy.per_ats'][k] || ''" :aria-label="name" @change="setPolicy(k, $event.target.value)"><option value="">跟默认一样</option><option value="approve_then_submit">自动提交</option><option value="manual">我自己点提交</option></AaSelect></td>
              </tr>
            </tbody>
          </table>
          <div class="callout" style="margin-top: 14px; display: block">
            <b>按现在页面上的选择，结果是：</b>
            <ul style="margin: 6px 0 0 18px"><li v-for="(line, i) in submitNow" :key="i">{{ line }}</li></ul>
            <div class="small muted" style="margin-top: 6px">各条之间的关系：公司的例外和“答案没把握”只会让一次申请改由你提交，不会反过来；招聘系统的选择盖过默认。不管怎么选，遇到这两种情况也会停下由你提交：有程序核对不了、由 AI 选定的填写项；表单在填完后仍然报告需要你处理的问题。具体到每份草案，草案页上会写明它由谁提交、为什么。</div>
          </div>
        </div>
        <details class="card" :open="s['auto_approve.enabled'] || route.params.section === 'submit-auto'">
          <summary><b>符合条件时自动批准</b> <span class="muted small">（{{ s['auto_approve.enabled'] ? '已打开' : '没有打开：每份草案都要你批准' }}）</span></summary>
          <p class="muted" style="margin-top: 10px">默认每份草案都要你批准。打开后，同时满足下面所有条件的草案不用你看，直接填写提交。建议用熟了再开。</p>
          <div class="kv">
            <label for="f-aa">开启自动批准</label><div><input id="f-aa" v-model="s['auto_approve.enabled']" type="checkbox" /></div>
            <label for="f-aa-min">岗位评分至少</label><input id="f-aa-min" v-model.number="s['auto_approve.min_score']" type="number" step="0.5" style="width: 100px" />
            <label for="f-aa-n">这个招聘系统已连续成功提交</label><div><input id="f-aa-n" v-model.number="s['auto_approve.min_driver_successes']" type="number" style="width: 100px" /> 次以上</div>
            <label for="f-aa-cl">新写的求职信也不用我看</label><div><input id="f-aa-cl" v-model="s['auto_approve.allow_new_cover_letter']" type="checkbox" /></div>
            <label>允许自动批准的招聘系统</label>
            <div class="row" style="flex-wrap: wrap"><label v-for="[k, name] in SYSTEMS" :key="k"><input type="checkbox" :checked="!!s['auto_approve.per_ats'][k]" @change="toggle('auto_approve.per_ats', k)" /> {{ name }}</label></div>
          </div>
          <p class="hint" style="margin-top: 12px">还必须同时满足：没有答不上的问题；所有答案都来自你确认过的资料，把握高；没有第一次遇到的敏感问题；网站已登录；草案里没有需要留意的备注。</p>
        </details>
      </SetSection>

      <SetSection id="permissions" title="操作权限">
        <div class="card">
          <div class="kv">
            <label for="f-consent">遇到挡住表单的“数据隐私声明”</label>
            <div><input id="f-consent" v-model="s['consent.acknowledge_notices']" type="checkbox" /> <span class="hint">自动点“I understand / Accept”后继续。这说的是打开申请表之前弹出来、只是告知你的声明，它是申请的前提条件。申请表里面要你勾选的同意项（“我同意保留我的资料”等）不在此列：那些是表单的问题，照草案里你批准的答案填。不勾的话，遇到声明就停下来等你。</span></div>
            <label for="f-optional">非必填项也填上</label><div><input id="f-optional" v-model="s['fill.optional']" type="checkbox" /> <span class="hint">表单上不带星号的问题和整段可选内容（工作经历、教育经历、语言、链接等），只要你的资料或简历里有，就填上。关掉后只填必填项。</span></div>
            <label for="f-walk">审批前先把分步表单读完</label><div><input id="f-walk" v-model="s['recon.walk']" type="checkbox" /> <span class="hint">有些表单要填完前一步才打得开后一步。打开后，程序会带着草案的答案在隐藏窗口里一步步填到确认页，把后面问到的问题加进草案，不会提交；填进去的内容雇主网站可能会存成未完成的申请。</span></div>
          </div>
          <p class="hint" style="margin-top: 12px">程序能不能自己注册账号，在<router-link to="/settings/accounts/logins">招聘网站的登录</router-link>里。</p>
        </div>
      </SetSection>

      <SetSection id="adaptive" title="出问题时自己调整">
        <div class="card">
          <div class="kv">
            <label for="f-repair">填写出错时让 AI 接手</label><div><input id="f-repair" v-model="s['repair.enabled']" type="checkbox" /> <span class="hint">AI 只能把你批准过的内容填进去，不能编新答案，也不能点提交；表单限制字数或格式时，它会把批准过的答案改写到符合要求，提交前给你看改写前后的内容。</span></div>
            <label for="f-learn">让程序从运行里学习</label><div><input id="f-learn" v-model="s['learned.enabled']" type="checkbox" /> <span class="hint">一次运行里有明显偏离平时的地方（某一步特别慢、AI 反复接手）时，让 AI 写下下次在这个网站上该怎么做。</span></div>
            <label>学到之后</label><AaSelect v-model="s['learned.mode']"><option value="auto">通过检查就自动试用</option><option value="ask">先问我</option></AaSelect>
            <label>为新网站写的驱动稳定之后</label><AaSelect v-model="s['learned.share']"><option value="ask">问我要不要分享给项目</option><option value="always">直接准备好 issue</option><option value="never">不分享</option></AaSelect>
          </div>
          <p class="hint" style="margin-top: 12px">学到了什么、效果怎样，在<router-link :to="{ path: '/analytics', query: { view: 'time' } }">数据分析 → 耗时与优化</router-link>里看；每一项都可以在那里撤回。</p>
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
          <details class="tech" style="margin-top: 6px"><summary>维护</summary>
            <div class="kv" style="margin-top: 10px">
              <label for="f-canary">自检间隔</label><div>每 <input id="f-canary" v-model.number="s['schedule.canary_minutes']" type="number" style="width: 90px" /> 分钟 <span class="hint">定期检查各招聘系统的适配是否还正常，填 0 关闭</span></div>
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
            <div><input id="f-trev" v-model="s['tailor.review']" type="checkbox" /> <span class="hint">勾选后，用了新调整简历的草案不会自动通过，一定等你批准。</span></div>
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

      <SetSection id="answers" title="回答的复用" how="">
        <div class="card">
          <p class="muted" style="margin: 0">你在草案里确认过的答案会被记住，下次遇到同样的问题直接用。通用的事实（工作许可、毕业时间、你的链接）到处都用；只对某个雇主有意义的答案（“为什么想来我们公司”、是否认识这里的员工、是否在这里工作过）只在那个雇主的网站上再用，不会带到别家。每个答案在草案里都写着它是从哪里来的；要改一条长期的答法，在草案里改答案时勾“以后都这样答”，它会进<router-link to="/profile">个人资料</router-link>的“Standard answers”。</p>
        </div>
      </SetSection>
    </template>

    <!-- 账号与连接 -->
    <template v-if="group === 'accounts'">
      <SetSection id="logins" title="招聘网站的登录">
        <div class="card">
          <p class="muted" style="margin-top: 0">需要登录的招聘网站：你以前投过的公司，会请你登录一次并记住；没投过的，由程序自己注册账号（密码存在本机的系统凭据管理器里）。每个网站现在的登录状态在<router-link to="/accounts">网站账号</router-link>里。</p>
          <div class="kv">
            <label for="f-reg">允许程序自己注册账号</label><div><input id="f-reg" v-model="s['register.auto']" type="checkbox" /></div>
            <label>这些招聘系统上允许自己注册</label>
            <div class="row" style="flex-wrap: wrap"><label v-for="[k, name] in SYSTEMS" :key="k"><input type="checkbox" :disabled="!s['register.auto']" :checked="s['register.per_ats'][k] !== false" @change="setRegister(k, $event.target.checked)" /> {{ name }}</label></div>
            <label for="f-email">注册和登录用的邮箱</label><input id="f-email" v-model="s['account.email']" />
            <label>网站支持“用第三方账号登录”时</label>
            <div><AaSelect v-model="s['sso.mode']"><option value="ask">每个网站第一次先问我用哪种方式</option><option value="auto">直接用我已登录的第三方账号</option><option value="never">不用第三方账号，用邮箱注册</option></AaSelect>
              <div class="hint">指 Google / LinkedIn / Microsoft / Apple 等，需要先在<router-link to="/accounts">网站账号</router-link>里登录。用第三方账号登录时，对方会把你的姓名和邮箱提供给招聘网站；好处是不用多一个密码，也不用收验证邮件。网站上已经有账号的，始终用原来的账号。</div></div>
            <label for="f-sso">第三方账号的优先顺序</label>
            <div><input id="f-sso" :value="(s['sso.order'] || []).join(', ')" style="width: 260px" @change="s['sso.order'] = $event.target.value.split(/[,，\s]+/).map((x) => x.trim().toLowerCase()).filter(Boolean)" />
              <span class="hint"> 一个网站同时支持几种时，用排在前面的。</span></div>
          </div>
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
          <ul class="hint" style="margin: 10px 0 0 18px; line-height: 1.8">
            <li><b>导出</b>随时可以做，不用停任务。压缩包里有数据库、你上传和程序生成的文件、个人资料和规则；不含历次运行的截图，不含密码和 API key（它们在系统的密码库里）。登录状态是加密保存的，只能在这台电脑上用。</li>
            <li><b>恢复</b>要先退出程序：在<router-link :to="{ path: '/runs', query: { tab: 'plan' } }">工作计划</router-link>里点“做完手上的就停”，等它停下后退出，然后在程序文件夹里运行 <code>uv run autoapply restore 导出文件.zip</code>，原来的数据会另存一份。</li>
            <li><b>更新</b>同样先“做完手上的就停”再退出，覆盖程序文件后重新启动。</li>
          </ul>
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
