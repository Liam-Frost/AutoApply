<script setup>
import { t as T } from '../i18n/catalog'
// Where postings come from: the employers that are watched, what the last scan read, the school's portal. It was
// three cards of the settings; it is looked at and added to all the time, and belongs with the postings.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import EmployersPanel from '../components/EmployersPanel.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import SectionHead from '../components/SectionHead.vue'
import Status from '../components/Status.vue'
import TechDetails from '../components/TechDetails.vue'
import Trunc from '../components/Trunc.vue'
import { fmtTime, persona, run, toast } from '../ui'

// what each source gave when it was last read, why the rest was dropped, and where its postings stand now (discover.report)
const rep = ref({ at: null, sources: [], total: { read: 0, kept: 0, new: 0, dropped: [], now: {} } })
const open = ref('')        // the source whose reasons are shown in full
const bm = ref({ href: '' })
const portal = ref({ on: false, base: '', account: null })
async function load() {
  api.get('/sources/report').then((c) => (rep.value = c)).catch((e) => toast(e.message, 'bad'))
  if (persona.features.portal !== 'ubc') return
  api.get('/import/pdportal/bookmarklet').then((c) => (bm.value = c)).catch(() => {})
  const [st, accounts] = await Promise.all([api.get('/settings'), api.get('/accounts').catch(() => [])])
  portal.value = { on: !!st.settings['sources.pdportal'], base: st.settings['app.base_url'], account: accounts.find((a) => a.tenant_key === 'pdportal:ubc') || null }
}
const setPortal = (on) => run(() => api.put('/settings', { settings: { 'sources.pdportal': on } }), on ? T('sources.pdPortalIsRead') : T('sources.pdPortalIsNo'), load)
const portalLogin = () => run(() => api.post('/accounts/takeover', { tenant_key: 'pdportal:ubc', url: 'https://pdportal.apsc.ubc.ca/home.htm', save_credentials: false }), T('sources.aBrowserWindowIs'), load)
const scanNow = () => run(() => api.post('/tasks', { kind: 'discover' }), T('sources.scanStartedYoullBe'), load)
onMounted(load)
</script>

