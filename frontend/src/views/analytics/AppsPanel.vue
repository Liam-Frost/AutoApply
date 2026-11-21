<script setup>
// Applications: what came of them. Every figure here is about the applications SENT in the chosen range (a cohort);
// the one exception - replies by the month they arrived - says so where it is shown.
import { computed, ref, watch } from 'vue'
import { change, pct } from '../../analytics'
import ColumnChart from '../../components/ColumnChart.vue'
import EmptyState from '../../components/EmptyState.vue'
import Explain from '../../components/Explain.vue'
import Icon from '../../components/Icon.vue'
import Pager from '../../components/Pager.vue'
import SplitBar from '../../components/SplitBar.vue'

const props = defineProps({ d: { type: Object, required: true }, params: { type: Object, default: () => ({ bucket: '' }) } })
const t = computed(() => props.d.total)
const STATE_COLOR = { silent: 'var(--chart-other)', receipt: 'var(--chart-soft)', assessment: 'var(--chart-1)', interview: 'var(--chart-deep)', offer: 'var(--ok)', rejected: 'var(--bad)', other: 'var(--neutral-soft)' }
const states = computed(() => props.d.states.map((s) => ({ ...s, color: STATE_COLOR[s.key] })))
// how many were sent along the stretch of time the page is set to: by day, week or month (the server picks by the
// length of the stretch unless one is chosen here)
const SENT_TITLE = { day: '每天投了多少', week: '每周投了多少', month: '每个月投了多少' }
const SENT_SUB = { day: '按投出的日期（本地时间）', week: '按投出的那一周（周一起算，本地时间）', month: '按投出的月份（本地时间）' }
const STEP_HEAD = { day: '日期', week: '哪一周（周一）', month: '月份' }
const steps = computed(() => (props.d.by_time ? props.d.by_time.rows : []))
const size = computed(() => (props.d.by_time ? props.d.by_time.bucket : 'month'))
// (a long stretch by day has more steps than there is room for labels: every few of them are named)
const every = computed(() => Math.max(1, Math.ceil(steps.value.length / 16)))
const monthly = computed(() => steps.value.map((m, i) => ({ label: i % every.value === 0 ? m.label : '', value: m.n, tip: m.key + ' 投出' })))
const wait = computed(() => (props.d.median_wait_days == null ? '—' : props.d.median_wait_days ? props.d.median_wait_days + ' 天' : '当天'))
const rateOf = (r) => (r.thin ? '—' : pct(r.decided, r.n) + '%')

// the months as a chart or as a table: one or the other in the same card, never one under the other
const asTable = ref(false)
const page = ref(0)
const SIZE = 6
const months = computed(() => [...steps.value].reverse())
watch(() => props.d.by_time, () => { page.value = 0 })
</script>

