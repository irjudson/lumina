import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { CameraDevice, DiscoveredFile } from '@/api/client'
import type { Job } from '@/stores/jobs'
import { useCatalogStore } from '@/stores/catalog'

export interface SelectableFile extends DiscoveredFile {
  selected: boolean
}

export const useCameraImportStore = defineStore('cameraImport', () => {
  const catalogStore = useCatalogStore()

  const devices = ref<CameraDevice[]>([])
  const selectedDevice = ref<CameraDevice | null>(null)
  const discoveredFiles = ref<SelectableFile[]>([])
  const isDiscovering = ref(false)
  const discoverError = ref<string | null>(null)
  const deleteSource = ref(false)
  const currentJob = ref<Job | null>(null)

  const selectedFiles = computed(() => discoveredFiles.value.filter(f => f.selected))
  const totalSelectedBytes = computed(() =>
    selectedFiles.value.reduce((sum, f) => sum + f.size_bytes, 0)
  )

  async function fetchDevices() {
    if (!catalogStore.activeCatalog) return
    try {
      devices.value = await api.getCameraDevices(catalogStore.activeCatalog.id)
    } catch {
      devices.value = []
    }
  }

  async function discoverFiles(devicePath: string) {
    if (!catalogStore.activeCatalog) return
    isDiscovering.value = true
    discoverError.value = null
    discoveredFiles.value = []
    try {
      const files = await api.discoverCameraFiles(catalogStore.activeCatalog.id, devicePath)
      discoveredFiles.value = files.map(f => ({ ...f, selected: true }))
    } catch (e: any) {
      discoverError.value = e?.response?.data?.detail ?? 'Discovery failed'
    } finally {
      isDiscovering.value = false
    }
  }

  function toggleFile(path: string) {
    const f = discoveredFiles.value.find(f => f.path === path)
    if (f) f.selected = !f.selected
  }

  function selectAll() {
    discoveredFiles.value.forEach(f => { f.selected = true })
  }

  function deselectAll() {
    discoveredFiles.value.forEach(f => { f.selected = false })
  }

  async function startImport() {
    if (!catalogStore.activeCatalog) return
    const paths = selectedFiles.value.map(f => f.path)
    if (!paths.length) return
    const job = await api.createJob({
      catalog_id: catalogStore.activeCatalog.id,
      job_type: 'camera_import',
      params: {
        file_paths: paths,
        delete_source: deleteSource.value,
      },
    })
    currentJob.value = { ...job, created_at: job.created_at ?? new Date().toISOString() }
  }

  function reset() {
    discoveredFiles.value = []
    currentJob.value = null
    discoverError.value = null
    selectedDevice.value = null
  }

  return {
    devices,
    selectedDevice,
    discoveredFiles,
    isDiscovering,
    discoverError,
    deleteSource,
    currentJob,
    selectedFiles,
    totalSelectedBytes,
    fetchDevices,
    discoverFiles,
    toggleFile,
    selectAll,
    deselectAll,
    startImport,
    reset,
  }
})
