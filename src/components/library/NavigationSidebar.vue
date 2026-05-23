<template>
  <div class="h-full flex flex-col bg-gray-900 border-r border-gray-800" @click="closeContextMenu">
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
        <NavItem icon="Images" label="All Photos" :active="activeView === 'all'" @click="$emit('navigate', 'all')" />
        <NavItem icon="Calendar" label="Timeline" :active="activeView === 'timeline'" @click="$emit('navigate', 'timeline')" />
        <NavItem icon="Map" label="Map" :active="activeView === 'map'" @click="$emit('navigate', 'map')" />
        <NavItem icon="Star" label="Favorites" :count="counts.favorites" :active="activeView === 'favorites'" @click="$emit('navigate', 'favorites')" />
        <NavItem icon="BarChart2" label="Analytics" :active="activeView === 'analytics'" @click="$emit('navigate', 'analytics')" />
      </nav>

      <!-- Collections (system + user, collapsible 2-level tree) -->
      <nav class="border-t border-gray-800 mt-2">
        <button
          @click="collectionsOpen = !collectionsOpen"
          class="w-full flex items-center justify-between px-6 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide hover:text-gray-400 transition-colors"
        >
          <span>Collections</span>
          <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': collectionsOpen }" />
        </button>
        <div v-if="collectionsOpen" class="px-3 pb-2 space-y-0.5">
          <!-- System collections (up to 3-level tree) -->
          <template v-for="col in systemCollections" :key="col.id">
            <!-- Top-level system category -->
            <div class="flex items-center gap-1 group/parent">
              <button
                v-if="col.childCount > 0"
                @click.stop="toggleExpanded(col.id)"
                class="shrink-0 p-1 text-gray-600 hover:text-gray-400 transition-colors"
                :title="expandedCategories.has(col.id) ? 'Collapse' : 'Expand'"
              >
                <ChevronRightIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-90': expandedCategories.has(col.id) }" />
              </button>
              <span v-else class="w-5 shrink-0" />
              <NavItem
                icon="Layers"
                :label="col.name"
                :count="col.imageCount || undefined"
                :active="activeView === `collection:${col.id}`"
                class="flex-1 min-w-0"
                @click="$emit('navigate', `collection:${col.id}`)"
              />
              <span
                v-if="col.pendingCount > 0"
                class="shrink-0 px-1.5 py-0.5 text-xs rounded-full bg-amber-600/30 text-amber-400 font-medium"
                :title="`${col.pendingCount} unreviewed suggestions`"
              >{{ col.pendingCount }}</span>
              <!-- Add Group button — only shown for People and similar multi-person parents -->
              <button
                v-if="col.systemKey === 'people'"
                @click.stop="promptNewGroup(col.id)"
                class="shrink-0 p-1 text-gray-700 hover:text-gray-400 transition-colors opacity-0 group-hover/parent:opacity-100"
                title="New group under People"
              >
                <FolderPlusIcon class="w-3 h-3" />
              </button>
            </div>

            <!-- Children of this system category -->
            <div v-if="expandedCategories.has(col.id)" class="pl-5 space-y-0.5">
              <template v-for="child in childrenOf(col.id)" :key="child.id">
                <!-- If the child itself has children it's a group (e.g. "My Family") -->
                <template v-if="child.childCount > 0 || groupChildrenOf(child.id).length > 0">
                  <div class="flex items-center gap-1 group/grp">
                    <button
                      @click.stop="toggleExpanded(child.id)"
                      class="shrink-0 p-1 text-gray-600 hover:text-gray-400 transition-colors"
                    >
                      <ChevronRightIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-90': expandedCategories.has(child.id) }" />
                    </button>
                    <CollectionLabel
                      :collection="child"
                      :active="activeView === `collection:${child.id}`"
                      :renaming="renaming?.id === child.id"
                      :rename-value="renaming?.value ?? ''"
                      icon="FolderOpen"
                      @click="$emit('navigate', `collection:${child.id}`)"
                      @dblclick="startRename(child)"
                      @contextmenu.prevent="showContextMenu($event, child)"
                      @rename-input="v => { if (renaming) renaming.value = v }"
                      @rename-save="saveRename"
                      @rename-cancel="cancelRename"
                    />
                    <span
                      v-if="child.pendingCount > 0"
                      class="shrink-0 px-1.5 py-0.5 text-xs rounded-full bg-amber-600/30 text-amber-400 font-medium"
                    >{{ child.pendingCount }}</span>
                  </div>
                  <!-- Group children (Person N) -->
                  <div v-if="expandedCategories.has(child.id)" class="pl-5 space-y-0.5">
                    <div v-for="grandchild in groupChildrenOf(child.id)" :key="grandchild.id" class="flex items-center gap-1">
                      <CollectionLabel
                        :collection="grandchild"
                        :active="activeView === `collection:${grandchild.id}`"
                        :renaming="renaming?.id === grandchild.id"
                        :rename-value="renaming?.value ?? ''"
                        icon="User"
                        @click="$emit('navigate', `collection:${grandchild.id}`)"
                        @dblclick="startRename(grandchild)"
                        @contextmenu.prevent="showContextMenu($event, grandchild)"
                        @rename-input="v => { if (renaming) renaming.value = v }"
                        @rename-save="saveRename"
                        @rename-cancel="cancelRename"
                      />
                      <span
                        v-if="grandchild.pendingCount > 0"
                        class="shrink-0 px-1.5 py-0.5 text-xs rounded-full bg-amber-600/30 text-amber-400 font-medium"
                      >{{ grandchild.pendingCount }}</span>
                    </div>
                  </div>
                </template>

                <!-- Leaf child (no sub-children) -->
                <template v-else>
                  <div class="flex items-center gap-1">
                    <CollectionLabel
                      :collection="child"
                      :active="activeView === `collection:${child.id}`"
                      :renaming="renaming?.id === child.id"
                      :rename-value="renaming?.value ?? ''"
                      :icon="child.systemKey?.startsWith('people_person:') ? 'User' : 'Folder'"
                      @click="$emit('navigate', `collection:${child.id}`)"
                      @dblclick="startRename(child)"
                      @contextmenu.prevent="showContextMenu($event, child)"
                      @rename-input="v => { if (renaming) renaming.value = v }"
                      @rename-save="saveRename"
                      @rename-cancel="cancelRename"
                    />
                    <span
                      v-if="child.pendingCount > 0"
                      class="shrink-0 px-1.5 py-0.5 text-xs rounded-full bg-amber-600/30 text-amber-400 font-medium"
                      :title="`${child.pendingCount} unreviewed`"
                    >{{ child.pendingCount }}</span>
                  </div>
                </template>
              </template>
              <p v-if="childrenOf(col.id).length === 0 && col.childCount > 0" class="text-xs text-gray-600 px-3 py-1">Loading…</p>
            </div>
          </template>

          <!-- Divider between system and user collections -->
          <div v-if="systemCollections.length > 0" class="border-t border-gray-800 my-1" />

          <!-- New Collection button -->
          <button
            @click="$emit('create-collection')"
            class="w-full px-3 py-2 text-left text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded transition-colors flex items-center gap-2"
          >
            <PlusIcon class="w-4 h-4" />
            <span>New Collection</span>
          </button>

          <!-- User collections -->
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
          <NavItem icon="PartyPopper" label="Events" :count="counts.events" :active="activeView === 'events'" @click="$emit('navigate', 'events')" />
          <NavItem icon="Zap" label="Bursts" :count="counts.bursts" :active="activeView === 'bursts'" @click="$emit('navigate', 'bursts')" />
          <NavItem icon="Copy" label="Duplicates" :count="counts.duplicates" :active="activeView === 'duplicates'" @click="$emit('navigate', 'duplicates')" />
          <NavItem icon="Monitor" label="Screenshots" :count="counts.screenshots" :active="activeView === 'screenshots'" @click="$emit('navigate', 'screenshots')" />
          <NavItem icon="FileText" label="Documents" :count="counts.documents" :active="activeView === 'documents'" @click="$emit('navigate', 'documents')" />
          <NavItem icon="Trash2" label="Noise" :count="counts.noise" :active="activeView === 'noise'" @click="$emit('navigate', 'noise')" />
          <NavItem icon="Clock" label="Recent" :count="counts.recent" :active="activeView === 'recent'" @click="$emit('navigate', 'recent')" />
          <NavItem icon="Tag" label="Untagged" :count="counts.untagged" :active="activeView === 'untagged'" @click="$emit('navigate', 'untagged')" />
          <NavItem icon="AlertCircle" label="Needs Review" :count="counts.needs_review" :active="activeView === 'needs-review'" @click="$emit('navigate', 'needs-review')" />
          <NavItem icon="Trash2" label="Rejected" :count="counts.rejected" :active="activeView === 'rejected'" @click="$emit('navigate', 'rejected')" />
          <NavItem icon="Video" label="Videos" :count="counts.videos" :active="activeView === 'videos'" @click="$emit('navigate', 'videos')" />
          <NavItem icon="CopyX" label="Skipped Imports" :count="counts.skipped_imports" :active="activeView === 'skipped_imports'" @click="$emit('navigate', 'skipped_imports')" />
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
          <TagBrowser :tags="availableTags" :selected-tags="selectedTags" @update:selected-tags="$emit('filter-tags', $event)" />
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

    <!-- Context menu -->
    <Teleport to="body">
      <div
        v-if="contextMenu"
        :style="{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }"
        class="fixed z-50 min-w-40 bg-gray-800 border border-gray-700 rounded shadow-lg py-1 text-sm"
        @click.stop
      >
        <button
          @click="startRename(contextMenu.collection); closeContextMenu()"
          class="w-full px-3 py-1.5 text-left text-gray-200 hover:bg-gray-700 flex items-center gap-2"
        >
          <PencilIcon class="w-3.5 h-3.5" /> Rename
        </button>
        <template v-if="availableGroups(contextMenu.collection).length > 0 || peopleParentOf(contextMenu.collection)">
          <div class="border-t border-gray-700 my-1" />
          <p class="px-3 py-1 text-xs text-gray-500 font-medium">Move to group</p>
          <button
            v-for="grp in availableGroups(contextMenu.collection)"
            :key="grp.id"
            @click="moveToGroup(contextMenu!.collection, grp.id)"
            class="w-full px-3 py-1.5 text-left text-gray-300 hover:bg-gray-700 flex items-center gap-2"
          >
            <FolderOpenIcon class="w-3.5 h-3.5" /> {{ grp.name }}
          </button>
          <button
            v-if="peopleParentOf(contextMenu.collection)"
            @click="promptNewGroup(peopleParentOf(contextMenu.collection)!, contextMenu.collection.id)"
            class="w-full px-3 py-1.5 text-left text-gray-400 hover:bg-gray-700 flex items-center gap-2"
          >
            <FolderPlusIcon class="w-3.5 h-3.5" /> New group…
          </button>
        </template>
      </div>
    </Teleport>

    <!-- New-group name prompt -->
    <Teleport to="body">
      <div
        v-if="newGroupPrompt"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        @click.self="newGroupPrompt = null"
      >
        <div class="bg-gray-800 border border-gray-700 rounded-lg p-4 w-72 shadow-xl">
          <p class="text-sm font-medium text-gray-200 mb-3">New group name</p>
          <input
            ref="groupNameInput"
            v-model="newGroupName"
            type="text"
            placeholder="e.g. My Family"
            class="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
            @keydown.enter="confirmNewGroup"
            @keydown.esc="newGroupPrompt = null"
          />
          <div class="flex justify-end gap-2 mt-3">
            <button @click="newGroupPrompt = null" class="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200">Cancel</button>
            <button
              @click="confirmNewGroup"
              :disabled="!newGroupName.trim()"
              class="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded"
            >Create</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
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
  ChevronRight as ChevronRightIcon,
  BarChart2 as BarChart2Icon,
  Layers as LayersIcon,
  Pencil as PencilIcon,
  FolderOpen as FolderOpenIcon,
  FolderPlus as FolderPlusIcon,
} from 'lucide-vue-next'

