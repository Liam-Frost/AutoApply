<script setup>
import { cn } from "@/lib/utils"
const props = defineProps({ class: { type: [String, Array, Object], default: "" } })
</script>

<template>
  <h3 :class="cn('text-lg font-semibold leading-none tracking-tight', props.class)">
    <slot />
  </h3>
</template>
