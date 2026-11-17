<script setup>
// Settings -> 访问与安全: where the server listens, the proxy in front of it, the administrator's password, the open logins.
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import Icon from './Icon.vue'
import { ask, run, session, toast } from '../ui'
import { clone, same, useUnsaved } from '../dirty'

const info = ref(null)
const c = ref(null)
const where = ref('local')     // local | all | one
const pw = ref({ current: '', password: '', again: '', user: '' })
const proxies = ref('')
const hosts = ref('')

async function load() {
  info.value = await api.get('/access')
  c.value = { ...info.value.settings }
  where.value = c.value.host === '127.0.0.1' || c.value.host === 'localhost' ? 'local' : c.value.host === '0.0.0.0' ? 'all' : 'one'
  proxies.value = c.value.trusted_proxies.join(', ')
  hosts.value = c.value.allowed_hosts.join(', ')
  pw.value.user = info.value.user
  base.value = clone(shown())
}
// what this panel saves with its own button, as it was last read or saved
const base = ref(null)
const shown = () => ({ c: c.value, proxies: proxies.value, hosts: hosts.value })
const dirty = computed(() => !!base.value && !same(shown(), base.value))
function discard() { c.value = clone(base.value.c); proxies.value = base.value.proxies; hosts.value = base.value.hosts; where.value = c.value.host === '127.0.0.1' || c.value.host === 'localhost' ? 'local' : c.value.host === '0.0.0.0' ? 'all' : 'one' }
const typedPw = computed(() => !!(pw.value.password || pw.value.again))      // (not the current one: a browser fills that in by itself)
const list = (t) => t.split(/[\s,;]+/).filter(Boolean)
const exposed = computed(() => where.value !== 'local')
const unencrypted = computed(() => exposed.value && !c.value.https_by_proxy)
function pickWhere(v) { where.value = v; c.value.host = v === 'local' ? '127.0.0.1' : v === 'all' ? '0.0.0.0' : (info.value.addresses.find((a) => /^\d/.test(a)) || '') }
const save = () => run(async () => {
  await api.put('/access', { settings: { ...c.value, trusted_proxies: list(proxies.value), allowed_hosts: list(hosts.value) } })
  await load()
}, '已保存。监听地址、端口和路径前缀在重启服务后生效（托盘图标 → 重启服务）。')
const changePassword = () => {
  if (pw.value.password !== pw.value.again) { toast('两次输入的新密码不一样', 'bad'); return false }
  return run(async () => {
    await api.post('/auth/password', { current: pw.value.current, password: pw.value.password, user: pw.value.user })
    pw.value = { current: '', password: '', again: '', user: pw.value.user }
    session.user = pw.value.user
    await load()
  }, '密码已更改，其他设备上的登录都已退出')
}
useUnsaved({ id: 'access', label: '访问设置', dirty: () => dirty.value, save: () => save(), discard })
useUnsaved({ id: 'access-pw', label: '新密码', dirty: () => typedPw.value, save: () => changePassword(), discard: () => { pw.value = { current: '', password: '', again: '', user: info.value.user } } })
const signOutAll = async () => (await ask('退出所有设备上的登录？这个浏览器也要重新登录。')) && run(async () => { await api.post('/auth/logout', { everywhere: true }); session.in = false }, '已全部退出')
onMounted(load)
</script>

