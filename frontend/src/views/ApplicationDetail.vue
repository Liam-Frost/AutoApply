<script setup>
// One application, whole: where it stands and what comes next, what shows it was sent, what was sent, the mails
// about it, who you know there, and everything that happened to it - with the things you can do about it in place.
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import AgentJournal from '../components/AgentJournal.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import AaSelect from '../components/Select.vue'
import TechDetails from '../components/TechDetails.vue'
import { ask, fmtTime, run, toast } from '../ui'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const a = ref(null)
const failed = ref('')
const busy = ref('')
const fix = ref({ open: false, status: '', date: '', note: '' })
const others = ref(null)          // mails the program could not put on any application

// where the applicant may put an application by hand: a step that happened outside the program's sight
const BY_HAND = [['submitted', '已提交'], ['confirmed', '雇主已确认收到'], ['assessment', '笔试 / OA / VA'], ['interview', '面试'], ['offer', '收到 Offer'], ['rejected', '已被拒'], ['withdrawn', '不投了']]

async function load() {
  try { a.value = await api.get('/applications/' + props.id); failed.value = '' } catch (e) { failed.value = e.message }
}
// one thing at a time, and the button says so while it runs
// (one action of this page at a time - they all change where the application stands; `busy` names the one under way)
async function act(name, fn, ok) {
  if (busy.value) return false
  busy.value = name
  try { return await run(fn, ok, load) } finally { busy.value = '' }
}
const draftId = computed(() => (a.value && a.value.materials_from_draft) || (a.value && a.value.drafts.length ? a.value.drafts[a.value.drafts.length - 1].id : null))
const can = (k) => !!a.value && a.value.actions.includes(k)

const checkMail = () => act('mail', () => api.post(`/applications/${props.id}/check-mail`), '正在查邮箱；有确认邮件的话，这份申请会记为已投出')
const markSubmitted = () => act('sent', () => api.post(`/applications/${props.id}/mark-submitted`), '已记为“已提交”，稍后会查确认邮件')
const rerun = () => act('rerun', () => api.post(`/jobs/${a.value.job_id}/draft`, {}), 'Agent 已重新开始')
async function rerunNotSubmitted() {
  if (!(await ask('确定这份申请没有提交成功吗？如果其实已经提交了，再做一次会向雇主再投一次。', { ok: '确定没提交，再做一次' }))) return
  await act('rerun', () => api.post(`/applications/${props.id}/not-submitted`), 'Agent 已重新开始')
}

function openFix() {
  fix.value = { open: true, status: a.value.sent || a.value.status === 'withdrawn' ? a.value.status : '', date: a.value.submitted_at ? a.value.submitted_at.slice(0, 10) : '', note: '' }
}
async function saveFix() {
  const body = { note: fix.value.note }
  if (fix.value.status && fix.value.status !== a.value.status) body.status = fix.value.status
  if (fix.value.date && fix.value.date !== (a.value.submitted_at || '').slice(0, 10)) body.submitted_at = fix.value.date + 'T12:00:00'
  if (!body.status && !body.submitted_at && !body.note) { fix.value.open = false; return }
  const r = await act('fix', () => api.post(`/applications/${props.id}/correct`, body), '已记录')
  if (r) fix.value.open = false
}
async function unlink(m) {
  if (!(await ask(`“${m.subject}”不是关于这份申请的？它会回到“需要我处理”里等你指定；这份申请现在的状态不会自动改回去，需要的话在上面“更正记录”里改。`, { ok: '不是这份申请的' }))) return
  await act('unlink', () => api.post(`/applications/${props.id}/mails/unlink`, { message_id: m.message_id }), '已解除关联')
}
async function showOthers() {
  try { others.value = await api.get(`/applications/${props.id}/mail-candidates`) } catch (e) { toast(e.message, 'bad') }
}
async function link(m) {
  await act('link', () => api.post(`/applications/${props.id}/mails/link`, { message_id: m.message_id }), '已关联，这份申请的状态已按邮件更新')
  others.value = null
}
watch(() => props.id, load)
onMounted(load)
</script>

