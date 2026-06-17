<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 bg-black flex flex-col"
      @keydown="handleKeydown"
      tabindex="0"
      ref="overlayRef"
    >
      <!-- Top Bar -->
      <div class="flex-none flex items-center justify-between px-4 py-2 bg-black/80 border-b border-gray-800/50 z-10">
        <div class="flex items-center gap-3 min-w-0">
          <span class="text-sm text-gray-300 truncate">{{ filename }}</span>
          <span v-if="images.length > 1" class="text-xs text-gray-500 whitespace-nowrap">
            {{ currentIndex + 1 }} of {{ images.length }}
          </span>
          <button
            v-if="!isFullRes"
            @click="loadFullRes"
            class="text-[10px] px-1.5 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 rounded cursor-pointer transition-colors whitespace-nowrap"
            title="Load full resolution"
          >HD</button>
          <span v-else class="text-[10px] px-1.5 py-0.5 bg-blue-900/50 text-blue-400 rounded whitespace-nowrap">FULL</span>
          <span v-if="cropMode" class="text-[10px] px-1.5 py-0.5 bg-orange-900/60 text-orange-300 rounded whitespace-nowrap">
            {{ cropDimensions }}
          </span>
        </div>

        <div class="flex items-center gap-1">
          <button @click="$emit('favorite', currentImage?.id)"
            class="p-2 rounded hover:bg-gray-800 transition-colors text-gray-400 hover:text-yellow-400"
            title="Favorite (F)">
            <StarIcon class="w-4 h-4" />
          </button>
          <button @click="$emit('reject', currentImage?.id)"
            class="p-2 rounded hover:bg-gray-800 transition-colors text-gray-400 hover:text-red-400"
            title="Reject (X)">
            <Trash2Icon class="w-4 h-4" />
          </button>
          <div class="w-px h-4 bg-gray-700 mx-1" />

          <button v-for="tab in TABS" :key="tab.id"
            @click="setTab(tab.id)"
            class="p-2 rounded transition-colors"
            :class="panelOpen && activeTab === tab.id ? 'text-blue-400 bg-gray-800' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'"
            :title="`${tab.label} (${tab.key})`"
          >
            <component :is="tab.icon" class="w-4 h-4" />
          </button>

          <div class="w-px h-4 bg-gray-700 mx-1" />
          <button @click="$emit('close')"
            class="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
            title="Close (Esc)">
            <XIcon class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- Image Area -->
      <div class="flex-1 relative overflow-hidden" ref="imageAreaRef">
        <!-- Loading Spinner -->
        <div v-if="imageLoading" class="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
          <LoaderIcon class="w-10 h-10 animate-spin text-blue-500" />
        </div>

        <!-- Image + Crop Overlay -->
        <div class="absolute inset-0 flex items-center justify-center">
          <div class="relative" :style="imageWrapperStyle" ref="imageWrapperRef">
            <img
              ref="imgEl"
              :src="currentSrc"
              :key="currentSrc"
              class="block w-full h-full"
              :style="{ filter: hasHSAdjustment ? 'none' : cssFilter, display: imageLoading ? 'none' : 'block' }"
              @load="onImageLoad"
              @error="imageLoading = false"
              crossorigin="anonymous"
            />
            <!-- Pixel-level preview for Highlights/Shadows (canvas bakes in all adjustments) -->
            <img
              v-if="previewSrc && !imageLoading"
              :src="previewSrc"
              class="absolute inset-0 w-full h-full pointer-events-none"
              style="filter: none"
            />

            <!-- Crop Overlay -->
            <div v-if="cropMode && !imageLoading" class="absolute inset-0 cursor-crosshair" @mousedown="onCropAreaMousedown">
              <!-- Dark: top -->
              <div class="absolute left-0 right-0 top-0 bg-black/60 pointer-events-none" :style="{ height: `${cropRect.y * 100}%` }" />
              <!-- Dark: bottom -->
              <div class="absolute left-0 right-0 bottom-0 bg-black/60 pointer-events-none" :style="{ height: `${(1 - cropRect.y - cropRect.h) * 100}%` }" />
              <!-- Dark: left -->
              <div class="absolute bg-black/60 pointer-events-none" :style="{ top: `${cropRect.y * 100}%`, height: `${cropRect.h * 100}%`, left: 0, width: `${cropRect.x * 100}%` }" />
              <!-- Dark: right -->
              <div class="absolute bg-black/60 pointer-events-none" :style="{ top: `${cropRect.y * 100}%`, height: `${cropRect.h * 100}%`, right: 0, width: `${(1 - cropRect.x - cropRect.w) * 100}%` }" />

              <!-- Crop selection box -->
              <div
                class="absolute border border-white/80 cursor-move"
                :style="cropSelectionStyle"
                @mousedown.stop="startCropDrag('move', $event)"
              >
                <!-- Rule of thirds -->
                <div class="absolute inset-0 pointer-events-none overflow-hidden">
                  <div class="absolute left-1/3 top-0 bottom-0 border-l border-white/20" />
                  <div class="absolute left-2/3 top-0 bottom-0 border-l border-white/20" />
                  <div class="absolute top-1/3 left-0 right-0 border-t border-white/20" />
                  <div class="absolute top-2/3 left-0 right-0 border-t border-white/20" />
                </div>
                <!-- Corner handles -->
                <div v-for="h in CORNER_HANDLES" :key="h.id"
                  class="absolute w-4 h-4 bg-white border border-gray-400 shadow"
                  :style="h.style"
                  :class="h.cursor"
                  @mousedown.stop="startCropDrag(h.id, $event)"
                />
                <!-- Edge handles -->
                <div v-for="h in EDGE_HANDLES" :key="h.id"
                  class="absolute w-3 h-3 bg-white border border-gray-400 shadow"
                  :style="h.style"
                  :class="h.cursor"
                  @mousedown.stop="startCropDrag(h.id, $event)"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Left Nav Arrow -->
        <button
          v-if="currentIndex > 0"
          @click="navigatePrev"
          class="absolute left-0 top-1/2 -translate-y-1/2 h-24 w-12 flex items-center justify-center text-white/40 hover:text-white hover:bg-black/50 transition-all"
        >
          <ChevronLeftIcon class="w-7 h-7" />
        </button>

        <!-- Right Nav Arrow -->
        <button
          v-if="currentIndex < images.length - 1"
          @click="navigateNext"
          class="absolute right-0 top-1/2 -translate-y-1/2 h-24 w-12 flex items-center justify-center text-white/40 hover:text-white hover:bg-black/50 transition-all"
        >
          <ChevronRightIcon class="w-7 h-7" />
        </button>
      </div>

      <!-- Drag Handle -->
      <div
        v-if="panelOpen"
        class="flex-none h-1.5 bg-gray-800 hover:bg-blue-600 cursor-ns-resize transition-colors group flex items-center justify-center"
        @mousedown="startPanelResize"
      >
        <div class="w-8 h-0.5 bg-gray-600 group-hover:bg-blue-400 rounded transition-colors" />
      </div>

      <!-- Bottom Panel -->
      <div v-if="panelOpen" class="flex-none flex flex-col bg-gray-950 border-t border-gray-800" :style="{ height: `${panelHeight}px` }">
        <!-- Tab bar -->
        <div class="flex-none flex items-center gap-0.5 px-3 pt-1.5 pb-0 border-b border-gray-800">
          <button v-for="tab in TABS" :key="tab.id"
            @click="setTab(tab.id)"
            class="px-3 py-1.5 text-xs rounded-t transition-colors flex items-center gap-1.5"
            :class="activeTab === tab.id
              ? 'bg-gray-800 text-gray-100 border border-gray-700 border-b-gray-800'
              : 'text-gray-500 hover:text-gray-300'"
          >
            <component :is="tab.icon" class="w-3.5 h-3.5" />
            {{ tab.label }}
          </button>
          <div class="ml-auto">
            <button @click="panelOpen = false" class="p-1.5 text-gray-600 hover:text-gray-400 transition-colors" title="Collapse panel">
              <ChevronDownIcon class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <!-- Tab content -->
        <div class="flex-1 overflow-y-auto">
          <!-- Info Tab -->
          <div v-if="activeTab === 'info'" class="p-4 space-y-4 text-xs">
            <section>
              <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">File</h4>
              <div class="space-y-1">
                <div class="text-gray-300 break-all">{{ filename }}</div>
                <div class="flex justify-between gap-2 text-gray-500">
                  <span>{{ fileTypeLabel }}</span>
                  <span>{{ fileSizeLabel }}</span>
                </div>
                <div v-if="captureDate" class="text-gray-500">{{ captureDate }}</div>
              </div>
            </section>

            <section v-if="cameraInfo || metadata?.lens_model">
              <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Camera</h4>
              <div class="space-y-1">
                <div v-if="cameraInfo" class="text-gray-300">{{ cameraInfo }}</div>
                <div v-if="metadata?.lens_model" class="text-gray-500 truncate">{{ metadata.lens_model }}</div>
              </div>
            </section>

            <section v-if="metadata?.iso || metadata?.aperture || metadata?.shutter_speed || metadata?.focal_length">
              <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Exposure</h4>
              <div class="flex flex-wrap gap-x-3 gap-y-1 text-gray-400">
                <span v-if="metadata?.iso">ISO {{ metadata.iso }}</span>
                <span v-if="metadata?.aperture">f/{{ metadata.aperture }}</span>
                <span v-if="shutterSpeed">{{ shutterSpeed }}</span>
                <span v-if="metadata?.focal_length">{{ Math.round(metadata.focal_length) }}mm</span>
              </div>
            </section>

            <section v-if="metadata?.width && metadata?.height">
              <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Dimensions</h4>
              <div class="text-gray-400">
                {{ metadata.width }} × {{ metadata.height }}
                <span class="text-gray-600 ml-2">{{ ((metadata.width * metadata.height) / 1e6).toFixed(1) }} MP</span>
              </div>
            </section>

            <section v-if="metadata?.gps_latitude">
              <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Location</h4>
              <div class="text-gray-400 space-y-1">
                <div>{{ Number(metadata.gps_latitude).toFixed(5) }}, {{ Number(metadata.gps_longitude).toFixed(5) }}</div>
                <div v-if="metadata.gps_altitude" class="text-gray-600">{{ Math.round(metadata.gps_altitude) }}m altitude</div>
              </div>
            </section>

            <section v-if="currentImage?.quality_score != null">
              <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Quality</h4>
              <div class="flex items-center gap-2">
                <div class="flex-1 bg-gray-800 rounded-full h-1.5">
                  <div class="h-1.5 rounded-full transition-all" :class="qualityColor" :style="{ width: `${currentImage.quality_score}%` }" />
                </div>
                <span class="text-gray-300">{{ Math.round(currentImage.quality_score) }}</span>
              </div>
            </section>
          </div>

          <!-- Histogram Tab -->
          <div v-else-if="activeTab === 'histogram'" class="p-4">
            <div v-if="histogramLoading" class="flex items-center justify-center h-24 text-gray-600">
              <LoaderIcon class="w-5 h-5 animate-spin" />
            </div>
            <div v-else-if="histogram" class="space-y-2">
              <div class="bg-black rounded overflow-hidden border border-gray-800">
                <svg viewBox="0 0 256 80" class="w-full h-28" preserveAspectRatio="none">
                  <path :d="histPaths.lum" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.35)" stroke-width="0.6" />
                  <path :d="histPaths.red" fill="rgba(220,60,60,0.18)" stroke="rgba(255,90,90,0.7)" stroke-width="0.6" />
                  <path :d="histPaths.green" fill="rgba(60,180,60,0.18)" stroke="rgba(80,220,80,0.7)" stroke-width="0.6" />
                  <path :d="histPaths.blue" fill="rgba(60,80,220,0.18)" stroke="rgba(80,120,255,0.7)" stroke-width="0.6" />
                </svg>
              </div>
              <div class="flex justify-between text-[10px] text-gray-600 px-0.5">
                <span>Shadows</span><span>Midtones</span><span>Highlights</span>
              </div>
              <div class="flex gap-3 text-[10px] text-gray-500">
                <span class="text-red-400">R</span>
                <span class="text-green-400">G</span>
                <span class="text-blue-400">B</span>
                <span class="text-gray-400">Lum</span>
              </div>
            </div>
            <div v-else class="text-xs text-gray-600 text-center py-6">Failed to load histogram</div>
          </div>

          <!-- Adjust Tab -->
          <div v-else-if="activeTab === 'adjust'" class="p-4 space-y-3">
            <div class="space-y-2">
              <div v-for="slider in SLIDERS" :key="slider.key" class="flex items-center gap-2">
                <span class="text-[11px] text-gray-500 w-20 flex-none">{{ slider.label }}</span>
                <input
                  type="range"
                  :min="slider.min"
                  :max="slider.max"
                  :step="slider.step"
                  v-model.number="adjustments[slider.key]"
                  class="flex-1 accent-blue-500 h-1"
                />
                <span class="text-[11px] text-gray-400 w-9 text-right tabular-nums flex-none">
                  {{ adjustments[slider.key] > 0 ? '+' : '' }}{{ adjustments[slider.key] }}
                </span>
              </div>
            </div>

            <!-- Crop -->
            <div class="pt-2 border-t border-gray-800 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-[11px] text-gray-500">Crop</span>
                <div class="flex gap-1">
                  <button
                    @click="toggleCrop"
                    class="text-[11px] px-2 py-1 rounded transition-colors"
                    :class="cropMode ? 'bg-orange-700/60 text-orange-200' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'"
                  >{{ cropMode ? 'Cropping…' : 'Enable Crop' }}</button>
                  <button v-if="cropMode" @click="resetCrop" class="text-[11px] px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors">Reset</button>
                </div>
              </div>
              <p v-if="cropMode" class="text-[10px] text-gray-600">Drag corners/edges to adjust. Drag interior to move.</p>
            </div>

            <!-- Actions -->
            <div class="pt-2 border-t border-gray-800 flex gap-2 flex-wrap">
              <button
                @click="resetAdjustments"
                class="flex-1 text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors"
              >Reset All</button>
              <button
                @click="showExport = true"
                class="flex-1 text-xs px-3 py-1.5 bg-blue-700 hover:bg-blue-600 text-white rounded transition-colors flex items-center justify-center gap-1.5"
              >
                <DownloadIcon class="w-3.5 h-3.5" />
                Export…
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Collapsed tab strip -->
      <div v-else class="flex-none flex items-center gap-0.5 px-3 py-1 border-t border-gray-800 bg-gray-950">
        <button v-for="tab in TABS" :key="tab.id"
          @click="setTab(tab.id)"
          class="px-3 py-1 text-xs text-gray-600 hover:text-gray-300 rounded transition-colors flex items-center gap-1.5"
        >
          <component :is="tab.icon" class="w-3 h-3" />
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- Export Modal -->
    <ExportModal
      v-if="showExport"
      :catalog-id="props.catalogId"
      :image-id="props.imageId"
      :filename="filename"
      @close="showExport = false"
    />
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted, watch, nextTick, markRaw } from 'vue'
import ExportModal from './ExportModal.vue'
import {
  X as XIcon,
  Info as InfoIcon,
  BarChart2 as BarChart2Icon,
  SlidersHorizontal as SlidersHorizontalIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  ChevronDown as ChevronDownIcon,
  Loader as LoaderIcon,
  Star as StarIcon,
  Trash2 as Trash2Icon,
  Download as DownloadIcon,
} from 'lucide-vue-next'
import type { Image } from '@/stores/library'

