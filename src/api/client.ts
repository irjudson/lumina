import axios, { type AxiosInstance } from 'axios'

// --- Interfaces ---

export interface SkippedImport {
  id: string
  source_path: string
  checksum: string
  matched_image_id: string
  skipped_at: string
  reviewed_at?: string | null
  overridden: boolean
  matched_image?: {
    id: string
    source_path: string
    thumbnail_path?: string | null
    dates?: any
  }
}

export interface Catalog {
  id: string
  name: string
  source_directories: string[]
  organized_directory?: string | null
  created_at?: string
  updated_at?: string
  // Additional fields
  image_count?: number
  size_bytes?: number
}

export interface OrganizeException {
  image_id: string
  source_path: string
  proposed_destination: string
  issue: string
  detail: string
}

export interface OrganizePreviewResponse {
  dry_run: boolean
  summary: {
    total: number
    skipped_already_in_output: number
    skipped_already_organized: number
    skipped_out_of_scope: number
    skipped_pending_duplicates: number
    will_organize: number
    pending_duplicate_count: number
    pending_duplicate_size_bytes: number
    confirmed_duplicate_size_bytes: number
    resolved: number
    iffy: number
    date_only: number
    unresolved: number
    rejected: number
    archived: number
    collisions_resolved: number
    errors: number
    total_size_bytes: number
    missing_checksum_count: number
    available_bytes: number | null
    cross_filesystem?: boolean
  }
  exceptions: OrganizeException[]
}

export interface CreateCatalogRequest {
  name: string
  source_directories: string[]
}

export interface Image {
  id: string
  source_path: string
  file_type: 'image' | 'video'
  checksum: string
  size_bytes: number
  dates: {
    exif_date?: string
    filename_date?: string
    directory_date?: string
    filesystem_date?: string
    selected_date?: string
    source?: string
  }
  metadata: Record<string, any>
  quality_score?: number
  status: string
  created_at: string
  content_class?: string | null
}

export interface JobProgress {
  current: number
  total: number
  percent: number
  message: string
  rate?: number
}

export interface PrerequisiteInfo {
  prereq_job_id: string
  prereq_job_type: string
  description: string
  detail: string
  chained_job_type: string
}

export interface Job {
  id: string
  catalog_id?: string
  job_type: string
  status: 'pending' | 'running' | 'success' | 'failure' | 'cancelled'
  progress?: JobProgress
  result?: any
  error?: string
  created_at: string
  updated_at?: string
  completed_at?: string
  job_source?: 'user' | 'warehouse'
  priority?: number
  warehouse_trigger?: string
  prerequisite?: PrerequisiteInfo
}

export interface CreateJobRequest {
  catalog_id: string
  job_type: string
  params?: Record<string, any>
  job_source?: 'user' | 'warehouse'
  priority?: number
}

export interface WarehouseTaskConfig {
  task_type: string
  enabled: boolean
  check_interval_minutes: number
  threshold: Record<string, any>
  last_run?: string
  next_run?: string
}

export interface WarehouseConfig {
  catalog_id: string
  tasks: WarehouseTaskConfig[]
}

// --- Collections Interfaces ---

export interface CollectionListItem {
  id: string
  name: string
  description?: string
  cover_image_id?: string
  image_count: number
  pending_count: number
  source: 'user' | 'system'
  system_key?: string | null
  created_at: string
  updated_at: string
}

export interface CollectionDetail {
  id: string
  name: string
  description?: string
  cover_image_id?: string
  image_ids: string[]
  source: 'user' | 'system'
  system_key?: string | null
  created_at: string
  updated_at: string
}

export interface CreateCollectionRequest {
  name: string
  description?: string
}

export interface UpdateCollectionRequest {
  name?: string
  description?: string
  cover_image_id?: string
}

// --- Events Interfaces ---

export interface EventItem {
  id: string
  name?: string | null
  start_time: string
  end_time: string
  duration_minutes: number
  image_count: number
  center_lat?: number | null
  center_lon?: number | null
  radius_km?: number | null
  score: number
  detected_at: string
}

export interface EventsResponse {
  events: EventItem[]
  total: number
}

export interface EventImage {
  id: string
  source_path: string
  file_type?: string
  lat?: number | null
  lon?: number | null
  photo_date?: string | null
}

// --- Map Interfaces ---

export interface MapCluster {
  geohash: string
  count: number
  center_lat: number
  center_lon: number
}

export interface MapClustersResponse {
  clusters: MapCluster[]
  total_with_gps: number
  precision: number
}

export interface TimelineBucket {
  period: string
  count: number
}

export interface MapTimelineResponse {
  buckets: TimelineBucket[]
  total: number
}

export interface MapImage {
  id: string
  source_path: string
  file_type?: string
  thumbnail_path?: string
  lat: number
  lon: number
  photo_date?: string | null
}

export interface MapImagesResponse {
  images: MapImage[]
  total: number
}

// --- API Client ---

class ApiClient {
  private client: AxiosInstance

