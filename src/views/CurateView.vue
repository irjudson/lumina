<template>
  <LibraryLayout>
  <div class="flex h-full overflow-hidden">

    <!-- Left panel: Tag Tree -->
    <aside class="w-56 shrink-0 border-r border-gray-800 flex flex-col bg-gray-900 overflow-hidden">
      <div class="px-3 py-3 border-b border-gray-800 flex items-center justify-between">
        <span class="text-xs font-semibold uppercase tracking-widest text-gray-500">Tags</span>
        <button
          class="w-6 h-6 flex items-center justify-center rounded text-gray-500 hover:text-gray-200 hover:bg-gray-800"
          title="New tag"
          @click="showNewTag = true"
        >
          <PlusIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="flex-1 overflow-y-auto py-1">
        <TagTree
          :tree="folkTags.tagTree"
          :selected-id="selectedTagId"
          @select="selectTag"
        />
      </div>
    </aside>

    <!-- Center panel: ML Groups or Tag Images -->
    <main class="flex-1 flex flex-col overflow-hidden bg-gray-950">

      <!-- Tab bar -->
      <div class="flex items-center gap-1 px-4 py-2 border-b border-gray-800 bg-gray-900">
        <button
          class="px-3 py-1.5 text-xs rounded font-medium transition-colors"
          :class="activeTab === 'groups' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'"
          @click="activeTab = 'groups'"
        >
          ML Groups
          <span v-if="folkTags.mlGroups.length > 0" class="ml-1 px-1.5 py-0.5 bg-purple-600 text-white rounded-full text-xs">
            {{ folkTags.mlGroups.length }}
          </span>
        </button>
        <button
          class="px-3 py-1.5 text-xs rounded font-medium transition-colors"
          :class="activeTab === 'tag' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'"
          @click="activeTab = 'tag'"
        >
          Tag Images
        </button>
        <div class="flex-1" />
        <button
          class="px-3 py-1.5 text-xs rounded text-gray-500 hover:text-gray-200 hover:bg-gray-800 flex items-center gap-1.5"
          :disabled="isEnriching"
          @click="runEnrichment"
        >
          <RefreshCwIcon class="w-3 h-3" :class="isEnriching ? 'animate-spin' : ''" />
          {{ isEnriching ? 'Running…' : 'Enrich' }}
        </button>
      </div>

      <!-- ML Groups tab -->
      <div v-if="activeTab === 'groups'" class="flex-1 overflow-y-auto p-4">
        <div v-if="folkTags.mlGroups.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
          <LayersIcon class="w-10 h-10 text-gray-700 mb-3" />
          <p class="text-gray-500 text-sm">No pending ML groups.</p>
          <p class="text-gray-600 text-xs mt-1">Click Enrich to discover new clusters.</p>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="group in folkTags.mlGroups"
            :key="group.id"
            class="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition-colors"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-xs px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300 font-mono">
                    {{ group.method }}
                  </span>
                  <span class="text-xs text-gray-500">{{ group.image_count }} images</span>
                </div>
                <div v-if="group.label_hint" class="text-sm text-gray-300 mb-2 italic">
                  "{{ group.label_hint }}"
                </div>
                <div v-if="group.signals?.start" class="text-xs text-gray-600">
                  {{ fmtDate(group.signals.start) }}
                  <span v-if="group.signals?.end && group.signals.end !== group.signals.start">
                    → {{ fmtDate(group.signals.end) }}
                  </span>
                </div>
              </div>

              <!-- Sample thumbnails -->
              <div class="flex gap-1 shrink-0">
                <div
                  v-for="sid in group.sample_image_ids.slice(0, 4)"
                  :key="sid"
                  class="w-10 h-10 rounded bg-gray-700 overflow-hidden"
                >
                  <img
                    :src="`/api/catalogs/${catalogId}/images/${sid}/thumbnail`"
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                </div>
              </div>
            </div>

            <!-- Naming form (inline) -->
            <div v-if="namingGroupId === group.id" class="mt-3 flex gap-2">
              <input
                v-model="nameInput"
                placeholder="Label for this group…"
                class="flex-1 bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 outline-none"
                @keydown.enter="confirmName(group.id)"
                @keydown.escape="namingGroupId = null"
                autofocus
              />
              <button class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded" @click="confirmName(group.id)">
                Save
              </button>
              <button class="px-3 py-1.5 text-gray-400 hover:text-gray-200 text-sm" @click="namingGroupId = null">
                Cancel
              </button>
            </div>

            <!-- Actions -->
            <div v-else class="mt-3 flex gap-2">
              <button
                class="px-3 py-1.5 text-xs bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 rounded border border-blue-700/30 transition-colors"
                @click="startNaming(group)"
              >
                Name it
              </button>
              <button
                class="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300 rounded border border-gray-700 hover:border-gray-600 transition-colors"
                @click="skip(group.id)"
              >
                Skip
              </button>
              <button
                class="px-3 py-1.5 text-xs text-gray-600 hover:text-red-400 rounded border border-gray-700 hover:border-red-800/50 transition-colors"
                @click="deleteGroup(group.id)"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Tag images tab -->
      <div v-if="activeTab === 'tag'" class="flex-1 flex items-center justify-center">
        <div class="text-center text-gray-600 text-sm">
          <TagIcon class="w-10 h-10 mx-auto mb-3 text-gray-700" />
          <p>Select a tag from the left panel.</p>
          <p class="text-xs mt-1">Grid-based tagging coming soon.</p>
        </div>
      </div>
    </main>

    <!-- Right panel: Tag detail -->
    <aside v-if="selectedTag" class="w-64 shrink-0 border-l border-gray-800 bg-gray-900 overflow-y-auto">
      <div class="px-4 py-3 border-b border-gray-800">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-widest text-gray-500">Tag</span>
          <button class="text-gray-600 hover:text-gray-400" @click="selectedTag = null">
            <XIcon class="w-4 h-4" />
          </button>
        </div>
        <div class="mt-2 text-base font-medium text-gray-200">{{ selectedTag.label }}</div>
        <div class="text-xs text-gray-600 font-mono mt-0.5">{{ selectedTag.slug }}</div>
      </div>
      <div class="px-4 py-3 space-y-3">
        <div class="flex items-center justify-between text-sm">
          <span class="text-gray-500">Images</span>
          <span class="text-gray-300 tabular-nums">{{ selectedTag.image_count.toLocaleString() }}</span>
        </div>
        <div v-if="selectedTag.notes" class="text-sm text-gray-400">{{ selectedTag.notes }}</div>
        <button
          class="w-full px-3 py-2 text-xs text-red-400 hover:text-red-300 border border-red-900/30 hover:border-red-700/50 rounded transition-colors"
          @click="deleteSelectedTag"
        >
          Delete Tag
        </button>
      </div>
    </aside>

    <!-- New Tag modal -->
    <div v-if="showNewTag" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="showNewTag = false">
      <div class="bg-gray-800 rounded-xl border border-gray-700 shadow-xl p-5 w-80">
        <h3 class="text-sm font-semibold text-gray-200 mb-3">New Tag</h3>
        <input
          v-model="newTagLabel"
          placeholder="Label…"
          class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm text-gray-200 focus:border-blue-500 outline-none mb-3"
          @keydown.enter="createTag"
        />
        <div class="flex gap-2 justify-end">
          <button class="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200" @click="showNewTag = false">Cancel</button>
          <button class="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded" @click="createTag">Create</button>
        </div>
      </div>
    </div>

  </div>
  </LibraryLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { PlusIcon, LayersIcon, TagIcon, XIcon, RefreshCwIcon } from 'lucide-vue-next'
