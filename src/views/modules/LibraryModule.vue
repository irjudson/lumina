<template>
  <LibraryLayout>
    <PanelContainer
      :left-panel-visible="layoutStore.leftPanelVisible"
      :right-panel-visible="layoutStore.rightPanelVisible"
      :filmstrip-expanded="filterBarExpanded"
    >
      <!-- Left Panel: Navigation and Filters -->
      <template #left>
        <LeftPanel
          :visible="layoutStore.leftPanelVisible"
          @toggle="layoutStore.toggleLeftPanel"
        >
          <!-- New Navigation Sidebar -->
          <NavigationSidebar
            :active-view="currentView"
            :catalog-name="catalogStore.activeCatalog?.name"
            :counts="smartViewCounts"
            :collections="collectionsStore.sortedCollections"
            :available-tags="availableTags"
            :selected-tags="selectedTagsFilter"
            @navigate="handleNavigate"
            @open-settings="showSettings = true"
            @create-collection="showCreateCollection = true"
            @filter-tags="handleTagFilter"
            @load-children="collectionsStore.loadChildren"
          />
        </LeftPanel>
      </template>

      <!-- Main Content: Image Grid -->
      <template #main>
        <div class="relative h-full">
          <!-- Panel Toggle Buttons - Always Visible -->
          <PanelToggle
            position="left"
            :collapsed="!layoutStore.leftPanelVisible"
            @toggle="layoutStore.toggleLeftPanel"
            class="absolute top-2 left-2 z-20"
          />
          <PanelToggle
            position="right"
            :collapsed="!layoutStore.rightPanelVisible"
            @toggle="layoutStore.toggleRightPanel"
            class="absolute top-2 right-2 z-20"
          />

          <!-- Loading State -->
          <div v-if="libraryStore.isLoading" class="flex flex-col items-center justify-center h-full text-gray-400">
            <LoaderIcon class="w-8 h-8 animate-spin text-blue-500" />
            <div class="text-sm text-gray-400 mt-3">Loading images...</div>
          </div>

          <!-- Error State -->
          <div v-else-if="libraryStore.error" class="flex flex-col items-center justify-center h-full text-gray-400">
            <AlertCircleIcon class="w-8 h-8 text-red-500" />
            <div class="text-sm text-gray-200 mt-3">{{ libraryStore.error }}</div>
            <button
              @click="retryLoad"
              class="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
            >
              Retry
            </button>
          </div>

          <!-- No Catalog Selected -->
          <div v-else-if="!catalogStore.activeCatalog" class="flex flex-col items-center justify-center h-full text-gray-400">
            <div class="w-16 h-16 bg-gray-900 rounded-full flex items-center justify-center mb-4 border border-gray-800">
              <ImageIcon class="w-8 h-8 text-blue-500" />
            </div>
            <h2 class="text-xl font-semibold text-gray-200 mb-2">Welcome to Lumina</h2>
            <p class="text-sm text-center max-w-md mb-4">
              Create a catalog to start organizing your photos and videos.
            </p>
            <p class="text-xs text-gray-500">
              Click the <SettingsIcon class="w-3 h-3 inline" /> settings icon in the top-right corner
            </p>
          </div>

          <!-- No Images in Catalog -->
          <div v-else-if="libraryStore.images.length === 0" class="flex flex-col items-center justify-center h-full text-gray-400">
            <div class="w-16 h-16 bg-gray-900 rounded-full flex items-center justify-center mb-4 border border-gray-800">
              <ImageIcon class="w-8 h-8 text-blue-500" />
            </div>
            <h3 class="text-sm font-medium text-gray-300 mt-4">No Images</h3>
            <p class="text-xs text-gray-500 mt-1 text-center max-w-md">
              This catalog doesn't have any images yet. Use the Import module to scan directories.
            </p>
          </div>

          <!-- Views Container -->
          <div v-else class="h-full flex flex-col">
            <!-- Timeline View -->
            <TimelineView
              v-if="currentView === 'timeline'"
              :images="displayedImages"
              :catalog-id="catalogStore.activeCatalog?.id"
              @select="handleTimelineSelect"
            />

            <!-- Map View -->
            <MapView
              v-else-if="currentView === 'map' && catalogStore.activeCatalog"
              :images="displayedImages"
              :catalog-id="catalogStore.activeCatalog.id"
              @select="handleTimelineSelect"
            />

            <!-- Bursts View -->
            <BurstsView
              v-else-if="currentView === 'bursts' && catalogStore.activeCatalog"
              :catalog-id="catalogStore.activeCatalog.id"
              @open-image="openDetailFromId"
            />

            <!-- Duplicates View -->
            <DuplicatesView
              v-else-if="currentView === 'duplicates' && catalogStore.activeCatalog"
              :catalog-id="catalogStore.activeCatalog.id"
              @open-image="openDetailFromId"
              @resolved="fetchSmartViewStats"
            />

            <!-- Events View -->
            <EventsView
              v-else-if="currentView === 'events' && catalogStore.activeCatalog"
              :catalog-id="catalogStore.activeCatalog.id"
              @open-image="openDetailFromId"
            />

            <!-- Skipped Imports View -->
            <SkippedImportsView
              v-else-if="currentView === 'skipped_imports' && catalogStore.activeCatalog"
              :catalog-id="catalogStore.activeCatalog.id"
              @dismissed="fetchSmartViewStats"
            />

            <!-- Analytics View -->
            <AnalyticsView
              v-else-if="currentView === 'analytics'"
            />

            <!-- Grid View (Default for other views) -->
            <template v-else>
              <!-- View Header -->
              <div class="flex-none bg-gray-900/50 border-b border-gray-800 px-4 py-3">
                <div class="flex items-center justify-between">
                  <div>
                    <h2 class="text-lg font-semibold text-gray-200">{{ viewTitle }}</h2>
                    <p class="text-sm text-gray-500">
                      {{ displayedImages.length.toLocaleString() }} of {{ libraryStore.totalCount.toLocaleString() }} items{{ libraryStore.isLoadingMore ? ' (loading more...)' : '' }}
                    </p>
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      v-if="currentView === 'rejected' && libraryStore.totalCount > 0"
                      @click="restoreAllRejected"
                      class="text-xs px-3 py-1.5 bg-green-900/40 hover:bg-green-900/60 text-green-400 rounded transition-colors flex items-center gap-1.5"
                    >
                      <RotateCcwIcon class="w-3.5 h-3.5" />
                      Restore All ({{ libraryStore.totalCount.toLocaleString() }})
                    </button>
                    <button
                      v-if="displayedImages.length > 0"
                      @click="selectAll"
                      class="text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors"
                    >
                      Select All ({{ displayedImages.length.toLocaleString() }})
                    </button>
                  </div>
                </div>
              </div>

              <!-- Grid -->
              <div class="flex-1 overflow-hidden">
                <VirtualGrid
                  :items="displayedImages"
                  :selected-items="libraryStore.selectedImageIds"
                  @select="handleImageSelect"
                  @open="handleImageOpen"
                  @load-more="libraryStore.fetchMore()"
                />
              </div>
            </template>
          </div>
        </div>
      </template>

      <!-- Right Panel: View Info & Metadata -->
      <template #right>
        <RightPanel
          :visible="layoutStore.rightPanelVisible"
          @toggle="layoutStore.toggleRightPanel"
        >
          <div class="space-y-6">
            <!-- Current View Info -->
            <section v-if="!libraryStore.hasSelection">
              <h3 class="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">
                {{ viewTitle }}
              </h3>

              <!-- View-specific info -->
              <div class="space-y-3 text-sm">
                <div v-if="currentView === 'all'" class="space-y-2">
                  <div class="flex justify-between">
                    <span class="text-gray-500">Total Items</span>
                    <span class="text-gray-300">{{ libraryStore.totalCount.toLocaleString() }}</span>
                  </div>
                  <div class="flex justify-between">
                    <span class="text-gray-500">Loaded</span>
                    <span class="text-gray-300">{{ libraryStore.images.length.toLocaleString() }}</span>
                  </div>
                  <div v-if="libraryStore.hasMore" class="text-xs text-gray-500">
                    Scroll down to load more
                  </div>
                </div>

                <div v-else-if="currentView === 'recent'" class="space-y-2">
                  <p class="text-gray-400">Photos imported in the last 30 days</p>
                  <div class="flex justify-between">
                    <span class="text-gray-500">Count</span>
                    <span class="text-gray-300">{{ smartViewCounts.recent }}</span>
                  </div>
                </div>

                <div v-else-if="currentView === 'untagged'" class="space-y-2">
                  <p class="text-gray-400">Photos without AI tags</p>
                  <div class="flex justify-between">
                    <span class="text-gray-500">Count</span>
                    <span class="text-gray-300">{{ smartViewCounts.untagged }}</span>
                  </div>
                </div>

                <div v-else-if="currentView === 'videos'" class="space-y-2">
                  <p class="text-gray-400">All video files in your library</p>
                  <div class="flex justify-between">
                    <span class="text-gray-500">Count</span>
                    <span class="text-gray-300">{{ smartViewCounts.videos }}</span>
                  </div>
                </div>
              </div>

              <!-- Active Jobs Status -->
              <div v-if="jobStore.activeJobs.length > 0" class="mt-4 pt-4 border-t border-gray-800">
                <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Active Jobs
                </h4>
                <div class="space-y-2">
                  <div
                    v-for="job in jobStore.activeJobs"
                    :key="job.id"
                    class="bg-gray-800/50 rounded p-3 space-y-2"
                  >
                    <div class="flex items-center justify-between">
                      <span class="text-sm font-medium text-gray-300">
                        {{ formatJobTypeShort(job.job_type) }}
                      </span>
                      <span class="text-xs px-2 py-0.5 rounded-full"
                        :class="job.status === 'running' ? 'bg-blue-600/30 text-blue-400' : 'bg-gray-700 text-gray-400'"
                      >
                        {{ job.status }}
                      </span>
                    </div>
                    <div v-if="job.progress?.message" class="text-xs text-gray-500 truncate">
                      {{ job.progress.message }}
                    </div>
                    <div v-if="job.progress && job.progress.percent && job.progress.percent > 0" class="w-full bg-gray-700 rounded-full h-1.5">
                      <div
                        class="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
                        :style="{ width: `${job.progress?.percent || 0}%` }"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <!-- Quick Actions -->
              <div class="mt-4 pt-4 border-t border-gray-800">
                <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Quick Actions
                </h4>
                <div class="space-y-2">
                  <!-- Scan (always visible) -->
                  <button
                    @click="triggerScan"
                    :disabled="isScanRunning"
                    class="w-full px-3 py-2 text-left text-sm bg-blue-600/20 hover:bg-blue-600/30 disabled:opacity-50 text-blue-400 rounded transition-colors flex items-center gap-2"
                  >
                    <RefreshCwIcon :class="['w-4 h-4', { 'animate-spin': isScanRunning }]" />
                    <span>{{ isScanRunning ? 'Scanning...' : 'Scan for New Images' }}</span>
                  </button>

                  <!-- Tag All (shown in untagged view) -->
                  <button
                    v-if="currentView === 'untagged' && libraryStore.filteredImages.length > 0"
                    @click="triggerAutoTag"
                    class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors flex items-center gap-2"
                  >
                    <SparklesIcon class="w-4 h-4" />
                    <span>Tag All with AI</span>
                  </button>

                  <!-- General actions (visible when images loaded) -->
                  <button
                    v-if="libraryStore.filteredImages.length > 0"
                    @click="triggerDuplicateDetection"
                    class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors flex items-center gap-2"
                  >
                    <CopyIcon class="w-4 h-4" />
                    <span>Find Duplicates</span>
                  </button>

                  <!-- Detect Bursts with expandable options -->
                  <div v-if="libraryStore.filteredImages.length > 0" class="rounded overflow-hidden">
                    <button
                      @click="showBurstOptions = !showBurstOptions"
                      class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 transition-colors flex items-center gap-2"
                    >
                      <ZapIcon class="w-4 h-4" />
                      <span class="flex-1">Detect Bursts</span>
                      <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': showBurstOptions }" />
                    </button>
                    <div v-if="showBurstOptions" class="bg-gray-850 border-t border-gray-700 px-3 py-2 space-y-2">
                      <div>
                        <label class="text-xs text-gray-500 flex justify-between mb-1">
                          <span>Max gap between shots</span>
                          <span class="text-gray-300 font-mono">{{ burstGapThreshold.toFixed(1) }}s</span>
                        </label>
                        <input
                          type="range"
                          min="0.3" max="3.0" step="0.1"
                          v-model.number="burstGapThreshold"
                          class="w-full accent-blue-500"
                        />
                        <div class="flex justify-between text-[10px] text-gray-600 mt-0.5">
                          <span>0.3s (fast burst)</span>
                          <span>3.0s (loose)</span>
                        </div>
                      </div>
                      <div>
                        <label class="text-xs text-gray-500 flex justify-between mb-1">
                          <span>Min images per burst</span>
                          <span class="text-gray-300 font-mono">{{ burstMinSize }}</span>
                        </label>
                        <input
                          type="range"
                          min="2" max="10" step="1"
                          v-model.number="burstMinSize"
                          class="w-full accent-blue-500"
                        />
                      </div>
                      <button
                        @click="triggerBurstDetection"
                        class="w-full py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors"
                      >
                        Run Detection
                      </button>
                    </div>
                  </div>

                  <!-- Classify Images with expandable model option -->
                  <div v-if="libraryStore.filteredImages.length > 0" class="rounded overflow-hidden">
                    <button
                      @click="showClassifyOptions = !showClassifyOptions"
                      class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 transition-colors flex items-center gap-2"
                    >
                      <FileWarningIcon class="w-4 h-4" />
                      <span class="flex-1">Classify Images</span>
                      <ChevronDownIcon class="w-3 h-3 transition-transform" :class="{ 'rotate-180': showClassifyOptions }" />
                    </button>
                    <div v-if="showClassifyOptions" class="bg-gray-850 border-t border-gray-700 px-3 py-2 space-y-2">
                      <div>
                        <label class="text-xs text-gray-500 mb-1 block">Vision model</label>
                        <select
                          v-model="classifyModel"
                          class="w-full bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1"
                        >
                          <option value="qwen3-vl">qwen3-vl (recommended)</option>
                          <option value="llava">llava</option>
                        </select>
                      </div>
                      <label class="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
                        <input type="checkbox" v-model="classifyReclassify" class="accent-blue-500" />
                        Re-classify already classified
                      </label>
                      <button
                        @click="triggerClassifyImages"
                        class="w-full py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors"
                      >
                        Run Classification
                      </button>
                    </div>
                  </div>

                  <button
                    v-if="libraryStore.filteredImages.length > 0"
                    @click="triggerThumbnailGeneration"
                    class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors flex items-center gap-2"
                  >
                    <ImagePlusIcon class="w-4 h-4" />
                    <span>Generate Thumbnails</span>
                  </button>

                  <button
                    v-if="libraryStore.filteredImages.length > 0"
                    @click="triggerDetectEvents"
                    class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors flex items-center gap-2"
                  >
                    <PartyPopperIcon class="w-4 h-4" />
                    <span>Detect Events</span>
                  </button>

                  <button
                    v-if="libraryStore.filteredImages.length > 0"
                    @click="triggerCategorize"
                    :disabled="isCategorizeRunning"
                    class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-400 rounded transition-colors flex items-center gap-2"
                  >
                    <LayersIcon class="w-4 h-4" />
                    <span>{{ isCategorizeRunning ? 'Categorizing...' : 'Categorize Library' }}</span>
                  </button>

                  <button
                    v-if="libraryStore.filteredImages.length > 0"
                    @click="triggerDetectPeople"
                    :disabled="isDetectPeopleRunning"
                    class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-400 rounded transition-colors flex items-center gap-2"
                  >
                    <UsersIcon class="w-4 h-4" />
                    <span>{{ isDetectPeopleRunning ? 'Detecting People...' : 'Detect People' }}</span>
                  </button>
                </div>
              </div>
            </section>

            <!-- Selection Info -->
            <section v-else>
              <h3 class="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">
                Selection
              </h3>
              <div class="text-sm text-gray-400 mb-4">
                <p v-if="libraryStore.selectedImages.length === 1">
                  1 item selected
                </p>
                <p v-else>
                  {{ libraryStore.selectedImages.length }} items selected
                </p>
              </div>

              <!-- Bulk Actions -->
              <div class="space-y-2">
                <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Bulk Actions
                </h4>

                <!-- AI Tagging -->
                <button
                  @click="bulkTagSelected"
                  class="w-full px-3 py-2 text-left text-sm bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded transition-colors flex items-center gap-2"
                >
                  <SparklesIcon class="w-4 h-4" />
                  <span>Tag Selected with AI</span>
                </button>

                <!-- Favorite Actions -->
                <button
                  @click="bulkAddToFavorites"
                  class="w-full px-3 py-2 text-left text-sm bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-400 rounded transition-colors flex items-center gap-2"
                >
                  <StarIcon class="w-4 h-4" />
                  <span>Add to Favorites</span>
                </button>

                <button
                  @click="bulkRemoveFromFavorites"
                  class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors flex items-center gap-2"
                >
                  <StarIcon class="w-4 h-4" />
                  <span>Remove from Favorites</span>
                </button>

                <!-- Collection Actions -->
                <div v-if="collectionsStore.collections.length > 0" class="pt-2 border-t border-gray-800">
                  <p class="text-xs text-gray-500 mb-2">Add to Collection</p>
                  <div class="space-y-1 max-h-32 overflow-y-auto">
                    <button
                      v-for="collection in collectionsStore.sortedCollections.slice(0, 5)"
                      :key="collection.id"
                      @click="bulkAddToCollection(collection.id)"
                      class="w-full px-3 py-2 text-left text-xs bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors flex items-center gap-2"
                    >
                      <FolderIcon class="w-3 h-3" />
                      <span class="truncate">{{ collection.name }}</span>
                    </button>
                  </div>
                </div>

                <!-- Reject / Restore -->
                <div class="pt-2 border-t border-gray-800 space-y-1">
                  <button
                    v-if="currentView !== 'rejected'"
                    @click="bulkRejectSelected"
                    class="w-full px-3 py-2 text-left text-sm bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded transition-colors flex items-center gap-2"
                  >
                    <AlertCircleIcon class="w-4 h-4" />
                    <span>Reject Selected</span>
                  </button>
                  <button
                    v-if="currentView === 'rejected'"
                    @click="restoreSelected"
                    class="w-full px-3 py-2 text-left text-sm bg-green-900/30 hover:bg-green-900/50 text-green-400 rounded transition-colors flex items-center gap-2"
                  >
                    <RotateCcwIcon class="w-4 h-4" />
                    <span>Restore Selected</span>
                  </button>
                  <p class="text-[10px] text-gray-600 mt-1 px-1">Marks as rejected — source files are never deleted.</p>
                </div>

                <!-- Deselect -->
                <button
                  @click="libraryStore.clearSelection()"
                  class="w-full px-3 py-2 text-left text-sm bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-colors mt-3"
                >
                  Clear Selection
                </button>
              </div>

              <!-- Single Image Metadata -->
              <div v-if="libraryStore.selectedImages.length === 1" class="mt-4 pt-4 border-t border-gray-800 space-y-4">
                <!-- File -->
                <div>
                  <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">File</h4>
                  <div class="space-y-1 text-xs">
                    <p class="text-gray-400 truncate" :title="libraryStore.selectedImages[0].path">{{ selectedImageFilename }}</p>
                    <div class="flex justify-between text-gray-600">
                      <span>{{ selectedImageTypeLabel }}</span>
                      <span>{{ selectedImageSizeLabel }}</span>
                    </div>
                    <p v-if="selectedImageDate" class="text-gray-600">{{ selectedImageDate }}</p>
                  </div>
                </div>

                <!-- Camera -->
                <div v-if="selectedImageMeta?.camera_model || selectedImageMeta?.camera_make">
                  <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Camera</h4>
                  <div class="space-y-1 text-xs text-gray-400">
                    <p>{{ [selectedImageMeta.camera_make, selectedImageMeta.camera_model].filter(Boolean).join(' ') }}</p>
                    <p v-if="selectedImageMeta.lens_model" class="text-gray-600 truncate">{{ selectedImageMeta.lens_model }}</p>
                  </div>
                </div>

                <!-- Exposure -->
                <div v-if="selectedImageMeta?.iso || selectedImageMeta?.aperture || selectedImageMeta?.shutter_speed">
                  <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Exposure</h4>
                  <div class="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400">
                    <span v-if="selectedImageMeta.iso">ISO {{ selectedImageMeta.iso }}</span>
                    <span v-if="selectedImageMeta.aperture">f/{{ selectedImageMeta.aperture }}</span>
                    <span v-if="selectedImageMeta.shutter_speed">{{ selectedImageShutter }}</span>
                    <span v-if="selectedImageMeta.focal_length">{{ Math.round(selectedImageMeta.focal_length) }}mm</span>
                  </div>
                </div>

                <!-- Dimensions -->
                <div v-if="selectedImageMeta?.width && selectedImageMeta?.height">
                  <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Dimensions</h4>
                  <div class="text-xs text-gray-400">
                    <span>{{ selectedImageMeta.width }} × {{ selectedImageMeta.height }}</span>
                    <span class="text-gray-600 ml-2">{{ ((selectedImageMeta.width * selectedImageMeta.height) / 1e6).toFixed(1) }} MP</span>
                  </div>
                </div>

                <!-- Tags -->
                <div v-if="selectedImageTags.length > 0">
                  <h4 class="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Tags</h4>
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="tag in selectedImageTags"
                      :key="tag.name"
                      class="px-1.5 py-0.5 bg-gray-800 text-gray-400 text-[10px] rounded"
                      :title="`${tag.source} · ${Math.round(tag.confidence * 100)}%`"
                    >{{ tag.name }}</span>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </RightPanel>
      </template>

      <!-- Filter Bar (filmstrip slot repurposed) -->
      <template #filmstrip>
        <FilterBar
          :model-value="libraryStore.activeFilters"
          :expanded="filterBarExpanded"
          @update:model-value="applyFilterBar"
          @toggle="filterBarExpanded = !filterBarExpanded"
        />
      </template>
    </PanelContainer>

    <!-- Settings Modal Overlay -->
    <Transition name="fade">
      <div
        v-if="showSettings"
        class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"
        @click.self="showSettings = false"
      >
        <div class="w-full h-full bg-gray-950 overflow-hidden">
          <CatalogSettings
            :catalog="catalogStore.activeCatalog"
            :total-images="libraryStore.images.length"
            @close="showSettings = false"
          />
        </div>
      </div>
    </Transition>

    <!-- Create Collection Modal -->
    <CreateCollectionModal
      v-model="showCreateCollection"
      @created="handleCollectionCreated"
    />

    <!-- Image Detail Overlay -->
    <ImageDetailOverlay
      v-if="showDetail && catalogStore.activeCatalog"
      :catalog-id="catalogStore.activeCatalog.id"
      :image-id="detailImageId"
      :images="displayedImages"
      @close="showDetail = false"
      @navigate="detailImageId = $event"
      @reject="id => id && rejectSingleImage(id)"
      @favorite="id => id && favoritesStore.addFavorites([id])"
    />
  </LibraryLayout>
