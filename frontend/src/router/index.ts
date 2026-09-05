import { createRouter, createWebHistory } from 'vue-router'

import CanvasView from '@/app/CanvasView.vue'
import LoginView from '@/app/LoginView.vue'
import TemplatesGallery from '@/app/templates/TemplatesGallery.vue'
import ManagerPage from '@/manager/ManagerPage.vue'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: CanvasView },
    { path: '/w/:id', name: 'workflow', component: CanvasView },
    // The layout lives in the URL so an App or Wizard link opens straight into it (design 8.4).
    { path: '/w/:id/:mode', name: 'workflow-mode', component: CanvasView },
    { path: '/templates', name: 'templates', component: TemplatesGallery },
    { path: '/manager', name: 'manager', component: ManagerPage, meta: { admin: true } },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

/**
 * On a `--auth users` server nothing but the login page renders before a session exists, and
 * `/manager` is admin-only because the pack manager installs into the server's own environment
 * (design §12). On a single-user server `probe()` settles on `'single'` and every guard is a
 * no-op, so the desktop tier never sees a redirect.
 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.probe()
  if (auth.requiresLogin) {
    return to.name === 'login' ? true : { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login') return { name: 'home' }
  if (to.meta.admin && !auth.canManagePacks) return { name: 'home' }
  return true
})

export default router
