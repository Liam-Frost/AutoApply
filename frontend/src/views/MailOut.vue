<script setup>
import { t as T } from '../i18n/catalog'
// A mail the program wrote for the applicant - an application sent by e-mail, a reply to an employer: read it,
// change it, send it from their own mailbox.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import DataState from '../components/DataState.vue'
import Icon from '../components/Icon.vue'
import IconButton from '../components/IconButton.vue'
import PageHead from '../components/PageHead.vue'
import Status from '../components/Status.vue'
import Trunc from '../components/Trunc.vue'
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
const TONE = { sent: 'ok', sending: 'info', discarded: '' }

const save = () => run(async () => { m.value = await api.patch(`/mail/out/${props.id}`, form.value) }, T('mail.saved'))
async function send() {
  if (!(await ask(T('mail.sendToFromYour', { p0: form.value.to }), { ok: T('mail.send') }))) return
  await run(async () => {
    if (changed.value) m.value = await api.patch(`/mail/out/${props.id}`, form.value)
    m.value = await api.post(`/mail/out/${props.id}/send`)
  }, T('mail.sent'))
}
async function discard() {
  if (!(await ask(T('mail.notSendThisE'), { ok: T('mail.discard'), danger: true }))) return
  await run(async () => { await api.post(`/mail/out/${props.id}/discard`); router.push('/todos') }, T('mail.discarded'))
}
const removeFile = (name) => run(async () => { m.value = await api.patch(`/mail/out/${props.id}`, { remove_attachment: name }) }, T('mail.attachmentRemoved'))
</script>

<template>
  <!-- (the line under the title is what the mail is about - the application - and leads to it) -->
  <PageHead :title="m && m.reply_to ? $t('mail.reply') : $t('mail.applicationEMail')">
    <template v-if="m && m.about" #sub>
      <router-link v-if="m.application_id" :to="'/applications/' + m.application_id">{{ m.about }}</router-link>
      <template v-else>{{ m.about }}</template>
    </template>
  </PageHead>
  <DataState :s="st" :what="$t('mail.thisEMail')" @retry="load" />
  <template v-if="m">
    <div class="card">
      <div class="actions mo-state">
        <span v-if="m.status === 'failed'" class="tag bad">{{ STATUS.failed }}</span>
        <Status v-else :tone="TONE[m.status]" :label="STATUS[m.status] || m.status" />
        <span v-if="m.sent_at" class="t-meta atomic">{{ $t('mail.sentFrom', { p0: fmtTime(m.sent_at), p1: m.sent_from }) }}</span>
      </div>
      <p v-if="m.status === 'failed' && m.error" class="callout warn"><Icon name="alert" /><span>{{ $t('mail.notSentLastTime', { p0: m.error }) }}</span></p>
      <p v-if="m.can_edit && !m.can_send" class="callout warn"><Icon name="alert" /><span class="grow">{{ $t('mail.theProgramIsNot') }}</span><router-link to="/settings/accounts/mailbox" class="btn sm">{{ $t('mail.openTheMailboxSettings') }}</router-link></p>
      <p v-if="m.can_edit && open.length" class="callout warn"><Icon name="edit" /><span>{{ $t('mail.toFill', { n: open.length }, open.length) }}</span></p>

      <div class="kv">
        <label for="mo-to">{{ $t('mail.to') }}</label>
        <input id="mo-to" v-model="form.to" class="w-full" :disabled="!m.can_edit" />
        <label for="mo-cc">{{ $t('mail.cc') }}</label>
        <input id="mo-cc" v-model="form.cc" class="w-full" :disabled="!m.can_edit" :placeholder="$t('mail.leaveEmptyForNo')" />
        <label for="mo-subject">{{ $t('mail.subject') }}</label>
        <input id="mo-subject" v-model="form.subject" class="w-full" :disabled="!m.can_edit" />
        <label for="mo-body">{{ $t('mail.text') }}</label>
        <textarea id="mo-body" v-model="form.body" class="prose" :disabled="!m.can_edit" rows="16"></textarea>
        <span class="mo-k">{{ $t('mail.attachments') }}</span>
        <div>
          <span v-if="!m.attachments.length" class="none">{{ $t('mail.noAttachments') }}</span>
          <div v-for="a in m.attachments" :key="a.name" class="mo-file">
            <Trunc v-if="a.there" as="a" :href="`/api/mail/out/${m.id}/attachment/${encodeURIComponent(a.name)}`" target="_blank" rel="noopener" :text="a.name" />
            <Trunc v-else class="muted" :text="$t('mail.theFileIsGone', { p0: a.name })" />
            <IconButton v-if="m.can_edit" icon="x" size="sm" :label="$t('mail.removeFile', { name: a.name })" @click="removeFile(a.name)" />
          </div>
        </div>
      </div>

      <div v-if="m.can_edit" class="actions form-acts">
        <button class="ghost" @click="discard">{{ $t('mail.dontSendDiscard') }}</button>
        <span class="grow"></span>
        <button :disabled="!changed" @click="save">{{ $t('mail.saveChanges') }}</button>
        <button class="primary" :disabled="!m.can_send || !!open.length || !form.to || !form.subject || !form.body" @click="send"><Icon name="mail" />{{ $t('mail.sendFromMyMailbox') }}</button>
      </div>
    </div>
  </template>
</template>
