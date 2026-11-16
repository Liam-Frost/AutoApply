<script setup>
// What this computer has and lacks for the program to do its whole job (backend/autoapply/doctor.py).
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { toast } from '../ui'
import Icon from './Icon.vue'

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
    <div class="card-title">这台电脑的状况</div>
    <p class="muted">程序完整工作需要的东西，这台电脑上有哪些、缺哪些。缺的每一项都给出了补上它的命令。</p>
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
    <div class="row" style="margin-top: 12px">
      <button class="sm" :disabled="busy" @click="load(true)"><Icon name="refresh" />{{ busy ? '正在检查…' : '重新检查（并实际启动一次浏览器）' }}</button>
    </div>
  </div>
</template>
