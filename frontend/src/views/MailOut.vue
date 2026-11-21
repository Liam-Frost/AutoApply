<script setup>
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
const STATUS = { draft: '还没发', sending: '正在发', sent: '已发出', failed: '上次没有发出去', discarded: '已作废' }
const TONE = { sent: 'ok', failed: 'bad', discarded: '' }

const save = () => run(async () => { m.value = await api.patch(`/mail/out/${props.id}`, form.value) }, '已保存')
async function send() {
  if (!(await ask(`从你的邮箱发给 ${form.value.to}？发出后收不回来。`, { ok: '发送' }))) return
  await run(async () => {
    if (changed.value) m.value = await api.patch(`/mail/out/${props.id}`, form.value)
    m.value = await api.post(`/mail/out/${props.id}/send`)
  }, '已发出')
}
async function discard() {
  if (!(await ask('不发这封邮件了？', { ok: '作废' }))) return
  await run(async () => { await api.post(`/mail/out/${props.id}/discard`); router.push('/todos') }, '已作废')
}
const removeFile = (name) => run(async () => { m.value = await api.patch(`/mail/out/${props.id}`, { remove_attachment: name }) }, '已去掉这个附件')
</script>

<template>
  <PageHead :title="m && m.reply_to ? '回复邮件' : '申请邮件'" :sub="m ? m.about : ''" />
  <DataState :s="st" what="这封邮件" @retry="load" />
  <template v-if="m">
    <div class="card">
      <div class="row" style="margin-bottom: 10px">
        <span class="tag" :class="TONE[m.status]">{{ STATUS[m.status] || m.status }}</span>
        <span v-if="m.sent_at" class="small muted">{{ fmtTime(m.sent_at) }} 从 {{ m.sent_from }} 发出</span>
        <span class="grow"></span>
        <router-link v-if="m.application_id" :to="'/applications/' + m.application_id" class="btn sm">查看这份申请</router-link>
      </div>
      <p v-if="m.status === 'failed' && m.error" class="callout warn"><Icon name="alert" /><span>上次没有发出去：{{ m.error }}</span></p>
      <p v-if="m.can_edit && !m.can_send" class="callout warn"><Icon name="alert" /><span>程序还没有从你的邮箱发信的权限。先到邮箱设置里重新授权一次（授权页会多出“发送邮件”），回来再点发送。</span><router-link to="/settings/accounts/mailbox" class="btn sm">打开邮箱设置</router-link></p>
      <p v-if="m.can_edit && open.length" class="callout warn"><Icon name="edit" /><span>正文里有 {{ open.length }} 处要你自己填（用 [[ ]] 标出来的）：把整个 [[…]] 换成你的回答，填完才能发。</span></p>

      <div class="kv">
        <label for="mo-to">收件人</label>
        <div><input id="mo-to" v-model="form.to" :disabled="!m.can_edit" style="width: 100%" /></div>
        <label for="mo-cc">抄送</label>
        <div><input id="mo-cc" v-model="form.cc" :disabled="!m.can_edit" placeholder="不抄送就留空" style="width: 100%" /></div>
        <label for="mo-subject">主题</label>
        <div><input id="mo-subject" v-model="form.subject" :disabled="!m.can_edit" style="width: 100%" /></div>
        <label for="mo-body">正文</label>
        <div><textarea id="mo-body" v-model="form.body" :disabled="!m.can_edit" rows="16" style="width: 100%; font-family: inherit"></textarea></div>
        <label>附件</label>
        <div>
          <span v-if="!m.attachments.length" class="muted">没有附件</span>
          <div v-for="a in m.attachments" :key="a.name" class="row" style="margin-bottom: 4px">
            <a v-if="a.there" :href="`/api/mail/out/${m.id}/attachment/${encodeURIComponent(a.name)}`" target="_blank" rel="noopener">{{ a.name }}</a>
            <span v-else class="muted">{{ a.name }}（文件不在了）</span>
            <button v-if="m.can_edit" class="sm ghost" @click="removeFile(a.name)">去掉</button>
          </div>
        </div>
      </div>

      <div v-if="m.can_edit" class="acts" style="margin-top: 14px">
        <button class="primary" :disabled="!m.can_send || !!open.length || !form.to || !form.subject || !form.body" @click="send"><Icon name="mail" />从我的邮箱发出</button>
        <button :disabled="!changed" @click="save">保存修改</button>
        <button class="ghost" @click="discard">不发了，作废</button>
      </div>
    </div>
  </template>
</template>
