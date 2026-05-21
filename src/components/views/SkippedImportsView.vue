<template>
  <div class="h-full flex flex-col">
    <!-- Stats Bar -->
    <div class="flex-none bg-gray-900/50 border-b border-gray-800 px-4 py-3">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-lg font-semibold text-gray-200">Skipped Imports</h2>
          <p class="text-sm text-gray-500">
            {{ total }} file{{ total !== 1 ? 's' : '' }} skipped at import (exact duplicates of existing photos)
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="total > 0"
            @click="dismissAll"
            :disabled="dismissing"
            class="text-xs px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-gray-300 flex items-center gap-1.5 transition-colors"
          >
            <LoaderIcon v-if="dismissing" class="w-3.5 h-3.5 animate-spin" />
            <CheckIcon v-else class="w-3.5 h-3.5" />
            Dismiss All ({{ total }})
          </button>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <LoaderIcon class="w-6 h-6 text-gray-500 animate-spin" />
    </div>

    <!-- Empty State -->
    <div v-else-if="items.length === 0" class="flex-1 flex items-center justify-center">
      <div class="text-center text-gray-500">
        <CopyXIcon class="w-12 h-12 mx-auto mb-3 opacity-30" />
        <p class="text-sm">No skipped imports</p>
        <p class="text-xs mt-1 text-gray-600">Files that match existing photos will appear here</p>
      </div>
    </div>

    <!-- List -->
    <div v-else class="flex-1 overflow-y-auto">
      <div class="divide-y divide-gray-800">
        <div
          v-for="item in items"
          :key="item.id"
          class="flex items-start gap-4 px-4 py-3 hover:bg-gray-800/30 transition-colors"
          :class="{ 'opacity-50': item.overridden || item.reviewed_at }"
        >
          <!-- Matched image thumbnail -->
          <div class="flex-none w-16 h-16 rounded overflow-hidden bg-gray-800 relative">
            <img
              v-if="thumbnailUrl(item)"
              :src="thumbnailUrl(item) ?? undefined"
              :alt="item.matched_image?.source_path"
              class="w-full h-full object-cover"
            />
            <div v-else class="w-full h-full flex items-center justify-center">
              <ImageIcon class="w-6 h-6 text-gray-600" />
            </div>
          </div>

          <!-- File info -->
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-200 truncate" :title="item.source_path">
              {{ filename(item.source_path) }}
            </p>
            <p class="text-xs text-gray-500 truncate mt-0.5" :title="item.source_path">
              {{ item.source_path }}
            </p>
            <p class="text-xs text-gray-600 mt-1">
              Matches: <span class="text-gray-400 truncate" :title="item.matched_image?.source_path">{{ item.matched_image?.source_path || item.matched_image_id }}</span>
            </p>
            <p class="text-xs text-gray-600 mt-0.5">
              Skipped {{ formatDate(item.skipped_at) }}
              <span v-if="item.reviewed_at" class="text-green-600"> · Dismissed</span>
              <span v-if="item.overridden" class="text-amber-500"> · Override requested</span>
            </p>
          </div>

          <!-- Actions -->
          <div class="flex-none flex items-center gap-2">
            <button
              v-if="!item.overridden"
              @click="override(item)"
              :disabled="overriding === item.id"
              class="text-xs px-2 py-1 rounded bg-amber-900/40 hover:bg-amber-900/60 disabled:opacity-50 text-amber-400 flex items-center gap-1 transition-colors"
              title="Mark as wanting to import this file (does not import automatically)"
            >
              <LoaderIcon v-if="overriding === item.id" class="w-3 h-3 animate-spin" />
              <FlagIcon v-else class="w-3 h-3" />
              Override
            </button>
          </div>
        </div>
      </div>

      <!-- Load more -->
      <div v-if="items.length < total" class="p-4 flex justify-center">
        <button
          @click="loadMore"
          :disabled="loading"
          class="text-xs px-4 py-2 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 transition-colors disabled:opacity-50"
        >
          Load more ({{ total - items.length }} remaining)
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Loader as LoaderIcon,
  Check as CheckIcon,
  CopyX as CopyXIcon,
  Image as ImageIcon,
  Flag as FlagIcon,
} from 'lucide-vue-next'
import { api, type SkippedImport } from '@/api/client'

const props = defineProps<{
  catalogId: string
}>()

const emit = defineEmits<{
  dismissed: []
}>()

const items = ref<SkippedImport[]>([])
const total = ref(0)
const loading = ref(false)
const dismissing = ref(false)
const overriding = ref<string | null>(null)

const PAGE_SIZE = 50

async function fetchItems(reset = false) {
  loading.value = true
  try {
    const offset = reset ? 0 : items.value.length
    const result = await api.getSkippedImports(props.catalogId, {
      limit: PAGE_SIZE,
      offset,
    })
    total.value = result.total
    if (reset) {
      items.value = result.items
    } else {
      items.value = [...items.value, ...result.items]
    }
  } catch (e) {
    console.error('Failed to load skipped imports', e)
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  await fetchItems(false)
}

async function override(item: SkippedImport) {
  overriding.value = item.id
  try {
    const updated = await api.overrideSkippedImport(props.catalogId, item.id)
    const idx = items.value.findIndex((i) => i.id === item.id)
    if (idx !== -1) {
      items.value[idx] = updated
    }
  } catch (e) {
    console.error('Failed to override skipped import', e)
  } finally {
    overriding.value = null
  }
}

async function dismissAll() {
  dismissing.value = true
  try {
    await api.dismissAllSkippedImports(props.catalogId)
    emit('dismissed')
    await fetchItems(true)
  } catch (e) {
    console.error('Failed to dismiss all skipped imports', e)
  } finally {
    dismissing.value = false
  }
}

function filename(path: string): string {
  return path.split('/').pop() || path
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

function thumbnailUrl(item: SkippedImport): string | null {
  if (!item.matched_image?.thumbnail_path) return null
  return `/api/catalogs/${props.catalogId}/images/${item.matched_image_id}/thumbnail`
}

onMounted(() => {
  fetchItems(true)
})
</script>
