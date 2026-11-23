import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import Dashboard from './pages/Dashboard.vue'
import Review from './pages/Review.vue'
import Reports from './pages/Reports.vue'
import Alarms from './pages/Alarms.vue'
import Settings from './pages/Settings.vue'

/* 演示构建部署在 GitHub Pages 子路径下，用 hash 路由避免 404 回退问题 */
const DEMO = import.meta.env.VITE_DEMO === '1'

export default createRouter({
  history: DEMO ? createWebHashHistory() : createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', component: Dashboard },
    { path: '/review', component: Review },
    { path: '/reports', component: Reports },
    { path: '/alarms', component: Alarms },
    { path: '/settings', component: Settings },
  ],
})
