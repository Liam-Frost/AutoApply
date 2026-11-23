<script>
// The server's zones and their offsets now, asked for once per open page (again after an hour: offsets change with the
// seasons). A failed request is asked again the next time.
let asked = null
let askedAt = 0
function zonesOnce(get) {
  if (!asked || Date.now() - askedAt > 3600e3) {
    askedAt = Date.now()
    asked = get().catch((e) => { asked = null; throw e })
  }
  return asked
}
let counter = 0
</script>

<script setup>
// The time zone setting (docs/component-guidelines.md, TimeZonePicker): a Combobox of every zone the program knows,
// with "follow this computer" first. What is saved is the IANA id ('' = the computer's), never an offset; the offsets
// shown are the server's (timezones.js says why). A saved value that is not a zone is shown as it is, marked, with a
// line saying what is used instead - it is never replaced by something else without the applicant choosing.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { lang, t as T, tag } from '../i18n/catalog'
import { buildOptions, genericNames, isValidZone, readRecent, rememberZone } from '../timezones'
import Combobox from './Combobox.vue'

defineOptions({ inheritAttrs: false })
const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, default: '' },        // the field's name (default "Time zone")
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue', 'change'])
const uid = 'tzp' + ++counter

const data = ref(null)
const failed = ref(false)
const recent = ref(readRecent())
const generic = ref(new Map())
function load() {
  if (data.value) return
  zonesOnce(() => api.get('/time/zones')).then((d) => { data.value = d; failed.value = false; names() }).catch(() => { failed.value = true })
}
onMounted(load)

// The generic names ("Pacific Time") only help the search, and asking Intl for 600 of them takes a moment: they are
// worked out when the browser has nothing else to do, in English and in the interface language.
let idle = 0
const later = (fn) => (typeof requestIdleCallback === 'function' ? requestIdleCallback(fn, { timeout: 2000 }) : setTimeout(() => fn(null), 60))
function names() {
  if (!data.value) return
  const ids = data.value.zones.map((z) => z.id)
  const locales = [...new Set(['en', tag()])]
  const out = new Map()
  let i = 0
  const work = (deadline) => {
    while (i < ids.length && (!deadline || deadline.timeRemaining() > 2)) { out.set(ids[i], genericNames(ids[i], locales)); i++ }
    if (i < ids.length) idle = later(work); else generic.value = out
  }
  idle = later(work)
}
watch(() => lang.value, names)
onBeforeUnmount(() => { if (typeof cancelIdleCallback === 'function') cancelIdleCallback(idle); else clearTimeout(idle) })

const built = computed(() => (data.value ? buildOptions(data.value, { t: T, locale: tag(), recent: recent.value, generic: generic.value }) : { options: [], groups: [] }))
const invalid = computed(() => !!data.value && !isValidZone(props.modelValue, data.value))
const noted = computed(() => invalid.value || failed.value)

function pick(v) {
  emit('update:modelValue', v)
  emit('change', v)
  if (v) recent.value = rememberZone(v)
}
</script>

<template>
  <div class="tzp">
    <Combobox v-bind="$attrs" :model-value="modelValue" :options="built.options" :groups="built.groups" :label="label || $t('tz.label')"
      :placeholder="$t('tz.followComputer')" :invalid="invalid" :disabled="disabled" :empty-text="data ? $t('tz.none') : $t('tz.loading')"
      :search-placeholder="$t('tz.search')" :width="460" :aria-describedby="noted ? uid + '-note' : undefined" @update:model-value="pick" @open="load" />
    <p v-if="invalid" :id="uid + '-note'" class="cb-note bad">{{ $t('tz.invalid', { zone: modelValue }) }}</p>
    <p v-else-if="failed" :id="uid + '-note'" class="cb-note bad">{{ $t('tz.loadFailed') }}</p>
  </div>
</template>
