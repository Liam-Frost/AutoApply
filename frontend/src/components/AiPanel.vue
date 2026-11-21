<script setup>
// Which AI service does the work. Each service keeps its own settings; "用这个" switches to it.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { run, toast } from '../ui'
import { clockOf, shortDayOf } from '../i18n/format'
import { mayLeave, same, useUnsaved } from '../dirty'
import Icon from './Icon.vue'
import ModelPick from './ModelPick.vue'
import TechDetails from './TechDetails.vue'

const props = defineProps({ s: { type: Object, required: true }, sec: { type: Object, required: true }, secrets: { type: Object, default: () => ({}) } })
const emit = defineEmits(['changed'])
const d = ref(null)
const pick = ref('')
const form = ref({ base_url: '', model: '', small_model: '', effort: '', api_key: '' })
const models = ref([])
const claude = ref(null)
const busy = ref(false)
const loadingModels = ref(false)
const modelNote = ref('')

const cur = computed(() => d.value && d.value.providers.find((p) => p.key === pick.value))
const inUse = computed(() => d.value && d.value.current === pick.value)
const GROUPS = [['用订阅登录（不按量付费）', ['claude_subscription', 'chatgpt']], ['用 API key（按用量付费）', ['anthropic', 'openai', 'gemini', 'deepseek', 'qwen', 'openrouter']], ['其他', ['custom']]]
const byKey = (k) => d.value.providers.find((p) => p.key === k)

