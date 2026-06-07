<template>
  <button
    @click="handleClick"
    :disabled="disabled"
    :class="[
      'w-full px-3 py-2 text-left text-sm rounded transition-colors flex items-center gap-2 group',
      {
        'bg-blue-600 text-white': active && !disabled,
        'text-gray-400 hover:text-gray-200 hover:bg-gray-800': !active && !disabled,
        'opacity-50 cursor-not-allowed text-gray-600': disabled
      }
    ]"
  >
    <!-- Icon -->
    <component
      v-if="icon"
      :is="iconComponent"
      :class="[
        'w-4 h-4',
        {
          'text-white': active && !disabled,
          'text-gray-500 group-hover:text-gray-300': !active && !disabled,
          'text-gray-700': disabled
        }
      ]"
    />

    <!-- Label -->
    <span class="flex-1">{{ label }}</span>

    <!-- Count Badge -->
    <span
      v-if="count !== undefined && count > 0"
      :class="[
        'px-2 py-0.5 text-xs font-medium rounded-full',
        {
          'bg-blue-700 text-white': active && !disabled,
          'bg-gray-800 text-gray-400': !active && !disabled,
          'bg-gray-900 text-gray-700': disabled
        }
      ]"
    >
      {{ count }}
    </span>

    <!-- Disabled indicator -->
    <span v-if="disabled" class="text-xs text-gray-600">(soon)</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
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
  Folder as FolderIcon,
  Trash2 as Trash2Icon,
  FileWarning as FileWarningIcon,
  FileText as FileTextIcon,
  Monitor as MonitorIcon,
  PartyPopper as PartyPopperIcon,
  BarChart2 as BarChart2Icon,
  Layers as LayersIcon,
  Download as DownloadIcon,
  Users as UsersIcon,
  Briefcase as BriefcaseIcon,
  Archive as ArchiveIcon,
  Heart as HeartIcon,
  Plane as PlaneIcon,
  FolderOpen as FolderOpenIcon,
  User as UserIcon,
  MapPin as MapPinIcon,
} from 'lucide-vue-next'

interface Props {
  icon: string
  label: string
  active?: boolean
  disabled?: boolean
  count?: number
}

const props = withDefaults(defineProps<Props>(), {
  active: false,
  disabled: false
})

const emit = defineEmits<{
  click: []
}>()

// Map icon names to components
const iconMap: Record<string, any> = {
  Images: ImagesIcon,
  Calendar: CalendarIcon,
  Map: MapIcon,
  Star: StarIcon,
  Zap: ZapIcon,
  Copy: CopyIcon,
  CopyX: CopyXIcon,
  Clock: ClockIcon,
  Tag: TagIcon,
  AlertCircle: AlertCircleIcon,
  Video: VideoIcon,
  Folder: FolderIcon,
  Trash2: Trash2Icon,
  FileWarning: FileWarningIcon,
  FileText: FileTextIcon,
  Monitor: MonitorIcon,
  PartyPopper: PartyPopperIcon,
  BarChart2: BarChart2Icon,
  Layers: LayersIcon,
  Download: DownloadIcon,
  Users: UsersIcon,
  Briefcase: BriefcaseIcon,
  Archive: ArchiveIcon,
  Heart: HeartIcon,
  Plane: PlaneIcon,
  FolderOpen: FolderOpenIcon,
  User: UserIcon,
  MapPin: MapPinIcon,
}

const iconComponent = computed(() => iconMap[props.icon] || ImagesIcon)

function handleClick() {
  if (!props.disabled) {
    emit('click')
  }
}
</script>
