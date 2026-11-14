<script setup>
defineProps({ title: { type: String, required: true }, sub: { type: String, default: '' } })
</script>

<template>
  <header class="page-head">
    <div>
      <h2>{{ title }}</h2>
      <div v-if="sub || $slots.sub" class="sub"><slot name="sub">{{ sub }}</slot></div>
    </div>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </header>
</template>
