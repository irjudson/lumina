<template>
  <div class="h-full overflow-y-auto bg-gray-950 p-6 space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold text-gray-100">Analytics</h1>
      <button
        @click="runScoreQuality"
        :disabled="scoringRunning"
        class="px-3 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded transition-colors"
      >
        {{ scoringRunning ? 'Scoring…' : 'Re-score Quality' }}
      </button>
    </div>

    <div v-if="loading" class="flex items-center justify-center h-48 text-gray-500">
      Loading analytics…
    </div>

    <template v-else>
      <!-- Library Health -->
      <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
        <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Library Health</h2>
        <div class="space-y-3">
          <div
            v-for="(item, key) in health?.coverage"
            :key="key"
            class="flex items-center gap-3"
          >
            <span class="w-36 text-xs text-gray-400 shrink-0">{{ healthLabel(String(key)) }}</span>
            <div class="flex-1 bg-gray-800 rounded-full h-2">
              <div
                class="h-2 rounded-full transition-all"
                :class="item.pct >= 80 ? 'bg-green-500' : item.pct >= 40 ? 'bg-yellow-500' : 'bg-red-500'"
                :style="{ width: item.pct + '%' }"
              />
            </div>
            <span class="w-20 text-xs text-right text-gray-400">
              {{ item.count.toLocaleString() }} ({{ item.pct.toFixed(1) }}%)
            </span>
          </div>
        </div>
      </section>

      <!-- Quality Score Distribution -->
      <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
        <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-1">Quality Score Distribution</h2>
        <div v-if="quality" class="flex items-baseline gap-4 mb-4">
          <span class="text-2xl font-bold text-gray-100">{{ quality.mean?.toFixed(1) ?? '—' }}</span>
          <span class="text-sm text-gray-500">mean</span>
          <span class="text-sm text-gray-400">median {{ quality.median ?? '—' }}</span>
          <span class="text-sm text-gray-500">{{ quality.total_scored.toLocaleString() }} scored · {{ quality.total_unscored.toLocaleString() }} unscored</span>
          <span v-if="quality.verified_count > 0" class="text-sm text-indigo-400">
            {{ quality.verified_count }} verified
            <template v-if="quality.verified_mean_delta != null">
              (Δ {{ quality.verified_mean_delta > 0 ? '+' : '' }}{{ quality.verified_mean_delta.toFixed(1) }})
            </template>
          </span>
        </div>
        <div v-if="quality?.histogram" class="flex items-end gap-1 h-24">
          <div
            v-for="bucket in quality.histogram"
            :key="bucket.bucket"
            class="flex-1 flex flex-col items-center gap-1"
          >
            <div
              class="w-full bg-indigo-600 rounded-t transition-all"
              :style="{ height: barHeight(bucket.count, maxBucketCount) + 'px' }"
              :title="`${bucket.bucket}: ${bucket.count.toLocaleString()}`"
            />
            <span class="text-xs text-gray-600 rotate-45 origin-left" style="font-size:9px">{{ bucket.bucket }}</span>
          </div>
        </div>
        <p v-else class="text-sm text-gray-500">No quality scores yet. Click "Re-score Quality" to run scoring.</p>
      </section>

      <div class="grid grid-cols-2 gap-6">
        <!-- Camera Breakdown -->
        <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
          <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Camera</h2>
          <div class="space-y-2">
            <div
              v-for="cam in cameras?.cameras?.slice(0, 10)"
              :key="`${cam.make}-${cam.model}`"
              class="flex items-center gap-2"
            >
              <span class="flex-1 text-xs text-gray-300 truncate">{{ cam.make }} {{ cam.model }}</span>
              <div class="w-24 bg-gray-800 rounded-full h-1.5">
                <div class="h-1.5 rounded-full bg-blue-500" :style="{ width: cam.pct + '%' }" />
              </div>
              <span class="w-12 text-right text-xs text-gray-500">{{ cam.pct.toFixed(1) }}%</span>
            </div>
            <p v-if="cameras?.unknown_count" class="text-xs text-gray-600 mt-1">
              {{ cameras.unknown_count.toLocaleString() }} without camera data
            </p>
          </div>
        </section>

        <!-- Format Breakdown -->
        <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
          <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Format</h2>
          <div class="space-y-2">
            <div
              v-for="fmt in formats?.formats"
              :key="fmt.format"
              class="flex items-center gap-2"
            >
              <span class="w-16 text-xs text-gray-300 shrink-0">{{ fmt.format || 'Unknown' }}</span>
              <div class="flex-1 bg-gray-800 rounded-full h-1.5">
                <div class="h-1.5 rounded-full bg-teal-500" :style="{ width: fmt.pct + '%' }" />
              </div>
              <span class="w-12 text-right text-xs text-gray-500">{{ fmt.pct.toFixed(1) }}%</span>
            </div>
          </div>
        </section>
      </div>

      <!-- Photo Timeline -->
      <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
        <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Timeline</h2>
        <div v-if="timeline?.by_month?.length" class="flex items-end gap-px h-20 overflow-x-auto pb-4">
          <div
            v-for="m in timeline.by_month"
            :key="`${m.year}-${m.month}`"
            class="shrink-0 flex flex-col items-center"
            style="min-width: 4px"
          >
            <div
              class="w-full bg-violet-600 hover:bg-violet-400 rounded-t cursor-default transition-colors"
              :style="{ height: barHeight(m.count, maxMonthCount) + 'px' }"
              :title="`${m.year}-${String(m.month).padStart(2,'0')}: ${m.count.toLocaleString()}`"
            />
          </div>
        </div>
        <p v-else class="text-sm text-gray-500">No timeline data available.</p>
        <div v-if="timeline?.by_month?.length" class="flex justify-between text-xs text-gray-600 mt-1">
          <span>{{ timeline.by_month[0]?.year }}-{{ String(timeline.by_month[0]?.month).padStart(2,'0') }}</span>
          <span>{{ timeline.by_month[timeline.by_month.length-1]?.year }}-{{ String(timeline.by_month[timeline.by_month.length-1]?.month).padStart(2,'0') }}</span>
        </div>
      </section>

      <!-- Organization Status -->
      <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
        <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">Organization &amp; Safety</h2>
        <div v-if="orgStats" class="space-y-4">

          <!-- Progress bar: organized vs not -->
          <div>
            <div class="flex justify-between text-xs text-gray-400 mb-1">
              <span>Consolidated into organized directory</span>
              <span>{{ orgStats.organized.toLocaleString() }} / {{ orgStats.total.toLocaleString() }} ({{ orgStats.organized_pct.toFixed(1) }}%)</span>
            </div>
            <div class="h-3 bg-gray-800 rounded-full overflow-hidden flex">
              <div class="h-full bg-emerald-500 transition-all" :style="{ width: orgStats.organized_pct + '%' }" title="Organized" />
              <div class="h-full bg-gray-700 transition-all" :style="{ width: (100 - orgStats.organized_pct) + '%' }" title="Source only" />
            </div>
            <div class="flex justify-between text-xs text-gray-600 mt-1">
              <span class="text-emerald-500">● Organized (safe copy)</span>
              <span>● Source only (not yet consolidated)</span>
            </div>
          </div>

          <!-- Confidence tier breakdown (only for organized images) -->
          <div v-if="orgStats.organized > 0">
            <p class="text-xs text-gray-500 mb-2">Date confidence of organized images</p>
            <div class="grid grid-cols-4 gap-2 text-center">
              <div v-for="(tier, key) in orgStats.by_confidence" :key="key"
                class="bg-gray-800 rounded p-2">
                <div class="text-lg font-bold" :class="tierColor(String(key))">{{ tier.pct.toFixed(0) }}%</div>
                <div class="text-xs text-gray-500 capitalize">{{ String(key).replace('_', ' ') }}</div>
                <div class="text-xs text-gray-600">{{ tier.count.toLocaleString() }}</div>
              </div>
            </div>
          </div>

          <!-- Source archived -->
          <div v-if="orgStats.organized > 0">
            <div class="flex justify-between text-xs text-gray-400 mb-1">
              <span>Source files archived (reclaimed disk space)</span>
              <span>{{ orgStats.source_archived.toLocaleString() }} / {{ orgStats.organized.toLocaleString() }} ({{ orgStats.source_archived_pct.toFixed(1) }}%)</span>
            </div>
            <div class="h-2 bg-gray-800 rounded-full overflow-hidden">
              <div class="h-full bg-amber-500 transition-all" :style="{ width: orgStats.source_archived_pct + '%' }" />
            </div>
          </div>

          <!-- Disk usage -->
          <div class="grid grid-cols-3 gap-3 text-xs">
            <div class="bg-gray-800 rounded p-2 text-center">
              <div class="text-base font-semibold text-gray-200">{{ formatBytes(orgStats.organized_bytes) }}</div>
              <div class="text-gray-500">Organized</div>
            </div>
            <div class="bg-gray-800 rounded p-2 text-center">
              <div class="text-base font-semibold text-gray-400">{{ formatBytes(orgStats.not_organized_bytes) }}</div>
              <div class="text-gray-500">Source only</div>
            </div>
            <div class="bg-gray-800 rounded p-2 text-center">
              <div class="text-base font-semibold text-gray-300">{{ formatBytes(orgStats.total_bytes) }}</div>
              <div class="text-gray-500">Total</div>
            </div>
          </div>

          <!-- Action buttons -->
          <div class="flex gap-2 pt-1">
            <button
              @click="runArchiveSource(true)"
              :disabled="archiveRunning"
              class="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-gray-200 rounded transition-colors"
            >Preview Archive</button>
            <button
              @click="runArchiveSource(false)"
              :disabled="archiveRunning || orgStats.organized === orgStats.source_archived"
              class="px-3 py-1.5 text-xs bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white rounded transition-colors"
            >Archive Sources</button>
            <button
              @click="runBackup"
              :disabled="backupRunning"
              class="px-3 py-1.5 text-xs bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white rounded transition-colors ml-auto"
            >{{ backupRunning ? 'Backing up…' : 'Backup to Cloud' }}</button>
          </div>
          <p v-if="archiveRunning" class="text-xs text-amber-400">{{ archiveStatus }}</p>
          <p v-if="backupRunning" class="text-xs text-blue-400">{{ backupStatus }}</p>
        </div>
        <p v-else class="text-sm text-gray-500">No organization data yet. Run the Organize job first.</p>
      </section>

      <!-- Quality Verification -->
      <section class="bg-gray-900 rounded-lg p-5 border border-gray-800">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wide">Quality Verification</h2>
          <div class="flex items-center gap-3">
            <span class="text-xs text-gray-500">{{ quality?.verified_count ?? 0 }} / {{ quality?.total_scored ?? 0 }} verified</span>
            <button @click="loadSample" class="text-xs text-indigo-400 hover:text-indigo-300">New Sample</button>
          </div>
        </div>

        <div v-if="sampleLoading" class="text-sm text-gray-500">Loading sample…</div>
        <div v-else-if="sample.length === 0" class="text-sm text-gray-500">
          No scored images to verify yet.
        </div>
        <div v-else class="grid grid-cols-4 gap-3">
          <div
            v-for="img in sample"
            :key="img.id"
            class="bg-gray-800 rounded-lg overflow-hidden border border-gray-700"
          >
            <div class="relative aspect-square bg-gray-900">
              <img
                :src="img.thumbnail_url"
                :alt="img.id"
                class="w-full h-full object-cover"
                @error="(e) => (e.target as HTMLImageElement).style.display='none'"
              />
              <div class="absolute top-1 right-1 bg-black/70 rounded px-1 py-0.5 text-xs text-white font-mono">
                {{ img.quality_score }}
              </div>
              <div v-if="img.quality_verified_score != null" class="absolute top-1 left-1 bg-indigo-600/90 rounded px-1 py-0.5 text-xs text-white font-mono">
                ✓ {{ img.quality_verified_score }}
              </div>
            </div>
            <div class="p-2 space-y-1.5">
              <div class="text-xs text-gray-500 truncate" :title="img.source_path">
                {{ img.source_path.split('/').pop() }}
              </div>
              <!-- Score component bars -->
              <div class="space-y-0.5">
                <ScoreBar label="Fmt" :value="img.format_score" color="bg-orange-500" />
                <ScoreBar label="Res" :value="img.resolution_score" color="bg-blue-500" />
                <ScoreBar label="Size" :value="img.size_score" color="bg-green-500" />
                <ScoreBar label="Meta" :value="img.metadata_score" color="bg-purple-500" />
              </div>
              <!-- Verification input -->
              <div class="flex items-center gap-1 pt-1">
                <input
                  type="number"
                  min="0"
                  max="100"
                  :value="img.quality_verified_score ?? img.quality_score"
                  @change="(e) => verifyScore(img.id, parseInt((e.target as HTMLInputElement).value))"
                  class="w-14 text-xs bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-gray-200 text-center"
                  placeholder="0-100"
                />
                <span class="text-xs text-gray-600">/ 100</span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useCatalogStore } from '@/stores/catalog'
