<template>
  <div class="p-4 space-y-6">
    <div>
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Destination</h4>
      <div v-if="catalogStore.activeCatalog?.organized_directory" class="space-y-1">
        <div class="text-xs text-gray-500">Organized directory</div>
        <div class="text-xs text-gray-300 font-mono break-all">
          {{ catalogStore.activeCatalog.organized_directory }}/YYYY/MM-DD/
        </div>
      </div>
      <div v-else class="text-xs text-amber-400">
        No organized directory set. Configure one in Catalog Settings.
      </div>
    </div>

    <div class="pt-4 border-t border-gray-800">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Options</h4>
      <label class="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          v-model="store.deleteSource"
          class="mt-0.5 rounded border-gray-700 bg-gray-800 text-red-600"
        />
        <div>
          <div class="text-xs text-gray-300">Delete from device after import</div>
          <div class="text-xs text-gray-500 mt-0.5">Frees space on camera/card</div>
        </div>
      </label>
    </div>

    <div class="pt-4 border-t border-gray-800">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Summary</h4>
      <div class="space-y-2 text-xs">
        <div class="flex justify-between">
          <span class="text-gray-400">Selected</span>
          <span class="text-gray-200">{{ store.selectedFiles.length }} files</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-400">Total size</span>
          <span class="text-gray-200">{{ formatBytes(store.totalSelectedBytes) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useCameraImportStore } from '@/stores/cameraImport'
import { useCatalogStore } from '@/stores/catalog'

const store = useCameraImportStore()
const catalogStore = useCatalogStore()

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}
</script>
