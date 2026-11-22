<script setup>
// The password of a site account, in a row or beside a label: one layout for every state, so the column reads down in
// a straight line - what is kept at the start, the one button at the end.
//   saved      eight dots and an eye; shown, the password itself (cut when it is longer than its place) with "copy" and
//              a crossed eye
//   not saved  the words, and a plus that opens the form to add one
// The password is the page's to read and to forget: it arrives here as `value` only while it is shown. It is never
// put into a tooltip or a name (so it is cut without the overflow tooltip other text gets).
import IconButton from '../IconButton.vue'

defineProps({
  saved: Boolean,                               // a password is stored for this account
  value: { type: String, default: null },       // the password, only while it is shown; null otherwise
  loading: Boolean,                             // it is being read
})
const emit = defineEmits(['reveal', 'hide', 'copy', 'add'])
const DOTS = '•'.repeat(8)
</script>

<template>
  <div class="cred" :class="{ shown: saved && value !== null }">
    <span v-if="!saved" class="cred-text none">{{ $t('accounts.notSaved') }}</span>
    <code v-else-if="value !== null" class="cred-text cred-value">{{ value }}</code>
    <span v-else class="cred-text cred-dots" role="img" :aria-label="$t('accounts.passwordSaved')">{{ DOTS }}</span>
    <span class="cred-acts">
      <IconButton v-if="saved && value !== null" icon="copy" :label="$t('accounts.copyPassword')" @click="emit('copy')" />
      <IconButton v-if="saved" :icon="value !== null ? 'eye_off' : 'eye'" :label="value !== null ? $t('accounts.hidePassword') : $t('accounts.showPassword')" :loading="loading"
        @click="value !== null ? emit('hide') : emit('reveal')" />
      <IconButton v-else icon="plus" :label="$t('accounts.addPassword')" @click="emit('add')" />
    </span>
  </div>
</template>
