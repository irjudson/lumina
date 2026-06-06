<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-800 shrink-0">
      <button @click="store.selectAll()" class="text-xs text-blue-400 hover:text-blue-300">Select All</button>
      <span class="text-gray-700">|</span>
      <button @click="store.deselectAll()" class="text-xs text-blue-400 hover:text-blue-300">None</button>
      <span class="text-xs text-gray-500 ml-auto">
        {{ store.selectedFiles.length }} / {{ store.discoveredFiles.length }} selected
      </span>
      <button
        v-if="store.selectedDevice"
        @click="store.discoverFiles(store.selectedDevice!.dcim_path)"
        :disabled="store.isDiscovering"
        class="flex items-center gap-1.5 px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-xs disabled:opacity-50"
      >
        <RefreshCwIcon class="w-3 h-3" :class="store.isDiscovering ? 'animate-spin' : ''" />
        Refresh
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="!store.selectedDevice" class="flex flex-col items-center justify-center h-full text-center">
        <CameraIcon class="w-12 h-12 text-gray-700 mb-4" />
        <p class="text-sm text-gray-400">Select a device from the left panel</p>
      </div>

      <div v-else-if="store.isDiscovering" class="flex flex-col items-center justify-center h-full">
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

const store = useCameraImportStore()
</script>