</template>

<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { useLayoutStore } from '@/stores/layout'
import { useLibraryStore } from '@/stores/library'
import { useCatalogStore } from '@/stores/catalog'
import { useJobStore } from '@/stores/jobs'
import { useFavoritesStore } from '@/stores/favorites'
import { useCollectionsStore } from '@/stores/collections'
import { api } from '@/api/client'
import LibraryLayout from '@/layouts/LibraryLayout.vue'
import PanelContainer from '@/components/layout/PanelContainer.vue'
import LeftPanel from '@/components/layout/LeftPanel.vue'
import RightPanel from '@/components/layout/RightPanel.vue'
import PanelToggle from '@/components/layout/PanelToggle.vue'
import VirtualGrid from '@/components/virtual/VirtualGrid.vue'
import TimelineView from '@/components/views/TimelineView.vue'
import MapView from '@/components/views/MapView.vue'
import BurstsView from '@/components/views/BurstsView.vue'
import DuplicatesView from '@/components/views/DuplicatesView.vue'
import EventsView from '@/components/views/EventsView.vue'
import AnalyticsView from '@/components/views/AnalyticsView.vue'
import SkippedImportsView from '@/components/views/SkippedImportsView.vue'
import ImageDetailOverlay from '@/components/views/ImageDetailOverlay.vue'
import NavigationSidebar from '@/components/library/NavigationSidebar.vue'
import FilterBar from '@/components/library/FilterBar.vue'
import { ImageIcon, SettingsIcon, LoaderIcon, AlertCircleIcon, Star as StarIcon, Folder as FolderIcon, Sparkles as SparklesIcon, Copy as CopyIcon, Zap as ZapIcon, ImagePlus as ImagePlusIcon, RefreshCw as RefreshCwIcon, ChevronDown as ChevronDownIcon, FileWarning as FileWarningIcon, RotateCcw as RotateCcwIcon, PartyPopper as PartyPopperIcon, Layers as LayersIcon, Users as UsersIcon } from 'lucide-vue-next'
import type { Image, FileType, ImageStatus } from '@/stores/library'
import CatalogSettings from '@/views/CatalogSettings.vue'
import CreateCollectionModal from '@/components/collections/CreateCollectionModal.vue'
import { useKeyboardShortcuts } from '@/composables/useKeyboardShortcuts'

