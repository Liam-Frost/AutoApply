<script setup>
import { t as T } from '../i18n/catalog'
// Choose a model from the service's own list. Typing a name by hand stays possible (new models, private deployments).
import { computed, ref, watch } from 'vue'

const props = defineProps({ modelValue: { type: String, default: '' }, models: { type: Array, default: () => [] }, loading: Boolean, allowEmpty: { type: String, default: '' }, placeholder: { type: String, default: () => T('common.model.pick') } })
const emit = defineEmits(['update:modelValue'])
const manual = ref(false)
// a saved value that the list does not contain is still shown, not silently dropped
const options = computed(() => (props.modelValue && !props.models.includes(props.modelValue) ? [props.modelValue, ...props.models] : props.models))
watch(() => props.models, (m) => { if (m.length) manual.value = false })
</script>

<template>
  <div class="row" style="flex-wrap: nowrap; gap: 6px">
    <template v-if="options.length && !manual">
      <AaSelect class="grow" :model-value="modelValue" :placeholder="placeholder" @update:model-value="emit('update:modelValue', $event)">
        <option v-if="allowEmpty" value="">{{ allowEmpty }}</option>
        <option v-for="m in options" :key="m" :value="m">{{ m }}</option>
      </AaSelect>
      <button class="sm ghost nowrap" :title="$t('common.model.typeHow')" @click="manual = true">{{ $t('common.model.type') }}</button>
    </template>
    <template v-else>
      <input class="grow" :value="modelValue" :placeholder="loading ? $t('common.model.loading') : $t('common.model.name')" @input="emit('update:modelValue', $event.target.value)" />
      <button v-if="options.length" class="sm ghost nowrap" @click="manual = false">{{ $t('common.model.fromList') }}</button>
    </template>
  </div>
</template>
