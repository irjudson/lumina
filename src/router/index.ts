import { createRouter, createWebHistory } from 'vue-router'
import LibraryView from '@/views/LibraryView.vue'
import ImportView from '@/views/ImportView.vue'
import HomeView from '@/views/HomeView.vue'
import CurateView from '@/views/CurateView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'library',
      component: LibraryView
    },
    {
      path: '/home',
      name: 'home',
      component: HomeView
    },
    {
      path: '/curate',
      name: 'curate',
      component: CurateView
    },
    {
      path: '/import',
      name: 'import',
      component: ImportView
    },
  ]
})

export default router