const layoutStore = useLayoutStore()
const libraryStore = useLibraryStore()
const catalogStore = useCatalogStore()
const jobStore = useJobStore()
const favoritesStore = useFavoritesStore()
const collectionsStore = useCollectionsStore()

// UI State
const currentView = ref('all')
const filterBarExpanded = ref(false)
const showSettings = ref(false)
const showCreateCollection = ref(false)
const showDetail = ref(false)
const detailImageId = ref('')
const showBurstOptions = ref(false)
const burstGapThreshold = ref(1.0)
const burstMinSize = ref(3)
const showClassifyOptions = ref(false)
const classifyModel = ref('qwen3-vl')
const classifyReclassify = ref(false)

// DB-accurate counts for all smart views
const smartCounts = ref({ recent: 0, untagged: 0, videos: 0, geotagged: 0, bursts: 0, duplicates: 0, screenshots: 0, documents: 0, noise: 0, needs_review: 0, rejected: 0, events: 0, skipped_imports: 0 })

// Available tags for filtering
const availableTags = ref<Array<{ name: string; count: number }>>([])
const selectedTagsFilter = ref<string[]>([])

async function fetchAvailableTags() {
  if (!catalogStore.activeCatalog) return
  try {
    availableTags.value = await api.getTags(catalogStore.activeCatalog.id)
  } catch (e) {
    console.warn('Failed to fetch tags:', e)
  }
}