<template>
  <template v-if="c">
    <div class="card">
      <div class="card-title">从哪里可以打开 AutoApply</div>
      <p class="muted">默认只有这台电脑能打开。要在手机或别的电脑上用，就让它监听局域网的地址；不管从哪里打开，都要先登录。</p>
      <p v-if="info.restart_needed" class="callout"><Icon name="info" /><span>现在运行的服务监听 {{ info.running.host }}:{{ info.running.port }}，和这里保存的不一样：重启服务后生效（托盘图标 → 重启服务）。</span></p>
      <div class="kv">
        <label>监听地址 <span class="badge">重启后生效</span></label>
        <div class="row" style="flex-wrap: wrap">
          <div class="seg">
            <button :class="{ on: where === 'local' }" @click="pickWhere('local')">只有这台电脑</button>
            <button :class="{ on: where === 'all' }" @click="pickWhere('all')">这台电脑所在的所有网络</button>
            <button :class="{ on: where === 'one' }" @click="pickWhere('one')">指定一个地址</button>
          </div>
          <input v-if="where === 'one'" v-model.trim="c.host" style="width: 180px" placeholder="192.168.1.20" aria-label="监听的 IP 地址" />
          <span v-if="where !== 'local' && info.addresses.length" class="hint">这台电脑的地址：{{ info.addresses.join('、') }}</span>
        </div>
        <label>端口 <span class="badge">重启后生效</span></label><div><input v-model.number="c.port" type="number" style="width: 110px" /></div>
        <label>路径前缀 <span class="badge">重启后生效</span></label><div><input v-model.trim="c.root_path" style="width: 220px" placeholder="留空" /> <span class="hint">放在反向代理的某个路径下面时才填，例如 /autoapply</span></div>
        <label>登录保持</label><div><input v-model.number="c.session_days" type="number" style="width: 90px" /> 天 <span class="hint">到期后要重新登录</span></div>
      </div>
      <p v-if="unencrypted" class="callout warn" style="margin-top: 14px"><Icon name="alert" /><span>别的设备访问时，密码和页面内容在网络上是不加密的。只在你信任的网络（家里的局域网）里这样用；要从外面访问，请在前面放一个负责 HTTPS 的反向代理，并打开下面的开关。</span></p>
    </div>

    <div class="card">
      <div class="card-title">反向代理</div>
      <p class="muted">AutoApply 自己不提供 HTTPS。需要加密访问时，由它前面的反向代理（Caddy、nginx、Cloudflare Tunnel 等）负责，这里告诉程序前面有这样一个代理。</p>
      <div class="kv">
        <label>由反向代理负责 HTTPS</label><div><input v-model="c.https_by_proxy" type="checkbox" /> <span class="hint">打开后，登录状态只在 HTTPS 下发送；这台电脑上的代理会被自动信任</span></div>
        <label>代理的地址</label><div><input v-model="proxies" placeholder="留空" style="width: 320px" /> <span class="hint">代理在别的机器上时，填它的 IP 地址，多个用逗号隔开</span></div>
        <label>访问用的域名</label><div><input v-model="hosts" placeholder="jobs.example.com" style="width: 320px" /> <span class="hint">通过域名访问时填，程序只应答填在这里的名字</span></div>
      </div>
      <div class="row" style="margin-top: 14px"><button class="primary" :disabled="!dirty" @click="save"><Icon name="check" />保存访问设置</button>
        <span v-if="dirty" class="badge warn">有改动还没保存</span><span v-else class="hint">这一页上面两块（从哪里打开、反向代理）都由这个按钮保存。</span></div>
    </div>

    <div class="card">
      <div class="card-title">管理员账号</div>
      <p class="muted">唯一的账号。密码只保存加密后的结果。忘记密码时，在这台电脑的托盘图标里选“重置管理员密码”。</p>
      <div class="kv">
        <label>用户名</label><div><input v-model.trim="pw.user" autocomplete="username" style="width: 260px" /></div>
        <label>现在的密码</label><div><input v-model="pw.current" type="password" autocomplete="current-password" style="width: 260px" /></div>
        <label>新密码</label><div><input v-model="pw.password" type="password" autocomplete="new-password" style="width: 260px" /> <span class="hint">至少 8 个字符</span></div>
        <label>再输入一次新密码</label><div><input v-model="pw.again" type="password" autocomplete="new-password" style="width: 260px" /></div>
      </div>
      <div class="row" style="margin-top: 14px">
        <button :disabled="!pw.current || !pw.password" @click="changePassword"><Icon name="key" />更改密码</button>
        <button class="ghost danger" @click="signOutAll">退出所有设备上的登录</button>
      </div>
    </div>
  </template>
</template>
