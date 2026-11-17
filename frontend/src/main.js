import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import AaSelect from './components/Select.vue'
import './style.css'
import { loadPersona, persona, session } from './ui'
import { followServerLang, initI18n } from './i18n'
import AnalyticsView from './views/AnalyticsView.vue'
import FilesView from './views/FilesView.vue'
import ContactsView from './views/ContactsView.vue'
import HomeView from './views/HomeView.vue'
import WelcomeView from './views/WelcomeView.vue'
import JobsView from './views/JobsView.vue'
import ApplicationsView from './views/ApplicationsView.vue'
import ApplicationDetail from './views/ApplicationDetail.vue'
import DraftsView from './views/DraftsView.vue'
import DraftDetail from './views/DraftDetail.vue'
import TodosView from './views/TodosView.vue'
import AccountsView from './views/AccountsView.vue'
import ProfileView from './views/ProfileView.vue'
import RunsView from './views/RunsView.vue'
import SettingsView from './views/SettingsView.vue'
import RemoteView from './views/RemoteView.vue'

const router = createRouter({
  history: createWebHistory(new URL(document.baseURI).pathname),
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
    { path: '/drafts', component: DraftsView },
    { path: '/drafts/:id', component: DraftDetail, props: true },
    { path: '/todos', component: TodosView },
    { path: '/accounts', component: AccountsView },
    { path: '/profile', component: ProfileView },
    { path: '/runs', component: RunsView },
    { path: '/settings', component: SettingsView },
    { path: '/remote/:id', component: RemoteView, props: true },
  ],
})

// a fresh install goes to the first-run guide before anything else
router.beforeEach(async (to) => {
  if (!session.in) return true      // the login is showing instead of the views; nothing is loaded for them
  if (!persona.loaded) await loadPersona()
  if (!persona.done && to.path !== '/welcome' && !to.path.startsWith('/remote/')) return '/welcome'      // a window that waits for you can be opened from the guide too
})

createApp(App).component('AaSelect', AaSelect).directive('focus', { mounted: (el) => el.focus() }).use(router).mount('#app')
initI18n().then(followServerLang)