const props = defineProps<{
  catalogId: string
  imageId: string
  images: Image[]
}>()

const emit = defineEmits<{
  close: []
  navigate: [imageId: string]
  reject: [imageId: string | undefined]
  favorite: [imageId: string | undefined]
}>()

// ─── Constants ────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'info' as const, label: 'Info', icon: markRaw(InfoIcon), key: 'I' },
  { id: 'histogram' as const, label: 'Histogram', icon: markRaw(BarChart2Icon), key: 'H' },
  { id: 'adjust' as const, label: 'Adjust', icon: markRaw(SlidersHorizontalIcon), key: 'A' },
]

const SLIDERS = [
  { key: 'exposure' as const, label: 'Exposure', min: -100, max: 100, step: 1 },
  { key: 'contrast' as const, label: 'Contrast', min: -100, max: 100, step: 1 },
  { key: 'highlights' as const, label: 'Highlights', min: -100, max: 100, step: 1 },
  { key: 'shadows' as const, label: 'Shadows', min: -100, max: 100, step: 1 },
  { key: 'saturation' as const, label: 'Saturation', min: -100, max: 100, step: 1 },
]

const CORNER_HANDLES = [
  { id: 'nw' as const, cursor: 'cursor-nw-resize', style: 'top:0;left:0;transform:translate(-50%,-50%)' },
  { id: 'ne' as const, cursor: 'cursor-ne-resize', style: 'top:0;right:0;transform:translate(50%,-50%)' },
  { id: 'sw' as const, cursor: 'cursor-sw-resize', style: 'bottom:0;left:0;transform:translate(-50%,50%)' },
  { id: 'se' as const, cursor: 'cursor-se-resize', style: 'bottom:0;right:0;transform:translate(50%,50%)' },
]