import NavItem from './NavItem.vue'
import CollectionLabel from './CollectionLabel.vue'
import TagBrowser from './TagBrowser.vue'
import type { Collection } from '@/stores/collections'
import { useCollectionsStore } from '@/stores/collections'

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
    events: 0, bursts: 0, duplicates: 0, screenshots: 0, documents: 0,
    noise: 0, recent: 0, untagged: 0, needs_review: 0, rejected: 0,
    videos: 0, favorites: 0, skipped_imports: 0,
  }),
  collections: () => [],
  availableTags: () => [],
  selectedTags: () => [],
})

const emit = defineEmits<{
  navigate: [view: string]
  'open-settings': []
  'create-collection': []
  'filter-tags': [tags: string[]]
  'load-children': [parentId: string]
}>()

const collectionsStore = useCollectionsStore()

const smartViewsOpen = ref(false)
const tagsOpen = ref(false)
const collectionsOpen = ref(false)

// Expanded state
const expandedCategories = ref<Set<string>>(new Set())

function toggleExpanded(id: string) {
  if (expandedCategories.value.has(id)) {
    expandedCategories.value.delete(id)
  } else {
    expandedCategories.value.add(id)
    emit('load-children', id)
  }
  expandedCategories.value = new Set(expandedCategories.value)
}

