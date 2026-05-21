<template>
  <div class="h-full flex flex-col bg-gray-900 border-r border-gray-800">
    <!-- Header -->
    <div class="p-4 border-b border-gray-800">
      <h2 class="text-lg font-semibold text-gray-200">Lumina</h2>
      <p class="text-xs text-gray-500 mt-1">{{ catalogName }}</p>
    </div>

    <!-- Navigation Sections -->
    <div class="flex-1 overflow-y-auto">
      <!-- Primary Views -->
      <nav class="p-3 space-y-1">
        <h3 class="text-xs font-semibold text-gray-500 uppercase tracking-wide px-3 py-2">
          Library
        </h3>
        <NavItem
          icon="Images"
          label="All Photos"
          :active="activeView === 'all'"
          @click="$emit('navigate', 'all')"
        />
        <NavItem
          icon="Calendar"
          label="Timeline"
          :active="activeView === 'timeline'"
          @click="$emit('navigate', 'timeline')"
        />
        <NavItem
          icon="Map"
          label="Map"
          :active="activeView === 'map'"
          @click="$emit('navigate', 'map')"
        />
        <NavItem
          icon="Star"
          label="Favorites"
          :count="counts.favorites"
          :active="activeView === 'favorites'"
          @click="$emit('navigate', 'favorites')"
        />
        <NavItem
          icon="BarChart2"
          label="Analytics"
          :active="activeView === 'analytics'"
          @click="$emit('navigate', 'analytics')"
        />
      </nav>

      <!-- Smart Views (collapsible) -->
      <nav class="border-t border-gray-800 mt-2">
        <button
          @click="smartViewsOpen = !smartViewsOpen"
          class="w-full flex items-center justify-between px-6 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:text-gray-400 transition-colors"
        >
          <span>Smart Views</span>
          <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': smartViewsOpen }" />
        </button>
        <div v-if="smartViewsOpen" class="px-3 pb-2 space-y-1">
          <NavItem
            icon="PartyPopper"
            label="Events"
            :count="counts.events"
            :active="activeView === 'events'"
            @click="$emit('navigate', 'events')"
          />
          <NavItem
            icon="Zap"
            label="Bursts"
            :count="counts.bursts"
            :active="activeView === 'bursts'"
            @click="$emit('navigate', 'bursts')"
          />
          <NavItem
            icon="Copy"
            label="Duplicates"
            :count="counts.duplicates"
            :active="activeView === 'duplicates'"
            @click="$emit('navigate', 'duplicates')"
          />
          <NavItem
            icon="Monitor"
            label="Screenshots"
            :count="counts.screenshots"
            :active="activeView === 'screenshots'"
            @click="$emit('navigate', 'screenshots')"
          />
          <NavItem
            icon="FileText"
            label="Documents"
            :count="counts.documents"
            :active="activeView === 'documents'"
            @click="$emit('navigate', 'documents')"
          />
          <NavItem
            icon="Trash2"
            label="Noise"
            :count="counts.noise"
            :active="activeView === 'noise'"
            @click="$emit('navigate', 'noise')"
          />
          <NavItem
            icon="Clock"
            label="Recent"
            :count="counts.recent"
            :active="activeView === 'recent'"
            @click="$emit('navigate', 'recent')"
          />
          <NavItem
            icon="Tag"
            label="Untagged"
            :count="counts.untagged"
            :active="activeView === 'untagged'"
            @click="$emit('navigate', 'untagged')"
          />
          <NavItem
            icon="AlertCircle"
            label="Needs Review"
            :count="counts.needs_review"
            :active="activeView === 'needs-review'"
            @click="$emit('navigate', 'needs-review')"
          />
          <NavItem
            icon="Trash2"
            label="Rejected"
            :count="counts.rejected"
            :active="activeView === 'rejected'"
            @click="$emit('navigate', 'rejected')"
          />
          <NavItem
            icon="Video"
            label="Videos"
            :count="counts.videos"
            :active="activeView === 'videos'"
            @click="$emit('navigate', 'videos')"
          />
          <NavItem
            icon="CopyX"
            label="Skipped Imports"
            :count="counts.skipped_imports"
            :active="activeView === 'skipped_imports'"
            @click="$emit('navigate', 'skipped_imports')"
          />
        </div>
      </nav>

      <!-- Tags Filter (collapsible) -->
      <nav v-if="availableTags.length > 0" class="border-t border-gray-800 mt-2">
        <button
          @click="tagsOpen = !tagsOpen"
          class="w-full flex items-center justify-between px-6 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:text-gray-400 transition-colors"
        >
          <span>Filter by Tag</span>
          <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': tagsOpen }" />
        </button>
        <div v-if="tagsOpen" class="px-3 pb-2">
          <TagBrowser
            :tags="availableTags"
            :selected-tags="selectedTags"
            @update:selected-tags="$emit('filter-tags', $event)"
          />
        </div>
      </nav>

      <!-- Categories (system collections, collapsible) -->
      <nav v-if="systemCollections.length > 0" class="border-t border-gray-800 mt-2">
        <button
          @click="categoriesOpen = !categoriesOpen"
          class="w-full flex items-center justify-between px-6 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:text-gray-400 transition-colors"
        >
          <span>Categories</span>
          <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': categoriesOpen }" />
        </button>
        <div v-if="categoriesOpen" class="px-3 pb-2 space-y-1">
          <div
            v-for="col in systemCollections"
            :key="col.id"
            class="flex items-center gap-1"
          >
            <NavItem
              icon="Layers"
              :label="col.name"
              :count="col.imageCount"
              :active="activeView === `collection:${col.id}`"
              class="flex-1 min-w-0"
              @click="$emit('navigate', `collection:${col.id}`)"
            />
            <span
              v-if="col.pendingCount > 0"
              class="shrink-0 px-1.5 py-0.5 text-xs rounded-full bg-amber-600/30 text-amber-400 font-medium"
              :title="`${col.pendingCount} unreviewed suggestions`"
            >{{ col.pendingCount }}</span>
          </div>
        </div>
      </nav>

      <!-- Collections (user collections, collapsible) -->
      <nav class="border-t border-gray-800 mt-2">
        <button
          @click="collectionsOpen = !collectionsOpen"
          class="w-full flex items-center justify-between px-6 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:text-gray-400 transition-colors"
        >
          <span>Collections</span>
          <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': collectionsOpen }" />
        </button>
        <div v-if="collectionsOpen" class="px-3 pb-2 space-y-1">
          <button
            @click="$emit('create-collection')"
            class="w-full px-3 py-2 text-left text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded transition-colors flex items-center gap-2"
          >
            <PlusIcon class="w-4 h-4" />
            <span>New Collection</span>
          </button>

          <!-- User Collections List -->
          <div v-if="userCollections.length > 0" class="space-y-1 mt-1">
            <NavItem
              v-for="collection in userCollections"
              :key="collection.id"
              icon="Folder"
              :label="collection.name"
              :count="collection.imageCount"
              :active="activeView === `collection:${collection.id}`"
              @click="$emit('navigate', `collection:${collection.id}`)"
            />
          </div>
          <p v-else class="text-xs text-gray-600 px-3 py-1">No collections yet</p>
        </div>
      </nav>
    </div>

    <!-- Settings at Bottom -->
    <div class="p-3 border-t border-gray-800">
      <button
        @click="$emit('open-settings')"
        class="w-full px-3 py-2 text-left text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded transition-colors flex items-center gap-2"
      >
        <SettingsIcon class="w-4 h-4" />
        <span>Catalog Settings</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Images as ImagesIcon,
  Calendar as CalendarIcon,
  Map as MapIcon,
  Star as StarIcon,
  Zap as ZapIcon,
  Copy as CopyIcon,
  CopyX as CopyXIcon,
  Clock as ClockIcon,
  Tag as TagIcon,
  AlertCircle as AlertCircleIcon,
  Video as VideoIcon,
  Plus as PlusIcon,
  Settings as SettingsIcon,
  FileWarning as FileWarningIcon,
  PartyPopper as PartyPopperIcon,
  ChevronDown as ChevronDownIcon,
  BarChart2 as BarChart2Icon,
  Layers as LayersIcon,
} from 'lucide-vue-next'

