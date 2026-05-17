<script setup>
// Phase 17.8: shared tab strip across /materials, /materials/library,
// /materials/templates. Lives as its own component so the three views
// don't drift.
import { RouterLink } from "vue-router"
</script>

<template>
  <nav class="flex flex-wrap items-center gap-1 border-b border-border">
    <RouterLink
      to="/materials"
      class="border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
      active-class="!border-primary !text-foreground"
      exact-active-class="!border-primary !text-foreground"
    >
      Generate
    </RouterLink>
    <RouterLink
      to="/materials/library"
      class="border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
      active-class="!border-primary !text-foreground"
    >
      Library
    </RouterLink>
    <RouterLink
      to="/materials/templates"
      class="border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
      active-class="!border-primary !text-foreground"
    >
      Templates
    </RouterLink>
  </nav>
</template>