function handleTagFilter(tags: string[]) {
  selectedTagsFilter.value = tags
  libraryStore.setFilter({ tags: tags.length ? tags : undefined })
}

async function fetchSmartViewStats() {
  if (!catalogStore.activeCatalog) return
  try {
    smartCounts.value = await api.getSmartCounts(catalogStore.activeCatalog.id)
  } catch (e) {
    console.warn('Failed to fetch smart view counts:', e)
  }
}

// Per-image tags — fetched reactively when a single image is selected
const selectedImageTags = ref<Array<{ name: string, confidence: number, source: string }>>([])

watch(
  () => libraryStore.lastSelectedId,
  async (imageId) => {
    selectedImageTags.value = []
    if (!imageId || !catalogStore.activeCatalog) return
    try {
      selectedImageTags.value = await api.getImageTags(catalogStore.activeCatalog.id, imageId)
    } catch { /* non-critical */ }
  }
)

// Single-image metadata helpers
const selectedImageMeta = computed(() => libraryStore.selectedImages[0]?.metadata || null)

const selectedImageFilename = computed(() => {
  const path = libraryStore.selectedImages[0]?.path || ''
  return path.split('/').pop() || path
})

const selectedImageTypeLabel = computed(() => {
  const img = libraryStore.selectedImages[0]
  if (!img) return ''
  const ext = img.path?.split('.').pop()?.toUpperCase()
  const type = img.file_type?.toUpperCase()
  return ext ? `${ext} ${type}` : type
})

