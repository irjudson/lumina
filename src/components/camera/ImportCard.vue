<template>
  <div
    class="relative group cursor-pointer rounded-md overflow-hidden border transition-all"
    :class="file.selected ? 'border-blue-500' : 'border-gray-700 opacity-60'"
    @click="$emit('toggle', file.path)"
  >
    <div class="aspect-square bg-gray-800">
      <img
        v-if="file.thumbnail_data_url"
        :src="file.thumbnail_data_url"
        :alt="file.filename"
        class="w-full h-full object-cover"
      />
      <div v-else class="w-full h-full flex items-center justify-center">
        <ImageIcon class="w-8 h-8 text-gray-600" />
      </div>
    </div>

    <div class="absolute top-1.5 left-1.5">
      <div
        class="w-5 h-5 rounded border-2 flex items-center justify-center transition-colors"
        :class="file.selected
          ? 'bg-blue-500 border-blue-500'
          : 'bg-black/40 border-gray-400'"
      >
        <CheckIcon v-if="file.selected" class="w-3 h-3 text-white" />
      </div>
    </div>

    <div class="absolute bottom-0 inset-x-0 bg-black/70 px-1.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <div class="text-xs text-gray-200 truncate">{{ file.filename }}</div>
      <div v-if="file.taken_at" class="text-xs text-gray-400">{{ formatDate(file.taken_at) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ImageIcon, CheckIcon } from 'lucide-vue-next'
import type { SelectableFile } from '@/stores/cameraImport'

defineProps<{ file: SelectableFile }>()
defineEmits<{ (e: 'toggle', path: string): void }>()

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
</script>
