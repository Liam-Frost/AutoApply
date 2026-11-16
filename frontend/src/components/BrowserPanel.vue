<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'

const props = defineProps({ s: { type: Object, required: true } })
const status = ref(null)
const busy = ref(false)
const load = async () => { try { status.value = await api.get('/browser/status') } catch (e) { toast(e.message, 'bad') } }
const add = () => { props.s['browser.rules'].push({ domain: '', backend: 'nodriver', operations: [] }) }
async function test() {
  busy.value = true
  try { await api.post('/browser/test'); toast('nodriver 浏览器启动和页面操作测试通过') } catch (e) { toast(e.message, 'bad') }
  finally { busy.value = false; await load() }
}
onMounted(load)
</script>

<template>
  <div class="card">
    <div class="card-title">浏览器后端</div>
    <p class="muted">默认使用 Playwright。启用后，命中下方规则的任务使用原生 nodriver；规则在任务打开浏览器时生效。</p>
    <label><input v-model="props.s['browser.nodriver_enabled']" type="checkbox" />启用 nodriver</label>
    <div class="kv" style="margin-top: 16px">
      <label>Chrome / Edge 路径</label><input v-model="props.s['browser.executable']" placeholder="留空自动检测" />
    </div>
    <p v-if="status" class="hint">{{ status.installed ? 'nodriver 已安装' : '安装命令：uv sync --extra nodriver' }} · {{ status.executable || '未找到 Chrome / Edge' }}</p>
    <button :disabled="busy || !status?.installed" @click="test">{{ busy ? '测试中…' : '用已保存的设置测试浏览器' }}</button>
  </div>
  <div class="card">
    <div class="row"><span class="card-title grow">站点规则</span><button @click="add">添加规则</button></div>
    <p class="hint">账号规则优先于域名规则。同一类型按列表顺序匹配。域名包含其子域名。操作留空表示全部。</p>
    <div v-for="(rule, i) in props.s['browser.rules']" :key="i" class="row" style="margin-top: 10px; flex-wrap: wrap">
      <AaSelect :value="rule.tenant !== undefined ? 'tenant' : 'domain'" @change="rule[$event.target.value] = rule.tenant || rule.domain || ''; delete rule[$event.target.value === 'tenant' ? 'domain' : 'tenant']">
        <option value="tenant">账号 / 租户</option><option value="domain">域名</option>
      </AaSelect>
      <input v-if="rule.tenant !== undefined" v-model="rule.tenant" placeholder="pdportal:ubc" />
      <input v-else v-model="rule.domain" placeholder="accounts.google.com" />
      <AaSelect v-model="rule.backend"><option value="playwright">Playwright</option><option value="nodriver">nodriver</option></AaSelect>
      <label v-for="(label, key) in { login: '登录', scan: '扫描', read: '读取', apply: '填写申请' }" :key="key"><input v-model="rule.operations" type="checkbox" :value="key" />{{ label }}</label>
      <button @click="props.s['browser.rules'].splice(i, 1)">删除</button>
    </div>
  </div>
</template>
