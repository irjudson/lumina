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

    <!-- Center panel -->
    <main class="flex-1 flex flex-col overflow-hidden bg-gray-950">

      <!-- Tab bar -->
      <div class="flex items-center gap-1 px-4 py-2 border-b border-gray-800 bg-gray-900 shrink-0">
        <button
          class="px-3 py-1.5 text-xs rounded font-medium transition-colors"
          :class="activeTab === 'groups' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'"
          @click="activeTab = 'groups'; browsingGroup = null"
        >
          ML Groups
          <span v-if="folkTags.mlGroups.length > 0" class="ml-1 px-1.5 py-0.5 bg-purple-600 text-white rounded-full text-xs">
            {{ folkTags.mlGroups.length }}
          </span>
        </button>
        <button
          class="px-3 py-1.5 text-xs rounded font-medium transition-colors"
          :class="activeTab === 'tag' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'"
          @click="activeTab = 'tag'; browsingGroup = null"
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

      <!-- ── Group browse view (full-panel image grid) ── -->
      <template v-if="browsingGroup">
        <!-- Browse header -->
        <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-900 shrink-0">
          <button class="text-gray-400 hover:text-gray-200 flex items-center gap-1.5 text-sm" @click="browsingGroup = null">
            <ChevronLeftIcon class="w-4 h-4" />
            Back
          </button>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-xs px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300 font-mono">{{ browsingGroup.method }}</span>
              <span class="text-sm font-medium text-gray-200">{{ browsingGroup.image_count }} images</span>
              <span v-if="browsingGroup.label_hint" class="text-sm text-gray-500 italic">"{{ browsingGroup.label_hint }}"</span>
            </div>
            <div v-if="browsingGroup.signals?.start" class="text-xs text-gray-600 mt-0.5">
              {{ fmtDate(browsingGroup.signals.start) }}
              <span v-if="browsingGroup.signals?.end && browsingGroup.signals.end !== browsingGroup.signals.start">
                → {{ fmtDate(browsingGroup.signals.end) }}
              </span>
            </div>
          </div>
          <!-- Browse actions -->
          <div class="flex items-center gap-2 shrink-0">
            <template v-if="namingGroupId === browsingGroup.id">
              <input
                v-model="nameInput"
                placeholder="Label for this group…"
                class="bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 outline-none w-52"
                @keydown.enter="confirmName(browsingGroup.id)"
                @keydown.escape="namingGroupId = null"
                autofocus
              />
              <button class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded" @click="confirmName(browsingGroup.id)">Save</button>
              <button class="px-3 py-1.5 text-gray-400 hover:text-gray-200 text-sm" @click="namingGroupId = null">Cancel</button>
            </template>
            <template v-else>
              <button
                class="px-3 py-1.5 text-xs bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 rounded border border-blue-700/30 transition-colors"
                @click="startNaming(browsingGroup)"
              >Name it</button>
              <button
                class="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300 rounded border border-gray-700 transition-colors"
                @click="skip(browsingGroup.id); browsingGroup = null"
              >Skip</button>
              <button
                class="px-3 py-1.5 text-xs text-gray-600 hover:text-red-400 rounded border border-gray-700 hover:border-red-800/50 transition-colors"
                @click="deleteGroup(browsingGroup.id); browsingGroup = null"
              >Delete</button>
            </template>
          </div>
        </div>

        <!-- Image grid -->
        <div class="flex-1 overflow-y-auto p-3">
          <div v-if="groupImagesLoading" class="flex items-center justify-center py-16">
            <div class="w-6 h-6 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin"></div>
          </div>
          <div v-else class="grid gap-1" style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))">
            <div
              v-for="img in groupImages"
              :key="img.id"
              class="relative aspect-square bg-gray-800 rounded overflow-hidden group"
            >
              <img
                :src="`/api/catalogs/${catalogId}/images/${img.id}/thumbnail`"
                class="w-full h-full object-cover"
                loading="lazy"
              />
              <div class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
              <div v-if="img.capture_time" class="absolute bottom-0 left-0 right-0 px-1.5 py-1 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                <span class="text-xs text-white/80">{{ fmtDateShort(img.capture_time) }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ── ML Groups list ── -->
      <div v-else-if="activeTab === 'groups'" class="flex-1 overflow-y-auto p-4">
        <div v-if="folkTags.mlGroups.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
          <LayersIcon class="w-10 h-10 text-gray-700 mb-3" />
          <p class="text-gray-500 text-sm">No pending ML groups.</p>
          <p class="text-gray-600 text-xs mt-1">Click Enrich to discover new clusters.</p>
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="group in folkTags.mlGroups"
            :key="group.id"
            class="bg-gray-800 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
          >
            <!-- Group summary row — click to browse -->
            <button
              class="w-full flex items-center gap-3 px-4 py-3 text-left"
              @click="openGroupBrowse(group)"
            >
              <!-- Sample thumbnails -->
              <div class="flex gap-0.5 shrink-0">
                <div
                  v-for="sid in group.sample_image_ids.slice(0, 5)"
                  :key="sid"
                  class="w-12 h-12 rounded bg-gray-700 overflow-hidden"
                >
                  <img
                    :src="`/api/catalogs/${catalogId}/images/${sid}/thumbnail`"
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                </div>
              </div>

              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-0.5">
                  <span class="text-xs px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300 font-mono">{{ group.method }}</span>
                  <span class="text-sm text-gray-300 font-medium">{{ group.image_count }} images</span>
                </div>
                <div v-if="group.label_hint" class="text-sm text-gray-400 italic truncate">"{{ group.label_hint }}"</div>
                <div v-if="group.signals?.start" class="text-xs text-gray-600 mt-0.5">
                  {{ fmtDate(group.signals.start) }}
                  <span v-if="group.signals?.end && group.signals.end !== group.signals.start"> → {{ fmtDate(group.signals.end) }}</span>
                </div>
              </div>

              <div class="flex items-center gap-1.5 text-xs text-gray-500 shrink-0">
                <GridIcon class="w-3.5 h-3.5" />
                Browse
                <ChevronRightIcon class="w-3.5 h-3.5" />
              </div>
            </button>

            <!-- Inline actions below row -->
            <div class="flex gap-2 px-4 pb-3">
              <template v-if="namingGroupId === group.id">
                <input
                  v-model="nameInput"
                  placeholder="Label for this group…"
                  class="flex-1 bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-blue-500 outline-none"
                  @keydown.enter="confirmName(group.id)"
                  @keydown.escape="namingGroupId = null"
                  autofocus
                />
                <button class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded" @click="confirmName(group.id)">Save</button>
                <button class="px-3 py-1.5 text-gray-400 text-sm" @click="namingGroupId = null">Cancel</button>
              </template>
              <template v-else>
                <button class="px-3 py-1.5 text-xs bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 rounded border border-blue-700/30 transition-colors" @click.stop="startNaming(group)">Name it</button>
                <button class="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300 rounded border border-gray-700 hover:border-gray-600 transition-colors" @click.stop="skip(group.id)">Skip</button>
                <button class="px-3 py-1.5 text-xs text-gray-600 hover:text-red-400 rounded border border-gray-700 hover:border-red-800/50 transition-colors" @click.stop="deleteGroup(group.id)">Delete</button>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- Tag images tab -->
      <div v-else-if="activeTab === 'tag'" class="flex-1 flex items-center justify-center">
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
          class="w-full px-3 py-2 text-xs text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-600 rounded transition-colors"
          @click="showMergeModal = true"
        >
          Merge into…
        </button>
        <button
          class="w-full px-3 py-2 text-xs text-red-400 hover:text-red-300 border border-red-900/30 hover:border-red-700/50 rounded transition-colors"
          @click="deleteSelectedTag"
        >
          Delete Tag
        </button>
      </div>
    </aside>

    <!-- Merge Tag modal -->
    <div v-if="showMergeModal && selectedTag" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="showMergeModal = false">
      <div class="bg-gray-800 rounded-xl border border-gray-700 shadow-xl p-5 w-96">
        <h3 class="text-sm font-semibold text-gray-200 mb-1">Merge "{{ selectedTag.label }}" into…</h3>
        <p class="text-xs text-gray-500 mb-3">All images will move to the target tag. This tag will be deleted.</p>
        <input
          v-model="mergeSearch"
          placeholder="Search tags…"
          class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm text-gray-200 focus:border-blue-500 outline-none mb-2"
          @keydown.escape="showMergeModal = false"
        />
        <div class="max-h-48 overflow-y-auto space-y-0.5">
          <button
            v-for="tag in mergeTargets"
            :key="tag.id"
            class="w-full text-left px-3 py-2 rounded text-sm transition-colors flex items-center justify-between"
            :class="mergeTarget?.id === tag.id ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'"
            @click="mergeTarget = tag"
          >
            <span class="truncate">{{ tag.label }}</span>
            <span class="text-xs opacity-60 tabular-nums ml-2">{{ tag.image_count }}</span>
          </button>
          <div v-if="mergeTargets.length === 0" class="px-3 py-4 text-xs text-gray-600 text-center">No matching tags</div>
        </div>
        <div class="flex gap-2 justify-end mt-4">
          <button class="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200" @click="showMergeModal = false; mergeTarget = null; mergeSearch = ''">Cancel</button>
          <button
            class="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded disabled:opacity-40 disabled:cursor-not-allowed"
            :disabled="!mergeTarget"
            @click="confirmMerge"
          >
            Merge
          </button>
        </div>
      </div>
    </div>

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
import axios from 'axios'
import {
  PlusIcon, LayersIcon, TagIcon, XIcon, RefreshCwIcon,
  ChevronLeftIcon, ChevronRightIcon, GridIcon,
} from 'lucide-vue-next'
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

