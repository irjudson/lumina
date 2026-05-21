import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'

export type FileType = 'image' | 'video'
export type ImageStatus = 'ok' | 'rejected' | 'archived' | 'flagged'

export interface ImageFilters {
  search?: string
  dateRange?: [Date, Date]
  fileTypes?: FileType[]
  tags?: string[]
  hasTags?: boolean          // true = tagged only, false = untagged only
  createdAfter?: string      // ISO date — filters by catalog import date
  status?: ImageStatus[]
  qualityMin?: number
  folder?: string
  sortBy?: string
  sortOrder?: string
  contentClass?: string      // e.g. "screenshot,document" or "!screenshot,!document"
  minSizeBytes?: number
  maxSizeBytes?: number
  statusFilter?: string   // 'active' | 'rejected' | 'archived' | 'flagged'
  collectionId?: string
}

export interface Image {
  id: string
  path: string
  thumbnail_url: string
  file_type: FileType
  status: ImageStatus
  quality_score?: number
  metadata?: Record<string, any>
  tags?: string[]
  created_at: string
  size_bytes?: number
  dates?: Record<string, any>
  content_class?: string | null
}

export const useLibraryStore = defineStore('library', () => {
  const currentCatalogId = ref<string | null>(null)
  const stats = ref({
    imageCount: 0,
    videoCount: 0,
    totalSize: 0,
    lastScanned: null as string | null
  })

  // Images and filtering
  const images = ref<Image[]>([])
  const totalCount = ref(0)
  const activeFilters = ref<ImageFilters>({})
  const isLoading = ref(false)
  const isLoadingMore = ref(false)
  const hasMore = ref(false)
  const error = ref<string | null>(null)
  const PAGE_SIZE = 200

  // Selection state
  const selectedImageIds = ref<Set<string>>(new Set())
  const lastSelectedId = ref<string | null>(null)

  // Filmstrip state
  const filmstripImages = ref<Image[]>([])
  const filmstripIndex = ref(0)

  // Computed
  const selectedImages = computed(() =>
    images.value.filter(img => selectedImageIds.value.has(img.id))
  )

  const selectedImage = computed(() =>
    lastSelectedId.value ? images.value.find(img => img.id === lastSelectedId.value) : null
  )

  const hasSelection = computed(() => selectedImageIds.value.size > 0)

  const filteredImages = computed(() => {
    let filtered = [...images.value]

    if (activeFilters.value.dateRange) {
      const [start, end] = activeFilters.value.dateRange
      filtered = filtered.filter(img => {
        const date = new Date(img.created_at)
        return date >= start && date <= end
      })
    }

    if (activeFilters.value.fileTypes?.length) {
      filtered = filtered.filter(img =>
        activeFilters.value.fileTypes!.includes(img.file_type)
      )
    }

    if (activeFilters.value.tags?.length) {
      filtered = filtered.filter(img =>
        activeFilters.value.tags!.some(tag => img.tags?.includes(tag))
      )
    }

    if (activeFilters.value.status?.length) {
      filtered = filtered.filter(img =>
        activeFilters.value.status!.includes(img.status)
      )
    }

    if (activeFilters.value.qualityMin !== undefined) {
      filtered = filtered.filter(img =>
        (img.quality_score ?? 0) >= activeFilters.value.qualityMin!
      )
    }

    if (activeFilters.value.folder) {
      filtered = filtered.filter(img =>
        img.path.startsWith(activeFilters.value.folder!)
      )
    }

    return filtered
  })

  // Actions
  function setCatalog(id: string) {
    currentCatalogId.value = id
    clearSelection()
  }

  function updateStats(newStats: Partial<typeof stats.value>) {
    stats.value = { ...stats.value, ...newStats }
  }

  function setImages(newImages: Image[]) {
    images.value = newImages
    filmstripImages.value = newImages
  }

  function buildApiParams(offset = 0): Record<string, any> {
    const params: any = {
      limit: PAGE_SIZE,
      offset,
      include_tags: true,
    }

    if (activeFilters.value.search) {
      params.search = activeFilters.value.search
    }

    if (activeFilters.value.fileTypes?.length === 1) {
      params.file_type = activeFilters.value.fileTypes[0]
    }

    if (activeFilters.value.dateRange) {
      params.date_from = activeFilters.value.dateRange[0].toISOString()
      params.date_to = activeFilters.value.dateRange[1].toISOString()
    }

    if (activeFilters.value.tags?.length) {
      params.tags = activeFilters.value.tags.join(',')
    }

    if (activeFilters.value.hasTags !== undefined) {
      params.has_tags = activeFilters.value.hasTags
    }

    if (activeFilters.value.createdAfter) {
      params.created_at_from = activeFilters.value.createdAfter
    }

    if (activeFilters.value.sortBy) {
      params.sort_by = activeFilters.value.sortBy
    }

    if (activeFilters.value.sortOrder) {
      params.sort_order = activeFilters.value.sortOrder
    }

    if (activeFilters.value.contentClass) {
      params.content_class = activeFilters.value.contentClass
    }

    if (activeFilters.value.minSizeBytes !== undefined) {
      params.min_size_bytes = activeFilters.value.minSizeBytes
    }

    if (activeFilters.value.maxSizeBytes !== undefined) {
      params.max_size_bytes = activeFilters.value.maxSizeBytes
    }

    if (activeFilters.value.statusFilter) {
      params.status = activeFilters.value.statusFilter
    }

    if (activeFilters.value.collectionId) {
      params.collection_id = activeFilters.value.collectionId
    }

    return params
  }

  function getReliableDate(img: any): string {
    const maxDate = new Date()
    maxDate.setFullYear(maxDate.getFullYear() + 1)

    const candidates = [
      img.dates?.selected_date,
      img.dates?.filesystem_modified,
      img.dates?.filesystem_created,
      img.created_at
    ]

    for (const candidate of candidates) {
      if (!candidate) continue
      const d = new Date(candidate)
      if (!isNaN(d.getTime()) && d <= maxDate) {
        return candidate
      }
    }

    return img.created_at || new Date().toISOString()
  }

  function mapApiImage(img: any, catalogId: string): Image {
    return {
      id: img.id,
      path: img.source_path,
      thumbnail_url: `/api/catalogs/${catalogId}/images/${img.id}/thumbnail`,
      file_type: img.file_type,
      status: img.status as ImageStatus,
      quality_score: img.quality_score,
      metadata: img.metadata,
      tags: (img.tags ?? []).map((t: any) => t.name ?? t),
      created_at: getReliableDate(img),
      size_bytes: img.size_bytes,
      dates: img.dates,
      content_class: img.content_class,
    }
  }

  async function fetchImages(catalogId: string) {
    if (!catalogId) return

    isLoading.value = true
    error.value = null

    try {
      const params = buildApiParams(0)
      const response = await api.getImages(catalogId, params)

      images.value = response.images.map(img => mapApiImage(img, catalogId))
      totalCount.value = response.total
      hasMore.value = images.value.length < response.total

      filmstripImages.value = [...images.value]
    } catch (e: any) {
      error.value = e.message || 'Failed to load images'
      console.error('fetchImages error:', e)
    } finally {
      isLoading.value = false
    }
  }

  async function fetchMore() {
    if (!currentCatalogId.value || isLoadingMore.value || !hasMore.value) return

    isLoadingMore.value = true

    try {
      const params = buildApiParams(images.value.length)
      const response = await api.getImages(currentCatalogId.value, params)

      const newImages = response.images.map(img => mapApiImage(img, currentCatalogId.value!))
      images.value.push(...newImages)
      totalCount.value = response.total
      hasMore.value = images.value.length < response.total

      filmstripImages.value = [...images.value]
    } catch (e: any) {
      console.error('fetchMore error:', e)
    } finally {
      isLoadingMore.value = false
    }
  }

  function setFilter(filter: Partial<ImageFilters>) {
    activeFilters.value = { ...activeFilters.value, ...filter }

    // Auto-refresh images when filters change
    if (currentCatalogId.value) {
      fetchImages(currentCatalogId.value)
    }
  }

  function clearFilters() {
    activeFilters.value = {}
  }

  // Remove images from the local list without re-fetching (preserves scroll position)
  function removeImageIds(ids: string[]) {
    const idSet = new Set(ids)
    images.value = images.value.filter(img => !idSet.has(img.id))
    filmstripImages.value = filmstripImages.value.filter(img => !idSet.has(img.id))
    totalCount.value = Math.max(0, totalCount.value - ids.length)
    ids.forEach(id => selectedImageIds.value.delete(id))
  }

  function toggleSelection(imageId: string, multiSelect = false) {
    if (multiSelect) {
      if (selectedImageIds.value.has(imageId)) {
        selectedImageIds.value.delete(imageId)
      } else {
        selectedImageIds.value.add(imageId)
      }
    } else {
      selectedImageIds.value.clear()
      selectedImageIds.value.add(imageId)
    }
    lastSelectedId.value = imageId
  }

  function selectRange(fromId: string, toId: string) {
    const fromIndex = images.value.findIndex(img => img.id === fromId)
    const toIndex = images.value.findIndex(img => img.id === toId)

    if (fromIndex === -1 || toIndex === -1) return

    const start = Math.min(fromIndex, toIndex)
    const end = Math.max(fromIndex, toIndex)

    for (let i = start; i <= end; i++) {
      selectedImageIds.value.add(images.value[i].id)
    }
    lastSelectedId.value = toId
  }

  function clearSelection() {
    selectedImageIds.value.clear()
    lastSelectedId.value = null
  }

  function setFilmstripIndex(index: number) {
    if (index >= 0 && index < filmstripImages.value.length) {
      filmstripIndex.value = index
      const image = filmstripImages.value[index]
      if (image) {
        lastSelectedId.value = image.id
      }
    }
  }

  function navigateNext() {
    if (filmstripIndex.value < filmstripImages.value.length - 1) {
      setFilmstripIndex(filmstripIndex.value + 1)
    }
  }

  function navigatePrev() {
    if (filmstripIndex.value > 0) {
      setFilmstripIndex(filmstripIndex.value - 1)
    }
  }

  return {
    // State
    currentCatalogId,
    stats,
    images,
    totalCount,
    activeFilters,
    isLoading,
    isLoadingMore,
    hasMore,
    error,
    selectedImageIds,
    lastSelectedId,
    filmstripImages,
    filmstripIndex,

    // Computed
    selectedImages,
    selectedImage,
    hasSelection,
    filteredImages,

    // Actions
    setCatalog,
    updateStats,
    setImages,
    fetchImages,
    fetchMore,
    setFilter,
    clearFilters,
    removeImageIds,
    toggleSelection,
    selectRange,
    clearSelection,
    setFilmstripIndex,
    navigateNext,
    navigatePrev
  }
})