const selectedImageSizeLabel = computed(() => {
  const bytes = libraryStore.selectedImages[0]?.size_bytes
  if (!bytes) return ''
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(2)} GB`
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(0)} KB`
  return `${bytes} B`
})

const selectedImageDate = computed(() => {
  const img = libraryStore.selectedImages[0]
  if (!img) return ''
  const dateStr = img.dates?.selected_date || img.dates?.exif_date || img.created_at
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
})

const selectedImageShutter = computed(() => {
  const ss = selectedImageMeta.value?.shutter_speed
  if (!ss) return undefined
  if (ss >= 1) return `${ss}s`
  return `1/${Math.round(1 / ss)}s`
})

const smartViewCounts = computed(() => ({
  events:          smartCounts.value.events ?? 0,
  bursts:          smartCounts.value.bursts,
  duplicates:      smartCounts.value.duplicates,
  screenshots:     smartCounts.value.screenshots ?? 0,
  documents:       smartCounts.value.documents ?? 0,
  noise:           smartCounts.value.noise ?? 0,
  recent:          smartCounts.value.recent,
  untagged:        smartCounts.value.untagged,
  videos:          smartCounts.value.videos,
  needs_review:    smartCounts.value.needs_review ?? 0,
  rejected:        smartCounts.value.rejected ?? 0,
  favorites:       favoritesStore.count,
  skipped_imports: smartCounts.value.skipped_imports ?? 0,
}))

