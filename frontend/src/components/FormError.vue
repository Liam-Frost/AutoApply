<script setup>
// What went wrong the last time this form was sent (ui.run with `form`): it stays next to the button until the form
// is sent again.
import { formErrors } from '../ui'
import Icon from './Icon.vue'

defineProps({ name: { type: String, required: true } })
</script>

<template>
  <div v-if="formErrors[name]" class="form-error" role="alert"><Icon name="alert" /><span>{{ formErrors[name] }}</span></div>
</template>