import axios from 'axios'
import ScoreBar from './ScoreBar.vue'

const catalogStore = useCatalogStore()
const catalogId = computed(() => catalogStore.activeCatalog?.id)

const loading = ref(true)
const sampleLoading = ref(false)
const scoringRunning = ref(false)
const archiveRunning = ref(false)
const archiveStatus = ref('')
const backupRunning = ref(false)
const backupStatus = ref('')

const health = ref<any>(null)
const quality = ref<any>(null)
const cameras = ref<any>(null)
const formats = ref<any>(null)
const timeline = ref<any>(null)
const orgStats = ref<any>(null)
const sample = ref<any[]>([])

const maxBucketCount = computed(() =>
  Math.max(1, ...(quality.value?.histogram?.map((b: any) => b.count) ?? [1]))
)
const maxMonthCount = computed(() =>
  Math.max(1, ...(timeline.value?.by_month?.map((m: any) => m.count) ?? [1]))
)

function barHeight(count: number, max: number): number {
  return Math.max(2, Math.round((count / max) * 72))
}

function healthLabel(key: string): string {
  const labels: Record<string, string> = {
    has_date: 'Date',
    has_camera: 'Camera',
    has_format: 'Format',
    has_clip: 'CLIP Embedding',
    has_quality_score: 'Quality Score',
    has_tags: 'Tags',
    in_burst: 'In Burst',
    quality_verified: 'Verified',
  }
  return labels[key] ?? key
}

