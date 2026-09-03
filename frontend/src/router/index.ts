import { createRouter, createWebHistory } from 'vue-router'

import CanvasView from '@/app/CanvasView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: CanvasView },
    { path: '/w/:id', name: 'workflow', component: CanvasView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
