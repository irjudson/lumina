<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center gap-2 px-4 py-2 border-b border-gray-800 shrink-0">
      <button @click="store.selectAll()" class="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap">All</button>
      <span class="text-gray-700">|</span>
      <button @click="store.deselectAll()" class="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap">None</button>
      <span class="text-xs text-gray-600 mx-1">·</span>
      <span class="text-xs text-gray-500 whitespace-nowrap">
        {{ store.selectedFiles.length }} / {{ store.discoveredFiles.length }}
      </span>
      <span v-if="store.isDiscovering" class="text-xs text-gray-500 italic">scanning…</span>
      <button
        v-if="store.selectedDevice && !store.isDiscovering"
        @click="store.discoverFiles(store.selectedDevice!.dcim_path)"
        class="flex items-center gap-1 px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded text-xs"
        title="Refresh"
      >
        <RefreshCwIcon class="w-3 h-3" />
      </button>
      <button
        v-if="store.discoveredFiles.length > 0"
        @click="emit('import')"
        :disabled="store.selectedFiles.length === 0"
        class="ml-auto px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
      >
        Import {{ store.selectedFiles.length > 0 ? store.selectedFiles.length : '' }} Photo{{ store.selectedFiles.length !== 1 ? 's' : '' }}
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="!store.selectedDevice" class="flex flex-col items-center justify-center h-full text-center">
        <CameraIcon class="w-12 h-12 text-gray-700 mb-4" />
        <p class="text-sm text-gray-400">Select a device from the left panel</p>
      </div>

      <div v-else-if="store.isDiscovering && store.discoveredFiles.length === 0" class="flex flex-col items-center justify-center h-full">
        <LoaderIcon class="w-8 h-8 text-blue-500 animate-spin mb-3" />
        <p class="text-sm text-gray-400">Scanning for new photos...</p>
      </div>

      <div v-else-if="store.discoverError" class="flex flex-col items-center justify-center h-full text-center">
        <AlertCircleIcon class="w-10 h-10 text-red-500 mb-3" />
        <p class="text-sm text-red-400">{{ store.discoverError }}</p>
      </div>

      <div v-else-if="store.discoveredFiles.length === 0 && store.selectedDevice" class="flex flex-col items-center justify-center h-full text-center">
        <CheckCircleIcon class="w-12 h-12 text-green-600 mb-4" />
        <p class="text-sm text-gray-400">All photos already imported</p>
      </div>

      <div v-else class="grid gap-2" style="grid-template-columns: repeat(auto-fill, minmax(120px, 1fr))">
        <ImportCard
          v-for="file in store.discoveredFiles"
          :key="file.path"
          :file="file"
          @toggle="store.toggleFile"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CameraIcon, LoaderIcon, AlertCircleIcon, CheckCircleIcon, RefreshCwIcon } from 'lucide-vue-next'
import { useCameraImportStore } from '@/stores/cameraImport'
import ImportCard from './ImportCard.vue'

const emit = defineEmits<{ import: [] }>()
const store = useCameraImportStore()
</script>