async function fetchAll() {
  if (!catalogId.value) return
  loading.value = true
  try {
    const base = `/api/catalogs/${catalogId.value}/analytics`
    const [h, q, c, f, t, o] = await Promise.all([
      axios.get(`${base}/health`),
      axios.get(`${base}/quality`),
      axios.get(`${base}/cameras`),
      axios.get(`${base}/formats`),
      axios.get(`${base}/timeline`),
      axios.get(`${base}/organization`),
    ])
    health.value = h.data
    quality.value = q.data
    cameras.value = c.data
    formats.value = f.data
    timeline.value = t.data
    orgStats.value = o.data
  } finally {
    loading.value = false
  }
}

function tierColor(tier: string): string {
  return {
    resolved: 'text-emerald-400',
    iffy: 'text-yellow-400',
    date_only: 'text-orange-400',
    unresolved: 'text-red-400',
  }[tier] ?? 'text-gray-400'
}

function formatBytes(bytes: number): string {
  if (bytes >= 1e12) return (bytes / 1e12).toFixed(1) + ' TB'
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB'
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB'
  return (bytes / 1e3).toFixed(0) + ' KB'
}

async function runArchiveSource(dryRun: boolean) {
  if (!catalogId.value) return
  archiveRunning.value = true
  archiveStatus.value = dryRun ? 'Previewing…' : 'Archiving sources…'
  try {
    await axios.post('/api/v2/jobs/', {
      job_type: 'archive_source',
      catalog_id: catalogId.value,
      params: { dry_run: dryRun },
    })
    archiveStatus.value = dryRun
      ? 'Preview job submitted — check job progress panel'
      : 'Archive job submitted — check job progress panel'
    if (!dryRun) {
      await new Promise(r => setTimeout(r, 3000))
      const r = await axios.get(`/api/catalogs/${catalogId.value}/analytics/organization`)
      orgStats.value = r.data
    }
  } catch (e) {
    archiveStatus.value = 'Failed to submit job'
  } finally {
    archiveRunning.value = false
  }
}

