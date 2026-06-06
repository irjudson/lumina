<template>
  <div class="p-4 space-y-4">
    <div class="flex items-center justify-between">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Devices</h4>
      <button @click="store.fetchDevices()" class="text-gray-500 hover:text-gray-300 transition-colors">
        <RefreshCwIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <div v-if="store.devices.length" class="space-y-2">
      <button
        v-for="device in store.devices"
        :key="device.path"
        @click="selectDevice(device)"
        class="w-full flex items-start gap-3 p-3 rounded-md text-left transition-colors"
        :class="store.selectedDevice?.path === device.path
          ? 'bg-blue-600/20 border border-blue-500/40'
          : 'bg-gray-800 hover:bg-gray-700 border border-transparent'"
      >
        <CameraIcon class="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
        <div class="min-w-0">
          <div class="text-sm font-medium text-gray-200 truncate">{{ device.name }}</div>
          <div class="text-xs text-gray-500">{{ device.file_count_estimate }} files</div>
        </div>
      </button>
    </div>

    <div v-else class="text-xs text-gray-500 italic">No devices detected</div>

    <div class="pt-4 border-t border-gray-800">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Manual Path</h4>
      <div class="flex gap-2">
        <input
          v-model="manualPath"
          placeholder="/path/to/DCIM"
          class="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
          @keydown.enter="selectManual"
        />
        <button
          @click="selectManual"
          :disabled="!manualPath"
          class="px-2 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs disabled:opacity-50"
        >
          Go
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { CameraIcon, RefreshCwIcon } from 'lucide-vue-next'
import { useCameraImportStore } from '@/stores/cameraImport'
import type { CameraDevice } from '@/api/client'

const store = useCameraImportStore()
const manualPath = ref('')
let pollTimer: number | null = null

function selectDevice(device: CameraDevice) {
  store.selectedDevice = device
  store.discoverFiles(device.dcim_path)
}

function selectManual() {
  if (!manualPath.value) return
  store.selectedDevice = { name: manualPath.value, path: manualPath.value, dcim_path: manualPath.value, file_count_estimate: 0 }
  store.discoverFiles(manualPath.value)
}

onMounted(() => {
  store.fetchDevices()
  pollTimer = window.setInterval(() => store.fetchDevices(), 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