  constructor() {
    this.client = axios.create({
      baseURL: '/api',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // Request interceptor for Auth Token
    this.client.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('lumina_token')
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
        return config
      },
      (error) => Promise.reject(error)
    )

    // Response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          // Handle unauthorized (e.g., redirect to login or clear token)
          // localStorage.removeItem('lumina_token')
        }
        return Promise.reject(error)
      }
    )
  }

  // --- Catalogs ---

  async getCatalogs(): Promise<Catalog[]> {
    const response = await this.client.get<Catalog[]>('/catalogs/')
    return response.data
  }

  async getCatalog(id: string): Promise<Catalog> {
    const response = await this.client.get<Catalog>(`/catalogs/${id}/`)
    return response.data
  }

  async createCatalog(data: CreateCatalogRequest): Promise<Catalog> {
    const response = await this.client.post<Catalog>('/catalogs/', data)
    return response.data
  }

  async updateCatalog(id: string, data: { name: string; source_directories: string[]; organized_directory?: string | null }): Promise<Catalog> {
    const response = await this.client.put<Catalog>(`/catalogs/${id}`, data)
    return response.data
  }

  async deleteCatalog(id: string): Promise<void> {
    await this.client.delete(`/catalogs/${id}/`)
  }

  // --- Images ---

  async getImages(
    catalogId: string,
    params: {
      // Pagination
      limit?: number
      offset?: number
      // Sorting
      sort_by?: string
      sort_order?: 'asc' | 'desc'
      // Filters
      file_type?: 'image' | 'video'
      date_from?: string
      date_to?: string
      tags?: string
      status?: string
      camera_make?: string
      camera_model?: string
      has_gps?: boolean
      content_class?: string
    } = {}
  ): Promise<{ images: Image[], total: number }> {
    const response = await this.client.get(`/catalogs/${catalogId}/images`, { params })
    // Backend may return either { images: [...], total: N } or just [...]
    if (Array.isArray(response.data)) {
      return { images: response.data, total: response.data.length }
    }
    return response.data
  }

  async getImage(catalogId: string, imageId: string): Promise<Image> {
    const response = await this.client.get<Image>(`/catalogs/${catalogId}/images/${imageId}`)
    return response.data
  }

  async getTags(catalogId: string): Promise<Array<{ name: string, count: number }>> {
    const response = await this.client.get(`/catalogs/${catalogId}/tags`)
    return response.data.tags || []
  }

  async getImageTags(catalogId: string, imageId: string): Promise<Array<{ name: string, confidence: number, source: string }>> {
    const response = await this.client.get(`/catalogs/${catalogId}/images/${imageId}/tags`)
    return response.data.tags || []
  }

  // --- Jobs ---

  async getJobs(catalogId?: string, jobSource?: string, limit?: number): Promise<Job[]> {
    const params: Record<string, any> = {}
    if (catalogId) params.catalog_id = catalogId
    if (jobSource) params.job_source = jobSource
    if (limit) params.limit = limit
    const response = await this.client.get<Job[]>('/jobs/', { params })
    return response.data
  }

  async getJob(jobId: string): Promise<Job> {
    const response = await this.client.get<Job>(`/jobs/${jobId}`)
    return response.data
  }

  async createJob(data: CreateJobRequest): Promise<Job> {
    // All jobs use the /jobs/submit endpoint
    const payload = {
      catalog_id: data.catalog_id,
      job_type: data.job_type,
      parameters: data.params || {}
    }

    const response = await this.client.post<Job>('/jobs/submit', payload)
    return response.data
  }

  async cancelJob(jobId: string): Promise<void> {
    await this.client.delete(`/jobs/${jobId}`)
  }

  async previewOrganize(
    catalogId: string,
    scope: 'new' | 'skip_pending_duplicates' | 'resolved_only' | 'iffy' | 'date_only' | 'unresolved' | 'all' = 'new'
  ): Promise<OrganizePreviewResponse> {
    const response = await this.client.post<OrganizePreviewResponse>(
      `/catalogs/${catalogId}/organize/preview`,
      null,
      { params: { scope } }
    )
    return response.data
  }

  // --- Warehouse ---

  async getWarehouseConfig(catalogId: string): Promise<WarehouseConfig> {
    const response = await this.client.get<WarehouseConfig>(`/warehouse/catalogs/${catalogId}/warehouse/config`)
    return response.data
  }

  async updateWarehouseTaskConfig(
    catalogId: string,
    taskType: string,
    config: Partial<WarehouseTaskConfig>
  ): Promise<WarehouseTaskConfig> {
    const response = await this.client.put<WarehouseTaskConfig>(
      `/warehouse/catalogs/${catalogId}/warehouse/config/${taskType}`,
      config
    )
    return response.data
  }

  async getWarehouseStatus(catalogId: string): Promise<any> {
    const response = await this.client.get(`/warehouse/catalogs/${catalogId}/warehouse/status`)
    return response.data
  }

  // --- Collections ---

  async getCollections(catalogId: string): Promise<CollectionListItem[]> {
    const response = await this.client.get<CollectionListItem[]>(`/catalogs/${catalogId}/collections`)
    return response.data
  }

  async getCollection(catalogId: string, collectionId: string): Promise<CollectionDetail> {
    const response = await this.client.get<CollectionDetail>(`/catalogs/${catalogId}/collections/${collectionId}`)
    return response.data
  }

  async createCollection(catalogId: string, data: CreateCollectionRequest): Promise<CollectionDetail> {
    const response = await this.client.post<CollectionDetail>(`/catalogs/${catalogId}/collections`, data)
    return response.data
  }

  async updateCollection(catalogId: string, collectionId: string, data: UpdateCollectionRequest): Promise<CollectionDetail> {
    const response = await this.client.put<CollectionDetail>(`/catalogs/${catalogId}/collections/${collectionId}`, data)
    return response.data
  }

  async deleteCollection(catalogId: string, collectionId: string): Promise<void> {
    await this.client.delete(`/catalogs/${catalogId}/collections/${collectionId}`)
  }

  async addImagesToCollection(catalogId: string, collectionId: string, imageIds: string[]): Promise<{ added: number }> {
    const response = await this.client.post<{ added: number }>(`/catalogs/${catalogId}/collections/${collectionId}/images`, { image_ids: imageIds })
    return response.data
  }

  async removeImagesFromCollection(catalogId: string, collectionId: string, imageIds: string[]): Promise<{ removed: number }> {
    const response = await this.client.delete<{ removed: number }>(`/catalogs/${catalogId}/collections/${collectionId}/images`, { data: { image_ids: imageIds } })
    return response.data
  }

  async confirmCollectionMemberships(catalogId: string, collectionId: string, imageIds: string[]): Promise<{ confirmed: number }> {
    const response = await this.client.post<{ confirmed: number }>(`/catalogs/${catalogId}/collections/${collectionId}/confirm`, { image_ids: imageIds })
    return response.data
  }

  async rejectCollectionMemberships(catalogId: string, collectionId: string, imageIds: string[]): Promise<{ rejected: number }> {
    const response = await this.client.post<{ rejected: number }>(`/catalogs/${catalogId}/collections/${collectionId}/reject`, { image_ids: imageIds })
    return response.data
  }

  // --- Map ---

  async getMapClusters(catalogId: string, params: { precision?: number, date_from?: string, date_to?: string, bounds_sw_lat?: number, bounds_sw_lon?: number, bounds_ne_lat?: number, bounds_ne_lon?: number } = {}): Promise<MapClustersResponse> {
    const response = await this.client.get<MapClustersResponse>(`/catalogs/${catalogId}/map/clusters`, { params })
    return response.data
  }

  async getMapTimeline(catalogId: string, params: { interval?: string } = {}): Promise<MapTimelineResponse> {
    const response = await this.client.get<MapTimelineResponse>(`/catalogs/${catalogId}/map/timeline`, { params })
    return response.data
  }

  async getMapImages(catalogId: string, params: { geohash?: string, lat?: number, lon?: number, radius_km?: number, limit?: number, offset?: number }): Promise<MapImagesResponse> {
    const response = await this.client.get<MapImagesResponse>(`/catalogs/${catalogId}/map/images`, { params })
    return response.data
  }

  // --- Smart view counts ---

  async getSmartCounts(catalogId: string): Promise<{
    recent: number
    untagged: number
    videos: number
    geotagged: number
    bursts: number
    duplicates: number
    screenshots: number
    documents: number
    noise: number
    needs_review: number
    rejected: number
    events: number
    skipped_imports: number
  }> {
    const response = await this.client.get(`/catalogs/${catalogId}/smart-counts`)
    return response.data
  }

  async getSkippedImports(catalogId: string, params: { limit?: number; offset?: number } = {}): Promise<{ items: SkippedImport[]; total: number }> {
    const response = await this.client.get(`/catalogs/${catalogId}/skipped-imports`, { params })
    return response.data
  }

  async overrideSkippedImport(catalogId: string, skipId: string): Promise<SkippedImport> {
    const response = await this.client.post(`/catalogs/${catalogId}/skipped-imports/${skipId}/override`)
    return response.data
  }

  async dismissAllSkippedImports(catalogId: string): Promise<{ dismissed: number }> {
    const response = await this.client.post(`/catalogs/${catalogId}/skipped-imports/dismiss-all`)
    return response.data
  }

  // --- Events ---

  async getEvents(catalogId: string, params: { limit?: number; offset?: number } = {}): Promise<EventsResponse> {
    const response = await this.client.get<EventsResponse>(`/catalogs/${catalogId}/events`, { params })
    return response.data
  }

  async getEventImages(catalogId: string, eventId: string, params: { limit?: number; offset?: number } = {}): Promise<{ images: EventImage[]; total: number }> {
    const response = await this.client.get(`/catalogs/${catalogId}/events/${eventId}/images`, { params })
    return response.data
  }
}

export const api = new ApiClient()