async function runBackup() {
  if (!catalogId.value) return
  backupRunning.value = true
  backupStatus.value = 'Submitting backup job…'
  try {
    await axios.post('/api/v2/jobs/', {
      job_type: 'backup_catalog',
      catalog_id: catalogId.value,
      params: {},
    })
    backupStatus.value = 'Backup job submitted — check job progress panel'
  } catch (e: any) {
    backupStatus.value = e?.response?.data?.detail ?? 'Failed to submit job'
  } finally {
    backupRunning.value = false
  }
}

async function loadSample() {
  if (!catalogId.value) return
  sampleLoading.value = true
  try {
    const r = await axios.get(`/api/catalogs/${catalogId.value}/analytics/quality/sample?n=20`)
    sample.value = r.data.images
  } finally {
    sampleLoading.value = false
  }
}

async function verifyScore(imageId: string, score: number) {
  if (!catalogId.value || isNaN(score) || score < 0 || score > 100) return
  await axios.post(`/api/catalogs/${catalogId.value}/analytics/quality/verify`, {
    image_id: imageId,
    verified_score: score,
  })
  const img = sample.value.find(i => i.id === imageId)
  if (img) img.quality_verified_score = score
  // Refresh quality stats
  const r = await axios.get(`/api/catalogs/${catalogId.value}/analytics/quality`)
  quality.value = r.data
}

async function runScoreQuality() {
  if (!catalogId.value) return
  scoringRunning.value = true
  try {
    await axios.post('/api/v2/jobs/', {
      job_type: 'score_quality',
      catalog_id: catalogId.value,
    })
    // Poll briefly then refresh stats
    await new Promise(r => setTimeout(r, 2000))
    await fetchAll()
  } catch (e) {
    console.warn('Score quality job failed to submit', e)
  } finally {
    scoringRunning.value = false
  }
}

onMounted(async () => {
  await fetchAll()
  await loadSample()
})

watch(catalogId, async () => {
  await fetchAll()
  await loadSample()
})
</script>