// View title based on current view
const viewTitle = computed(() => {
  if (currentView.value.startsWith('collection:')) {
    const collectionId = currentView.value.substring('collection:'.length)
    const collection = collectionsStore.getCollection(collectionId)
    return collection?.name || 'Collection'
  }

  switch (currentView.value) {
    case 'all': return 'All Photos'
    case 'recent': return 'Recent'
    case 'untagged': return 'Untagged'
    case 'videos': return 'Videos'
    case 'events': return 'Events'
    case 'analytics': return 'Analytics'
    case 'bursts': return 'Bursts'
    case 'duplicates': return 'Duplicates'
    case 'screenshots': return 'Screenshots'
    case 'documents': return 'Documents'
    case 'noise': return 'Noise'
    case 'needs-review': return 'Needs Review'
    case 'rejected': return 'Rejected'
    case 'timeline': return 'Timeline'
    case 'map': return 'Map'
    case 'favorites': return 'Favorites'
    case 'skipped_imports': return 'Skipped Imports'
    default: return 'Library'
  }
})

// Displayed images - applies favorites/collection filtering on top of libraryStore filters
const displayedImages = computed(() => {
  let images = libraryStore.filteredImages

  // Apply favorites filter
  if (currentView.value === 'favorites') {
    images = images.filter(img => favoritesStore.isFavorite(img.id))
  }

  return images
})


// Set active module and load data
onMounted(async () => {
  layoutStore.setActiveModule('library')

  if (catalogStore.activeCatalog) {
    libraryStore.setCatalog(catalogStore.activeCatalog.id)

    // Fetch real images, smart view stats, collections, and tags
    await libraryStore.fetchImages(catalogStore.activeCatalog.id)
    await fetchSmartViewStats()
    await collectionsStore.initForCatalog(catalogStore.activeCatalog.id)
    await fetchAvailableTags()
  }
})

// Watch for catalog changes
watch(() => catalogStore.activeCatalog, async (newCatalog) => {
  if (newCatalog) {
    libraryStore.setCatalog(newCatalog.id)
    await libraryStore.fetchImages(newCatalog.id)
    await fetchSmartViewStats()
    await collectionsStore.initForCatalog(newCatalog.id)
    await fetchAvailableTags()
  }
})

// Retry handler for error state
function retryLoad() {
  if (catalogStore.activeCatalog) {
    libraryStore.fetchImages(catalogStore.activeCatalog.id)
  }
}

// Watch for job completion to refresh data
watch(() => jobStore.activeJobs, async (jobs, oldJobs) => {
  if (!catalogStore.activeCatalog) return

  const justCompleted = (jobType: string) => {
    const wasRunning = oldJobs?.some(j => j.job_type === jobType && j.status === 'running')
    const isRunning = jobs.some(j => j.job_type === jobType && j.status === 'running')
    return wasRunning && !isRunning
  }

  // Scan just completed - refresh images
  if (justCompleted('scan')) {
    await libraryStore.fetchImages(catalogStore.activeCatalog.id)
    await fetchSmartViewStats()
  }

  // Burst, duplicate, event detection completed - refresh smart view counts
  if (justCompleted('detect_bursts') || justCompleted('detect_duplicates') || justCompleted('detect_duplicates_v2') || justCompleted('classify_images') || justCompleted('detect_events')) {
    await fetchSmartViewStats()
  }

  // Auto-tag completed — refresh available tags list
  if (justCompleted('auto_tag')) {
    await fetchAvailableTags()
    await fetchSmartViewStats()
  }

  // Face detection completed — auto-chain cluster_faces
  if (justCompleted('detect_faces') && catalogStore.activeCatalog) {
    try {
      const job = await api.createJob({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'cluster_faces',
        params: {},
        job_source: 'user',
        priority: 75,
      })
      jobStore.addJob(job)
    } catch (error) {
      console.error('Failed to auto-chain cluster_faces:', error)
    }
  }

  // Categorize or cluster completed — refresh collections
  if (justCompleted('categorize_images') || justCompleted('cluster_faces')) {
    await collectionsStore.initForCatalog(catalogStore.activeCatalog.id)
  }
})

// Filter bar handler — merges bar state into active filters and re-fetches
async function applyFilterBar(newFilters: import('@/stores/library').ImageFilters) {
  await libraryStore.setFilter(newFilters)
}

// Navigation handler
async function handleNavigate(view: string) {
  currentView.value = view

  // ALWAYS clear filters first - critical for proper view switching
  libraryStore.clearFilters()

  // Apply view-specific filters
  switch (view) {
    case 'all':
      // No filters - explicitly fetch all images
      if (catalogStore.activeCatalog) {
        await libraryStore.fetchImages(catalogStore.activeCatalog.id)
      }
      break

    case 'recent': {
      // Photos imported in the last 30 days, newest first
      const thirtyDaysAgo = new Date()
      thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)
      libraryStore.setFilter({
        createdAfter: thirtyDaysAgo.toISOString(),
        sortBy: 'created_at',
        sortOrder: 'desc',
      })
      break
    }

    case 'untagged':
      // Photos with no tags — use backend has_tags=false filter
      libraryStore.setFilter({ hasTags: false })
      break

    case 'videos':
      // Only videos
      libraryStore.setFilter({
        fileTypes: ['video'] as FileType[]
      })
      break

    case 'timeline':
    case 'map':
      // Special views with their own UI - no filtering needed
      // The views themselves handle how to display the data
      break

    case 'favorites':
      // Filter to favorited images
      // No libraryStore filter - we'll handle this in computed
      break

    case 'screenshots':
      libraryStore.setFilter({ contentClass: 'screenshot' })
      break

    case 'documents':
      libraryStore.setFilter({ contentClass: 'document' })
      break

    case 'noise':
      libraryStore.setFilter({ contentClass: 'invalid,social_media,meme,received' })
      break

    case 'bursts':
    case 'duplicates':
    case 'events':
    case 'analytics':
    case 'skipped_imports':
      // These views self-fetch their own data
      break

    case 'needs-review':
      libraryStore.setFilter({ statusFilter: 'flagged' })
      break

    case 'rejected':
      libraryStore.setFilter({ statusFilter: 'rejected' })
      break

    default:
      // Check if it's a collection view
      if (view.startsWith('collection:')) {
        const collectionId = view.substring('collection:'.length)
        collectionsStore.activeCollectionId = collectionId
        if (catalogStore.activeCatalog) {
          libraryStore.setFilter({ collectionId })
        }
      } else {
        console.log('Unknown view:', view)
      }
  }
}


