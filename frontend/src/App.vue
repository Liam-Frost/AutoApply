<script setup>
import { RouterLink, RouterView, useRoute } from "vue-router"

import DockIcon from "./components/DockIcon.vue"

const route = useRoute()

const items = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/jobs", label: "Jobs", icon: "jobs" },
  { to: "/applications", label: "Applications", icon: "applications" },
  { to: "/profile", label: "Profile", icon: "profile" },
  { to: "/settings", label: "Settings", icon: "settings" },
]

function isActive(item) {
  if (item.to === "/") {
    return route.path === "/"
  }

  return route.path === item.to || route.path.startsWith(`${item.to}/`)
}
</script>

<template>
  <div class="app-shell">
    <aside class="dock" aria-label="Primary navigation">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        class="dock-item"
        :class="{ 'is-active': isActive(item) }"
        :aria-label="item.label"
      >
        <DockIcon :name="item.icon" />
      </RouterLink>
    </aside>

    <main class="workspace">
      <header class="page-header">
        <span class="page-eyebrow">AutoApply</span>
        <h1 class="page-title">{{ route.meta.label }}</h1>
      </header>

      <RouterView />
    </main>
  </div>
</template>
