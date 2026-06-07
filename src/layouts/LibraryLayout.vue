<template>
  <div class="flex flex-col h-screen bg-gray-900 text-gray-100">
    <!-- Global Header -->
    <header class="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-900 shrink-0 z-10">
      <!-- Left: Logo -->
      <div class="flex items-center space-x-4">
        <div class="font-bold text-xl tracking-tight text-blue-500 flex items-center gap-2">
          <span>Lumina</span>
        </div>

        <!-- Catalog name (read-only, subtle) -->
        <div v-if="activeCatalog" class="text-xs text-gray-500 italic">
          {{ activeCatalog.name }}
        </div>
      </div>

      <!-- Center: Navigation Modes -->
      <nav class="flex space-x-1 bg-gray-800 p-1 rounded-lg">
        <router-link to="/home" class="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200" :class="$route.path === '/home' ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'">Home</router-link>
        <router-link to="/" class="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200" :class="$route.path === '/' ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'">Library</router-link>
        <router-link to="/curate" class="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200" :class="$route.path.startsWith('/curate') ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'">Curate</router-link>
        <router-link to="/import" class="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200" :class="$route.path.startsWith('/import') ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'">Import</router-link>
      </nav>

      <!-- Right: Search, Jobs, Settings, User -->
      <div class="flex items-center space-x-3">
        <div class="relative hidden md:block">
          <SearchIcon class="w-4 h-4 absolute left-2.5 top-2 text-gray-500" />
          <input type="text" placeholder="Search..." class="bg-gray-800 border border-transparent focus:border-blue-500/50 rounded-full py-1.5 pl-9 pr-4 text-sm text-gray-200 focus:ring-2 focus:ring-blue-500/20 outline-none w-48 transition-all" />
        </div>

        <button
          @click="showJobsModal = true"
          class="p-2 text-gray-400 hover:text-white relative rounded-full hover:bg-gray-800 transition-colors"
          title="Background Jobs"
        >
          <ActivityIcon class="w-5 h-5" />
          <span v-if="activeJobCount > 0" class="absolute top-1.5 right-1.5 w-2.5 h-2.5 bg-blue-500 border-2 border-gray-900 rounded-full animate-pulse"></span>
        </button>

        <!-- Settings Dropdown -->
        <div class="relative" v-click-outside="() => showSettingsDropdown = false">
          <button
            @click="showSettingsDropdown = !showSettingsDropdown"
            class="p-2 text-gray-400 hover:text-white rounded-full hover:bg-gray-800 transition-colors"
            title="Settings"
          >
            <SettingsIcon class="w-5 h-5" />
          </button>

          <!-- Settings Menu -->
          <div
            v-if="showSettingsDropdown"
            class="absolute top-full right-0 mt-1 w-56 bg-gray-800 border border-gray-700 rounded-md shadow-xl py-1 z-50"
          >
            <div class="px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wide border-b border-gray-700">
              Catalogs
            </div>
            <div v-if="catalogs.length > 0">
              <button
                v-for="cat in catalogs"
                :key="cat.id"
                @click="selectCatalog(cat.id)"
                class="w-full text-left px-4 py-2 text-sm hover:bg-gray-700 flex items-center justify-between"
                :class="cat.id === activeCatalog?.id ? 'text-blue-400' : 'text-gray-300'"
              >
                <span>{{ cat.name }}</span>
                <CheckIcon v-if="cat.id === activeCatalog?.id" class="w-4 h-4" />
              </button>
            </div>
            <div class="border-t border-gray-700 mt-1 pt-1">
              <button
                @click="openCreateModal"
                class="w-full text-left px-4 py-2 text-sm text-blue-400 hover:bg-gray-700 hover:text-blue-300 flex items-center"
              >
                <PlusIcon class="w-3 h-3 mr-2" /> New Catalog
              </button>
            </div>
          </div>
        </div>

        <button class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-600 to-blue-700 flex items-center justify-center text-xs font-bold text-white shadow-lg hover:shadow-blue-500/20 transition-shadow">
          IJ
        </button>
      </div>
    </header>

    <!-- Main Content Area -->
    <main class="flex-1 overflow-hidden flex relative">
      <slot />
    </main>

    <!-- Modals -->
    <CatalogModal
      :is-open="showCreateModal"
      :is-submitting="catalogStore.isLoading"
      @close="showCreateModal = false"
      @create="handleCreateCatalog"
    />

    <JobsModal
      :is-open="showJobsModal"
      @close="showJobsModal = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { SearchIcon, ActivityIcon, PlusIcon, SettingsIcon, CheckIcon } from 'lucide-vue-next'
import { useJobStore } from '@/stores/jobs'
import { useCatalogStore } from '@/stores/catalog'
import CatalogModal from '@/components/CatalogModal.vue'
import JobsModal from '@/components/JobsModal.vue'

const router = useRouter()

const jobStore = useJobStore()
const catalogStore = useCatalogStore()

const activeJobCount = computed(() => jobStore.activeJobCount)
const catalogs = computed(() => catalogStore.catalogs)
const activeCatalog = computed(() => catalogStore.activeCatalog)

const showCreateModal = ref(false)
const showSettingsDropdown = ref(false)
const showJobsModal = ref(false)

// Click outside directive
const vClickOutside = {
  mounted(el: any, binding: any) {
    el.clickOutsideEvent = (event: Event) => {
      if (!(el === event.target || el.contains(event.target as Node))) {
        binding.value()
      }
    }
    document.addEventListener('click', el.clickOutsideEvent)
  },
  unmounted(el: any) {
    document.removeEventListener('click', el.clickOutsideEvent)
  }
}

onMounted(() => {
  catalogStore.fetchCatalogs()
})

function selectCatalog(id: string) {
  catalogStore.setActiveCatalog(id)
  showSettingsDropdown.value = false
}

function openCreateModal() {
  showCreateModal.value = true
  showSettingsDropdown.value = false
}

const handleCreateCatalog = async (data: { name: string, sourceDirectories: string[] }) => {
  try {
    await catalogStore.createCatalog(data.name, data.sourceDirectories)
    showCreateModal.value = false
    // Redirect to import page to start scanning
    router.push('/import')
  } catch (e: any) {
    console.error('Failed to create catalog:', e)
    alert('Failed to create catalog: ' + (e.message || 'Unknown error'))
  }
}
</script>