<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api, fmt } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
import { fmtTime, run as runAction, ask } from '../ui'

const accounts = ref([])
const form = ref({ tenant_key: '', login_email: '', password: '' })
const revealed = ref({})
const idps = ref([])
const idpState = ref({})
let timer
const custom = ref({ name: '', url: '', domains: '' })
const showAll = ref(false)
const MAIN = ['google', 'linkedin', 'microsoft', 'apple']
async function addCustom() {
  const d = await api.get('/settings')
  const cur = d.settings['identity.custom'] || []
  const row = { name: custom.value.name.trim(), url: custom.value.url.trim(), domains: custom.value.domains.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean) }
  if (!row.domains.length) { try { row.domains = [new URL(row.url).hostname.split('.').slice(-2).join('.')] } catch (e) { /* checked by the server */ } }
  await runAction(() => api.put('/settings', { settings: { 'identity.custom': [...cur, row] } }), `已添加 ${row.name}`, loadIdps)
  custom.value = { name: '', url: '', domains: '' }
}
async function setIdpEmail(p, v) {
  const d = await api.get('/settings')
  await runAction(() => api.put('/settings', { settings: { 'identity.emails': { ...(d.settings['identity.emails'] || {}), [p.key]: v.trim() } } }), '已保存', loadIdps)
}
async function removeCustom(p) {
  const d = await api.get('/settings')
  await api.del('/identities/' + p.key)
  await runAction(() => api.put('/settings', { settings: { 'identity.custom': (d.settings['identity.custom'] || []).filter((c) => c.name !== p.name) } }), `已移除 ${p.name}`, loadIdps)
}
const until = (x) => (x ? new Date(x).toLocaleDateString('zh-CN') : '')
function sessionText(x) {
  if (!x) return '没有保存'
  if (x.expired) return '已过期，需要重新登录'
  return `保存于 ${fmtTime(x.saved_at)}` + (x.valid_until ? `，最长有效到 ${until(x.valid_until)}` : '，关掉后可能失效')
}
async function loadIdps() { idps.value = await api.get('/identities'); idpState.value = await api.get('/identities/state') }
const idpLogin = (p) => runAction(() => api.post(`/identities/${p.key}/login`), `已打开窗口，请在里面登录 ${p.name}。登录成功后窗口会自己关闭。`, loadIdps)
const idpForget = async (p) => (await ask(`删除保存的 ${p.name} 登录状态？之后遇到“用 ${p.name} 登录”的网站需要你重新登录。`)) && runAction(() => api.del('/identities/' + p.key), '已删除', loadIdps)

const STATUS = { ok: ['可以自动登录', 'ok'], pending: ['注册中', 'warn'], locked: ['被锁定', 'bad'], needs_human: ['需要你登录一次', 'warn'], unknown: ['还没登录过', ''], not_needed: ['不登录也能申请', ''] }
const BY = { agent: '程序注册', takeover: '你登录时保存', manual: '手动添加', chrome_csv: '从 Chrome 导入' }

