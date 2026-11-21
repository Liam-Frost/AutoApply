<script setup>
// Which mailbox the program reads (read-only): verification codes and links, confirmations, interview invitations, rejections.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { run, toast } from '../ui'
import { clone, same, useUnsaved } from '../dirty'
import FileButton from './FileButton.vue'
import Icon from './Icon.vue'

const d = ref(null)
const pick = ref('gmail_api')   // gmail_api | <imap preset>
const form = ref({ host: '', port: 993, user: '', password: '' })
const busy = ref(false)
const result = ref(null)
const clientId = ref('')
let olTimer

const preset = computed(() => d.value && d.value.presets.find((p) => p.key === pick.value))
const inUse = computed(() => d.value && (pick.value === 'gmail_api' ? d.value.kind === 'gmail_api' : d.value.kind === 'imap' && d.value.imap.preset === pick.value))
async function load() {
  d.value = await api.get('/mailbox')
  pick.value = d.value.kind === 'imap' ? d.value.imap.preset || 'custom' : 'gmail_api'
  fill()
  base.value = clone(shown())
}
// which mailbox and how it is reached, as it was last read or saved
const base = ref(null)
const shown = () => ({ pick: pick.value, form: form.value })
const dirty = computed(() => !!base.value && !same(shown(), base.value))
function discard() { pick.value = base.value.pick; form.value = clone(base.value.form); result.value = null }
function fill() {
  const i = d.value.imap
  const mine = d.value.kind === 'imap' && i.preset === pick.value
  form.value = { host: mine ? i.host : (preset.value ? preset.value.host : ''), port: mine ? i.port : (preset.value ? preset.value.port : 993), user: i.user || '', password: '' }
  result.value = null
}
const isOutlook = computed(() => pick.value === 'outlook')
async function outlookAuth() {
  busy.value = true
  try {
    await api.put('/settings', { settings: { 'mail.kind': 'imap', 'mail.imap': imapBody() } })
    await api.post('/mailbox/outlook/authorize', clientId.value.trim() ? { client_id: clientId.value.trim() } : {})
    d.value = await api.get('/mailbox')
    clearInterval(olTimer)
    olTimer = setInterval(async () => {
      d.value = await api.get('/mailbox')
      if (d.value.outlook.flow.state !== 'waiting') { clearInterval(olTimer); if (d.value.outlook.flow.state === 'done') toast('Outlook 邮箱已授权') }
    }, 4000)
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
}
const outlookForget = () => run(() => api.del('/mailbox/outlook'), '已删除 Outlook 的授权', load)
const imapBody = () => ({ preset: pick.value, host: form.value.host, port: form.value.port, user: form.value.user })
async function test() {
  busy.value = true; result.value = null
  try {
    const r = await api.post('/mailbox/test', pick.value === 'gmail_api' ? {} : { imap: imapBody(), password: form.value.password })
    result.value = { ok: true, text: `能读到。最近三天收到 ${r.recent} 封邮件。` }
  } catch (e) { result.value = { ok: false, text: e.message } }
  busy.value = false
}
async function save() {
  busy.value = true
  try {
    if (pick.value === 'gmail_api') await api.put('/settings', { settings: { 'mail.kind': 'gmail_api' } })
    else await api.put('/settings', { settings: { 'mail.kind': 'imap', 'mail.imap': imapBody() }, secrets: form.value.password ? { imap_password: form.value.password } : {} })
    toast('邮箱设置已保存')
    await load()
    busy.value = false
    return true
  } catch (e) { toast(e.message, 'bad') }
  busy.value = false
  return false
}
useUnsaved({ id: 'mailbox', label: '邮箱', dirty: () => dirty.value, save, discard })
function gmailClient(ev) {
  const f = ev.target.files[0]
  if (!f) return
  const fd = new FormData(); fd.append('file', f)
  run(() => api.upload('/settings/gmail-client', fd), '文件已保存，接着点“授权”', load)
}
const gmailAuth = () => run(() => api.post('/settings/gmail-authorize'), '已打开浏览器，请在里面完成 Google 授权：把列出的几项权限都勾上', load)
onMounted(load)
</script>

<template>
  <div v-if="d" class="card">
    <div class="row"><span class="card-title grow">邮箱</span><span class="badge" :class="d.ready ? 'ok' : 'warn'">{{ d.ready ? '已连接' : '还没连接' }}</span></div>
    <p class="muted">读信：读取网站发来的验证码和激活链接，以及确认信、面试邀请、拒信，自动更新岗位状态；不会删除、移动邮件，也不会把邮件标为已读。发信（只有 Gmail 的 Google 授权方式可以）：邮件投递的申请和给雇主的回复从这个邮箱发出，每一封都先记在程序里，发不发、先不先给你看由你在“自动化”里定。请填你投简历时用的那个邮箱。</p>
    <div class="kv">
      <label>哪种邮箱</label>
      <AaSelect v-model="pick" @change="fill">
        <option value="gmail_api">Gmail（Google 授权，可以读信和发信）</option>
        <option v-for="p in d.presets" :key="p.key" :value="p.key">{{ p.name }}</option>
      </AaSelect>
    </div>

    <template v-if="pick === 'gmail_api'">
      <p class="hint" style="margin: 12px 0">授权时申请读取、发送、草稿和修改邮件标签这几项权限：读信用来跟踪申请的回信，发信用来替你发邮件投递的申请和回复雇主。需要你自己在 Google Cloud 建一个 OAuth 客户端（一次性，稍麻烦）；处于测试状态的客户端不用另外配置权限，授权页上把列出的几项都勾上就行。授权过只读的，重新点一次“授权”。只想让程序读信的话，可以在上面改选“Gmail（应用专用密码）”，那样不能发信。</p>
      <div class="row">
        <FileButton accept=".json" @change="gmailClient"><Icon name="inbox" />选择 JSON 文件</FileButton>
        <button :disabled="!d.client" @click="gmailAuth">授权</button>
        <span class="badge" :class="d.authorized ? 'ok' : ''">{{ d.authorized ? '已授权' : d.reconnect ? '授权已失效，请重新授权' : d.client ? '文件已上传，还没授权' : '还没上传文件' }}</span>
        <span v-if="d.authorized" class="badge" :class="d.can_send ? 'ok' : 'warn'">{{ d.can_send ? '可以发信' : '只能读信：重新授权一次才能发信' }}</span>
      </div>
      <details class="tech"><summary>怎么拿到这个文件</summary><pre>在 Google Cloud 创建“桌面应用”类型的 OAuth 客户端，启用 Gmail API，下载 JSON 文件后在这里上传，再点“授权”。</pre></details>
    </template>
    <template v-else>
      <p class="callout" style="margin-top: 12px"><Icon name="info" /><span>{{ preset.how }}</span></p>
      <div class="kv">
        <template v-if="pick === 'custom'">
          <label>IMAP 服务器</label><div class="row" style="flex-wrap: nowrap"><input v-model="form.host" class="grow" placeholder="imap.example.com" /><input v-model.number="form.port" type="number" style="width: 90px" aria-label="端口" /></div>
        </template>
        <label>邮箱地址</label><input v-model="form.user" placeholder="you@example.com" autocomplete="off" />
        <template v-if="isOutlook">
          <label>应用（客户端）ID</label><input v-model="clientId" :placeholder="d.outlook.client_id ? '已保存；要更换时在这里填新的' : '形如 xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'" autocomplete="off" />
          <label>授权</label>
          <div>
            <div class="row"><button :disabled="busy || !form.user || (!clientId.trim() && !d.outlook.client_id)" @click="outlookAuth"><Icon name="login" />{{ d.outlook.authorized ? '重新授权' : '授权' }}</button>
              <span class="badge" :class="d.outlook.authorized ? 'ok' : ''">{{ d.outlook.authorized ? '已授权' : '还没授权' }}</span>
              <button v-if="d.outlook.authorized" class="sm ghost danger" @click="outlookForget">删除授权</button></div>
            <p v-if="d.outlook.flow.state === 'waiting'" class="callout" style="margin-top: 8px"><Icon name="info" /><span>打开 <a :href="d.outlook.flow.url" target="_blank" rel="noopener">{{ d.outlook.flow.url }}</a>，输入代码 <b style="font-size: 16px; letter-spacing: 1px">{{ d.outlook.flow.code }}</b>，用你的 Outlook 账号登录并同意“读取邮件”。完成后这里会自动更新。</span></p>
            <p v-else-if="d.outlook.flow.state === 'failed'" class="small" style="color: var(--bad); margin-top: 6px">没有成功：{{ d.outlook.flow.error }}</p>
          </div>
        </template>
        <template v-else>
          <label>授权码 / 应用专用密码</label><input v-model="form.password" type="password" autocomplete="new-password" :placeholder="d.imap.has_password && inUse ? '已保存，留空表示不改' : '不是邮箱的登录密码'" />
        </template>
      </div>
      <p class="hint" style="margin-top: 8px">授权码 / 授权令牌保存在本机的系统凭据管理器里。邮件连接不经过“设置 → 系统与数据 → 网络连接”里的代理，是直接连到邮箱服务器的。</p>
    </template>

    <div class="row" style="margin-top: 12px">
      <button :disabled="busy" @click="test"><Icon name="refresh" />{{ busy ? '请稍候…' : '测试能不能读到' }}</button>
      <button class="primary" :disabled="busy || (pick !== 'gmail_api' && !form.user)" @click="save"><Icon name="check" />{{ inUse ? '保存' : '保存并改用这个邮箱' }}</button>
      <span v-if="result" class="small" :style="result.ok ? 'color: var(--ok)' : 'color: var(--bad)'">{{ result.text }}</span>
    </div>
  </div>
</template>