const EDGE_HANDLES = [
  { id: 'n' as const, cursor: 'cursor-n-resize', style: 'top:0;left:50%;transform:translate(-50%,-50%)' },
  { id: 's' as const, cursor: 'cursor-s-resize', style: 'bottom:0;left:50%;transform:translate(-50%,50%)' },
  { id: 'w' as const, cursor: 'cursor-w-resize', style: 'top:50%;left:0;transform:translate(-50%,-50%)' },
  { id: 'e' as const, cursor: 'cursor-e-resize', style: 'top:50%;right:0;transform:translate(50%,-50%)' },
]

// ─── Refs ─────────────────────────────────────────────────────────────────────

const overlayRef = ref<HTMLElement | null>(null)
const imageAreaRef = ref<HTMLElement | null>(null)
const imageWrapperRef = ref<HTMLElement | null>(null)
const imgEl = ref<HTMLImageElement | null>(null)
const showExport = ref(false)

// ─── Image loading ─────────────────────────────────────────────────────────────

const imageLoading = ref(true)
const isFullRes = ref(false)
const naturalW = ref(0)
const naturalH = ref(0)
const containerW = ref(0)
const containerH = ref(0)

const thumbnailSrc = computed(() =>
  `/api/catalogs/${props.catalogId}/images/${props.imageId}/thumbnail?size=xlarge`
)
const fullSrc = computed(() =>
  `/api/catalogs/${props.catalogId}/images/${props.imageId}/full`
)
const currentSrc = computed(() => isFullRes.value ? fullSrc.value : thumbnailSrc.value)