function selectAll() {
  const allIds = displayedImages.value.map(img => img.id)
  libraryStore.selectedImageIds = new Set(allIds)
}

async function bulkRejectSelected() {
  if (!catalogStore.activeCatalog) return
  const ids = libraryStore.selectedImages.map(img => img.id)
  if (ids.length === 0) return
  try {
    await fetch(`/api/catalogs/${catalogStore.activeCatalog.id}/images/bulk-status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_ids: ids, status: 'rejected' }),
    })
    // Remove locally — no re-fetch, no scroll reset
    libraryStore.removeImageIds(ids)
  } catch (e) {
    console.error('Failed to reject images:', e)
  }
}

async function restoreSelected() {
  if (!catalogStore.activeCatalog) return
  const ids = libraryStore.selectedImages.map(img => img.id)
  if (ids.length === 0) return
  try {
    await fetch(`/api/catalogs/${catalogStore.activeCatalog.id}/images/bulk-status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_ids: ids, status: 'active' }),
    })
    libraryStore.removeImageIds(ids)
    await fetchSmartViewStats()
  } catch (e) {
    console.error('Failed to restore images:', e)
  }
}

async function restoreAllRejected() {
  if (!catalogStore.activeCatalog) return
  const count = libraryStore.totalCount
  if (!confirm(`Restore all ${count.toLocaleString()} rejected images back to active?`)) return
  try {
    const res = await fetch(`/api/catalogs/${catalogStore.activeCatalog.id}/images/restore-all-rejected`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!res.ok) throw new Error('Failed')
    // Refresh the view
    await libraryStore.fetchImages(catalogStore.activeCatalog.id)
    await fetchSmartViewStats()
  } catch (e) {
    console.error('Failed to restore all rejected:', e)
  }
}

