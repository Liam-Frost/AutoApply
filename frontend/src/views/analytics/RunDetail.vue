<script setup>
import { t as T } from '../../i18n/catalog'
// One run of a task: what it came to, and every model request it made. Shown in a drawer, from the automation view
// and from the lists of the AI cost view. `run` needs an id (the task's) and whatever of the row is known.
import { ref, watch } from 'vue'
import { api, fmt } from '../../api'
import { compact, dur, money, ms } from '../../analytics'
import Status from '../../components/Status.vue'
import Trunc from '../../components/Trunc.vue'

const props = defineProps({ run: { type: Object, required: true } })
const rows = ref(null)
const error = ref('')
const TONE = { success: 'ok', handed: 'warn', unknown: 'warn', waiting: 'warn', rerun: 'warn', running: 'info', failed: 'bad', interrupted: 'bad', cancelled: '', skipped: '' }
const STATUS = { ok: T('analytics.run.success'), error: T('analytics.run.error'), refused: T('analytics.run.refused'), timeout: T('analytics.run.timedOut'), rate_limited: T('analytics.run.limitReached'), unavailable: T('analytics.run.serviceUnavailable'), unknown: T('analytics.run.notRecorded') }

watch(() => props.run.id, async (id) => {
  rows.value = null
  error.value = ''
  try {
    const got = (await api.get('/analytics/ai/requests?task_id=' + id)).requests
    if (props.run.id === id) rows.value = got       // an answer for a run that is no longer shown is dropped
  } catch (e) { if (props.run.id === id) error.value = e.message || T('analytics.run.couldNotReadThe') }
}, { immediate: true })
</script>

<template>
  <div class="facts run-facts">
    <div v-if="run.outcome"><div class="k">{{ $t('analytics.run.result') }}</div><div class="v"><Status :tone="TONE[run.outcome]" :label="run.outcome_label" /></div></div>
    <div v-if="run.at"><div class="k">{{ $t('analytics.run.start') }}</div><div class="v atomic">{{ fmt(run.at) }}</div></div>
    <div v-if="run.duration_s != null"><div class="k">{{ $t('analytics.run.duration') }}</div><div class="v">{{ dur(run.duration_s) }}</div></div>
    <div v-if="run.requests != null"><div class="k">{{ $t('analytics.run.aiRequests') }}</div><div class="v">{{ run.requests || 0 }}</div></div>
    <div v-if="run.tokens != null"><div class="k">{{ $t('analytics.page.tokens') }}</div><div class="v">{{ run.tokens ? compact(run.tokens) : '—' }}</div></div>
    <div v-if="run.cost !== undefined"><div class="k">{{ $t('analytics.run.aiCost') }}</div><div class="v">{{ money(run.cost, run.cost_partial && run.cost != null) }}</div></div>
  </div>
  <div v-if="run.reason" class="callout" :class="run.outcome === 'failed' || run.outcome === 'interrupted' ? 'bad' : 'warn'">
    <div><div class="t-primary">{{ run.reason }}</div><div v-if="run.stage" class="t-secondary">{{ $t('analytics.run.stoppedAt', { p0: run.stage }) }}</div></div>
  </div>

  <h4 class="run-title">{{ $t('analytics.run.modelRequestsOfThis') }}</h4>
  <div v-if="error" class="err">{{ error }}</div>
  <div v-else-if="!rows" class="skel"></div>
  <p v-else-if="!rows.length" class="muted">{{ $t('analytics.run.thisRunDidNot') }}</p>
  <div v-else class="an-scroll">
    <table class="an-table two">
      <colgroup><col /><col class="w-state" /><col class="w-xs" /><col class="w-n" /><col class="w-n opt-b" /><col class="w-n opt-b" /><col class="w-n" /><col class="w-n" /><col class="w-num" /></colgroup>
      <thead><tr><th v-tip.overflow>{{ $t('analytics.run.feature') }} · {{ $t('analytics.run.model') }}</th><th v-tip.overflow>{{ $t('analytics.run.status') }}</th><th v-tip.overflow class="num">{{ $t('analytics.run.turns') }}</th><th v-tip.overflow class="num">{{ $t('analytics.run.input') }}</th><th v-tip.overflow class="num opt-b">{{ $t('analytics.run.cacheRead') }}</th><th v-tip.overflow class="num opt-b">{{ $t('analytics.run.cacheWrite') }}</th><th v-tip.overflow class="num">{{ $t('analytics.run.output') }}</th><th v-tip.overflow class="num">{{ $t('analytics.run.duration') }}</th><th v-tip.overflow class="num">{{ $t('analytics.run.cost') }}</th></tr></thead>
      <tbody>
        <tr v-for="q in rows" :key="q.id">
          <td>
            <Trunc as="div" class="t-name" :text="(q.legacy ? $t('analytics.run.totalFromBefore') : q.label) + (q.attempt ? ' · ' + $t('analytics.run.backupServiceAttempt', { p0: q.attempt }) : '')" />
            <Trunc as="div" class="t-sub" :text="[q.model, q.provider_label].filter(Boolean).join(' · ') || '—'" />
          </td>
          <td><Status :tone="q.status === 'ok' ? 'ok' : q.status === 'unknown' ? '' : 'bad'" :label="STATUS[q.status] || q.status" :tip="q.error || ''" /></td>
          <td class="num">{{ q.turns }}</td>
          <td class="num">{{ q.input == null ? '—' : compact(q.input) }}</td>
          <td class="num opt-b">{{ q.cache_read == null ? '—' : compact(q.cache_read) }}</td>
          <td class="num opt-b">{{ q.cache_write == null ? '—' : compact(q.cache_write) }}</td>
          <td class="num">{{ q.output == null ? '—' : compact(q.output) }}</td>
          <td class="num">{{ ms(q.latency_ms) }}</td>
          <td class="num">{{ money(q.cost) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