function loadFullRes() {
  isFullRes.value = true
  imageLoading.value = true
}

function onImageLoad() {
  const img = imgEl.value
  if (img) {
    naturalW.value = img.naturalWidth
    naturalH.value = img.naturalHeight
  }
  imageLoading.value = false
  nextTick(updateContainerSize)
  nextTick(preloadAdjacent)
}

function preloadAdjacent() {
  for (const offset of [-1, 1]) {
    const idx = currentIndex.value + offset
    if (idx >= 0 && idx < props.images.length) {
      const preloadImg = new window.Image()
      preloadImg.src = `/api/catalogs/${props.catalogId}/images/${props.images[idx].id}/thumbnail?size=xlarge`
    }
  }
}

// ─── Image wrapper sizing ──────────────────────────────────────────────────────

let resizeObserver: ResizeObserver | null = null

function updateContainerSize() {
  const el = imageAreaRef.value
  if (el) {
    containerW.value = el.clientWidth
    containerH.value = el.clientHeight
  }
}

const imageWrapperStyle = computed(() => {
  if (!naturalW.value || !naturalH.value || !containerW.value || !containerH.value) return {}
  const imgRatio = naturalW.value / naturalH.value
  const conRatio = containerW.value / containerH.value
  let w: number, h: number
  if (imgRatio > conRatio) {
    w = containerW.value; h = containerW.value / imgRatio
  } else {
    h = containerH.value; w = containerH.value * imgRatio
  }
  return { width: `${Math.round(w)}px`, height: `${Math.round(h)}px` }
})

