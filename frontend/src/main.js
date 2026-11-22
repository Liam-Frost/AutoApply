import { createApp, nextTick } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import AaSelect from './components/Select.vue'
import './style.css'
import './styles/foundations.css'
import './styles/table.css'
import './styles/overlay.css'
import './styles/patterns.css'
import { tip } from './tip'
import { loadPersona, persona, session } from './ui'
import { followServerLang, initI18n } from './i18n'
import { i18n } from './i18n/catalog'
import { installGuards } from './dirty'
import { pairSoon } from './labels'
import { api } from './api'
import AnalyticsView from './views/AnalyticsView.vue'
import FilesView from './views/FilesView.vue'
import ContactsView from './views/ContactsView.vue'
import HomeView from './views/HomeView.vue'
import WelcomeView from './views/WelcomeView.vue'
import JobsView from './views/JobsView.vue'
import ApplicationsView from './views/ApplicationsView.vue'
import ApplicationDetail from './views/ApplicationDetail.vue'
import TodosView from './views/TodosView.vue'
import MailOut from './views/MailOut.vue'
import AccountsView from './views/AccountsView.vue'
import ProfileView from './views/ProfileView.vue'
import RunsView from './views/RunsView.vue'
import AboutView from './views/AboutView.vue'
import SettingsView from './views/SettingsView.vue'
import SourcesView from './views/SourcesView.vue'
import RemoteView from './views/RemoteView.vue'
import CalendarView from './views/CalendarView.vue'

// Back and Forward return to where the page was scrolled to - once the page has what it shows (a list that is still
// being read is too short to scroll to the place). Going to another page starts at its top; a change of the query
// alone (a filter, a drawer) leaves the scroll where it is.
const drawn = () => new Promise((resolve) => {
  const t0 = Date.now()
  const look = () => (document.querySelector('.data-wait') && Date.now() - t0 < 2500 ? setTimeout(look, 50) : resolve())
  setTimeout(look, 40)
})
const router = createRouter({
  history: createWebHistory(new URL(document.baseURI).pathname),
  scrollBehavior: async (to, from, saved) => {
    if (saved) { await drawn(); return saved }
    return to.path === from.path ? false : { top: 0 }
  },
  routes: [
    { path: '/', redirect: '/home' },
    { path: '/home', component: HomeView },
    { path: '/contacts', component: ContactsView },
    { path: '/welcome', component: WelcomeView },
    { path: '/files', component: FilesView },
    { path: '/analytics', component: AnalyticsView },
    { path: '/jobs', component: JobsView },
    { path: '/applications', component: ApplicationsView },
    { path: '/applications/:id', component: ApplicationDetail, props: true },
    // The drafts page is the applications page's "waiting for you" group now, and a record is on its application's page.
    { path: '/drafts', redirect: { path: '/applications', query: { group: 'me' } } },
    { path: '/drafts/:id', component: ApplicationsView, beforeEnter: async (to) => {
      try { return { path: '/applications/' + (await api.get('/drafts/' + to.params.id)).application.id, hash: '#record' } } catch { return { path: '/applications' } }
    } },
    { path: '/todos', component: TodosView },
    { path: '/calendar', component: CalendarView },
    { path: '/mail/:id', component: MailOut, props: true },
    { path: '/accounts', component: AccountsView },
    { path: '/profile', component: ProfileView },
    { path: '/runs', component: RunsView },
    { path: '/about', component: AboutView },
    { path: '/settings/:group?/:section?', component: SettingsView },
    { path: '/jobs/sources', component: SourcesView },
    { path: '/remote/:id', component: RemoteView, props: true },
    // the UI lab: every shared component in its states, with made-up data - for development and the layout tests; not in the navigation
    { path: '/ui-lab', component: () => import('./views/lab/LabView.vue') },
  ],
})

installGuards(router)       // what was typed and not saved is asked about before the page is left

// After going to another page the keyboard is at that page's title - not on a link of the sidebar, with the new page
// somewhere behind it. (A query that changed is the same page.)
router.afterEach((to, from) => {
  if (!from.matched.length || to.path === from.path) return
  nextTick(() => {
    const main = document.querySelector('main.content')
    if (!main) return
    const at = main.querySelector('.page-head h2') || main
    at.setAttribute('tabindex', '-1')
    at.focus({ preventScroll: true })
  })
})

// a fresh install goes to the first-run guide before anything else
router.beforeEach(async (to) => {
  if (!session.in) return true      // the login is showing instead of the views; nothing is loaded for them
  if (!persona.loaded) await loadPersona()
  if (!persona.done && to.path !== '/welcome' && !to.path.startsWith('/remote/')) return '/welcome'      // a window that waits for you can be opened from the guide too
})

// (labels.js: a label of a form grid is tied to the control it names - after the page was drawn or drawn again)
createApp(App).component('AaSelect', AaSelect).directive('focus', { mounted: (el) => el.focus() }).directive('tip', tip).mixin({ mounted: pairSoon, updated: pairSoon }).use(router).use(i18n).mount('#app')
initI18n().then(followServerLang)