// Merge modal
const showMergeModal = ref(false)
const mergeSearch = ref('')
const mergeTarget = ref<FolkTag | null>(null)

const mergeTargets = computed(() => {
  const q = mergeSearch.value.toLowerCase()
  return folkTags.tags
    .filter(t => t.id !== selectedTag.value?.id && t.label.toLowerCase().includes(q))
    .sort((a, b) => a.label.localeCompare(b.label))
})

// Group browse state
const browsingGroup = ref<MlGroup | null>(null)
const groupImages = ref<any[]>([])
const groupImagesLoading = ref(false)

onMounted(async () => {
  if (catalogId.value) {
    await Promise.all([
      folkTags.fetchTags(catalogId.value),
      folkTags.fetchMlGroups(catalogId.value),
    ])
  }
})

async function openGroupBrowse(group: MlGroup) {
  browsingGroup.value = group
  groupImages.value = []
  groupImagesLoading.value = true
  try {
    const res = await axios.get(`/api/catalogs/${catalogId.value}/ml-groups/${group.id}/images`)
    groupImages.value = res.data
  } finally {
    groupImagesLoading.value = false
  }
}

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
  browsingGroup.value = null
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

async function confirmMerge() {
  if (!selectedTag.value || !mergeTarget.value || !catalogId.value) return
  await folkTags.mergeTag(catalogId.value, selectedTag.value.id, mergeTarget.value.id)
  showMergeModal.value = false
  mergeSearch.value = ''
  selectedTag.value = null
  selectedTagId.value = null
  mergeTarget.value = null
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
  } catch { return iso }
}

function fmtDateShort(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })
  } catch { return '' }
}
</script>