// ─── Panel state ───────────────────────────────────────────────────────────────

const panelOpen = ref(false)
const activeTab = ref<'info' | 'histogram' | 'adjust'>('info')
const panelHeight = ref(220)
const MIN_PANEL = 100
const MAX_PANEL_FRAC = 0.65

function setTab(tab: 'info' | 'histogram' | 'adjust') {
  if (activeTab.value === tab && panelOpen.value) {
    panelOpen.value = false
  } else {
    activeTab.value = tab
    panelOpen.value = true
    if (tab === 'histogram') fetchHistogram()
    nextTick(updateContainerSize)
  }
}

function startPanelResize(e: MouseEvent) {
  e.preventDefault()
  const startY = e.clientY
  const startH = panelHeight.value
  const onMove = (ev: MouseEvent) => {
    const delta = startY - ev.clientY
    panelHeight.value = Math.max(MIN_PANEL, Math.min(startH + delta, window.innerHeight * MAX_PANEL_FRAC))
    updateContainerSize()
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

// ─── Adjustments ───────────────────────────────────────────────────────────────

const adjustments = reactive({
  exposure: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  saturation: 0,
})

const cssFilter = computed(() => {
  const b = 1 + adjustments.exposure / 100
  const c = 1 + adjustments.contrast / 100
  const s = 1 + adjustments.saturation / 100
  const parts: string[] = []
  if (b !== 1) parts.push(`brightness(${b.toFixed(3)})`)
  if (c !== 1) parts.push(`contrast(${c.toFixed(3)})`)
  if (s !== 1) parts.push(`saturate(${s.toFixed(3)})`)
  return parts.join(' ') || 'none'
})

// ─── Highlights / Shadows live preview ────────────────────────────────────────

const hasHSAdjustment = computed(() => adjustments.highlights !== 0 || adjustments.shadows !== 0)
const previewSrc = ref<string | null>(null)
let previewBlobUrl: string | null = null
let previewTimer: ReturnType<typeof setTimeout> | null = null

function schedulePreviewRender() {
  if (previewTimer) clearTimeout(previewTimer)
  if (!hasHSAdjustment.value) {
    if (previewBlobUrl) { URL.revokeObjectURL(previewBlobUrl); previewBlobUrl = null }
    previewSrc.value = null
    return
  }
  previewTimer = setTimeout(renderHSPreview, 120)
}

function renderHSPreview() {
  const img = imgEl.value
  if (!img || imageLoading.value || !img.naturalWidth) return

  const canvas = document.createElement('canvas')
  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  // Bake in exposure/contrast/saturation via canvas filter
  ctx.filter = cssFilter.value
  ctx.drawImage(img, 0, 0)
  ctx.filter = 'none'

  // Pixel-level highlights/shadows
  const id = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const d = id.data
  const hv = adjustments.highlights / 100
  const sv = adjustments.shadows / 100
  for (let i = 0; i < d.length; i += 4) {
    const lum = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255
    if (hv !== 0 && lum > 0.5) {
      const f = (lum - 0.5) * 2
      const adj = 1 + hv * f * 0.4
      d[i] = clamp255(d[i] * adj)
      d[i + 1] = clamp255(d[i + 1] * adj)
      d[i + 2] = clamp255(d[i + 2] * adj)
    }
    if (sv !== 0 && lum < 0.5) {
      const f = (0.5 - lum) * 2
      const adj = 1 + sv * f * 0.4
      d[i] = clamp255(d[i] * adj)
      d[i + 1] = clamp255(d[i + 1] * adj)
      d[i + 2] = clamp255(d[i + 2] * adj)
    }
  }
  ctx.putImageData(id, 0, 0)

  canvas.toBlob((blob) => {
    if (!blob) return
    if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl)
    previewBlobUrl = URL.createObjectURL(blob)
    previewSrc.value = previewBlobUrl
  }, 'image/jpeg', 0.92)
}

watch(
  [() => adjustments.highlights, () => adjustments.shadows,
   () => adjustments.exposure, () => adjustments.contrast, () => adjustments.saturation],
  () => { schedulePreviewRender() }
)

function resetAdjustments() {
  Object.assign(adjustments, { exposure: 0, contrast: 0, highlights: 0, shadows: 0, saturation: 0 })
  resetCrop()
  cropMode.value = false
}

// ─── Crop ──────────────────────────────────────────────────────────────────────

interface CropRect { x: number; y: number; w: number; h: number }
type CropHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'move'

const cropMode = ref(false)
const cropRect = ref<CropRect>({ x: 0.05, y: 0.05, w: 0.9, h: 0.9 })
let dragState: { handle: CropHandle; startX: number; startY: number; startRect: CropRect } | null = null

const cropSelectionStyle = computed(() => ({
  left: `${cropRect.value.x * 100}%`,
  top: `${cropRect.value.y * 100}%`,
  width: `${cropRect.value.w * 100}%`,
  height: `${cropRect.value.h * 100}%`,
}))

const cropDimensions = computed(() => {
  const w = Math.round(cropRect.value.w * naturalW.value)
  const h = Math.round(cropRect.value.h * naturalH.value)
  if (!w || !h) return 'Crop'
  const gcd = (a: number, b: number): number => b === 0 ? a : gcd(b, a % b)
  const d = gcd(w, h)
  return `${w}×${h} (${w/d}:${h/d})`
})

function toggleCrop() {
  cropMode.value = !cropMode.value
}

function resetCrop() {
  cropRect.value = { x: 0.05, y: 0.05, w: 0.9, h: 0.9 }
}

function onCropAreaMousedown(e: MouseEvent) {
  // Only start a new crop drag if not clicking inside the selection
  // (inner elements handle their own mousedown.stop)
  startCropDrag('move', e)
}

function startCropDrag(handle: CropHandle, e: MouseEvent) {
  e.preventDefault()
  dragState = { handle, startX: e.clientX, startY: e.clientY, startRect: { ...cropRect.value } }
  window.addEventListener('mousemove', onCropMouseMove)
  window.addEventListener('mouseup', onCropMouseUp)
}

function onCropMouseMove(e: MouseEvent) {
  if (!dragState || !imageWrapperRef.value) return
  const rect = imageWrapperRef.value.getBoundingClientRect()
  const dx = (e.clientX - dragState.startX) / rect.width
  const dy = (e.clientY - dragState.startY) / rect.height
  const sr = dragState.startRect
  const MIN = 0.04
  let { x, y, w, h } = { ...sr }

  if (dragState.handle === 'move') {
    x = clamp(sr.x + dx, 0, 1 - sr.w)
    y = clamp(sr.y + dy, 0, 1 - sr.h)
  }
  if (dragState.handle.includes('n')) {
    const ny = clamp(sr.y + dy, 0, sr.y + sr.h - MIN)
    h = sr.y + sr.h - ny; y = ny
  }
  if (dragState.handle.includes('s')) {
    h = clamp(sr.h + dy, MIN, 1 - sr.y)
  }
  if (dragState.handle.includes('w')) {
    const nx = clamp(sr.x + dx, 0, sr.x + sr.w - MIN)
    w = sr.x + sr.w - nx; x = nx
  }
  if (dragState.handle.includes('e')) {
    w = clamp(sr.w + dx, MIN, 1 - sr.x)
  }
  cropRect.value = { x, y, w, h }
}

function onCropMouseUp() {
  dragState = null
  window.removeEventListener('mousemove', onCropMouseMove)
  window.removeEventListener('mouseup', onCropMouseUp)
}

function clamp(v: number, lo: number, hi: number) { return Math.min(hi, Math.max(lo, v)) }
function clamp255(v: number) { return Math.min(255, Math.max(0, Math.round(v))) }

// ─── Histogram ─────────────────────────────────────────────────────────────────

interface HistData { red: number[]; green: number[]; blue: number[]; luminance: number[] }
const histogram = ref<HistData | null>(null)
const histogramLoading = ref(false)

async function fetchHistogram() {
  if (histogram.value || histogramLoading.value) return
  histogramLoading.value = true
  try {
    const res = await fetch(`/api/catalogs/${props.catalogId}/images/${props.imageId}/histogram`)
    if (res.ok) histogram.value = await res.json()
  } catch { /* non-critical */ } finally {
    histogramLoading.value = false
  }
}

function toSvgPath(data: number[], maxVal: number): string {
  if (!data?.length || maxVal === 0) return ''
  const W = 256; const H = 80
  const step = W / 255
  const pts = data.map((v, i) => `${(i * step).toFixed(1)},${(H - (v / maxVal) * H * 0.93).toFixed(1)}`).join(' L ')
  return `M 0,${H} L ${pts} L ${W},${H} Z`
}

const histPaths = computed(() => {
  const h = histogram.value
  if (!h) return { red: '', green: '', blue: '', lum: '' }
  const maxVal = Math.max(
    ...h.red, ...h.green, ...h.blue, ...h.luminance
  )
  return {
    red: toSvgPath(h.red, maxVal),
    green: toSvgPath(h.green, maxVal),
    blue: toSvgPath(h.blue, maxVal),
    lum: toSvgPath(h.luminance, maxVal),
  }
})

// ─── Navigation ────────────────────────────────────────────────────────────────

const currentIndex = computed(() => {
  const idx = props.images.findIndex(img => img.id === props.imageId)
  return idx >= 0 ? idx : 0
})
const currentImage = computed(() => props.images[currentIndex.value])

function navigateNext() {
  if (currentIndex.value < props.images.length - 1) {
    emit('navigate', props.images[currentIndex.value + 1].id)
  }
}

function navigatePrev() {
  if (currentIndex.value > 0) {
    emit('navigate', props.images[currentIndex.value - 1].id)
  }
}

// ─── Metadata helpers ──────────────────────────────────────────────────────────

const metadata = computed(() => currentImage.value?.metadata || null)

const filename = computed(() => {
  const path = currentImage.value?.path || ''
  return path.split('/').pop() || 'Unknown'
})

const fileTypeLabel = computed(() => {
  const img = currentImage.value
  if (!img) return undefined
  const ext = img.path?.split('.').pop()?.toUpperCase()
  const type = img.file_type?.toUpperCase()
  return ext ? `${ext} ${type}` : type
})

const fileSizeLabel = computed(() => {
  const bytes = currentImage.value?.size_bytes
  if (!bytes) return undefined
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`
  return `${bytes} B`
})

const captureDate = computed(() => {
  const dateStr = currentImage.value?.dates?.selected_date || currentImage.value?.dates?.exif_date || currentImage.value?.created_at
  if (!dateStr) return undefined
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit'
  })
})

const cameraInfo = computed(() => {
  if (!metadata.value) return undefined
  const combined = `${metadata.value.camera_make || ''} ${metadata.value.camera_model || ''}`.trim()
  return combined || undefined
})

const shutterSpeed = computed(() => {
  const ss = metadata.value?.shutter_speed
  if (!ss) return undefined
  return ss >= 1 ? `${ss}s` : `1/${Math.round(1 / ss)}s`
})

const qualityColor = computed(() => {
  const score = currentImage.value?.quality_score ?? 0
  if (score >= 70) return 'bg-green-500'
  if (score >= 40) return 'bg-yellow-500'
  return 'bg-red-500'
})

// ─── Keyboard ─────────────────────────────────────────────────────────────────

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') { e.preventDefault(); emit('close') }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); navigatePrev() }
  else if (e.key === 'ArrowRight') { e.preventDefault(); navigateNext() }
  else if (e.key === 'i' || e.key === 'I') { e.preventDefault(); setTab('info') }
  else if (e.key === 'h' || e.key === 'H') { e.preventDefault(); setTab('histogram') }
  else if (e.key === 'a' || e.key === 'A') { e.preventDefault(); setTab('adjust') }
  else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); emit('reject', currentImage.value?.id) }
  else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); emit('favorite', currentImage.value?.id) }
}

// ─── Watchers ─────────────────────────────────────────────────────────────────

watch(() => props.imageId, () => {
  imageLoading.value = true
  isFullRes.value = false
  histogram.value = null
  histogramLoading.value = false
  naturalW.value = 0
  naturalH.value = 0
  cropMode.value = false
  resetCrop()
  // Clear H/S preview from previous image
  if (previewBlobUrl) { URL.revokeObjectURL(previewBlobUrl); previewBlobUrl = null }
  previewSrc.value = null
})

watch(panelOpen, () => nextTick(updateContainerSize))

// ─── Lifecycle ────────────────────────────────────────────────────────────────

onMounted(() => {
  nextTick(() => {
    overlayRef.value?.focus()
    updateContainerSize()
    resizeObserver = new ResizeObserver(updateContainerSize)
    if (imageAreaRef.value) resizeObserver.observe(imageAreaRef.value)
  })
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('mousemove', onCropMouseMove)
  window.removeEventListener('mouseup', onCropMouseUp)
  if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl)
  if (previewTimer) clearTimeout(previewTimer)
})
</script>
