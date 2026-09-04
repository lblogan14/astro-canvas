import { createRouter, createWebHistory } from 'vue-router'

import CanvasView from '@/app/CanvasView.vue'
import TemplatesGallery from '@/app/templates/TemplatesGallery.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: CanvasView },
    { path: '/w/:id', name: 'workflow', component: CanvasView },
    // The layout lives in the URL so an App or Wizard link opens straight into it (design 8.4).
    { path: '/w/:id/:mode', name: 'workflow-mode', component: CanvasView },
    { path: '/templates', name: 'templates', component: TemplatesGallery },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