const smartViewsOpen = ref(true)
const tagsOpen = ref(false)
const categoriesOpen = ref(true)
const collectionsOpen = ref(true)
import NavItem from './NavItem.vue'
import TagBrowser from './TagBrowser.vue'
import type { Collection } from '@/stores/collections'

interface TagItem {
  name: string
  count: number
}

interface Props {
  activeView?: string
  catalogName?: string
  counts?: {
    events: number
    bursts: number
    duplicates: number
    screenshots: number
    documents: number
    noise: number
    recent: number
    untagged: number
    needs_review: number
    rejected: number
    videos: number
    favorites: number
    skipped_imports: number
  }
  collections?: Collection[]
  availableTags?: TagItem[]
  selectedTags?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  activeView: 'all',
  catalogName: 'My Photos',
  counts: () => ({
    events: 0,
    bursts: 0,
    duplicates: 0,
    screenshots: 0,
    documents: 0,
    noise: 0,
    recent: 0,
    untagged: 0,
    needs_review: 0,
    rejected: 0,
    videos: 0,
    favorites: 0,
    skipped_imports: 0
  }),
  collections: () => [],
  availableTags: () => [],
  selectedTags: () => [],
})

defineEmits<{
  navigate: [view: string]
  'open-settings': []
  'create-collection': []
  'filter-tags': [tags: string[]]
}>()

const systemCollections = computed(() =>
  (props.collections ?? []).filter(c => c.source === 'system')
)
const userCollections = computed(() =>
  (props.collections ?? []).filter(c => c.source !== 'system')
)
</script>
