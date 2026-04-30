<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { RouterLink, RouterView, useRoute } from "vue-router"

import AppIcon from "./components/AppIcon.vue"
import DockIcon from "./components/DockIcon.vue"
import { ensureLinkedInSessionLoaded } from "./lib/linkedin-session"

const route = useRoute()
const themeMenuRef = ref(null)
const themePreference = ref("system")
const systemPrefersDark = ref(false)
const themeMenuOpen = ref(false)
const THEME_STORAGE_KEY = "autoapply.theme"

const themeOptions = [
  { value: "system", label: "Follow system", icon: "system" },
  { value: "light", label: "Light mode", icon: "sun" },
  { value: "dark", label: "Dark mode", icon: "moon" },
]

let cleanupThemeListeners = () => {}

const items = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/jobs", label: "Jobs", icon: "jobs" },
  { to: "/materials", label: "Materials", icon: "materials" },
  { to: "/applications", label: "Applications", icon: "applications" },
  { to: "/profile", label: "Profile", icon: "profile" },
  { to: "/settings", label: "Settings", icon: "settings" },
]

const resolvedTheme = computed(() => {
  if (themePreference.value === "system") {
    return systemPrefersDark.value ? "dark" : "light"
  }
  return themePreference.value
})

const themeButtonIcon = computed(() => {
  if (themePreference.value === "system") {
    return "system"
  }
  return resolvedTheme.value === "dark" ? "moon" : "sun"
})

function isActive(item) {
  if (item.to === "/") {
    return route.path === "/"
  }

  return route.path === item.to || route.path.startsWith(`${item.to}/`)
}

function applyTheme() {
  document.documentElement.dataset.theme = resolvedTheme.value
  document.documentElement.style.colorScheme = resolvedTheme.value
  try {
    localStorage.setItem(THEME_STORAGE_KEY, themePreference.value)
  } catch {
    // Ignore storage restrictions and fall back to in-memory theme state.
  }
}

function selectTheme(value) {
  themePreference.value = value
  themeMenuOpen.value = false
}

function toggleThemeMenu() {
  themeMenuOpen.value = !themeMenuOpen.value
}

function onDocumentClick(event) {
  if (!themeMenuRef.value?.contains(event.target)) {
    themeMenuOpen.value = false
  }
}

onMounted(() => {
  let storedTheme = null
  try {
    storedTheme = localStorage.getItem(THEME_STORAGE_KEY)
  } catch {
    storedTheme = null
  }
  if (["system", "light", "dark"].includes(storedTheme)) {
    themePreference.value = storedTheme
  }

  const media = window.matchMedia("(prefers-color-scheme: dark)")
  systemPrefersDark.value = media.matches

  const updateSystemTheme = (event) => {
    systemPrefersDark.value = event.matches
  }

  if (media.addEventListener) {
    media.addEventListener("change", updateSystemTheme)
  } else {
    media.addListener(updateSystemTheme)
  }

  const stopThemeWatch = watch([themePreference, resolvedTheme], applyTheme, { immediate: true })
  document.addEventListener("click", onDocumentClick)
  void ensureLinkedInSessionLoaded()

  cleanupThemeListeners = () => {
    stopThemeWatch()
    document.removeEventListener("click", onDocumentClick)
    if (media.removeEventListener) {
      media.removeEventListener("change", updateSystemTheme)
    } else {
      media.removeListener(updateSystemTheme)
    }
  }
})

onBeforeUnmount(() => {
  cleanupThemeListeners()
})
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

      <div ref="themeMenuRef" class="dock-theme">
        <button
          class="dock-item dock-button"
          :class="{ 'is-active': themeMenuOpen }"
          type="button"
          aria-label="Theme mode"
          title="Theme mode"
          @click.stop="toggleThemeMenu"
        >
          <AppIcon :name="themeButtonIcon" />
        </button>

        <div v-if="themeMenuOpen" class="dock-theme-menu">
          <button
            v-for="option in themeOptions"
            :key="option.value"
            class="dock-theme-item"
            :class="{ 'is-active': themePreference === option.value }"
            type="button"
            :aria-label="option.label"
            :title="option.label"
            @click.stop="selectTheme(option.value)"
          >
            <AppIcon :name="option.icon" />
          </button>
        </div>
      </div>
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
