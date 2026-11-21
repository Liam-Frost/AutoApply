<script setup>
import { t as T } from '../i18n/catalog'
// A mail the program wrote for the applicant - an application sent by e-mail, a reply to an employer: read it,
// change it, send it from their own mailbox.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import DataState from '../components/DataState.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import { dataState } from '../data'
import { ask, fmtTime, run } from '../ui'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const m = ref(null)
const form = ref({ to: '', cc: '', subject: '', body: '' })

async function read() {
  m.value = await api.get(`/mail/out/${props.id}`)
  form.value = { to: m.value.to, cc: m.value.cc, subject: m.value.subject, body: m.value.body }
}
const { st, load } = dataState(read)
onMounted(load)

const changed = computed(() => m.value && ['to', 'cc', 'subject', 'body'].some((k) => form.value[k] !== m.value[k]))
// what is still to be filled in is read from the text as it stands in the box, not as it was saved
const open = computed(() => [...form.value.body.matchAll(/\[\[([\s\S]*?)\]\]/g)].map((x) => x[1].trim()))
const STATUS = { draft: T('mail.notSentYet'), sending: T('mail.sending'), sent: T('mail.sent'), failed: T('mail.notSentLastTime2'), discarded: T('mail.discarded') }
const TONE = { sent: 'ok', failed: 'bad', discarded: '' }

const save = () => run(async () => { m.value = await api.patch(`/mail/out/${props.id}`, form.value) }, T('mail.saved'))
async function send() {
  if (!(await ask(T('mail.sendToFromYour', { p0: form.value.to }), { ok: T('mail.send') }))) return
  await run(async () => {
    if (changed.value) m.value = await api.patch(`/mail/out/${props.id}`, form.value)
    m.value = await api.post(`/mail/out/${props.id}/send`)
  }, T('mail.sent'))
}
async function discard() {
  if (!(await ask(T('mail.notSendThisE'), { ok: T('mail.discard') }))) return
  await run(async () => { await api.post(`/mail/out/${props.id}/discard`); router.push('/todos') }, T('mail.discarded'))
}
const removeFile = (name) => run(async () => { m.value = await api.patch(`/mail/out/${props.id}`, { remove_attachment: name }) }, T('mail.attachmentRemoved'))
</script>

<template>
  <PageHead :title="m && m.reply_to ? $t('mail.reply') : $t('mail.applicationEMail')" :sub="m ? m.about : ''" />
  <DataState :s="st" :what="$t('mail.thisEMail')" @retry="load" />
  <template v-if="m">
    <div class="card">
      <div class="row" style="margin-bottom: 10px">
        <span class="tag" :class="TONE[m.status]">{{ STATUS[m.status] || m.status }}</span>
        <span v-if="m.sent_at" class="small muted">{{ $t('mail.sentFrom', { p0: fmtTime(m.sent_at), p1: m.sent_from }) }}</span>
        <span class="grow"></span>
        <router-link v-if="m.application_id" :to="'/applications/' + m.application_id" class="btn sm">{{ $t('mail.openThisApplication') }}</router-link>
      </div>
      <p v-if="m.status === 'failed' && m.error" class="callout warn"><Icon name="alert" /><span>{{ $t('mail.notSentLastTime', { p0: m.error }) }}</span></p>
      <p v-if="m.can_edit && !m.can_send" class="callout warn"><Icon name="alert" /><span>{{ $t('mail.theProgramIsNot') }}</span><router-link to="/settings/accounts/mailbox" class="btn sm">{{ $t('mail.openTheMailboxSettings') }}</router-link></p>
      <p v-if="m.can_edit && open.length" class="callout warn"><Icon name="edit" /><span>{{ $t('mail.theTextHasPlace', { p0: open.length }) }}</span></p>

      <div class="kv">
        <label for="mo-to">{{ $t('mail.to') }}</label>
        <div><input id="mo-to" v-model="form.to" :disabled="!m.can_edit" style="width: 100%" /></div>
        <label for="mo-cc">{{ $t('mail.cc') }}</label>
        <div><input id="mo-cc" v-model="form.cc" :disabled="!m.can_edit" :placeholder="$t('mail.leaveEmptyForNo')" style="width: 100%" /></div>
        <label for="mo-subject">{{ $t('mail.subject') }}</label>
        <div><input id="mo-subject" v-model="form.subject" :disabled="!m.can_edit" style="width: 100%" /></div>
        <label for="mo-body">{{ $t('mail.text') }}</label>
        <div><textarea id="mo-body" v-model="form.body" :disabled="!m.can_edit" rows="16" style="width: 100%; font-family: inherit"></textarea></div>
        <label>{{ $t('mail.attachments') }}</label>
        <div>
          <span v-if="!m.attachments.length" class="muted">{{ $t('mail.noAttachments') }}</span>
          <div v-for="a in m.attachments" :key="a.name" class="row" style="margin-bottom: 4px">
            <a v-if="a.there" :href="`/api/mail/out/${m.id}/attachment/${encodeURIComponent(a.name)}`" target="_blank" rel="noopener">{{ a.name }}</a>
            <span v-else class="muted">{{ $t('mail.theFileIsGone', { p0: a.name }) }}</span>
            <button v-if="m.can_edit" class="sm ghost" @click="removeFile(a.name)">{{ $t('mail.remove') }}</button>
          </div>
        </div>
      </div>

      <div v-if="m.can_edit" class="acts" style="margin-top: 14px">
        <button class="primary" :disabled="!m.can_send || !!open.length || !form.to || !form.subject || !form.body" @click="send"><Icon name="mail" />{{ $t('mail.sendFromMyMailbox') }}</button>
        <button :disabled="!changed" @click="save">{{ $t('mail.saveChanges') }}</button>
        <button class="ghost" @click="discard">{{ $t('mail.dontSendDiscard') }}</button>
      </div>
    </div>
  </template>
</template>