async function rejectSingleImage(imageId: string) {
  if (!catalogStore.activeCatalog) return
  try {
    await fetch(`/api/catalogs/${catalogStore.activeCatalog.id}/images/bulk-status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_ids: [imageId], status: 'rejected' }),
    })
    libraryStore.removeImageIds([imageId])
    // If viewing in overlay, advance to next image or close
    if (showDetail.value) {
      const remaining = displayedImages.value
      if (remaining.length === 0) {
        showDetail.value = false
      } else {
        // Stay at same index (now points to next image) or back one if at end
        const currentIdx = remaining.findIndex(img => img.id === detailImageId.value)
        if (currentIdx === -1) {
          detailImageId.value = remaining[Math.min(0, remaining.length - 1)].id
        }
      }
    }
  } catch (e) {
    console.error('Failed to reject image:', e)
  }
}

// Selection handlers
function handleImageSelect(image: Image, event: MouseEvent) {
  if (event.shiftKey && libraryStore.lastSelectedId) {
    libraryStore.selectRange(libraryStore.lastSelectedId, image.id)
  } else {
    libraryStore.toggleSelection(image.id, event.ctrlKey || event.metaKey)
  }
}

function handleImageOpen(image: Image, _event: MouseEvent) {
  detailImageId.value = image.id
  showDetail.value = true
}

function openDetailFromId(imageId: string) {
  detailImageId.value = imageId
  showDetail.value = true
}

// Handle selection from Timeline/Map views (simpler - just select without event handling)
function handleTimelineSelect(image: any) {
  console.log('Selected from timeline/map:', image.id)
  libraryStore.toggleSelection(image.id, false)
}

// Handle collection created
function handleCollectionCreated(collectionId: string) {
  // Navigate to the new collection
  handleNavigate(`collection:${collectionId}`)
}

// Bulk action: Add to favorites
function bulkAddToFavorites() {
  const selectedIds = libraryStore.selectedImages.map(img => img.id)
  favoritesStore.addFavorites(selectedIds)
}

// Bulk action: Remove from favorites
function bulkRemoveFromFavorites() {
  const selectedIds = libraryStore.selectedImages.map(img => img.id)
  favoritesStore.removeFavorites(selectedIds)
}

// Bulk action: Add to collection
async function bulkAddToCollection(collectionId: string) {
  const selectedIds = libraryStore.selectedImages.map(img => img.id)
  const count = await collectionsStore.addImagesToCollection(collectionId, selectedIds)
  console.log(`Added ${count} images to collection`)
}

// Quick Action: Tag all untagged images with AI
async function triggerAutoTag() {
  if (!catalogStore.activeCatalog) return

  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'auto_tag',
        parameters: {
          tag_mode: 'untagged_only',
          backend: 'auto',
          batch_size: 32
        },
        job_source: 'user',
        priority: 100
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit tagging job')
    }

    const job = await response.json()
    jobStore.addJob(job)
    console.log('Auto-tag job submitted:', job.id)
  } catch (error) {
    console.error('Failed to trigger auto-tag:', error)
  }
}

// Quick Action: Detect duplicates
async function triggerDuplicateDetection() {
  if (!catalogStore.activeCatalog) return

  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'detect_duplicates_v2',
        parameters: { mode: 'full' },
        job_source: 'user',
        priority: 100
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit duplicate detection job')
    }

    const job = await response.json()
    jobStore.addJob(job)
    console.log('Duplicate detection job submitted:', job.id)
  } catch (error) {
    console.error('Failed to trigger duplicate detection:', error)
  }
}

// Quick Action: Detect bursts
async function triggerBurstDetection() {
  if (!catalogStore.activeCatalog) return

  showBurstOptions.value = false
  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'detect_bursts',
        parameters: {
          gap_threshold: burstGapThreshold.value,
          min_burst_size: burstMinSize.value
        },
        job_source: 'user',
        priority: 100
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit burst detection job')
    }

    const job = await response.json()
    jobStore.addJob(job)
    console.log('Burst detection job submitted:', job.id)
  } catch (error) {
    console.error('Failed to trigger burst detection:', error)
  }
}

// Quick Action: Classify images by content type
async function triggerClassifyImages() {
  if (!catalogStore.activeCatalog) return

  showClassifyOptions.value = false
  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'classify_images',
        parameters: {
          model: classifyModel.value,
          reclassify: classifyReclassify.value,
        },
        job_source: 'user',
        priority: 100
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit classify job')
    }

    const job = await response.json()
    jobStore.addJob(job)
  } catch (error) {
    console.error('Failed to trigger image classification:', error)
  }
}

// Quick Action: Generate thumbnails
async function triggerThumbnailGeneration() {
  if (!catalogStore.activeCatalog) return

  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'generate_thumbnails',
        parameters: {
          force: false,
          size: 'medium'
        },
        job_source: 'user',
        priority: 90
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit thumbnail generation job')
    }

    const job = await response.json()
    jobStore.addJob(job)
    console.log('Thumbnail generation job submitted:', job.id)
  } catch (error) {
    console.error('Failed to trigger thumbnail generation:', error)
  }
}

// Quick Action: Detect Events
async function triggerDetectEvents() {
  if (!catalogStore.activeCatalog) return
  try {
    const job = await api.createJob({
      catalog_id: catalogStore.activeCatalog.id,
      job_type: 'detect_events',
      params: {},
      job_source: 'user',
      priority: 90,
    })
    jobStore.addJob(job)
  } catch (error) {
    console.error('Failed to trigger event detection:', error)
  }
}

// Quick Action: Scan for new images
const isScanRunning = computed(() =>
  jobStore.activeJobs.some(j => j.job_type === 'scan' && (j.status === 'running' || j.status === 'pending'))
)

const isCategorizeRunning = computed(() =>
  jobStore.activeJobs.some(j => j.job_type === 'categorize_images' && (j.status === 'running' || j.status === 'pending'))
)

const isDetectPeopleRunning = computed(() =>
  jobStore.activeJobs.some(j => (j.job_type === 'detect_faces' || j.job_type === 'cluster_faces') && (j.status === 'running' || j.status === 'pending'))
)

function formatJobTypeShort(type: string): string {
  const types: Record<string, string> = {
    scan: 'Scanning',
    detect_duplicates: 'Duplicates',
    detect_bursts: 'Burst Detection',
    auto_tag: 'AI Tagging',
    generate_thumbnails: 'Thumbnails',
    classify_images: 'Image Classification',
    categorize_images: 'Categorizing',
    detect_faces: 'Detecting Faces',
    cluster_faces: 'Clustering People',
  }
  return types[type] || type || 'Job'
}

async function triggerCategorize() {
  if (!catalogStore.activeCatalog) return
  try {
    const job = await api.createJob({
      catalog_id: catalogStore.activeCatalog.id,
      job_type: 'categorize_images',
      params: {},
      job_source: 'user',
      priority: 80,
    })
    jobStore.addJob(job)
  } catch (error) {
    console.error('Failed to trigger categorize:', error)
  }
}

async function triggerDetectPeople() {
  if (!catalogStore.activeCatalog) return
  try {
    const job = await api.createJob({
      catalog_id: catalogStore.activeCatalog.id,
      job_type: 'detect_faces',
      params: {},
      job_source: 'user',
      priority: 75,
    })
    jobStore.addJob(job)
  } catch (error) {
    console.error('Failed to trigger face detection:', error)
  }
}

async function triggerScan() {
  if (!catalogStore.activeCatalog) return

  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'scan',
        parameters: {},
        job_source: 'user',
        priority: 100
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit scan job')
    }

    const job = await response.json()
    jobStore.addJob(job)
    console.log('Scan job submitted:', job.id)
  } catch (error) {
    console.error('Failed to trigger scan:', error)
  }
}

// Bulk action: Tag selected images with AI
async function bulkTagSelected() {
  if (!catalogStore.activeCatalog || libraryStore.selectedImages.length === 0) return

  const selectedIds = libraryStore.selectedImages.map(img => img.id)

  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        catalog_id: catalogStore.activeCatalog.id,
        job_type: 'auto_tag',
        parameters: {
          tag_mode: 'selected',
          image_ids: selectedIds,
          backend: 'auto',
          batch_size: 32
        },
        job_source: 'user',
        priority: 100
      })
    })

    if (!response.ok) {
      throw new Error('Failed to submit bulk tagging job')
    }

    const job = await response.json()
    jobStore.addJob(job)
    console.log('Bulk tag job submitted:', job.id)
  } catch (error) {
    console.error('Failed to trigger bulk tag:', error)
  }
}

// Keyboard shortcuts
useKeyboardShortcuts([
  {
    key: 'a',
    ctrl: true,
    description: 'Select all',
    handler: () => {
      const allIds = displayedImages.value.map(img => img.id)
      libraryStore.selectedImageIds = new Set(allIds)
    }
  },
  {
    key: 'Escape',
    description: 'Clear selection',
    handler: () => {
      libraryStore.clearSelection()
    }
  },
  {
    key: 'f',
    description: 'Toggle favorite for selected',
    handler: () => {
      if (libraryStore.selectedImages.length > 0) {
        const selectedIds = libraryStore.selectedImages.map(img => img.id)
        // Toggle - if all are favorited, unfavorite; otherwise favorite all
        const allFavorited = selectedIds.every(id => favoritesStore.isFavorite(id))
        if (allFavorited) {
          favoritesStore.removeFavorites(selectedIds)
        } else {
          favoritesStore.addFavorites(selectedIds)
        }
      }
    }
  },
  {
    key: '1',
    description: 'Go to All Photos',
    handler: () => handleNavigate('all')
  },
  {
    key: '2',
    description: 'Go to Timeline',
    handler: () => handleNavigate('timeline')
  },
  {
    key: '3',
    description: 'Go to Map',
    handler: () => handleNavigate('map')
  },
  {
    key: '4',
    description: 'Go to Favorites',
    handler: () => handleNavigate('favorites')
  },
  {
    key: 'n',
    ctrl: true,
    description: 'New collection',
    handler: () => {
      showCreateCollection.value = true
    }
  }
])
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
