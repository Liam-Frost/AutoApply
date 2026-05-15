<script setup>
// Phase 14.8 -- Task queue + HITL gate + Beat schedule operator view.
//
// Intentionally a single page with three small sections rather than a
// "kanban": this is for inspection, not heavy interaction. Approve /
// reject / retry / cancel are one-click buttons; the SPA only renders
// what /api/tasks /api/gate /api/schedule return.

import { onMounted, reactive } from "vue"
import { CheckCircle2, RefreshCw, XCircle, Play } from "lucide-vue-next"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api } from "@/lib/api"

const state = reactive({
  loading: true,
  error: "",
  tasks: [],
  gate: [],
  schedule: [],
  busy: {},
})

async function refreshAll() {
  state.loading = true
  state.error = ""
  try {
    const [tasksResp, gateResp, scheduleResp] = await Promise.all([
      api.get("/api/tasks?limit=50"),
      api.get("/api/gate?status=pending&limit=50"),
      api.get("/api/schedule"),
    ])
    state.tasks = tasksResp.items || []
    state.gate = gateResp || []
    state.schedule = scheduleResp || []
  } catch (err) {
    state.error = err.message
  } finally {
    state.loading = false
  }
}

function statusVariant(status) {
  if (status === "succeeded") return "default"
  if (status === "failed") return "destructive"
  if (status === "waiting_human") return "secondary"
  return "outline"
}

async function decideGate(id, action) {
  state.busy[id] = action
  try {
    await api.post(`/api/gate/${id}/${action}`, { decided_by: "operator" })
    await refreshAll()
  } catch (err) {
    state.error = err.message
  } finally {
    delete state.busy[id]
  }
}

async function runScheduleNow(name) {
  state.busy[name] = "run-now"
  try {
    await api.post(`/api/schedule/${name}/run-now`, {})
    await refreshAll()
  } catch (err) {
    state.error = err.message
  } finally {
    delete state.busy[name]
  }
}

async function retryTask(id) {
  state.busy[id] = "retry"
  try {
    await api.post(`/api/tasks/${id}/retry`, {})
    await refreshAll()
  } catch (err) {
    state.error = err.message
  } finally {
    delete state.busy[id]
  }
}

async function cancelTask(id) {
  state.busy[id] = "cancel"
  try {
    await api.post(`/api/tasks/${id}/cancel`, {})
    await refreshAll()
  } catch (err) {
    state.error = err.message
  } finally {
    delete state.busy[id]
  }
}

onMounted(refreshAll)
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-semibold">Task Queue</h1>
      <Button variant="outline" :disabled="state.loading" @click="refreshAll">
        <RefreshCw class="size-4" :class="state.loading ? 'animate-spin' : ''" />
        Refresh
      </Button>
    </div>

    <Alert v-if="state.error" variant="destructive">
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>

    <!-- HITL gate (top of page; usually empty, but the most urgent) -->
    <Card>
      <CardHeader>
        <CardTitle>Awaiting human ({{ state.gate.length }})</CardTitle>
      </CardHeader>
      <CardContent>
        <p v-if="state.gate.length === 0" class="text-sm text-muted-foreground">
          No gate requests waiting on a decision.
        </p>
        <ul v-else class="divide-y">
          <li
            v-for="g in state.gate"
            :key="g.id"
            class="flex items-start justify-between gap-4 py-3"
          >
            <div class="space-y-1">
              <div class="text-sm font-medium">{{ g.kind }}</div>
              <div class="text-sm text-muted-foreground">{{ g.summary }}</div>
              <div class="text-xs text-muted-foreground">
                requested {{ g.requested_at }}
              </div>
            </div>
            <div class="flex gap-2">
              <Button
                size="sm"
                :disabled="!!state.busy[g.id]"
                @click="decideGate(g.id, 'approve')"
              >
                <CheckCircle2 class="size-4" />Approve
              </Button>
              <Button
                variant="outline"
                size="sm"
                :disabled="!!state.busy[g.id]"
                @click="decideGate(g.id, 'reject')"
              >
                <XCircle class="size-4" />Reject
              </Button>
            </div>
          </li>
        </ul>
      </CardContent>
    </Card>

    <!-- Recent tasks -->
    <Card>
      <CardHeader>
        <CardTitle>Recent tasks</CardTitle>
      </CardHeader>
      <CardContent>
        <p v-if="state.tasks.length === 0" class="text-sm text-muted-foreground">
          No tasks recorded.
        </p>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-muted-foreground">
              <th class="py-2">kind</th>
              <th class="py-2">queue</th>
              <th class="py-2">status</th>
              <th class="py-2">attempts</th>
              <th class="py-2">created</th>
              <th class="py-2 text-right">actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in state.tasks" :key="t.id" class="border-t">
              <td class="py-2 font-mono">{{ t.kind }}</td>
              <td class="py-2">{{ t.queue }}</td>
              <td class="py-2">
                <Badge :variant="statusVariant(t.status)">{{ t.status }}</Badge>
              </td>
              <td class="py-2 tabular-nums">{{ t.attempts }}</td>
              <td class="py-2 text-xs text-muted-foreground">{{ t.created_at }}</td>
              <td class="py-2 text-right">
                <Button
                  v-if="t.status === 'failed' || t.status === 'cancelled'"
                  size="sm"
                  variant="outline"
                  :disabled="!!state.busy[t.id]"
                  @click="retryTask(t.id)"
                >
                  Retry
                </Button>
                <Button
                  v-else-if="t.status === 'queued'"
                  size="sm"
                  variant="outline"
                  :disabled="!!state.busy[t.id]"
                  @click="cancelTask(t.id)"
                >
                  Cancel
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>

    <!-- Beat schedule -->
    <Card>
      <CardHeader>
        <CardTitle>Beat schedule</CardTitle>
      </CardHeader>
      <CardContent>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-muted-foreground">
              <th class="py-2">name</th>
              <th class="py-2">task</th>
              <th class="py-2">queue</th>
              <th class="py-2">cron</th>
              <th class="py-2 text-right">actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in state.schedule" :key="entry.name" class="border-t">
              <td class="py-2 font-mono">{{ entry.name }}</td>
              <td class="py-2 font-mono">{{ entry.task }}</td>
              <td class="py-2">{{ entry.queue }}</td>
              <td class="py-2 text-xs text-muted-foreground">{{ entry.schedule }}</td>
              <td class="py-2 text-right">
                <Button
                  size="sm"
                  variant="outline"
                  :disabled="!!state.busy[entry.name]"
                  @click="runScheduleNow(entry.name)"
                >
                  <Play class="size-4" />Run now
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </CardContent>
    </Card>
  </div>
</template>
