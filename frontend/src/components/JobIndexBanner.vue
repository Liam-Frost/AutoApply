<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { Clock, RefreshCw } from "lucide-vue-next"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

const props = defineProps({
  // Freshness payload mirroring the search form. The parent (JobsView)
  // already collects these so we just hand them through.
  payload: { type: Object, required: true },
  // Caller controls visibility -- only show after the user has actually
  // searched so a first-time page load isn't noisy.
  visible: { type: Boolean, default: false },
})

const emit = defineEmits(["refresh"])

const freshness = ref(null)
const loading = ref(false)
const refreshing = ref(false)
const error = ref("")

const ageLabel = computed(() => {
  if (!freshness.value || !freshness.value.known) {
    return ""
  }
  const hours = freshness.value.age_hours
  if (hours === null || hours === undefined) {
    return "never indexed"
  }
  if (hours < 1) {
    return `${Math.max(1, Math.round(hours * 60))}m ago`
  }
  if (hours < 48) {
    return `${Math.round(hours)}h ago`
  }
  return `${Math.round(hours / 24)}d ago`
})

const statusTone = computed(() => {
  if (!freshness.value || !freshness.value.known) return "neutral"
  if (freshness.value.status === "fresh") return "success"
  if (freshness.value.status === "stale") return "warning"
  return "neutral"
})

async function load() {
  if (!props.visible) return
  loading.value = true
  error.value = ""
  try {
    freshness.value = await api.jobIndexFreshness(props.payload)
  } catch (err) {
    error.value = err.message
    freshness.value = null
  } finally {
    loading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  error.value = ""
  try {
    await api.jobIndexRefresh(props.payload)
    // Tell the parent to re-run its search (the Phase 14 scheduler will
    // satisfy the queued task; in the meantime the search call itself
    // will pull fresh results via the Phase 13.4 force_refresh path).
    emit("refresh")
    // Optimistically reload our own metadata; the actual freshness flip
    // happens after the search completes.
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    refreshing.value = false
  }
}

onMounted(load)
watch(() => props.visible, load)
watch(() => JSON.stringify(props.payload), load)

defineExpose({ reload: load })
</script>

<template>
  <div
    v-if="visible && (freshness || loading || error)"
    class="job-index-banner"
    :data-tone="statusTone"
  >
    <Clock class="h-4 w-4 opacity-70" />
    <div class="job-index-banner-copy">
      <strong v-if="loading">Checking freshness...</strong>
      <strong v-else-if="error">Freshness check failed</strong>
      <strong v-else-if="!freshness?.known">Search not indexed yet</strong>
      <template v-else>
        <strong>Last updated {{ ageLabel }}</strong>
        <span class="muted-inline">
          {{ freshness.result_count }} indexed
          <template v-if="freshness.status !== 'fresh'">
            · status: {{ freshness.status }}
          </template>
        </span>
      </template>
      <span v-if="error" class="muted-inline">{{ error }}</span>
    </div>
    <Button
      type="button"
      variant="ghost"
      size="sm"
      :disabled="refreshing || loading"
      class="ml-auto"
      :title="'Re-fetch from LinkedIn and rebuild the index'"
      @click="refresh"
    >
      <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': refreshing }" />
      {{ refreshing ? "Re-fetching..." : "Re-fetch from LinkedIn" }}
    </Button>
  </div>
</template>

<style scoped>
.job-index-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  background: hsl(var(--muted) / 0.4);
  font-size: 0.875rem;
}
.job-index-banner[data-tone="warning"] {
  border-color: hsl(38 92% 50% / 0.4);
  background: hsl(38 92% 50% / 0.08);
}
.job-index-banner-copy {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  line-height: 1.2;
}
</style>
