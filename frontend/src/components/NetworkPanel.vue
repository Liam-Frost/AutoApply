<script setup>
// How the program connects to the internet. Edits the settings object it is given; the page's own "保存" stores them.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import Icon from './Icon.vue'

const props = defineProps({ s: { type: Object, required: true }, sec: { type: Object, required: true }, hasPassword: Boolean })
const state = ref(null)
const results = ref(null)
const testing = ref(false)

async function load() { state.value = await api.get('/proxy') }
async function test() {
  testing.value = true; results.value = null
  try { const r = await api.post('/proxy/test'); state.value = r; results.value = r.results } catch (e) { toast(e.message, 'bad') }
  testing.value = false
}
onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="card">
    <div class="card-title">网络连接</div>
    <p class="muted">程序联网的地方有四处：AI 模型、岗位来源、招聘网站（程序自己的浏览器）、通知和邮箱。这里的选择对它们全部生效。连接本机（这个页面本身）永远不走代理。</p>
    <div class="choice">
      <label :class="{ on: props.s['proxy.mode'] === 'system' }"><input v-model="props.s['proxy.mode']" type="radio" value="system" /><div><b>跟随系统</b>
        <span>用这台电脑的系统代理设置，和你自己的浏览器一样。<template v-if="state">现在系统代理是：{{ state.system || '没有设置（直接连接）' }}</template></span></div></label>
      <label :class="{ on: props.s['proxy.mode'] === 'none' }"><input v-model="props.s['proxy.mode']" type="radio" value="none" /><div><b>不走代理</b><span>全部直接连接，即使系统设置了代理。</span></div></label>
      <label :class="{ on: props.s['proxy.mode'] === 'custom' }"><input v-model="props.s['proxy.mode']" type="radio" value="custom" /><div><b>用指定的代理</b><span>只让这个程序走下面填的代理，不影响电脑上的其他软件。</span></div></label>
    </div>
    <div v-if="props.s['proxy.mode'] === 'custom'" class="kv" style="margin-top: 16px">
      <label>代理地址</label>
      <div><input v-model="props.s['proxy.url']" style="width: 100%" placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:1080" />
        <div class="hint">不写协议时按 http 处理。带用户名密码的 SOCKS 代理，程序的浏览器不支持，请改用 HTTP 代理。</div></div>
      <label>用户名</label><input v-model="props.s['proxy.username']" placeholder="不需要认证就留空" autocomplete="off" />
      <label>密码</label><input v-model="props.sec.proxy_password" type="password" :placeholder="hasPassword ? '已保存，留空表示不改' : '不需要认证就留空'" autocomplete="new-password" />
    </div>
    <div v-if="props.s['proxy.mode'] !== 'none'" class="kv" style="margin-top: 16px">
      <label>这些网站不走代理</label>
      <div><input v-model="props.s['proxy.bypass']" style="width: 100%" placeholder="例如：pdportal.apsc.ubc.ca, .ubc.ca（用逗号分开）" />
        <div class="hint">只在“用指定的代理”时起作用。跟随系统时，绕过名单以系统设置为准。</div></div>
    </div>
  </div>

  <div class="card">
    <div class="row"><span class="card-title grow">测试连接</span><button :disabled="testing" @click="test"><Icon name="refresh" />{{ testing ? '正在测试…' : '用已保存的设置测试' }}</button></div>
    <p class="muted" style="margin-top: 4px">改了上面的设置要先点右上角“保存”，再测试。<template v-if="state">目前生效的是：<b>{{ state.in_effect || '直接连接' }}</b></template></p>
    <table v-if="results">
      <thead><tr><th>连接到</th><th>结果</th><th>用时</th></tr></thead>
      <tbody>
        <tr v-for="r in results" :key="r.name">
          <td>{{ r.name }}</td>
          <td><span class="badge" :class="r.ok ? 'ok' : 'bad'">{{ r.ok ? '能连上' : '连不上' }}</span> <span class="muted small">{{ r.ok ? '' : r.detail }}</span></td>
          <td class="small">{{ (r.ms / 1000).toFixed(1) }} 秒</td>
        </tr>
      </tbody>
    </table>
    <p v-if="results" class="hint" style="margin-top: 10px">超过 10 秒的网站，生成草案时会明显变慢；连不上的那一项对应的功能会用不了。</p>
  </div>
</template>
