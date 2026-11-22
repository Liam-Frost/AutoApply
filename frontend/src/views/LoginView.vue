<script setup>
import { t as T } from '../i18n/catalog'
// The door of the program: sign in, or - the first time, on the computer it runs on - choose the administrator's name and password.
import BrandLogo from '../components/BrandLogo.vue'
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
  if (setup.value && password.value !== again.value) { error.value = T('login.theTwoPasswordsAre'); return }
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
      <div class="door-brand full"><BrandLogo /></div>

      <template v-if="setup && !session.canSetup">
        <div class="card-title">{{ $t('login.noAdministratorAccountYet') }}</div>
        <p class="muted">{{ $t('login.theFirstSetUp') }}</p>
        <p class="muted">{{ $t('login.ifThatComputerIs') }}</p>
        <p class="door-cmd"><code data-notr>autoapply set-admin</code></p>
        <p class="door-cmd"><span class="muted">{{ $t('login.inDocker') }}</span> <code data-notr>docker compose exec autoapply autoapply set-admin</code></p>
      </template>
      <template v-else>
        <div class="card-title">{{ setup ? $t('login.setUpTheAdministrator') : $t('login.signIn') }}</div>
        <p v-if="setup" class="muted">{{ $t('login.autoapplyHoldsYourProfile') }}</p>
        <label class="door-field">{{ $t('login.username') }}<input v-model.trim="user" v-focus autocomplete="username" required maxlength="60" /></label>
        <label class="door-field">{{ $t('login.password') }}<input v-model="password" type="password" :autocomplete="setup ? 'new-password' : 'current-password'" required :minlength="setup ? 8 : 1" /></label>
        <label v-if="setup" class="door-field">{{ $t('login.passwordAgain') }}<input v-model="again" type="password" autocomplete="new-password" required /></label>
        <p v-if="setup" class="hint">{{ $t('login.atLeastCharactersIf') }}</p>
        <p v-if="error || mismatch" class="door-error"><Icon name="alert" />{{ error || $t('login.theTwoPasswordsAre') }}</p>
        <button class="primary door-go" type="submit" :disabled="busy || mismatch"><Icon :name="setup ? 'check' : 'login'" />{{ busy ? $t('login.pleaseWait') : setup ? $t('login.saveAndEnter') : $t('login.signIn') }}</button>
      </template>
    </form>
  </div>
</template>
