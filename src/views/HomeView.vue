<template>
  <LibraryLayout>
  <div class="flex-1 overflow-y-auto bg-gray-900 p-6">
    <div class="max-w-3xl mx-auto">

      <!-- Question prompt -->
      <div class="mb-8">
        <h1 class="text-2xl font-semibold text-gray-100 mb-1">What are you looking for?</h1>
        <p class="text-sm text-gray-500">Browse by tag, review ML suggestions, or search across your library.</p>
      </div>

      <!-- Needs Attention -->
      <section v-if="homeData && homeData.needs_attention.length > 0" class="mb-8">
        <h2 class="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-3">Needs Attention</h2>
        <div class="space-y-2">
          <button
            v-for="item in homeData.needs_attention"
            :key="item.type"
            class="w-full flex items-center justify-between px-4 py-3 bg-gray-800 rounded-lg border border-gray-700 hover:border-blue-500/50 hover:bg-gray-750 transition-all text-left"
            @click="handleAction(item)"
          >
            <div class="flex items-center gap-3">
              <div :class="actionIcon(item.type)" class="w-8 h-8 rounded-full flex items-center justify-center shrink-0">
                <LayersIcon v-if="item.type === 'ml_groups'" class="w-4 h-4" />
                <TagIcon v-else-if="item.type === 'untagged'" class="w-4 h-4" />
                <CheckCircleIcon v-else class="w-4 h-4" />
              </div>
              <div>
                <div class="text-sm font-medium text-gray-200">{{ item.label }}</div>
                <div v-if="item.image_count" class="text-xs text-gray-500">{{ item.image_count.toLocaleString() }} images</div>
              </div>
            </div>
            <ChevronRightIcon class="w-4 h-4 text-gray-500" />
          </button>
        </div>
      </section>

      <!-- Loading -->
      <div v-if="isLoading" class="flex items-center justify-center py-12">
        <div class="w-6 h-6 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin"></div>
      </div>

      <!-- Empty state -->
      <div v-else-if="homeData && homeData.needs_attention.length === 0" class="text-center py-12">
        <div class="w-12 h-12 bg-green-500/10 rounded-full flex items-center justify-center mx-auto mb-3">
          <CheckCircleIcon class="w-6 h-6 text-green-500" />
        </div>
        <p class="text-gray-400 text-sm">All caught up. Run ML enrichment to surface new groups.</p>
        <button
          class="mt-4 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
          @click="runEnrichment"
        >
          Run ML Enrichment
        </button>
      </div>

      <!-- Recent Tags -->
      <section v-if="homeData && homeData.recent_tags.length > 0" class="mt-8">
        <h2 class="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-3">Recent Tags</h2>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="tag in homeData.recent_tags"
            :key="tag.id"
            class="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 rounded-full text-sm text-gray-300 hover:text-white hover:bg-gray-700 border border-gray-700 hover:border-gray-600 transition-all"
            @click="browseTag(tag)"
          >
            <TagIcon class="w-3 h-3 text-gray-500" />
            {{ tag.label }}
            <span class="text-xs text-gray-500">{{ tag.image_count }}</span>
          </button>
        </div>
      </section>

    </div>
  </div>
  </LibraryLayout>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { LayersIcon, TagIcon, CheckCircleIcon, ChevronRightIcon } from 'lucide-vue-next'
import { useFolkTagsStore, type HomeItem, type FolkTag } from '@/stores/folkTags'
import { useCatalogStore } from '@/stores/catalog'
import { api } from '@/api/client'
import LibraryLayout from '@/layouts/LibraryLayout.vue'

const router = useRouter()
const folkTags = useFolkTagsStore()
const catalog = useCatalogStore()

const { homeData, isLoading } = storeToRefs(folkTags)

onMounted(async () => {
  if (catalog.activeCatalogId) {
    await folkTags.fetchHome(catalog.activeCatalogId)
  }
})

function actionIcon(type: string) {
  if (type === 'ml_groups') return 'bg-purple-500/10 text-purple-400'
  if (type === 'untagged') return 'bg-yellow-500/10 text-yellow-400'
  return 'bg-blue-500/10 text-blue-400'
}

function handleAction(item: HomeItem) {
  if (item.action === 'curate') {
    router.push('/curate')
  } else if (item.action === 'browse_untagged') {
    router.push('/?filter=untagged')
  } else if (item.action === 'review_suggestions') {
    router.push('/curate?tab=suggestions')
  }
}

function browseTag(tag: FolkTag) {
  router.push(`/?folk_tag=${tag.id}`)
}

async function runEnrichment() {
  if (!catalog.activeCatalogId) return
  await api.createJob({
    catalog_id: catalog.activeCatalogId,
    job_type: 'enrich_ml_groups',
    params: {},
  })
  router.push('/curate')
}
</script>
