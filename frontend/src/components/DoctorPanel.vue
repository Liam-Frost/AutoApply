<script setup>
// What this computer has and lacks for the program to do its whole job (backend/autoapply/doctor.py).
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import Icon from './Icon.vue'
import CardHead from './CardHead.vue'

const found = ref(null)
const busy = ref(false)
const ICON = { ok: 'check', warn: 'alert', bad: 'x', info: 'info' }
const load = async (deep) => {
  busy.value = true
  try { found.value = await api.get('/doctor' + (deep ? '?deep=true' : '')) } catch (e) { toast(e.message, 'bad') }
  busy.value = false
}
onMounted(() => load(false))
</script>

<template>
  <div class="card">
    <CardHead :title="$t('common.doctor.title')" :help="$t('common.doctor.sub')">
      <button class="sm" :disabled="busy" @click="load(true)"><Icon name="refresh" />{{ busy ? $t('common.doctor.checking') : $t('common.doctor.recheck') }}</button>
    </CardHead>
    <ul v-if="found" class="doctor">
      <li v-for="f in found" :key="f.id">
        <Icon :name="ICON[f.level]" class="mark" :class="f.level" />
        <div>
          <div>{{ f.title }}</div>
          <div v-if="f.detail" class="d">{{ f.detail }}</div>
          <code v-if="f.fix" data-notr>{{ f.fix }}</code>
        </div>
      </li>
    </ul>
  </div>
</template>