<template>
  <PageHead :title="$t('sources.sourcesAndWatchedEmployers')" :help="$t('sources.thePostingsAreRead')">
    <router-link to="/jobs" class="btn ghost"><Icon name="back" />{{ $t('sources.backToPostings') }}</router-link>
    <button class="primary" @click="scanNow"><Icon name="refresh" />{{ $t('sources.scanNow') }}</button>
  </PageHead>

  <EmployersPanel />

  <div v-if="persona.features.portal === 'ubc'" class="card">
    <SectionHead title="UBC PD Portal" :help="$t('sources.theProgramReadsThe')">
      <Status v-if="portal.account" :tone="portal.account.status === 'ok' ? 'ok' : 'warn'" :label="portal.account.status === 'ok' ? $t('sources.signedIn') : $t('sources.needsSigningInAgain')" />
      <Status v-else tone="warn" :label="$t('sources.neverSignedIn')" />
      <button @click="portalLogin"><Icon name="login" />{{ $t('sources.signInToPd') }}</button>
    </SectionHead>
    <label class="src-toggle"><input type="checkbox" :checked="portal.on" @change="setPortal($event.target.checked)" /> {{ $t('sources.readPdPortalWhen') }} <span class="hint">{{ $t('sources.appliedAsYouChange') }}</span></label>
    <p class="hint">{{ $t('sources.whenThePortalRefuses') }}<router-link to="/settings/system/browser">{{ $t('sources.settingsSystemAndData') }}</router-link>{{ $t('sources.andTurnTheOrdinary') }}</p>
    <details class="tech"><summary>{{ $t('sources.orImportFromYour') }}</summary>
      <ol class="src-steps">
        <li>{{ $t('sources.putThisButton') }}<b>{{ $t('sources.dragToYourBrowsers') }}</b>：<a v-if="bm.href" :href="bm.href" class="btn sm primary" @click.prevent="toast($t('sources.dragItToThe'))">{{ $t('sources.importToAutoapply') }}</a></li>
        <li>{{ $t('sources.signInToPd2') }}</li>
        <li>{{ $t('sources.clickImportToAutoapply') }}</li>
      </ol>
      <pre>{{ $t('sources.ifTheBookmarksBar', { p0: portal.base }) }}</pre></details>
  </div>

  <div class="card">
    <SectionHead :title="$t('sources.whatEachSourceGave')"><router-link to="/settings/automation/schedule" class="btn sm ghost">{{ $t('sources.howOftenToScan') }}</router-link></SectionHead>
    <p v-if="!rep.at" class="muted">{{ $t('sources.notScannedYet') }}</p>
    <template v-else>
      <p class="t-secondary src-line">{{ $t('sources.latestScanPostingsWere', { p0: fmtTime(rep.at), p1: rep.total.read, p2: rep.total.kept, p3: rep.total.new }) }}</p>
      <p v-if="rep.total.dropped.length" class="src-line src-chips">{{ $t('sources.droppedByTheHard') }}<span v-for="d in rep.total.dropped" :key="d.key" class="meta small">{{ d.label }} <span class="num t-primary">{{ d.n }}</span></span>
        <router-link to="/settings/goals/filters">{{ $t('sources.tryTheConditionsOn') }}</router-link></p>
      <p v-if="rep.total.now.total" class="src-line src-chips">{{ $t('sources.theInTheLibrary', { p0: rep.total.now.total }) }}<Status tone="ok" :label="$t('sources.atOrAboveThe') + ' ' + rep.total.now.above" /><Status :label="$t('sources.belowTheThreshold') + ' ' + rep.total.now.below" /><Status tone="warn" :label="$t('sources.ruledOutByThe') + ' ' + rep.total.now.excluded" /><Status tone="info" :label="$t('sources.notScoredYet') + ' ' + rep.total.now.unscored" /></p>
      <div class="table-wrap src-table">
      <table>
        <thead><tr><th>{{ $t('sources.source') }}</th><th>{{ $t('sources.lastRead2') }}</th><th class="num">{{ $t('sources.read') }}</th><th class="num">{{ $t('sources.passedTheHardConditions') }}</th><th class="num">{{ $t('sources.add') }}</th><th>{{ $t('sources.whyTheRestWas') }}</th><th>{{ $t('sources.inTheLibraryNow') }}</th></tr></thead>
        <tbody>
          <template v-for="r in rep.sources" :key="r.name">
            <tr>
              <td class="src-name"><div class="entity-1"><Trunc class="t-primary" :text="r.name === 'pdportal' ? r.label : r.name" /><span v-if="r.priority" v-tip="$t('sources.priority')" class="mark prio" role="img" :aria-label="$t('sources.priority')"><Icon name="star" /></span></div><Trunc v-if="r.name !== 'pdportal'" as="div" class="t-meta" :text="r.label" /></td>
              <td class="small">
                <template v-if="r.error"><span class="bad-text">{{ $t('sources.couldNotBeRead', { p0: fmtTime(r.error_at) }) }}</span><template v-if="r.fails > 1">{{ $t('sources.timesInARow', { p0: r.fails }) }}</template>
                  <div class="muted">{{ r.ok_at ? $t('sources.lastRead', { p0: fmtTime(r.ok_at) }) : $t('sources.itHasNeverBeen') }}</div></template>
                <template v-else-if="r.ok_at">{{ fmtTime(r.ok_at) }}</template>
                <span v-else class="muted">{{ $t('sources.notReadYet') }}</span>
              </td>
              <td class="num">{{ r.read ?? '—' }}</td><td class="num">{{ r.read == null ? '—' : r.screened ? r.kept : $t('sources.notFiltered') }}</td><td class="num">{{ r.new ?? '—' }}</td>
              <td class="small">
                <template v-if="r.dropped.length">{{ r.dropped[0].label }} {{ r.dropped[0].n }}<button v-if="r.dropped.length > 1" class="sm ghost" :aria-expanded="open === r.name" @click="open = open === r.name ? '' : r.name">{{ open === r.name ? $t('sources.collapse') : $t('sources.more', { p0: r.dropped.length - 1 }) }}</button></template>
                <span v-else-if="r.read != null && !r.screened" class="muted">{{ $t('sources.thisSourceIsNot') }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td class="small"><template v-if="r.now.total">{{ $t('sources.atTheLine') }} <span class="t-primary num">{{ r.now.above }}</span> {{ $t('sources.belowRuledOutNot', { p0: r.now.below, p1: r.now.excluded, p2: r.now.unscored }) }}<div class="muted">{{ $t('sources.threshold', { p0: (r.lines || [r.line]).join(' / ') }) }}</div></template><span v-else class="muted">{{ $t('sources.noOpenPostings') }}</span></td>
            </tr>
            <tr v-if="r.error" class="src-more"><td colspan="7" class="small"><span class="bad-text">{{ r.error }}</span><TechDetails :text="r.error_detail" /></td></tr>
            <tr v-if="open === r.name" class="src-more"><td colspan="7" class="small src-chips"><span v-for="d in r.dropped" :key="d.key" class="meta small">{{ d.label }} <span class="num t-primary">{{ d.n }}</span></span></td></tr>
          </template>
        </tbody>
      </table>
      </div>
      <p class="hint src-foot">{{ $t('sources.passedTheHardConditions2') }}<router-link to="/settings/goals/filters">{{ $t('sources.hardConditionsBeforeIntake') }}</router-link>{{ $t('sources.theThresholdsAreIn') }}<router-link to="/settings/automation/prepare">{{ $t('sources.prepareDraftsAutomatically') }}</router-link>{{ $t('sources.onlyNumbersAreKept') }}</p>
    </template>
  </div>
</template>
