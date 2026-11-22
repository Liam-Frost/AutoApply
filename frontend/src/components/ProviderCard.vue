<script>
let counter = 0      // ids for the label / field pairs of the settings form: unique on the page, nothing more
</script>

<script setup>
// A sign-in provider (Google, LinkedIn, one the applicant added): one structure whatever is known about it, so that
// cards side by side line up row by row.
//   head    its name (and region), a note behind an (i); under it the state of its saved session
//   body    three facts, each on its own line and each always there (a dash where there is none)
//   foot    the one main action, as wide as the card allows, and a menu with the rest
// What is rarely set - the browser the sign-in is made in, the e-mail of the account there - is in a small form opened
// from the menu. The card does nothing by itself: it says what was asked for (login, forget, remove, save).
import { computed, reactive, ref } from 'vue'
import { t as T } from '../i18n/catalog'
import { asDate, dateOf } from '../i18n/format'
import { fmtTime } from '../ui'
import Icon from './Icon.vue'
import InfoTip from './InfoTip.vue'
import Menu from './Menu.vue'
import Popover from './Popover.vue'
import Status from './Status.vue'
import Trunc from './Trunc.vue'

const props = defineProps({
  provider: { type: Object, required: true },      // { key, name, region, note, custom, email, session: { saved_at, valid_until, expired } | null }
  state: { type: String, default: '' },            // '' | 'trying' (its sign-in window is open) | why the last try did not work
  backend: { type: String, default: '' },          // the browser its sign-in is made in: '' (the site's default) | playwright | nodriver
})
const emit = defineEmits(['login', 'forget', 'remove', 'save'])

const uid = 'pc' + ++counter
const pop = ref(null)
const form = reactive({ backend: '', email: '' })
const session = computed(() => props.provider.session || null)
const waiting = computed(() => props.state === 'trying')

// The state of the saved session. A saved session is not "signed in": the site may have ended it since.
const status = computed(() => {
  const s = session.value
  if (waiting.value) return { tone: 'info', label: T('accounts.signInWindowIs') }
  if (props.state) return { tone: 'bad', label: T('accounts.lastSignInFailed'), tip: T('accounts.lastAttemptFailed', { p0: props.state }) }
  if (!s) return { tone: '', label: T('accounts.notSignedIn') }
  if (s.expired) return { tone: 'warn', label: T('accounts.sessionExpired'), tip: T('accounts.sessionExpiredTip') }
  return { tone: 'ok', label: T('accounts.signedIn'), tip: s.valid_until ? T('accounts.expiresByTip') : T('accounts.noExpiryTip') }
})
const note = computed(() => props.provider.note || (props.provider.custom ? T('accounts.addedByYouJust') : ''))
const until = computed(() => {
  const s = session.value
  if (!s || s.expired) return ''
  return s.valid_until ? dateOf(asDate(s.valid_until)) : T('accounts.noExpiryGiven')
})
const items = computed(() => [
  { id: 'settings', label: T('accounts.signInSettings'), icon: 'settings' },
  { id: 'forget', label: T('accounts.deleteSignInSession'), icon: 'x', disabled: !session.value },
  ...(props.provider.custom ? [{ divider: true }, { id: 'remove', label: T('accounts.removeProvider'), icon: 'trash', danger: true }] : []),
])
function onPick(id) {
  if (id === 'settings') { Object.assign(form, { backend: props.backend || '', email: props.provider.email || '' }); pop.value.open() }
  else emit(id)
}
function save(close) {
  emit('save', { backend: form.backend, email: form.email.trim() })
  close()
}
</script>

<template>
  <article class="pcard" :aria-label="provider.name">
    <header class="pcard-head">
      <div class="pcard-name">
        <Trunc class="pcard-title" :text="provider.name" />
        <span v-if="provider.region" class="meta small">{{ provider.region }}</span>
        <InfoTip v-if="note" :text="note" />
      </div>
      <div class="pcard-state"><Status :tone="status.tone" :label="status.label" :tip="status.tip || ''" /></div>
    </header>

    <dl class="pcard-facts">
      <div><dt>{{ $t('accounts.account') }}</dt><dd><Trunc v-if="provider.email" :text="provider.email" /><span v-else class="none">—</span></dd></div>
      <div><dt>{{ $t('accounts.sessionSavedAt') }}</dt><dd><span v-if="session" class="num">{{ fmtTime(session.saved_at) }}</span><span v-else class="none">—</span></dd></div>
      <div><dt>{{ $t('accounts.expiresBy') }}</dt><dd><Trunc v-if="until" class="num" :text="until" /><span v-else class="none">—</span></dd></div>
    </dl>

    <footer class="pcard-foot">
      <button type="button" class="sm pcard-main" :class="{ primary: !session, waiting }" :disabled="waiting" @click="emit('login')">
        <Icon name="login" />{{ session ? $t('accounts.signInAgain') : $t('accounts.signIn') }}
      </button>
      <Popover ref="pop" :label="$t('accounts.signInSettings')" :width="300" align="end">
        <template #trigger><Menu :label="$t('common.more')" :items="items" @pick="onPick" /></template>
        <template #default="{ close }">
          <div class="field">
            <label :for="uid + '-b'">{{ $t('accounts.signInBrowser') }} <InfoTip :text="$t('accounts.browserHelp')" /></label>
            <AaSelect :id="uid + '-b'" v-model="form.backend">
              <option value="">{{ $t('accounts.followSiteRules') }}</option>
              <option value="playwright">{{ $t('accounts.browserOwn') }}</option>
              <option value="nodriver">{{ $t('accounts.browserOrdinary') }}</option>
            </AaSelect>
          </div>
          <div class="field">
            <label :for="uid + '-e'">{{ $t('accounts.providerEmail') }}</label>
            <input :id="uid + '-e'" v-model="form.email" type="email" autocomplete="off" placeholder="name@example.com" @keydown.enter="save(close)" />
            <span class="hint">{{ $t('accounts.providerEmailHint') }}</span>
          </div>
          <div class="actions pop-actions">
            <button type="button" class="sm" @click="close()">{{ $t('common.cancel') }}</button>
            <button type="button" class="sm primary" @click="save(close)">{{ $t('common.save') }}</button>
          </div>
        </template>
      </Popover>
    </footer>
  </article>
</template>
