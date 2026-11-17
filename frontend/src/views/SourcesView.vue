<script setup>
// Where postings come from: the employers that are watched, what the last scan read, the school's portal. It was
// three cards of the settings; it is looked at and added to all the time, and belongs with the postings.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import EmployersPanel from '../components/EmployersPanel.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
import { fmtTime, persona, run, toast } from '../ui'

const scan = ref({ at: null, sources: [] })
const bm = ref({ href: '' })
const portal = ref({ on: false, base: '', account: null })
async function load() {
  api.get('/sources/last-scan').then((c) => (scan.value = c)).catch(() => {})
  if (persona.features.portal !== 'ubc') return
  api.get('/import/pdportal/bookmarklet').then((c) => (bm.value = c)).catch(() => {})
  const [st, accounts] = await Promise.all([api.get('/settings'), api.get('/accounts').catch(() => [])])
  portal.value = { on: !!st.settings['sources.pdportal'], base: st.settings['app.base_url'], account: accounts.find((a) => a.tenant_key === 'pdportal:ubc') || null }
}
const setPortal = (on) => run(() => api.put('/settings', { settings: { 'sources.pdportal': on } }), on ? '扫描新岗位时会读 PD Portal' : '扫描时不再读 PD Portal', load)
const portalLogin = () => run(() => api.post('/accounts/takeover', { tenant_key: 'pdportal:ubc', url: 'https://pdportal.apsc.ubc.ca/home.htm', save_credentials: false }), '已打开一个浏览器窗口，请在里面用学校账号登录。登录好之后程序会保存登录状态，窗口自己关闭。', load)
const scanNow = () => run(() => api.post('/tasks', { kind: 'discover' }), '开始扫描，完成后会通知你；大厂官网全部读一遍大约需要十几分钟', load)
onMounted(load)
</script>

<template>
  <PageHead title="来源与关注公司" sub="岗位是从这些地方读来的。">
    <router-link to="/jobs" class="btn ghost">回到岗位</router-link>
    <button @click="scanNow"><Icon name="refresh" />现在扫描</button>
  </PageHead>

  <EmployersPanel />

  <div v-if="persona.features.portal === 'ubc'" class="card">
    <div class="row"><span class="card-title grow">UBC PD Portal</span>
      <span v-if="portal.account" class="badge" :class="portal.account.status === 'ok' ? 'ok' : 'warn'">{{ portal.account.status === 'ok' ? '已登录' : '需要重新登录' }}</span>
      <span v-else class="badge warn">还没有登录过</span></div>
    <p class="muted">程序在扫描新岗位时自己读门户上的岗位。门户用你的学校账号登录（CWL + Duo）：在这里登录一次，登录状态会保存下来；过期时待办里会出现“登录 PD Portal”。</p>
    <div class="row" style="flex-wrap: wrap">
      <label><input type="checkbox" :checked="portal.on" @change="setPortal($event.target.checked)" /> 扫描新岗位时读 PD Portal <span class="hint">（改了就生效）</span></label>
      <button class="primary" @click="portalLogin"><Icon name="login" />登录 PD Portal</button>
    </div>
    <p class="hint">门户挡住程序的浏览器时，到<router-link to="/settings/system/browser">设置 → 系统与数据 → 浏览器兼容</router-link>打开普通浏览器（nodriver）再试。</p>
    <details class="tech"><summary>也可以在你自己的浏览器里导入（书签）</summary>
      <ol class="small" style="margin: 8px 0 10px; padding-left: 20px; line-height: 1.9">
        <li>把这个按钮<b>拖到浏览器的书签栏</b>：<a v-if="bm.href" :href="bm.href" class="btn sm primary" @click.prevent="toast('把它拖到书签栏，不是点击')">导入到 AutoApply</a></li>
        <li>在 Chrome 里登录 PD Portal，打开 Job Postings 页面。</li>
        <li>点书签栏里的“导入到 AutoApply”。第一次会先列出全部岗位，列表出来后再点一次；右下角会显示进度。</li>
      </ol>
      <pre>书签栏用不了时，在门户页面按 F12 打开控制台，粘贴下面这行并回车：

var s=document.createElement('script');s.src='{{ portal.base }}/pdportal-import.js';document.body.appendChild(s)</pre></details>
  </div>

  <div class="card">
    <div class="row"><span class="card-title grow">上次扫描</span><router-link to="/settings/automation/schedule" class="small">多久扫描一次</router-link></div>
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
      <p class="hint" style="margin-top: 8px">“符合条件”按<router-link to="/settings/goals/filters">入库前的硬条件</router-link>算。</p>
    </template>
  </div>
</template>
