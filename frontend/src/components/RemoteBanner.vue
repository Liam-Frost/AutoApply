<script setup>
// "A window is waiting for you": on a server nobody sees a browser window open, so the page says it, wherever you are in it.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import Icon from './Icon.vue'

const route = useRoute()
const open = ref([])
let timer = null
const load = async () => { try { open.value = await api.get('/remote') } catch (e) { /* signed out, or the server is restarting */ } }
const WHAT = { login: '登录', apply: '申请表' }
onMounted(() => { load(); timer = setInterval(load, 3000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <template v-for="w in open" :key="w.id">
    <div v-if="route.path !== '/remote/' + w.id" class="callout warn rw-banner">
      <Icon name="external" />
      <div class="grow">有一个窗口在等你操作：{{ WHAT[w.purpose] || '窗口' }} <b data-notr>{{ w.title }}</b></div>
      <router-link :to="'/remote/' + w.id" class="btn sm primary">打开窗口</router-link>
    </div>
  </template>
</template>
