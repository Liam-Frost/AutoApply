<script setup>
// Applications: what came of them. Every figure here is about the applications SENT in the chosen range (a cohort);
// the one exception - replies by the month they arrived - says so where it is shown.
import { computed } from 'vue'
import { change, pct } from '../../analytics'
import ColumnChart from '../../components/ColumnChart.vue'
import EmptyState from '../../components/EmptyState.vue'
import SplitBar from '../../components/SplitBar.vue'

const props = defineProps({ d: { type: Object, required: true } })
const t = computed(() => props.d.total)
const STATE_COLOR = { silent: 'var(--chart-other)', receipt: 'var(--chart-soft)', assessment: 'var(--chart-1)', interview: 'var(--chart-deep)', offer: 'var(--ok)', rejected: 'var(--bad)', other: 'var(--neutral-soft)' }
const states = computed(() => props.d.states.map((s) => ({ ...s, color: STATE_COLOR[s.key] })))
const monthly = computed(() => props.d.by_month.map((m) => ({ label: m.label.slice(2).replace('-', '/'), value: m.n, tip: m.label + ' 投出' })))
const wait = computed(() => (props.d.median_wait_days == null ? '—' : props.d.median_wait_days ? props.d.median_wait_days + ' 天' : '当天'))
const rateOf = (r) => (r.thin ? '—' : pct(r.decided, r.n) + '%')
</script>

<template>
  <template v-if="t.n">
    <div class="kpis">
      <div class="kpi"><div class="n">{{ t.n }}</div><div class="l">个申请已投出</div><div v-if="d.previous" class="d">{{ change(t.n, d.previous.n) || '上一段没有投出，无从比较' }}</div></div>
      <div class="kpi" title="有明确结果 = 进入过笔试或面试，或者被拒。自动确认信不算。分母是这段时间投出的全部申请。">
        <div class="n">{{ pct(t.decided, t.n) }}%</div><div class="l">有明确结果</div><div class="d">{{ t.decided }} / {{ t.n }} 个</div></div>
      <div class="kpi" title="进入过笔试、测评或面试的申请占多少。后来被拒的也算进入过。">
        <div class="n" :class="{ ok: t.progressed }">{{ pct(t.progressed, t.n) }}%</div><div class="l">进入过笔试 / 面试</div><div class="d">{{ t.progressed }} / {{ t.n }} 个</div></div>
      <div class="kpi" title="从投出到第一封有实质内容的回复（不算自动确认信）隔了多少天，取中位数。">
        <div class="n" :class="{ na: d.median_wait_days == null }">{{ wait }}</div><div class="l">通常多久等到结果</div><div class="d">{{ d.waited ? d.waited + ' 个申请有记录' : '还没有可以计算的记录' }}</div></div>
    </div>

    <div class="an-grid">
      <div class="card w7">
        <div class="card-title">申请漏斗</div>
        <p class="card-sub">每一步都是上一步的一部分：投出的里有多少有了回音，有回音的里有多少有了明确结果，依此类推。</p>
        <div class="hbars tight">
          <template v-for="r in d.funnel" :key="r.key">
            <span class="lab">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：${r.value} 个，占投出的 ${pct(r.value, t.n)}%`"><div class="fill" :class="{ zero: !r.value }" :style="{ width: pct(r.value, t.n) + '%' }"></div></div>
            <span class="num">{{ r.value }} <span class="muted small" style="font-weight: 400">{{ pct(r.value, t.n) }}%</span></span>
          </template>
        </div>
      </div>
      <div class="card w5">
        <div class="card-title">现在各在什么状态</div>
        <p class="card-sub">每个申请只算在一处，加起来就是投出的总数。</p>
        <SplitBar :parts="states" rows />
        <p v-if="d.rejected_after_progress" class="hint" style="margin-top: 10px">被拒的里有 {{ d.rejected_after_progress }} 个进入过笔试或面试。</p>
      </div>
    </div>

    <div class="an-grid">
      <div class="card w6">
        <div class="card-title">每个月投了多少</div>
        <p class="card-sub">按投出的月份（本地时间）</p>
        <ColumnChart :data="monthly" unit=" 个" table-label="月份" />
        <details class="tech">
          <summary>每个月的结果和收到的回复</summary>
          <table class="an-table" style="margin-top: 6px">
            <thead><tr><th>月份</th><th class="num">投出</th><th class="num">其中已有明确结果</th><th class="num">当月收到的回复</th></tr></thead>
            <tbody><tr v-for="m in d.by_month" :key="m.label"><td>{{ m.label }}</td><td class="num">{{ m.n }}</td><td class="num">{{ m.decided }}</td><td class="num">{{ m.replies }}</td></tr></tbody>
          </table>
          <p class="hint" style="margin-top: 6px">前两列按投出的月份算（这个月投的后来怎么样）；最后一列按回复到达的月份算，不看是哪个月投的。</p>
        </details>
      </div>
      <div class="card w6">
        <div class="card-title">评分高的岗位更容易有回音吗</div>
        <p class="card-sub">各评分段里，有明确结果的申请占多少。用来检验评分规则准不准，不能说明因果。</p>
        <div class="hbars tight">
          <template v-for="r in d.by_score" :key="r.label">
            <span class="lab">{{ r.label === '没评分' ? r.label : r.label + ' 分' }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${r.decided} 个有明确结果，其中 ${r.progressed} 个进入过笔试或面试`"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
        <p class="hint" style="margin-top: 12px">少于 {{ d.min_sample }} 个申请的分组只列数量、不算比例：样本太少。</p>
      </div>
    </div>

    <div class="an-grid">
      <div class="card w6">
        <div class="card-title">在哪里投的更容易有回音</div>
        <p class="card-sub">按投递渠道，有明确结果的占比</p>
        <div class="hbars tight">
          <template v-for="r in d.by_channel" :key="r.label">
            <span class="lab">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${r.decided} 个有明确结果`"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
      <div class="card w6">
        <div class="card-title">哪个方向更容易有回音</div>
        <p class="card-sub">按岗位方向，有明确结果的占比</p>
        <div class="hbars tight">
          <template v-for="r in d.by_direction" :key="r.label">
            <span class="lab">{{ r.label }}</span>
            <div class="track rate" :title="`${r.label}：投 ${r.n} 个，${r.decided} 个有明确结果`"><div class="fill" :class="{ zero: !r.decided || r.thin }" :style="{ width: (r.thin ? 0 : pct(r.decided, r.n)) + '%' }"></div></div>
            <span class="num">{{ rateOf(r) }} <span class="muted small" style="font-weight: 400">{{ r.decided }}/{{ r.n }}</span></span>
          </template>
        </div>
      </div>
    </div>
  </template>
  <div v-else class="card"><EmptyState icon="activity" title="这段时间没有投出申请" text="换一个时间范围看看。" /></div>

  <div class="card an-tight">
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