const systemCollections = computed(() =>
  (props.collections ?? []).filter(c => c.source === 'system' && !c.parentId)
)
const userCollections = computed(() =>
  (props.collections ?? []).filter(c => c.source !== 'system' && !c.parentId)
)

function childrenOf(parentId: string): Collection[] {
  return (props.collections ?? []).filter(c => c.parentId === parentId)
}

function groupChildrenOf(groupId: string): Collection[] {
  return (props.collections ?? []).filter(c => c.parentId === groupId)
}

// ── Rename ──────────────────────────────────────────────────────────────────

const renaming = ref<{ id: string; value: string } | null>(null)

function startRename(col: Collection) {
  renaming.value = { id: col.id, value: col.name }
}

async function saveRename() {
  if (!renaming.value) return
  const { id, value } = renaming.value
  const trimmed = value.trim()
  if (trimmed) {
    await collectionsStore.updateCollection(id, { name: trimmed })
  }
  renaming.value = null
}

function cancelRename() {
  renaming.value = null
}

// ── Context menu ─────────────────────────────────────────────────────────────

const contextMenu = ref<{ collection: Collection; x: number; y: number } | null>(null)

function showContextMenu(event: MouseEvent, col: Collection) {
  contextMenu.value = { collection: col, x: event.clientX, y: event.clientY }
}

