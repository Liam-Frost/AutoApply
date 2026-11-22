<script setup>
import { t as T } from '../i18n/catalog'
// Choose a model from the service's own list. Typing a name by hand stays possible (new models, private deployments).
// The list takes the room there is and cuts a long model id; the whole id is said on hover when it is cut.
import { computed, ref, watch } from 'vue'
import IconButton from './IconButton.vue'

const props = defineProps({ modelValue: { type: String, default: '' }, models: { type: Array, default: () => [] }, loading: Boolean, allowEmpty: { type: String, default: '' }, placeholder: { type: String, default: () => T('common.model.pick') } })
const emit = defineEmits(['update:modelValue'])
const manual = ref(false)
// a saved value that the list does not contain is still shown, not silently dropped
const options = computed(() => (props.modelValue && !props.models.includes(props.modelValue) ? [props.modelValue, ...props.models] : props.models))
watch(() => props.models, (m) => { if (m.length) manual.value = false })
// (the drop-down cuts its value by itself; whether it is cut is looked at when the pointer comes)
const whole = ref('')
function look(e) { const v = e.currentTarget.querySelector('.sel-val'); whole.value = v && v.scrollWidth > v.clientWidth ? v.textContent : '' }
</script>

<template>
  <div class="model-pick">
    <template v-if="options.length && !manual">
      <span v-tip="whole" class="model-sel" @pointerenter="look">
        <AaSelect :model-value="modelValue" :placeholder="placeholder" @update:model-value="emit('update:modelValue', $event)">
          <option v-if="allowEmpty" value="">{{ allowEmpty }}</option>
          <option v-for="m in options" :key="m" :value="m">{{ m }}</option>
        </AaSelect>
      </span>
      <IconButton icon="edit" :label="$t('common.model.type')" @click="manual = true" />
    </template>
    <template v-else>
      <input :value="modelValue" :placeholder="loading ? $t('common.model.loading') : allowEmpty || $t('common.model.name')" :aria-label="$t('common.model.name')" @input="emit('update:modelValue', $event.target.value)" />
      <IconButton v-if="options.length" icon="menu" :label="$t('common.model.fromList')" @click="manual = false" />
    </template>
  </div>
</template>