async function load() { accounts.value = await api.get('/accounts'); loadIdps() }
const run = (fn, ok) => runAction(fn, ok, load)
const save = () => run(async () => { await api.put('/accounts/' + encodeURIComponent(form.value.tenant_key), form.value); form.value = { tenant_key: '', login_email: '', password: '' } }, '已保存')
const remove = async (a) => (await ask(`删除 ${a.site.name} 的账号记录、密码和登录状态？`)) && run(() => api.del('/accounts/' + encodeURIComponent(a.tenant_key)), '已删除')
async function reveal(a) {
  if (revealed.value[a.tenant_key]) { const r = { ...revealed.value }; delete r[a.tenant_key]; revealed.value = r; return }
  if (!(await ask(`在屏幕上显示 ${a.site.name} 的密码？`))) return
  await runAction(async () => { revealed.value = { ...revealed.value, [a.tenant_key]: (await api.post(`/accounts/${encodeURIComponent(a.tenant_key)}/reveal`, { confirm: a.tenant_key })).password } }, '')
}
function importCsv(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f)
  run(() => api.upload('/accounts/import-chrome-csv', fd), (r) => `已导入 ${r.imported.length} 个招聘网站的账号（跳过 ${r.skipped} 条无关记录）。请删除导出的 CSV 文件。`)
  ev.target.value = ''
}
const takeover = (a) => run(() => api.post('/accounts/takeover', { tenant_key: a.tenant_key, url: 'https://' + a.host, save_credentials: true }), '已打开一个浏览器窗口，请在里面登录')
onMounted(() => { load(); timer = setInterval(loadIdps, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <PageHead title="网站账号" sub="需要登录的招聘网站，每个一条。密码保存在本机的系统凭据管理器里，登录状态加密保存在本机；都不会进数据库、日志，也不会发给 AI。" />

  <div class="card">
    <div class="card-title">用来登录其他网站的账号</div>
    <p class="muted">很多招聘网站可以（有的只能）“用 Google / LinkedIn / Microsoft / Apple … 登录”。在这里登录一次，之后遇到这类网站，程序打开的窗口里就已经是登录状态。只保存登录状态（cookie，加密存在本机），<b>不保存这些账号的密码</b>。</p>
    <div class="idps">
      <div v-for="p in idps.filter((x) => showAll || MAIN.includes(x.key) || x.session || x.custom)" :key="p.key" class="idp">
        <div class="row"><b class="grow">{{ p.name }}<span v-if="p.region" class="muted small" style="font-weight: 400">　{{ p.region }}</span></b><span class="badge" :class="p.session && !p.session.expired ? 'ok' : ''">{{ p.session && !p.session.expired ? '已登录' : '未登录' }}</span></div>
        <div class="small muted" style="margin: 4px 0 10px; min-height: 36px">
          <template v-if="idpState[p.key] === 'trying'">登录窗口已打开，正在等你登录…</template>
          <template v-else-if="idpState[p.key]"><span style="color: var(--warn)">上次没有成功：{{ idpState[p.key] }}</span></template>
          <template v-else>{{ sessionText(p.session) }}</template>
        </div>
        <div class="row">
          <button class="sm" :class="{ primary: !p.session }" :disabled="idpState[p.key] === 'trying'" @click="idpLogin(p)"><Icon name="login" />{{ p.session ? '重新登录' : '去登录' }}</button>
          <button v-if="p.session" class="sm ghost danger" @click="idpForget(p)">删除登录状态</button>
          <button v-if="p.custom" class="sm ghost danger" @click="removeCustom(p)">移除</button>
        </div>
        <input v-if="p.session" :value="p.email" class="idp-mail" placeholder="这个账号的邮箱（和投递邮箱不同时填）" @change="setIdpEmail(p, $event.target.value)" />
        <div v-if="p.note" class="hint" style="margin-top: 8px">{{ p.note }}</div>
        <div v-else-if="p.custom" class="hint" style="margin-top: 8px">自己添加的：登录完成后请直接关掉窗口。</div>
      </div>
    </div>
    <div class="row" style="margin-top: 12px">
      <button class="sm ghost" @click="showAll = !showAll">{{ showAll ? '收起' : '更多：Facebook、Indeed、GitHub、SEEK、XING…' }}</button>
    </div>
    <details class="tech"><summary>没有你要的？自己加一个</summary>
      <div class="emp-add" style="margin-top: 8px">
        <input v-model="custom.name" style="width: 160px" placeholder="名称，例如 学校统一认证" />
        <input v-model="custom.url" class="grow" placeholder="它的登录页网址" />
        <input v-model="custom.domains" style="width: 220px" placeholder="它用的域名（可不填）" />
        <button :disabled="!custom.name.trim() || !custom.url.trim()" @click="addCustom">添加</button>
      </div>
      <p class="hint" style="margin-top: 6px">添加后在上面点“去登录”，在窗口里登录完直接关掉窗口。之后招聘网站上出现“用它登录”的按钮时，窗口里就已经是登录状态；但程序自动点这个按钮目前只支持内置的几家，自己加的需要你在“需要我处理”里点“我自己登录”。</p>
    </details>
  </div>

  <div class="table-wrap" style="max-height: none">
    <table>
      <thead><tr><th>网站</th><th>登录邮箱</th><th>密码</th><th>状态</th><th>登录状态</th><th>怎么来的</th><th></th></tr></thead>
      <tbody>
        <tr v-for="a in accounts" :key="a.tenant_key">
          <td><b>{{ a.site.name }}</b> <span v-if="a.site.system" class="badge">{{ a.site.system }}</span><div class="muted small">{{ a.host }}</div></td>
          <td>{{ a.login_email || '—' }}</td>
          <td>
            <template v-if="a.has_password">
              <code v-if="revealed[a.tenant_key]">{{ revealed[a.tenant_key] }}</code><span v-else class="muted">已保存</span>
              <button class="sm ghost" @click="reveal(a)">{{ revealed[a.tenant_key] ? '隐藏' : '显示' }}</button>
            </template>
            <span v-else class="muted">没有保存</span>
          </td>
          <td>
            <span class="badge" :class="(STATUS[a.status] || [])[1]">{{ (STATUS[a.status] || [a.status])[0] }}</span>
            <div v-if="a.explained.message && a.status !== 'ok'" class="small muted" style="margin-top: 4px; max-width: 320px">{{ a.explained.message }}</div>
            <TechDetails v-if="a.status !== 'ok'" :text="a.explained.detail" />
          </td>
          <td class="small" style="max-width: 240px">{{ sessionText(a.session) }}</td>
          <td class="small">{{ BY[a.created_by] || '—' }}</td>
          <td><div class="row" style="flex-wrap: nowrap"><button v-if="a.host" class="sm" @click="takeover(a)"><Icon name="login" />去登录</button><button class="sm ghost danger" @click="remove(a)">删除</button></div></td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-if="!accounts.length" icon="key" title="还没有保存任何网站账号" text="第一次遇到需要登录的网站时，会在“需要我处理”里请你登录，或由程序自己注册。" />
  </div>

  <div class="cols" style="margin-top: 16px">
    <div class="card">
      <div class="card-title">从 Chrome 导入已保存的密码</div>
      <p class="muted">在 Chrome 里打开：设置 → 密码管理器 → 设置 → 导出密码，会得到一个 CSV 文件。这里只导入属于招聘网站的记录，其余忽略；文件内容不会被保存。</p>
      <label class="btn"><Icon name="inbox" />选择 CSV 文件<input type="file" accept=".csv" hidden @change="importCsv" /></label>
      <p class="hint" style="margin-top: 8px">导入后请马上删除那个 CSV 文件。</p>
    </div>
    <div class="card">
      <div class="card-title">手动添加</div>
      <div class="kv" style="margin-top: 12px">
        <label>网站标识</label><input v-model="form.tenant_key" placeholder="workday:altera.wd1" />
        <label>登录邮箱</label><input v-model="form.login_email" />
        <label>密码</label><input v-model="form.password" type="password" autocomplete="new-password" />
      </div>
      <p class="hint" style="margin-top: 8px">Workday 的标识是 “workday:” 加上网址里 .myworkdayjobs.com 前面的部分，例如 altera.wd1.myworkdayjobs.com 写成 workday:altera.wd1。一般不需要手动添加，登录一次就会自动记住。</p>
      <button class="primary" :disabled="!form.tenant_key" @click="save">保存</button>
    </div>
  </div>
</template>