function fill() {
  const p = cur.value
  form.value = { base_url: p.base_url || '', model: p.model || '', small_model: p.small_model || '', effort: p.effort || '', api_key: '' }
  models.value = []
}
async function load(keep) {
  d.value = await api.get('/llm/providers')
  pick.value = keep || pick.value || d.value.current
  fill()
  autoModels()
  api.get('/settings/claude-status').then((c) => (claude.value = c)).catch(() => {})
}
// (switching the service that is being set up is leaving what was typed for the other one)
async function choose(k) { if (k === pick.value || !(await mayLeave(['ai-provider']))) return; pick.value = k; fill(); autoModels() }
const formDirty = computed(() => {
  const p = cur.value
  return !!p && (!!form.value.api_key || form.value.base_url !== (p.base_url || '') || form.value.model !== (p.model || '') || form.value.small_model !== (p.small_model || '') || form.value.effort !== (p.effort || ''))
})
let keyTimer
function keyTyped() { clearTimeout(keyTimer); keyTimer = setTimeout(autoModels, 700) }
async function autoModels() {
  const p = cur.value
  if (!p) return
  const can = p.key === 'claude_subscription' || p.key === 'anthropic' || (p.kind === 'codex' ? p.installed && p.logged_in : p.has_key || form.value.api_key || p.key === 'custom')
  models.value = []; modelNote.value = ''
  if (!can || (p.key === 'custom' && !form.value.base_url)) return
  loadingModels.value = true
  const asked = p.key
  try {
    const r = await api.post(`/llm/providers/${p.key}/models`, { base_url: form.value.base_url, api_key: form.value.api_key })
    if (pick.value === asked) models.value = r.models
  } catch (e) { if (pick.value === asked) modelNote.value = e.message }
  loadingModels.value = false
}
async function save(use) {
  busy.value = true
  try {
    await api.put('/llm/providers/' + pick.value, { ...form.value, use })
    toast(use ? `已切换到 ${cur.value.name}` : '已保存')
    await load(pick.value)
    emit('changed')
    busy.value = false
    return true
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
  return false
}
useUnsaved({ id: 'ai-provider', get label() { return cur.value ? `AI 服务“${cur.value.name.split('（')[0]}”` : 'AI 服务' }, dirty: () => formDirty.value, save: () => save(false), discard: fill })
async function listModels() {
  busy.value = true
  try {
    models.value = (await api.post(`/llm/providers/${pick.value}/models`, { base_url: form.value.base_url, api_key: form.value.api_key })).models
    toast(models.value.length ? `找到 ${models.value.length} 个模型，在下面选` : '这个服务没有返回模型列表，请手动填写')
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
}
const chatgptLogin = () => run(() => api.post('/llm/chatgpt/login'), '已在浏览器里打开 ChatGPT 登录页', poll)
const chatgptLogout = () => run(() => api.post('/llm/chatgpt/logout'), '已退出 ChatGPT 登录', () => load(pick.value))
let pollTimer
function poll() {
  clearInterval(pollTimer)
  let n = 0
  pollTimer = setInterval(async () => {
    d.value = await api.get('/llm/providers')
    const c = d.value.providers.find((p) => p.key === 'chatgpt')
    if (++n > 100 || !c || !c.login || c.login.state !== 'waiting') clearInterval(pollTimer)
  }, 3000)
}
const test = () => run(() => api.post('/settings/llm-test'), (r) => `能用。模型回复：${r.reply}`)

// --- backups: tried in this order when the service in use runs out or cannot be reached ---
const fo = ref({ chain: [], saved: [] })
const backups = ref([])          // editable copy of the saved list
const foModels = ref({})         // provider -> model names, read once per provider
const foTest = ref({})           // row index -> result of the test button
const foBusy = ref(false)
const usable = (p) => p.key === 'claude_subscription' || (p.kind === 'codex' ? p.installed && p.logged_in : p.kind === 'anthropic' ? p.has_key : (p.has_key || p.key === 'custom') && !!p.model)
const candidates = computed(() => (d.value ? d.value.providers : []))
const stateOf = (b) => fo.value.chain.find((c) => c.provider === b.provider && (c.set_model || '') === (b.model || ''))
async function loadFo() {
  fo.value = await api.get('/llm/failover')
  backups.value = fo.value.saved.map((e) => ({ ...e }))
  backups.value.forEach((b) => modelsFor(b.provider))
}
async function modelsFor(k) {
  if (!k || foModels.value[k]) return
  foModels.value = { ...foModels.value, [k]: [] }
  try { foModels.value = { ...foModels.value, [k]: (await api.post(`/llm/providers/${k}/models`, {})).models } } catch (e) { /* the list stays empty: the name can be typed */ }
}
function addBackup() {
  const used = new Set([d.value.current, ...backups.value.map((b) => b.provider)])
  const first = candidates.value.find((p) => usable(p) && !used.has(p.key)) || candidates.value.find((p) => !used.has(p.key)) || candidates.value[0]
  backups.value.push({ provider: first.key, model: '', small_model: '' })
  modelsFor(first.key)
}
const moveBackup = (i, by) => { const a = backups.value; const j = i + by; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; foTest.value = {} }
async function saveFo() {
  foBusy.value = true
  let ok = true
  try { fo.value = await api.put('/llm/failover', { entries: backups.value }); backups.value = fo.value.saved.map((e) => ({ ...e })); toast('备用顺序已保存'); loadQuota(false) } catch (e) { toast(e.message, 'bad'); ok = false }
  foBusy.value = false
  return ok
}
const foDirty = computed(() => !same(backups.value, fo.value.saved))
useUnsaved({ id: 'ai-backups', label: '备用服务', dirty: () => foDirty.value, save: saveFo, discard: () => { backups.value = fo.value.saved.map((e) => ({ ...e })); foTest.value = {} } })
async function testBackup(i) {
  foTest.value = { ...foTest.value, [i]: { busy: true } }
  try { foTest.value = { ...foTest.value, [i]: await api.post('/llm/failover/test', backups.value[i]) } } catch (e) { foTest.value = { ...foTest.value, [i]: { error: e.message } } }
}
const resetFo = () => run(() => api.post('/llm/failover/reset'), '已清除，下一次调用会重新从主用服务试起', loadFo)
const hhmm = (iso) => (iso ? clockOf(new Date(iso)) : '')      // (a local time without a zone)

// --- allowance of each service in the chain, where the service reports one ---
const quota = ref({ services: [], warn_percent: 80, warn_balance: 1, notify: true })
const quotaBusy = ref(false)
const quotaOf = (provider) => quota.value.services.find((x) => x.provider === provider)
async function loadQuota(refresh) {
  quotaBusy.value = true
  try { quota.value = await api.get('/llm/quota' + (refresh ? '?refresh=true' : '')) } catch (e) { if (refresh) toast(e.message, 'bad') }
  quotaBusy.value = false
}
const saveQuota = () => run(() => api.put('/llm/quota', { warn_percent: quota.value.warn_percent, warn_balance: quota.value.warn_balance, notify: quota.value.notify }), '已保存', (r) => (quota.value = r))
const winTone = (w) => (w.blocked || w.used >= 100 ? 'out' : w.used >= quota.value.warn_percent ? 'low' : '')
const resetAt = (ts) => {      // "01:36" today, "11/18 22:36" on another day: figures only, the words around them are in the template
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toDateString() === new Date().toDateString() ? clockOf(d) : `${shortDayOf(d)} ${clockOf(d)}`
}
onMounted(async () => { await load(); await loadFo(); loadQuota(false) })
</script>

<template>
  <div v-if="d" class="pr">
    <div class="card pr-nav">
      <template v-for="[g, keys] in GROUPS" :key="g">
        <div class="pr-group">{{ g }}</div>
        <button v-for="k in keys" :key="k" :class="{ on: pick === k }" @click="choose(k)">
          <span class="ell">{{ byKey(k).name.split('（')[0] }}</span>
          <span v-if="d.current === k" class="badge ok">在用</span>
        </button>
      </template>
    </div>

    <div class="card">
      <div class="row">
        <span class="card-title grow">{{ cur.name }}</span>
        <span v-if="formDirty" class="badge warn">有改动还没保存</span>
        <span v-if="inUse" class="badge ok">正在使用</span>
      </div>

      <!-- Claude subscription -->
      <template v-if="cur.key === 'claude_subscription'">
        <p class="muted">用你自己的 Claude 订阅，和平时用 Claude 共用额度；额度用完时任务会等额度恢复后自动继续。功能最完整，也是这个程序测试得最充分的方式。</p>
        <div v-if="claude" class="callout" :class="claude.logged_in ? '' : 'warn'"><Icon :name="claude.logged_in ? 'check' : 'alert'" />
          <div v-if="claude.logged_in">已登录{{ claude.plan ? '（' + claude.plan + '）' : '' }}
            <div v-if="claude.plan" class="small muted">套餐名是登录那一刻记下的。换了套餐后，在终端运行一次 <code>uv run autoapply claude-login</code> 重新登录，这里才会更新；额度本身不受这个显示影响。</div></div>
          <div v-else>还没有登录。在终端运行 <code>uv run autoapply claude-login</code>，在浏览器里登录后回到这里刷新。</div></div>
        <div class="kv" style="margin-top: 14px">
          <label>主要模型</label><div><ModelPick v-model="props.s['llm.model']" :models="models" :loading="loadingModels" /><div class="hint">做申请的 Agent 用的就是这个模型和下面的思考深度。它要能调用工具、能看网页截图；做不到这两样的模型做不了申请。</div></div>
          <label>简单任务用的模型</label><div><ModelPick v-model="props.s['llm.small_model']" :models="models" :loading="loadingModels" /><div class="hint">给邮件分类、读验证码这类小事用，省额度。</div></div>
          <label>思考深度</label><AaSelect v-model="props.s['llm.effort']"><option value="low">低（快）</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">最高（慢）</option></AaSelect>
          <label>长期令牌（可选）</label><div><input v-model="props.sec.claude_oauth_token" type="password" autocomplete="off" style="width: 100%" :placeholder="props.secrets.claude_oauth_token ? '已保存；要更换时在这里填新的' : '登录会过期；想长期无人值守时填 claude setup-token 生成的令牌'" /></div>
        </div>
        <p class="hint" style="margin-top: 10px">模型和令牌改完点右上角“保存”。</p>
      </template>

      <!-- Anthropic API -->
      <template v-else-if="cur.key === 'anthropic'">
        <p class="muted">用 Anthropic 的 API key，按用量付费。<a :href="cur.keys" target="_blank" rel="noopener">在这里申请 key ↗</a></p>
        <div class="kv" style="margin-top: 14px">
          <label>API key</label><input v-model="form.api_key" type="password" autocomplete="off" :placeholder="cur.has_key ? '已保存；要更换时在这里填新的' : '还没有保存'" @input="keyTyped" />
          <label>主要模型</label><div><ModelPick v-model="props.s['llm.model']" :models="models" :loading="loadingModels" /><div class="hint">做申请的 Agent 用的就是这个模型和下面的思考深度。它要能调用工具、能看网页截图；做不到这两样的模型做不了申请。</div></div>
          <label>简单任务用的模型</label><ModelPick v-model="props.s['llm.small_model']" :models="models" :loading="loadingModels" />
          <label>思考深度</label><AaSelect v-model="props.s['llm.effort']"><option value="low">低（快）</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">最高（慢）</option></AaSelect>
        </div>
        <p class="hint" style="margin-top: 10px">模型和思考深度改完点右上角“保存”；key 用下面的按钮保存。</p>
      </template>

      <!-- ChatGPT subscription through the official Codex SDK -->
      <template v-else-if="cur.kind === 'codex'">
        <p class="muted">用你的 ChatGPT 订阅（Plus / Pro 等），通过 OpenAI 官方的 Codex SDK。登录在 OpenAI 自己的页面上完成，这个程序接触不到你的密码。和 Claude 订阅一样，评分、答题、写求职信、让 AI 操作网页都可以用。</p>
        <div class="callout" :class="cur.installed && cur.logged_in ? '' : 'warn'" style="margin-top: 10px"><Icon :name="cur.installed && cur.logged_in ? 'check' : 'info'" />
          <div v-if="!cur.installed">还没有安装接入组件。在程序目录运行 <code>uv sync --extra chatgpt</code>（会下载约 190 MB），重启程序后回到这里。</div>
          <div v-else-if="cur.login && cur.login.state === 'waiting'">已在浏览器里打开 ChatGPT 的登录页，请在那里完成登录。没有弹出来的话，<a :href="cur.login.url" target="_blank" rel="noopener">点这里打开 ↗</a></div>
          <div v-else-if="!cur.logged_in">组件已安装，还没登录。<template v-if="cur.login && cur.login.error">上次没成功：{{ cur.login.error }}</template></div>
          <div v-else>已登录{{ cur.plan ? '（' + cur.plan + '）' : '' }}。</div></div>
        <div v-if="cur.installed" class="row" style="margin-top: 10px">
          <button v-if="!cur.logged_in" class="primary" @click="chatgptLogin"><Icon name="login" />用 ChatGPT 账号登录</button>
          <button v-else class="ghost danger" @click="chatgptLogout">退出登录</button>
        </div>
        <div class="kv" style="margin-top: 14px">
          <label>主要模型</label><ModelPick v-model="form.model" :models="models" :loading="loadingModels" allow-empty="用账号的默认模型" />
          <label>简单任务用的模型</label><ModelPick v-model="form.small_model" :models="models" :loading="loadingModels" allow-empty="和主要模型一样" />
          <label>思考深度</label><div><AaSelect v-model="form.effort"><option value="">按账号的默认</option><option value="low">低（快，省额度）</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">最高（慢，费额度）</option></AaSelect>
            <div class="hint">只管主要模型。思考得越深，同一份申请用掉的额度越多。</div></div>
        </div>
      </template>

      <!-- OpenAI-compatible -->
      <template v-else>
        <p class="muted">通过这家的 API key 使用，按用量付费。<a v-if="cur.keys" :href="cur.keys" target="_blank" rel="noopener">在这里申请 key ↗</a>
          <template v-if="cur.key === 'custom'">填任何兼容 OpenAI 接口的服务地址；本机的 Ollama 是 <code>http://localhost:11434/v1</code>，不需要 key。</template></p>
        <div class="kv" style="margin-top: 14px">
          <label>接口地址</label><input v-model="form.base_url" :placeholder="cur.default_base_url || 'https://…/v1'" />
          <label>API key</label><input v-model="form.api_key" type="password" autocomplete="off" :placeholder="cur.has_key ? '已保存；要更换时在这里填新的' : cur.key === 'custom' ? '不需要就留空' : '还没有保存'" @input="keyTyped" />
          <label>主要模型</label>
          <div><ModelPick v-model="form.model" :models="models" :loading="loadingModels" />
            <div v-if="!models.length && !loadingModels" class="hint">{{ modelNote || (cur.has_key || form.api_key || cur.key === 'custom' ? '这个服务没有返回模型列表，请手动填写模型名称。' : '填上 API key 后会自动读取这家的模型列表。') }}</div>
            <div class="hint">做申请的 Agent 用的就是这个模型。它要能调用工具、能看网页截图；做不到这两样的模型做不了申请。</div></div>
          <label>简单任务用的模型</label>
          <div><ModelPick v-model="form.small_model" :models="models" :loading="loadingModels" allow-empty="和主要模型一样" />
            <div class="hint">给邮件分类、读验证码这类小事用，可以选便宜的。</div></div>
          <label>思考深度</label><div><AaSelect v-model="form.effort"><option value="">不指定（这家服务的默认）</option><option value="low">低（快，便宜）</option><option value="medium">中</option><option value="high">高</option><option value="xhigh">最高（慢，贵）</option></AaSelect>
            <div class="hint">只管主要模型，作为 reasoning_effort 发给这家服务。不是会思考的模型、或这家服务不认识这个参数时会报错，那就选“不指定”。</div></div>
        </div>
      </template>

      <div class="row" style="margin-top: 16px">
        <button v-if="!inUse" class="primary" :disabled="busy" @click="save(true)"><Icon name="check" />保存并改用这个</button>
        <button v-if="cur.key !== 'claude_subscription'" :class="{ primary: inUse }" :disabled="busy" @click="save(false)">保存{{ inUse ? '' : '（先不切换）' }}</button>
        <button v-if="inUse" @click="test">测试一下能不能用</button>
      </div>
    </div>

    <div class="card" style="grid-column: 1 / -1">
      <div class="row"><span class="card-title grow">备用服务（主用的出问题时自动换）</span>
        <button class="sm ghost" :disabled="quotaBusy" @click="loadQuota(true)"><Icon name="refresh" />{{ quotaBusy ? '正在查…' : '刷新额度' }}</button>
        <button v-if="fo.chain.some((c) => c.state === 'cooling')" class="sm ghost" @click="resetFo">都重新试一次</button></div>
      <p class="muted">一家服务的额度用完、被限流、连不上或登录失效时，同一步会立刻改用下面的备用服务，按从上到下的顺序；出问题的那家先放一会儿，恢复后自动切回。
        主要模型和简单任务用的模型都按这个顺序走。没有备用时，任务会停下来等。</p>
      <div class="list" style="margin-top: 10px">
        <div v-if="fo.chain.length" class="item">
          <span class="badge info">主用</span>
          <div class="grow"><b>{{ fo.chain[0].name }}</b> <span class="muted small">{{ fo.chain[0].model }}{{ fo.chain[0].small_model && fo.chain[0].small_model !== fo.chain[0].model ? ' · 简单任务 ' + fo.chain[0].small_model : '' }}</span>
            <div v-if="fo.chain[0].state === 'cooling'" class="small" style="color: var(--warn)">暂时不用，{{ hhmm(fo.chain[0].until) }} 之后再试。</div>
            <div v-if="quotaOf(fo.chain[0].provider)" class="quota">
              <template v-for="q in [quotaOf(fo.chain[0].provider)]" :key="q.provider">
                <div v-if="!q.supported" class="muted small">{{ q.note }}</div>
                <div v-else-if="q.error" class="muted small">这次没查到额度。</div>
                <div v-else-if="q.pending" class="muted small">{{ q.note }}</div>
                <div v-for="w in q.windows || []" :key="w.key" class="qrow"><span class="lab">{{ w.label }}</span><span class="track"><span class="fill" :class="winTone(w)" :style="{ width: Math.min(100, w.used || 0) + '%' }"></span></span>
                  <span class="val"><template v-if="w.blocked || w.used >= 100">已用完</template><template v-else>已用 {{ w.used }}%</template><span v-if="w.resets_at" class="muted">，{{ resetAt(w.resets_at) }} 重置</span></span></div>
                <div v-for="b in q.balances || []" :key="b.currency" class="small">余额 <b>{{ b.amount.toFixed(2) }} {{ b.currency }}</b></div>
              </template>
            </div></div>
          <span class="badge" :class="fo.chain[0].state === 'cooling' ? 'warn' : 'ok'">{{ fo.chain[0].state === 'cooling' ? '暂时不用' : '可用' }}</span>
        </div>
        <div v-for="(b, i) in backups" :key="i" class="item" style="align-items: flex-start">
          <span class="badge">备用 {{ i + 1 }}</span>
          <div class="grow">
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <AaSelect v-model="b.provider" @change="b.model = ''; b.small_model = ''; modelsFor(b.provider)">
                <option v-for="p in candidates" :key="p.key" :value="p.key">{{ p.name.split('（')[0] }}{{ usable(p) ? '' : '（还没设置好）' }}</option>
              </AaSelect>
              <ModelPick v-model="b.model" :models="foModels[b.provider] || []" allow-empty="主要模型：用这家已保存的" />
              <ModelPick v-model="b.small_model" :models="foModels[b.provider] || []" allow-empty="简单任务：用这家已保存的" />
            </div>
            <div v-if="!usable(candidates.find((p) => p.key === b.provider) || {})" class="small" style="color: var(--warn); margin-top: 4px">这家还没有设置好（没登录、没填 key 或没选模型）。先在上面点开它设置并保存，否则轮到它时也用不了。</div>
            <div v-else-if="stateOf(b) && stateOf(b).state === 'cooling'" class="small" style="color: var(--warn); margin-top: 4px">暂时不用，{{ hhmm(stateOf(b).until) }} 之后再试。</div>
            <div v-if="quotaOf(b.provider)" class="quota">
              <template v-for="q in [quotaOf(b.provider)]" :key="q.provider">
                <div v-if="!q.supported" class="muted small">{{ q.note }}</div>
                <div v-else-if="q.error" class="muted small">这次没查到额度。</div>
                <div v-else-if="q.pending" class="muted small">{{ q.note }}</div>
                <div v-for="w in q.windows || []" :key="w.key" class="qrow"><span class="lab">{{ w.label }}</span><span class="track"><span class="fill" :class="winTone(w)" :style="{ width: Math.min(100, w.used || 0) + '%' }"></span></span>
                  <span class="val"><template v-if="w.blocked || w.used >= 100">已用完</template><template v-else>已用 {{ w.used }}%</template><span v-if="w.resets_at" class="muted">，{{ resetAt(w.resets_at) }} 重置</span></span></div>
                <div v-for="bal in q.balances || []" :key="bal.currency" class="small">余额 <b>{{ bal.amount.toFixed(2) }} {{ bal.currency }}</b></div>
              </template>
            </div>
            <template v-if="foTest[i]">
              <div v-if="foTest[i].busy" class="callout" style="margin-top: 8px"><Icon name="clock" /><div>正在向这家服务各问一句话，通常十几秒…</div></div>
              <div v-else-if="foTest[i].error" class="callout bad" style="margin-top: 8px"><Icon name="alert" /><div>{{ foTest[i].error }}</div></div>
              <template v-else>
                <div v-for="[k, lab] in [['main', '主要模型'], ['small', '简单任务用的模型']]" :key="k" class="callout" :class="foTest[i][k].ok ? 'ok' : 'warn'" style="margin-top: 8px">
                  <Icon :name="foTest[i][k].ok ? 'check' : 'alert'" />
                  <div class="grow">
                    <div><b>{{ lab }}</b><span class="muted">{{ foTest[i][k].model ? '（' + foTest[i][k].model + '）' : '' }}</span>：{{ foTest[i][k].ok ? '能用，轮到它时可以接手。' : foTest[i][k].message }}</div>
                    <div v-if="!foTest[i][k].ok && foTest[i].quota && foTest[i].quota.lines.length" class="small muted" style="margin-top: 2px">{{ foTest[i].quota.lines.map((l) => l[0] + '：' + l[1]).join('；') }}</div>
                    <TechDetails v-if="!foTest[i][k].ok" :text="foTest[i][k].detail" />
                  </div>
                </div>
              </template>
            </template>
          </div>
          <div class="row" style="gap: 4px">
            <button class="sm ghost" :disabled="i === 0" title="上移" @click="moveBackup(i, -1)">↑</button>
            <button class="sm ghost" :disabled="i === backups.length - 1" title="下移" @click="moveBackup(i, 1)">↓</button>
            <button class="sm" @click="testBackup(i)">测试</button>
            <button class="sm ghost danger" @click="backups.splice(i, 1); foTest = {}">删除</button>
          </div>
        </div>
      </div>
      <div class="row small" style="gap: 14px; flex-wrap: wrap; margin-top: 12px; align-items: center">
        <span class="muted">额度提醒（改了就生效）：</span>
        <label>用量到 <input v-model.number="quota.warn_percent" type="number" min="1" max="100" style="width: 70px" @change="saveQuota" /> % 时</label>
        <label>余额低于 <input v-model.number="quota.warn_balance" type="number" min="0" step="0.5" style="width: 80px" @change="saveQuota" /> 时</label>
        <label><input v-model="quota.notify" type="checkbox" @change="saveQuota" /> 发通知告诉我</label>
        <span class="muted">每 {{ quota.check_minutes || 30 }} 分钟查一次；Claude 订阅、ChatGPT 订阅、DeepSeek、OpenRouter 能查，其余几家官方不提供查询。</span>
      </div>
      <p v-if="!backups.length" class="muted" style="margin-top: 10px">还没有备用服务。建议至少加一个不同厂商的：这样一家的额度用完，工作不会停。</p>
      <div class="row" style="margin-top: 12px">
        <button @click="addBackup"><Icon name="plus" />添加备用服务</button>
        <button class="primary" :disabled="foBusy || !foDirty" @click="saveFo"><Icon name="check" />保存备用顺序</button>
        <span v-if="foDirty" class="badge warn">有改动还没保存</span>
      </div>
    </div>
  </div>
</template>