<template>
  <template v-if="t.n">
    <div class="kpis">
      <div class="kpi"><div class="n">{{ t.n }}</div><div class="l">个申请已投出</div><div v-if="d.previous" class="d">{{ change(t.n, d.previous.n) || '上一段没有投出，无从比较' }}</div></div>
      <div class="kpi">
        <div class="n">{{ pct(t.replied, t.n) }}%</div><div class="l">收到回执</div><div class="d">{{ t.replied }} / {{ t.n }} 个</div>
        <Explain>收到回执 = 对方有过任何回应，包括自动发的确认信。分母是这段时间投出的申请。</Explain></div>
      <div class="kpi">
        <div class="n">{{ pct(t.decided, t.n) }}%</div><div class="l">有实质结果</div><div class="d">{{ t.decided }} / {{ t.n }} 个</div>
        <Explain>有实质结果 = 进入过笔试或面试，或者被拒。自动确认信不算。分母是这段时间投出的申请。</Explain></div>
      <div class="kpi">
        <div class="n" :class="{ ok: t.progressed }">{{ pct(t.progressed, t.n) }}%</div><div class="l">进入笔试 / 面试</div><div class="d">{{ t.progressed }} / {{ t.n }} 个</div>
        <Explain>进入过笔试、测评或面试的申请占多少。后来被拒的也算进入过。</Explain></div>
      <div class="kpi">
        <div class="n" :class="{ na: d.median_wait_days == null }">{{ wait }}</div><div class="l">通常多久等到结果</div><div class="d">{{ d.waited ? d.waited + ' 个申请有记录' : '还没有可以计算的记录' }}</div>
        <Explain>从投出到第一封有实质内容的回复（不算自动确认信）隔了多少天，取中位数。</Explain></div>
    </div>
    <p v-if="d.coverage" class="small muted" style="margin: -4px 0 14px">全部已投出 {{ d.coverage.sent }} 份（概览页上的数字），其中 {{ d.coverage.dated }} 份有投递日期，计入这一页按时间的统计<template v-if="d.coverage.undated">；另外 {{ d.coverage.undated }} 份知道投出了、但没有记下是哪一天（从邮件或雇主网站上认出来的，或你手动记的），不在这一页的数字里，<router-link to="/applications">在“我的申请”里</router-link>可以补上日期</template>。</p>

    <div class="an-row c32">
      <div class="card">
        <div class="card-title">申请漏斗</div>
        <p class="card-sub">每一步都是上一步的一部分：投出的里有多少收到了回执，收到回执的里有多少有了实质结果，依此类推。</p>
        <div class="hbars tight even" style="--lab: 13em">
          <template v-for="r in d.funnel" :key="r.key">
            <span class="lab" :title="r.label">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：${r.value} 个，占投出的 ${pct(r.value, t.n)}%`"><div class="fill" :class="{ zero: !r.value }" :style="{ width: pct(r.value, t.n) + '%' }"></div></div>
            <span class="num">{{ r.value }} <span class="muted small" style="font-weight: 400">{{ pct(r.value, t.n) }}%</span></span>
          </template>
        </div>
      </div>
      <div class="card">
        <div class="card-title">现在各在什么状态</div>
        <p class="card-sub">每个申请只算在一处，加起来就是投出的总数。</p>
        <SplitBar :parts="states" rows />
        <div v-if="d.rejected_after_progress" class="card-foot"><span class="hint">被拒的里有 {{ d.rejected_after_progress }} 个进入过笔试或面试。</span></div>
      </div>
    </div>

    <div class="an-row c11">
      <div class="card">
        <div class="card-head">
          <span class="card-title">{{ SENT_TITLE[size] }}</span>
          <div class="seg" aria-label="按多长的时间看"><button v-for="[k, l] in [['', '自动'], ['day', '按天'], ['week', '按周'], ['month', '按月']]" :key="k" :class="{ on: params.bucket === k }" @click="params.bucket = k">{{ l }}</button></div>
          <div class="seg" role="tablist" aria-label="怎么看">
            <button role="tab" :aria-selected="!asTable" :class="{ on: !asTable }" @click="asTable = false"><Icon name="chart" />图表</button>
            <button role="tab" :aria-selected="asTable" :class="{ on: asTable }" @click="asTable = true"><Icon name="table" />表格</button>
          </div>
        </div>
        <p class="card-sub">{{ SENT_SUB[size] }}</p>
        <ColumnChart v-if="!asTable" :data="monthly" unit=" 个" :table="false" />
        <template v-else>
          <table class="an-table">
            <thead><tr><th>{{ STEP_HEAD[size] }}</th><th class="num">投出</th><th class="num">其中已有实质结果</th><th class="num">这段时间收到的回复</th></tr></thead>
            <tbody><tr v-for="m in months.slice(page * SIZE, (page + 1) * SIZE)" :key="m.key"><td>{{ m.key }}</td><td class="num">{{ m.n }}</td><td class="num">{{ m.decided }}</td><td class="num">{{ m.replies }}</td></tr></tbody>
          </table>
          <Pager v-model:page="page" :size="SIZE" :total="months.length" />
          <div class="card-foot"><span class="hint">前两列按投出的时间算（这段时间投的后来怎么样）；最后一列按回复到达的时间算，不看是什么时候投的。</span></div>
        </template>
      </div>
      <div class="card">
        <div class="card-title">评分高的岗位更容易有实质结果吗</div>
        <p class="card-sub">各评分段里，有实质结果的申请占多少。用来检验评分规则准不准，不能说明因果。</p>
        <div class="hbars tight even" style="--lab: 5.5em">
          <template v-for="r in d.by_score" :key="r.label">
            <span class="lab">{{ r.label === '没评分' ? r.label : r.label + ' 分' }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${r.decided} 个有实质结果，其中 ${r.progressed} 个进入过笔试或面试`"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
        <div class="card-foot"><span class="hint">少于 {{ d.min_sample }} 个申请的分组只列数量、不算比例：样本太少。</span></div>
      </div>
    </div>

    <div class="an-row c11">
      <div class="card">
        <div class="card-title">在哪里投的更容易有实质结果</div>
        <p class="card-sub">按投递渠道，有实质结果的占比</p>
        <div class="hbars tight even">
          <template v-for="r in d.by_channel" :key="r.label">
            <span class="lab" :title="r.label">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${r.decided} 个有实质结果`"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
      <div class="card">
        <div class="card-title">哪个方向更容易有实质结果</div>
        <p class="card-sub">按岗位方向，有实质结果的占比</p>
        <div class="hbars tight even">
          <template v-for="r in d.by_direction" :key="r.label">
            <span class="lab" :title="r.label">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${r.decided} 个有实质结果`"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
    </div>
  </template>
  <div v-else class="card"><EmptyState icon="activity" title="这段时间没有投出申请" text="换一个时间范围看看。" /></div>

  <div class="card">
    <div class="card-head"><span class="card-title">错过的好岗位</span><span class="badge" :class="d.missed_total ? 'warn' : 'ok'">{{ d.missed_total }} 个</span></div>
    <p class="card-sub">评分 7.5 以上、截止或下线时还没投的，按评分从高到低。这段时间里第一次看到的岗位才算。</p>
    <div v-if="d.missed.length" class="missed">
      <router-link v-for="m in d.missed" :key="m.id" :to="{ path: '/jobs', query: { open: m.id } }">
        <span class="score hi">{{ m.score.toFixed(1) }}</span>
        <div style="min-width: 0"><div class="main">{{ m.company }}</div><div class="sub">{{ m.title }}</div></div>
        <span class="right"><span class="badge" :class="m.stage === 'expired' ? 'warn' : ''">{{ m.stage === 'expired' ? '已截止' : '已下线' }}</span><div v-if="m.deadline" class="small muted" style="margin-top: 2px">截止 {{ m.deadline }}</div></span>
      </router-link>
    </div>
    <EmptyState v-else icon="check" title="没有错过高分岗位" />
    <p v-if="d.missed_total > d.missed.length" class="hint" style="margin-top: 10px">只列出评分最高的 {{ d.missed.length }} 个。</p>
  </div>
</template>
