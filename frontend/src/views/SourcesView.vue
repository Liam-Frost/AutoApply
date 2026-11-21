<script setup>
import { t as T } from '../i18n/catalog'
// Where postings come from: the employers that are watched, what the last scan read, the school's portal. It was
// three cards of the settings; it is looked at and added to all the time, and belongs with the postings.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import EmployersPanel from '../components/EmployersPanel.vue'
import Icon from '../components/Icon.vue'
import PageHead from '../components/PageHead.vue'
import TechDetails from '../components/TechDetails.vue'
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
  <PageHead :title="$t('sources.sourcesAndWatchedEmployers')" :sub="$t('sources.thePostingsAreRead')">
    <router-link to="/jobs" class="btn ghost">{{ $t('sources.backToPostings') }}</router-link>
    <button @click="scanNow"><Icon name="refresh" />{{ $t('sources.scanNow') }}</button>
  </PageHead>

  <EmployersPanel />

  <div v-if="persona.features.portal === 'ubc'" class="card">
    <div class="row"><span class="card-title grow">UBC PD Portal</span>
      <span v-if="portal.account" class="badge" :class="portal.account.status === 'ok' ? 'ok' : 'warn'">{{ portal.account.status === 'ok' ? $t('sources.signedIn') : $t('sources.needsSigningInAgain') }}</span>
      <span v-else class="badge warn">{{ $t('sources.neverSignedIn') }}</span></div>
    <p class="muted">{{ $t('sources.theProgramReadsThe') }}</p>
    <div class="row" style="flex-wrap: wrap">
      <label><input type="checkbox" :checked="portal.on" @change="setPortal($event.target.checked)" /> {{ $t('sources.readPdPortalWhen') }} <span class="hint">{{ $t('sources.appliedAsYouChange') }}</span></label>
      <button class="primary" @click="portalLogin"><Icon name="login" />{{ $t('sources.signInToPd') }}</button>
    </div>
    <p class="hint">{{ $t('sources.whenThePortalRefuses') }}<router-link to="/settings/system/browser">{{ $t('sources.settingsSystemAndData') }}</router-link>{{ $t('sources.andTurnTheOrdinary') }}</p>
    <details class="tech"><summary>{{ $t('sources.orImportFromYour') }}</summary>
      <ol class="small" style="margin: 8px 0 10px; padding-left: 20px; line-height: 1.9">
        <li>{{ $t('sources.putThisButton') }}<b>{{ $t('sources.dragToYourBrowsers') }}</b>：<a v-if="bm.href" :href="bm.href" class="btn sm primary" @click.prevent="toast($t('sources.dragItToThe'))">{{ $t('sources.importToAutoapply') }}</a></li>
        <li>{{ $t('sources.signInToPd2') }}</li>
        <li>{{ $t('sources.clickImportToAutoapply') }}</li>
      </ol>
      <pre>{{ $t('sources.ifTheBookmarksBar', { p0: portal.base }) }}</pre></details>
  </div>

  <div class="card">
    <div class="row"><span class="card-title grow">{{ $t('sources.whatEachSourceGave') }}</span><router-link to="/settings/automation/schedule" class="small">{{ $t('sources.howOftenToScan') }}</router-link></div>
    <p v-if="!rep.at" class="muted">{{ $t('sources.notScannedYet') }}</p>
    <template v-else>
      <p class="muted" style="margin-bottom: 6px">{{ $t('sources.latestScanPostingsWere', { p0: fmtTime(rep.at), p1: rep.total.read, p2: rep.total.kept, p3: rep.total.new }) }}</p>
      <p v-if="rep.total.dropped.length" class="small" style="margin: 0 0 4px">{{ $t('sources.droppedByTheHard') }}<span v-for="d in rep.total.dropped" :key="d.key" class="tag" style="margin: 0 6px 4px 0">{{ d.label }} <b>{{ d.n }}</b></span>
        <router-link to="/settings/goals/filters">{{ $t('sources.tryTheConditionsOn') }}</router-link></p>
      <p v-if="rep.total.now.total" class="small" style="margin: 0 0 10px">{{ $t('sources.theInTheLibrary', { p0: rep.total.now.total }) }}<span class="tag ok" style="margin-right: 6px">{{ $t('sources.atOrAboveThe') }} <b>{{ rep.total.now.above }}</b></span><span class="tag" style="margin-right: 6px">{{ $t('sources.belowTheThreshold') }} <b>{{ rep.total.now.below }}</b></span><span class="tag warn" style="margin-right: 6px">{{ $t('sources.ruledOutByThe') }} <b>{{ rep.total.now.excluded }}</b></span><span class="tag info">{{ $t('sources.notScoredYet') }} <b>{{ rep.total.now.unscored }}</b></span></p>
      <table>
        <thead><tr><th>{{ $t('sources.source') }}</th><th>{{ $t('sources.lastRead2') }}</th><th class="num">{{ $t('sources.read') }}</th><th class="num">{{ $t('sources.passedTheHardConditions') }}</th><th class="num">{{ $t('sources.add') }}</th><th>{{ $t('sources.whyTheRestWas') }}</th><th>{{ $t('sources.inTheLibraryNow') }}</th></tr></thead>
        <tbody>
          <template v-for="r in rep.sources" :key="r.name">
            <tr>
              <td><b>{{ r.name === 'pdportal' ? r.label : r.name }}</b><span v-if="r.priority" class="tag" style="margin-left: 6px">{{ $t('sources.priority') }}</span><div v-if="r.name !== 'pdportal'" class="small muted">{{ r.label }}</div></td>
              <td class="small">
                <template v-if="r.error"><span style="color: var(--bad)">{{ $t('sources.couldNotBeRead', { p0: fmtTime(r.error_at) }) }}</span><template v-if="r.fails > 1">{{ $t('sources.timesInARow', { p0: r.fails }) }}</template>
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
              <td class="small"><template v-if="r.now.total">{{ $t('sources.atTheLine') }} <b>{{ r.now.above }}</b> {{ $t('sources.belowRuledOutNot', { p0: r.now.below, p1: r.now.excluded, p2: r.now.unscored }) }}<div class="muted">{{ $t('sources.threshold', { p0: (r.lines || [r.line]).join(' / ') }) }}</div></template><span v-else class="muted">{{ $t('sources.noOpenPostings') }}</span></td>
            </tr>
            <tr v-if="r.error"><td colspan="7" class="small" style="border-top: 0; padding-top: 0"><span style="color: var(--bad)">{{ r.error }}</span><TechDetails :text="r.error_detail" /></td></tr>
            <tr v-if="open === r.name"><td colspan="7" class="small" style="border-top: 0; padding-top: 0"><span v-for="d in r.dropped" :key="d.key" class="tag" style="margin: 0 6px 4px 0">{{ d.label }} <b>{{ d.n }}</b></span></td></tr>
          </template>
        </tbody>
      </table>
      <p class="hint" style="margin-top: 8px">{{ $t('sources.passedTheHardConditions2') }}<router-link to="/settings/goals/filters">{{ $t('sources.hardConditionsBeforeIntake') }}</router-link>{{ $t('sources.theThresholdsAreIn') }}<router-link to="/settings/automation/prepare">{{ $t('sources.prepareDraftsAutomatically') }}</router-link>{{ $t('sources.onlyNumbersAreKept') }}</p>
    </template>
  </div>
</template>
