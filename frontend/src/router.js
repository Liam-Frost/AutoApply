import { createRouter, createWebHistory } from "vue-router"

import ApplicationsView from "./views/ApplicationsView.vue"
import DashboardView from "./views/DashboardView.vue"
import JobsView from "./views/JobsView.vue"
import MaterialsView from "./views/MaterialsView.vue"
import ProfileView from "./views/ProfileView.vue"
import SettingsView from "./views/SettingsView.vue"

const routes = [
  { path: "/", component: DashboardView, meta: { label: "Dashboard" } },
  { path: "/jobs", component: JobsView, meta: { label: "Jobs" } },
  { path: "/materials", component: MaterialsView, meta: { label: "Materials" } },
  { path: "/applications", component: ApplicationsView, meta: { label: "Applications" } },
  { path: "/profile", component: ProfileView, meta: { label: "Profile" } },
  { path: "/profile/:profileId", component: ProfileView, meta: { label: "Profile" } },
  { path: "/settings", component: SettingsView, meta: { label: "Settings" } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