function closeContextMenu() {
  contextMenu.value = null
}

/** Groups (non-person sub-collections) that are siblings of this collection under People. */
function availableGroups(col: Collection): Collection[] {
  if (!col.parentId) return []
  return (props.collections ?? []).filter(
    c => c.parentId === col.parentId && c.id !== col.id && (c.childCount > 0 || groupChildrenOf(c.id).length > 0)
  )
}

/** Returns the top-level People collection ID if this collection is a direct child of People. */
function peopleParentOf(col: Collection): string | null {
  if (!col.parentId) return null
  const parent = (props.collections ?? []).find(c => c.id === col.parentId)
  if (parent?.systemKey === 'people') return parent.id
  // Also allow persons inside a group (grandchild of People)
  if (parent?.parentId) {
    const grandparent = (props.collections ?? []).find(c => c.id === parent.parentId)
    if (grandparent?.systemKey === 'people') return grandparent.id
  }
  return null
}

async function moveToGroup(col: Collection, groupId: string) {
  closeContextMenu()
  await collectionsStore.updateCollection(col.id, { parentId: groupId })
  // Bump group's childCount locally so expand arrow appears
  const grp = (props.collections ?? []).find(c => c.id === groupId)
  if (grp) grp.childCount = Math.max(grp.childCount, 1)
}

// ── New Group prompt ─────────────────────────────────────────────────────────

const newGroupPrompt = ref<{ parentId: string; moveCollectionId?: string } | null>(null)
const newGroupName = ref('')
const groupNameInput = ref<HTMLInputElement | null>(null)

function promptNewGroup(parentId: string, moveCollectionId?: string) {
  closeContextMenu()
  newGroupName.value = ''
  newGroupPrompt.value = { parentId, moveCollectionId }
  nextTick(() => groupNameInput.value?.focus())
}

async function confirmNewGroup() {
  if (!newGroupPrompt.value || !newGroupName.value.trim()) return
  const { parentId, moveCollectionId } = newGroupPrompt.value
  newGroupPrompt.value = null

  const group = await collectionsStore.createCollection(newGroupName.value.trim(), undefined, parentId)
  // Auto-expand the parent
  expandedCategories.value = new Set([...expandedCategories.value, parentId])

  // If triggered from "Move to group → New group…", also move the collection
  if (moveCollectionId) {
    await collectionsStore.updateCollection(moveCollectionId, { parentId: group.id })
  }
}
</script>
