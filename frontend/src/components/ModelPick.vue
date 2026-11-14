<script setup>
// Choose a model from the service's own list. Typing a name by hand stays possible (new models, private deployments).
import { computed, ref, watch } from 'vue'

const props = defineProps({ modelValue: { type: String, default: '' }, models: { type: Array, default: () => [] }, loading: Boolean, allowEmpty: { type: String, default: '' }, placeholder: { type: String, default: '选一个模型' } })
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
      <button class="sm ghost nowrap" title="列表里没有你要的模型时用" @click="manual = true">手动填写</button>
    </template>
    <template v-else>
      <input class="grow" :value="modelValue" :placeholder="loading ? '正在读取模型列表…' : '填写模型名称'" @input="emit('update:modelValue', $event.target.value)" />
      <button v-if="options.length" class="sm ghost nowrap" @click="manual = false">从列表选</button>
    </template>
  </div>
</template>
