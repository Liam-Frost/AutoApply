<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import ColumnChart from '../components/ColumnChart.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHead from '../components/PageHead.vue'

const d = ref(null)
const days = ref(0)
const RANGES = [[0, '全部'], [90, '最近 90 天'], [30, '最近 30 天']]

async function load() { d.value = await api.get('/analytics?days=' + days.value) }
watch(days, load)
onMounted(load)

// "A reply" here means a human decision (test, interview, offer or rejection); an automatic receipt is counted separately.
const real = (r) => r.positive + r.rejected
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)
const t = computed(() => d.value.total)
const funnel = computed(() => [
  { label: '投出', value: t.value.n },
  { label: '收到确认信或任何回复', value: t.value.replied },
  { label: '有明确结果（进展或被拒）', value: real(t.value) },
  { label: '笔试 / 面试 / Offer', value: t.value.positive },
])
const monthly = computed(() => d.value.by_month.map((m) => ({ label: m.label.slice(2).replace('-', '/'), value: m.n, tip: m.label + ' 投出' })))
const thin = (r) => r.n < 5
</script>

<template>
  <PageHead title="数据分析" sub="投出去的申请结果怎么样，什么样的岗位更容易有回音，以及哪些机会错过了。">
    <div class="seg"><button v-for="[v, l] in RANGES" :key="v" :class="{ on: days === v }" @click="days = v">{{ l }}</button></div>
  </PageHead>

  <template v-if="d && t.n">
    <div class="grid-4" style="margin-bottom: 16px">
      <div class="stat"><div class="n">{{ t.n }}</div><div class="l">个申请已投出</div></div>
      <div class="stat"><div class="n">{{ pct(real(t), t.n) }}%</div><div class="l">有明确结果（{{ real(t) }} 个）</div></div>
      <div class="stat"><div class="n" :style="t.positive ? 'color: var(--ok)' : ''">{{ pct(t.positive, t.n) }}%</div><div class="l">进入笔试 / 面试（{{ t.positive }} 个）</div></div>
      <div class="stat"><div class="n">{{ d.median_wait_days == null ? '—' : d.median_wait_days ? d.median_wait_days + ' 天' : '当天' }}</div><div class="l">通常多久等到结果（不算自动确认信<span v-if="d.waited">，{{ d.waited }} 个有记录</span>）</div></div>
    </div>

    <div class="cols">
      <div class="card">
        <div class="card-title">申请漏斗</div>
        <p class="muted small" style="margin: 2px 0 14px">每一步还剩多少个申请</p>
        <div class="hbars">
          <template v-for="r in funnel" :key="r.label">
            <span class="lab">{{ r.label }}</span>
            <div class="track" :title="`${r.label}：${r.value} 个`"><div class="fill" :class="{ zero: !r.value }" :style="{ width: pct(r.value, t.n) + '%' }"></div></div>
            <span class="num">{{ r.value }} <span class="muted small" style="font-weight: 400">{{ pct(r.value, t.n) }}%</span></span>
          </template>
        </div>
        <p class="hint" style="margin-top: 14px">被拒 {{ t.rejected }} 个 · 还没有任何回音 {{ t.n - t.replied }} 个</p>
      </div>

      <div class="card">
        <div class="card-title">每个月投了多少</div>
        <p class="muted small" style="margin: 2px 0 14px">按提交月份</p>
        <ColumnChart :data="monthly" unit=" 个" table-label="月份" />
      </div>
    </div>

    <div class="cols">
      <div class="card">
        <div class="card-title">评分高的岗位更容易有回音吗</div>
        <p class="muted small" style="margin: 2px 0 14px">各评分段里，有明确结果的申请占多少。用来检验评分规则准不准。</p>
        <div class="hbars">
          <template v-for="r in d.by_score" :key="r.label">
            <span class="lab">{{ r.label }} 分</span>
            <div class="track rate" :title="`${r.label} 分：投 ${r.n} 个，${real(r)} 个有明确结果，其中 ${r.positive} 个进展`"><div class="fill" :class="{ zero: !real(r) }" :style="{ width: pct(real(r), r.n) + '%' }"></div></div>
            <span class="num">{{ thin(r) ? '—' : pct(real(r), r.n) + '%' }} <span class="muted small" style="font-weight: 400">{{ real(r) }}/{{ r.n }}</span></span>
          </template>
        </div>
        <p class="hint" style="margin-top: 14px">少于 5 个申请的评分段不算比例，样本太少。</p>
      </div>

      <div class="card">
        <div class="card-title">在哪里投的更容易有回音</div>
        <p class="muted small" style="margin: 2px 0 14px">按投递渠道</p>
        <div class="hbars">
          <template v-for="r in d.by_channel" :key="r.label">
            <span class="lab">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${real(r)} 个有明确结果`"><div class="fill" :class="{ zero: !real(r) }" :style="{ width: pct(real(r), r.n) + '%' }"></div></div>
            <span class="num">{{ thin(r) ? '—' : pct(real(r), r.n) + '%' }} <span class="muted small" style="font-weight: 400">{{ real(r) }}/{{ r.n }}</span></span>
          </template>
        </div>
        <div class="card-title" style="margin-top: 22px">按方向</div>
        <div class="hbars" style="margin-top: 12px">
          <template v-for="r in d.by_direction" :key="r.label">
            <span class="lab">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${real(r)} 个有明确结果`"><div class="fill" :class="{ zero: !real(r) }" :style="{ width: pct(real(r), r.n) + '%' }"></div></div>
            <span class="num">{{ thin(r) ? '—' : pct(real(r), r.n) + '%' }} <span class="muted small" style="font-weight: 400">{{ real(r) }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
    </div>

    <div class="cols">
      <div class="card">
        <div class="row"><span class="card-title grow">错过的好岗位</span><span class="badge" :class="d.missed_total ? 'warn' : 'ok'">{{ d.missed_total }} 个</span></div>
        <p class="muted small" style="margin: 2px 0 10px">评分 7.5 以上、但截止或下线时还没投的。</p>
        <div class="list">
          <router-link v-for="m in d.missed" :key="m.id" :to="{ path: '/jobs', query: { open: m.id } }" class="item" style="color: inherit; text-decoration: none">
            <span class="score hi" style="min-width: 28px">{{ m.score.toFixed(1) }}</span>
            <div><div class="main">{{ m.company }}</div><div class="sub">{{ m.title }}</div></div>
            <span class="small muted nowrap">{{ m.why }}</span>
          </router-link>
        </div>
        <EmptyState v-if="!d.missed.length" icon="check" title="没有错过高分岗位" />
      </div>

      <div class="card">
        <div class="card-title">程序替你做了多少</div>
        <div class="grid-3" style="margin: 12px 0 16px">
          <div><div style="font-size: 22px; font-weight: 700">{{ d.automation.reduce((a, r) => a + r.ok, 0) }}</div><div class="small muted">次自动填表成功</div></div>
          <div><div style="font-size: 22px; font-weight: 700">{{ d.automation.reduce((a, r) => a + r.failed, 0) }}</div><div class="small muted">次没有完成</div></div>
          <div><div style="font-size: 22px; font-weight: 700">{{ d.llm.calls }}</div><div class="small muted">次 AI 调用</div></div>
        </div>
        <table v-if="d.automation.length">
          <thead><tr><th>招聘系统</th><th>成功</th><th>没完成</th></tr></thead>
          <tbody><tr v-for="r in d.automation" :key="r.label"><td>{{ r.label }}</td><td>{{ r.ok }}</td><td>{{ r.failed }}</td></tr></tbody>
        </table>
        <p class="hint" style="margin-top: 12px">大部分已投的申请是在用这个程序之前手动投的，所以这里的次数还很少。</p>
      </div>
    </div>
  </template>
  <div v-else-if="d" class="card"><EmptyState icon="activity" title="这段时间没有投出申请" text="换一个时间范围看看。" /></div>
</template>