<template>
  <div v-if="!a && !failed" class="empty"><div class="t">正在读取…</div></div>
  <div v-else-if="failed" class="empty"><div class="t">没能读取这份申请</div><div class="muted">{{ failed }}</div>
    <div class="row" style="justify-content: center; margin-top: 8px"><button @click="load">再试一次</button><button class="ghost" @click="router.push('/applications')">回到我的申请</button></div>
  </div>
  <template v-else>
    <PageHead :title="a.company + ' · ' + a.title">
      <template #sub>
        <router-link to="/applications">我的申请</router-link>
        <template v-if="a.location"> · {{ a.location }}</template>
        <template v-if="a.job.apply_url"> · <a :href="a.job.apply_url" target="_blank" rel="noopener">岗位链接 ↗</a></template>
      </template>
      <button @click="openFix"><Icon name="edit" />更正记录</button>
      <router-link :to="{ path: '/jobs', query: { open: a.job_id } }" class="btn">在岗位里查看</router-link>
    </PageHead>

    <!-- where it stands, and what comes next -->
    <div class="card" :class="{ 'callout-card': a.unknown }">
      <div class="row" style="align-items: baseline; flex-wrap: wrap">
        <span class="tag" :class="a.unknown || a.status === 'ready_to_submit' ? 'warn' : a.tone" style="font-size: 14px">{{ a.status_label }}</span>
        <span v-if="a.submitted_at" class="muted">投出于 {{ a.submitted_at.slice(0, 10) }}</span>
        <span v-if="a.auto_approved" class="muted">· 自动批准</span>
      </div>
      <p style="margin: 10px 0 0"><b>接下来：</b>{{ a.next }}</p>
      <div v-if="a.explained.message" class="muted" style="margin-top: 6px">{{ a.explained.message }}</div>
      <TechDetails :text="a.explained.detail" />
      <div v-if="a.actions.length" class="row" style="margin-top: 12px; flex-wrap: wrap">
        <button v-if="can('check_mail')" :class="{ primary: a.unknown }" :disabled="!!busy" @click="checkMail"><Icon name="mail" />{{ busy === 'mail' ? '正在查…' : '现在检查确认邮件' }}</button>
        <button v-if="can('mark_submitted')" :disabled="!!busy" @click="markSubmitted"><Icon name="check" />我已经提交了</button>
        <button v-if="can('rerun')" class="primary" :disabled="!!busy" @click="rerun"><Icon name="refresh" />让 Agent 再做一次</button>
        <button v-if="can('rerun_not_submitted')" class="ghost" :disabled="!!busy" @click="rerunNotSubmitted">没提交成功，让 Agent 再做一次</button>
        <router-link v-if="can('open_draft') && draftId" :to="'/drafts/' + draftId" class="btn primary">打开草案</router-link>
        <router-link v-if="can('open_todos')" to="/todos" class="btn primary">去处理</router-link>
      </div>
      <div v-if="a.cards.length" style="margin-top: 12px">
        <div class="small muted">等你处理：</div>
        <router-link v-for="c in a.cards" :key="c.id" to="/todos" class="tag warn" style="margin: 4px 6px 0 0">{{ c.title }}</router-link>
      </div>
    </div>

    <AgentJournal :journal="a.journal || []" :spent="a.spent" :running-task="a.running_task || 0" :application-id="a.id" note="Agent 在这份申请上途中记下的话；它填了什么、依据是什么，在草案里。" @refresh="load" />

    <div v-if="fix.open" class="card">
      <div class="card-title">更正记录</div>
      <p class="muted" style="margin-top: 0">有些事发生在程序看不到的地方：线下面试、电话通知、自己在官网撤回。在这里记下来；它会作为“你”的记录留在经过里。</p>
      <div class="kv">
        <label for="fix-status">现在的状态</label>
        <AaSelect id="fix-status" v-model="fix.status" aria-label="现在的状态"><option value="">不改</option><option v-for="[k, l] in BY_HAND" :key="k" :value="k">{{ l }}</option></AaSelect>
        <label for="fix-date">投出日期</label>
        <div><input id="fix-date" v-model="fix.date" type="date" style="width: 180px" /> <span class="hint">只有已投出的申请有投出日期</span></div>
        <label for="fix-note">备注（可不填）</label>
        <input id="fix-note" v-model="fix.note" maxlength="300" placeholder="例如：11 月 20 日电话面试" />
      </div>
      <div class="row" style="margin-top: 12px"><button class="primary" :disabled="!!busy" @click="saveFix">{{ busy === 'fix' ? '正在保存…' : '保存' }}</button><button class="ghost" @click="fix.open = false">取消</button></div>
    </div>

    <div class="cols">
      <div>
        <div class="card">
          <div class="card-title">投出的证据</div>
          <template v-if="a.evidence.text || a.evidence.url || a.evidence.mail_ids.length || a.evidence.by_user">
            <div v-if="a.evidence.text || a.evidence.url">
              <div class="small muted">{{ a.evidence.already_applied ? '雇主网站显示这个岗位已经申请过' : '提交后网站显示的内容' }}<template v-if="a.evidence.read_by === 'model'">（由 AI 从页面读出）</template></div>
              <details class="tech" open><summary>{{ a.evidence.url || '页面内容' }}</summary><pre>{{ a.evidence.text }}</pre></details>
              <div v-if="a.evidence.has_screenshot" class="small" style="margin-top: 6px"><a :href="`/api/applications/${a.id}/confirmation.png`" target="_blank" rel="noopener">当时的页面截图</a></div>
            </div>
            <div v-if="a.evidence.mail_ids.length" class="small" style="margin-top: 8px">雇主的确认邮件 {{ a.evidence.mail_ids.length }} 封（见“往来邮件”）</div>
            <div v-if="a.evidence.by_user" class="small" style="margin-top: 8px">有你手动记录的进展（见“全部经过”）</div>
          </template>
          <div v-else class="muted">{{ a.sent ? '没有保存到确认页，也还没有收到确认邮件。' : '还没有投出。' }}</div>
        </div>

        <div class="card">
          <div class="card-title">提交的材料</div>
          <template v-if="a.materials.length">
            <div v-for="(m, i) in a.materials" :key="i" class="row" style="justify-content: space-between; padding: 4px 0">
              <span><span v-if="m.slot" class="muted">{{ m.slot }}：</span>
                <a v-if="m.document_id && m.exists" :href="`api/documents/${m.document_id}/file`" target="_blank" rel="noopener">{{ m.name }}</a>
                <span v-else>{{ m.name }}<span v-if="!m.exists" class="muted">（文件已不在）</span></span>
              </span>
            </div>
            <div class="small muted" style="margin-top: 6px">来自<router-link :to="'/drafts/' + a.materials_from_draft">填表用的那份草案</router-link>；所有答案也在那里。</div>
          </template>
          <div v-else class="muted">这份申请没有上传材料的记录<template v-if="draftId">（<router-link :to="'/drafts/' + draftId">查看草案</router-link>）</template>。</div>
        </div>

        <div class="card">
          <div class="card-title">你认识的人</div>
          <template v-if="a.contacts.length">
            <div v-for="c in a.contacts" :key="c.id" style="padding: 4px 0"><b>{{ c.name }}</b> <span class="muted">{{ [c.role, c.relation].filter(Boolean).join(' · ') }}</span>
              <span v-if="c.follow_up" class="tag" style="margin-left: 6px">跟进 {{ c.follow_up }}</span>
              <div v-if="c.note" class="small muted">{{ c.note }}</div>
            </div>
          </template>
          <div v-else class="muted">人脉里没有这家公司的人。<router-link to="/contacts">去添加</router-link></div>
        </div>
      </div>

      <div>
        <div class="card">
          <div class="card-title">往来邮件</div>
          <template v-if="a.mails.length">
            <div v-for="m in a.mails" :key="m.message_id" style="padding: 6px 0; border-bottom: 1px solid var(--border)">
              <div class="row" style="justify-content: space-between; align-items: baseline">
                <span><span class="tag" :class="m.is_evidence ? 'ok' : ''">{{ m.label }}</span> <b>{{ m.subject }}</b></span>
                <span class="small muted nowrap">{{ fmtTime(m.received_at) }}</span>
              </div>
              <div class="small muted">{{ m.sender }}<template v-if="m.linked_by === 'user'"> · 你指定的关联</template><template v-else-if="m.linked_by === 'site'"> · 按雇主网站上的申请列表关联</template></div>
              <div class="small" style="margin-top: 2px">{{ m.summary }}</div>
              <button class="sm ghost" style="margin-top: 4px" :disabled="!!busy" @click="unlink(m)">不是这份申请的</button>
            </div>
          </template>
          <div v-else class="muted">还没有关联到这份申请的邮件。</div>
          <div style="margin-top: 10px">
            <button v-if="others === null" class="sm" @click="showOthers">有一封邮件其实是这份申请的？</button>
            <template v-else>
              <div class="small muted">程序没能对上申请的邮件（最近 40 封）：</div>
              <div v-for="m in others" :key="m.message_id" class="row" style="justify-content: space-between; padding: 4px 0">
                <span class="small"><span class="tag">{{ m.label }}</span> {{ m.subject }} <span class="muted">{{ fmtTime(m.received_at) }}</span></span>
                <button class="sm" :disabled="!!busy" @click="link(m)">是这份的</button>
              </div>
              <div v-if="!others.length" class="small muted">没有这样的邮件。</div>
            </template>
          </div>
        </div>

        <div class="card">
          <div class="card-title">全部经过</div>
          <div v-for="(e, i) in a.timeline" :key="i" class="row" style="align-items: baseline; padding: 4px 0; gap: 10px">
            <span class="small muted nowrap" style="min-width: 118px">{{ fmtTime(e.at) }}</span>
            <span v-if="e.kind === 'status'" class="small">
              <template v-if="e.old !== e.new">{{ e.old || '新建' }} → <b>{{ e.new }}</b></template><template v-else>{{ e.note }}</template>
              <span v-if="e.by" class="muted">（{{ e.by }}）</span><span v-if="e.note && e.old !== e.new" class="muted"> {{ e.note }}</span>
            </span>
            <span v-else-if="e.kind === 'run'" class="small">{{ e.what }}：<span :class="e.ok ? '' : 'muted'">{{ e.ok ? '完成' : '没有完成' }}</span><span v-if="e.said" class="muted" data-notr>　{{ e.said }}</span> <router-link to="/runs" class="muted">记录</router-link></span>
            <span v-else class="small">邮件：{{ e.label }} <span class="muted">{{ e.subject }}</span></span>
          </div>
          <div v-if="!a.timeline.length" class="muted">还没有记录。</div>
        </div>
      </div>
    </div>
  </template>
</template>
