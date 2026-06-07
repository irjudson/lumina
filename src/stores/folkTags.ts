import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const BASE = '/api/catalogs'

export interface FolkTag {
  id: string
  slug: string
  label: string
  parent_id: string | null
  notes: string | null
  created_at: string | null
  image_count: number
  children?: FolkTag[]
}

export interface MlGroup {
  id: string
  method: string
  label_hint: string | null
  image_count: number
  sample_image_ids: string[]
  signals: Record<string, any>
  status: string
  created_at: string | null
}

export interface HomeItem {
  type: string
  label: string
  count: number
  image_count?: number
  action: string
}

export interface HomeData {
  needs_attention: HomeItem[]
  recent_tags: FolkTag[]
}

export const useFolkTagsStore = defineStore('folkTags', () => {
  const tags = ref<FolkTag[]>([])
  const mlGroups = ref<MlGroup[]>([])
  const homeData = ref<HomeData | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Flat list → tree
  const tagTree = computed((): FolkTag[] => {
    const map = new Map<string, FolkTag>()
    for (const t of tags.value) map.set(t.id, { ...t, children: [] })
    const roots: FolkTag[] = []
    for (const node of map.values()) {
      if (node.parent_id && map.has(node.parent_id)) {
        map.get(node.parent_id)!.children!.push(node)
      } else {
        roots.push(node)
      }
    }
    return roots.sort((a, b) => a.label.localeCompare(b.label))
  })

  async function fetchTags(catalogId: string) {
    isLoading.value = true
    error.value = null
    try {
      const res = await axios.get(`${BASE}/${catalogId}/folk-tags`)
      tags.value = res.data
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function createTag(catalogId: string, label: string, parentId?: string, notes?: string) {
    const res = await axios.post(`${BASE}/${catalogId}/folk-tags`, {
      label,
      parent_id: parentId ?? null,
      notes: notes ?? null,
    })
    tags.value.push({ ...res.data, children: [] })
    return res.data as FolkTag
  }

  async function updateTag(catalogId: string, tagId: string, patch: Partial<FolkTag>) {
    const res = await axios.patch(`${BASE}/${catalogId}/folk-tags/${tagId}`, patch)
    const idx = tags.value.findIndex(t => t.id === tagId)
    if (idx >= 0) tags.value[idx] = { ...tags.value[idx], ...res.data }
    return res.data
  }

  async function deleteTag(catalogId: string, tagId: string) {
    await axios.delete(`${BASE}/${catalogId}/folk-tags/${tagId}`)
    tags.value = tags.value.filter(t => t.id !== tagId)
  }

  async function mergeTag(catalogId: string, tagId: string, intoTagId: string) {
    const res = await axios.post(`${BASE}/${catalogId}/folk-tags/${tagId}/merge`, {
      into_tag_id: intoTagId,
    })
    // Remove the merged-away tag; update the target tag's image count
    tags.value = tags.value.filter(t => t.id !== tagId)
    const target = tags.value.find(t => t.id === intoTagId)
    if (target) target.image_count = res.data.image_count
    return res.data
  }

  async function bulkTag(catalogId: string, imageIds: string[], tagId: string) {
    const res = await axios.post(`${BASE}/${catalogId}/images/folk-tag`, {
      image_ids: imageIds,
      tag_id: tagId,
    })
    return res.data
  }

  async function bulkUntag(catalogId: string, imageIds: string[], tagId: string) {
    const res = await axios.delete(`${BASE}/${catalogId}/images/folk-tag`, {
      data: { image_ids: imageIds, tag_id: tagId },
    })
    return res.data
  }

  async function fetchMlGroups(catalogId: string, status = 'pending') {
    const res = await axios.get(`${BASE}/${catalogId}/ml-groups`, { params: { status } })
    mlGroups.value = res.data
    return res.data as MlGroup[]
  }

  async function nameGroup(catalogId: string, groupId: string, label: string, parentId?: string) {
    const res = await axios.post(`${BASE}/${catalogId}/ml-groups/${groupId}/name`, {
      label,
      parent_id: parentId ?? null,
    })
    mlGroups.value = mlGroups.value.filter(g => g.id !== groupId)
    tags.value.push({ ...res.data.tag, children: [] })
    return res.data
  }

  async function skipGroup(catalogId: string, groupId: string) {
    await axios.post(`${BASE}/${catalogId}/ml-groups/${groupId}/skip`)
    mlGroups.value = mlGroups.value.filter(g => g.id !== groupId)
  }

  async function deleteGroup(catalogId: string, groupId: string) {
    await axios.post(`${BASE}/${catalogId}/ml-groups/${groupId}/delete`)
    mlGroups.value = mlGroups.value.filter(g => g.id !== groupId)
  }

  async function mergeGroup(catalogId: string, groupId: string, intoTagId: string) {
    const res = await axios.post(`${BASE}/${catalogId}/ml-groups/${groupId}/merge`, {
      tag_id: intoTagId,
    })
    mlGroups.value = mlGroups.value.filter(g => g.id !== groupId)
    return res.data
  }

  async function fetchHome(catalogId: string) {
    const res = await axios.get(`${BASE}/${catalogId}/home`)
    homeData.value = res.data
    return res.data as HomeData
  }

  return {
    tags,
    mlGroups,
    homeData,
    isLoading,
    error,
    tagTree,
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    mergeTag,
    bulkTag,
    bulkUntag,
    fetchMlGroups,
    nameGroup,
    skipGroup,
    deleteGroup,
    mergeGroup,
    fetchHome,
  }
})
