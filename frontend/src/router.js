import { createRouter, createWebHistory } from "vue-router"

import ApplicationsView from "./views/ApplicationsView.vue"
import CacheSettingsView from "./views/CacheSettingsView.vue"
import DashboardView from "./views/DashboardView.vue"
import JobsView from "./views/JobsView.vue"
import MaterialsView from "./views/MaterialsView.vue"
import ProfileView from "./views/ProfileView.vue"
import SettingsView from "./views/SettingsView.vue"
import TasksView from "./views/TasksView.vue"
import TemplateEditorView from "./views/TemplateEditorView.vue"
import TemplateLibraryView from "./views/TemplateLibraryView.vue"

const routes = [
  { path: "/", component: DashboardView, meta: { label: "Dashboard" } },
  { path: "/jobs", component: JobsView, meta: { label: "Jobs" } },
  { path: "/materials", component: MaterialsView, meta: { label: "Materials" } },
  {
    path: "/materials/templates",
    component: TemplateLibraryView,
    meta: { label: "Template Library" },
  },
  {
    path: "/materials/templates/:documentType/:templateId",
    component: TemplateEditorView,
    meta: { label: "Edit Template" },
    props: true,
  },
  { path: "/applications", component: ApplicationsView, meta: { label: "Applications" } },
  { path: "/profile", component: ProfileView, meta: { label: "Profile" } },
  { path: "/profile/:profileId", component: ProfileView, meta: { label: "Profile" } },
  { path: "/settings", component: SettingsView, meta: { label: "Settings" } },
  {
    path: "/settings/cache",
    component: CacheSettingsView,
    meta: { label: "Cache" },
  },
  // Phase 14.8 -- task queue operator surface.
  { path: "/tasks", component: TasksView, meta: { label: "Tasks" } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
