import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './pages/Dashboard.vue'
import Review from './pages/Review.vue'
import Reports from './pages/Reports.vue'
import Alarms from './pages/Alarms.vue'
import Settings from './pages/Settings.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', component: Dashboard },
    { path: '/review', component: Review },
    { path: '/reports', component: Reports },
    { path: '/alarms', component: Alarms },
    { path: '/settings', component: Settings },
  ],
})