import { useFolkTagsStore, type FolkTag, type MlGroup } from '@/stores/folkTags'
import { useCatalogStore } from '@/stores/catalog'
import { api } from '@/api/client'
import TagTree from '@/components/curate/TagTree.vue'
import LibraryLayout from '@/layouts/LibraryLayout.vue'

const folkTags = useFolkTagsStore()
const catalog = useCatalogStore()

const catalogId = computed(() => catalog.activeCatalogId ?? '')

const activeTab = ref<'groups' | 'tag'>('groups')
const selectedTagId = ref<string | null>(null)
const selectedTag = ref<FolkTag | null>(null)
const namingGroupId = ref<string | null>(null)
const nameInput = ref('')
const showNewTag = ref(false)
const newTagLabel = ref('')
const isEnriching = ref(false)

onMounted(async () => {
  if (catalogId.value) {
    await Promise.all([
      folkTags.fetchTags(catalogId.value),
      folkTags.fetchMlGroups(catalogId.value),
    ])
  }
})

function selectTag(tag: FolkTag) {
  selectedTagId.value = tag.id
  selectedTag.value = tag
}

function startNaming(group: MlGroup) {
  namingGroupId.value = group.id
  nameInput.value = group.label_hint ?? ''
}

async function confirmName(groupId: string) {
  if (!nameInput.value.trim() || !catalogId.value) return
  await folkTags.nameGroup(catalogId.value, groupId, nameInput.value.trim())
  namingGroupId.value = null
  nameInput.value = ''
}

async function skip(groupId: string) {
  if (catalogId.value) await folkTags.skipGroup(catalogId.value, groupId)
}

async function deleteGroup(groupId: string) {
  if (catalogId.value) await folkTags.deleteGroup(catalogId.value, groupId)
}

async function deleteSelectedTag() {
  if (!selectedTag.value || !catalogId.value) return
  await folkTags.deleteTag(catalogId.value, selectedTag.value.id)
  selectedTag.value = null
  selectedTagId.value = null
}

async function createTag() {
  if (!newTagLabel.value.trim() || !catalogId.value) return
  await folkTags.createTag(catalogId.value, newTagLabel.value.trim())
  newTagLabel.value = ''
  showNewTag.value = false
}

async function runEnrichment() {
  if (!catalogId.value || isEnriching.value) return
  isEnriching.value = true
  try {
    await api.createJob({
      catalog_id: catalogId.value,
      job_type: 'enrich_ml_groups',
      params: { min_cluster_size: 8 },
    })
    // Refresh groups after a short delay
    setTimeout(async () => {
      await folkTags.fetchMlGroups(catalogId.value)
      isEnriching.value = false
    }, 3000)
  } catch {
    isEnriching.value = false
  }
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}
</script>
