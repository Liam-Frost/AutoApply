<script setup>
// The door of the program: sign in, or - the first time, on the computer it runs on - choose the administrator's name and password.
import { computed, ref } from 'vue'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import { session } from '../ui'

const emit = defineEmits(['done'])
const user = ref('')
const password = ref('')
const again = ref('')
const error = ref('')
const busy = ref(false)
const setup = computed(() => session.setup)
const mismatch = computed(() => setup.value && again.value !== '' && again.value !== password.value)

async function submit() {
  if (busy.value) return
  error.value = ''
  if (setup.value && password.value !== again.value) { error.value = '两次输入的密码不一样'; return }
  busy.value = true
  try {
    await api.post(setup.value ? '/auth/setup' : '/auth/login', { user: user.value, password: password.value })
    password.value = again.value = ''
    emit('done')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>

<template>
  <div class="door">
    <form class="card door-card" @submit.prevent="submit">
      <div class="door-brand"><img :src="'logo-mark.svg'" alt="" /><span>AutoApply</span></div>

      <template v-if="setup && !session.canSetup">
        <div class="card-title">还没有设置管理员账号</div>
        <p class="muted">第一次设置要在运行 AutoApply 的那台电脑上打开这个页面完成。设置好之后，这里就可以登录了。</p>
        <p class="muted">那台电脑是服务器或容器、没有浏览器的话，在它的终端里运行下面的命令来设置：</p>
        <p><code data-notr>autoapply set-admin</code>　<span class="muted">Docker：</span><code data-notr>docker compose exec autoapply autoapply set-admin</code></p>
      </template>
      <template v-else>
        <div class="card-title">{{ setup ? '设置管理员账号' : '登录' }}</div>
        <p v-if="setup" class="muted">AutoApply 里保存着你的个人资料、申请材料和各网站的登录状态，所以打开页面要先登录。这里设置的是唯一的账号；密码只保存加密后的结果，程序自己也看不到。</p>
        <label class="door-field">用户名<input v-model.trim="user" v-focus autocomplete="username" required maxlength="60" /></label>
        <label class="door-field">密码<input v-model="password" type="password" :autocomplete="setup ? 'new-password' : 'current-password'" required :minlength="setup ? 8 : 1" /></label>
        <label v-if="setup" class="door-field">再输入一次密码<input v-model="again" type="password" autocomplete="new-password" required /></label>
        <p v-if="setup" class="hint">至少 8 个字符。忘记密码时，在这台电脑的托盘图标里选“重置管理员密码”。</p>
        <p v-if="error || mismatch" class="door-error"><Icon name="alert" />{{ error || '两次输入的密码不一样' }}</p>
        <button class="primary door-go" type="submit" :disabled="busy || mismatch"><Icon :name="setup ? 'check' : 'login'" />{{ busy ? '请稍候…' : setup ? '保存并进入' : '登录' }}</button>
      </template>
    </form>
  </div>
</template>
