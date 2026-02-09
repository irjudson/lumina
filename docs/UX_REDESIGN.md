# Lumina UX Redesign: Asset-Centric Interface

## Philosophy
**OLD:** Folder-centric - "Browse folders that contain photos"
**NEW:** Asset-centric - "Manage your unified photo library"

Source directories are import plumbing, not primary navigation.

---

## Main Application Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ ☰ Lumina                    [Search...]           👤 [Settings] │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  LEFT SIDEBAR        │      MAIN CONTENT         │  RIGHT PANEL │
│  (Navigation)        │      (Photos Grid)        │  (Details)   │
│                      │                            │              │
│  📷 All Photos       │  ┌───┬───┬───┬───┬───┐   │  📷 Image    │
│  📅 Timeline         │  │   │   │   │   │   │   │              │
│  🗺️  Map             │  ├───┼───┼───┼───┼───┤   │  robin.jpg   │
│  ⭐ Favorites        │  │   │   │   │   │   │   │              │
│                      │  ├───┼───┼───┼───┼───┤   │  📅 Date     │
│  SMART VIEWS         │  │   │   │   │   │   │   │  📍 Location │
│  💥 Bursts (12)      │  ├───┼───┼───┼───┼───┤   │  🏷️  Tags     │
│  👥 Duplicates (8)   │  │   │   │   │   │   │   │  ⭐ Rating   │
│  🆕 Recent Import    │  └───┴───┴───┴───┴───┘   │              │
│  📤 Untagged         │                            │  [Actions]   │
│                      │  Showing 164 photos       │              │
│  COLLECTIONS         │  Sort: Date ▼  Filter: [] │              │
│  + New Collection    │                            │              │
│                      │                            │              │
│                      │                            │              │
└──────────────────────┴────────────────────────────┴──────────────┘
│                    FILMSTRIP (Optional)                          │
│  [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸] [▸]       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Left Sidebar Navigation

### PRIMARY VIEWS
- **📷 All Photos** - Complete library, chronological
- **📅 Timeline** - Photos organized by date (year/month/day hierarchy)
- **🗺️ Map** - Geotagged photos on interactive map
- **⭐ Favorites** - Starred/favorited photos

### SMART VIEWS (Dynamic, show counts)
- **💥 Bursts** (12) - Burst photo sequences needing review
- **👥 Duplicates** (8) - Detected duplicates needing resolution
- **🆕 Recent Import** - Last 30 days of imported photos
- **📤 Untagged** - Photos without AI tags yet
- **⚠️ Needs Review** - Flagged for attention
- **🎥 Videos** - All video assets

### COLLECTIONS (User-Created)
- **+ New Collection** - Create custom collections
- **📁 Vacation 2025**
- **📁 Family Events**
- **📁 Best of 2024**

### COLLAPSED BY DEFAULT
- **🔧 Catalog Settings** (gear icon at bottom)

---

## Main Content Area

### Toolbar (Above Grid)
```
┌─────────────────────────────────────────────────────────────┐
│ Sort: [Date ▼]  View: [Grid|Timeline|Map]  [Filters ▼]     │
│                                                              │
│ Showing 164 photos • 2.1 GB • 2015-2025                    │
└─────────────────────────────────────────────────────────────┘
```

### Grid View
- Responsive grid of thumbnails
- Hover shows quick info overlay (date, location, rating)
- Click opens detail view (right panel expands)
- Multi-select with shift/ctrl
- Infinite scroll or pagination

### Timeline View
```
2025 ───────────────────────────────
  February (89 photos)
    Feb 8 ─ [photos]
    Feb 7 ─ [photos]
  January (42 photos)

2024 ───────────────────────────────
  December (156 photos)
  ...
```

### Map View
- Interactive map with photo markers
- Cluster markers when zoomed out
- Click marker to see photos at that location

---

## Right Panel (Details/Metadata)

### When Photo Selected
```
┌─────────────────────────┐
│     [Photo Preview]     │
│                         │
├─────────────────────────┤
│ 📸 robin.jpg            │
│                         │
│ 📅 Date                 │
│   Feb 8, 2025 2:30 PM  │
│   [Edit] [Copy]         │
│                         │
│ 📍 Location             │
│   San Francisco, CA     │
│   [Show on Map]         │
│                         │
│ 🏷️ Tags                 │
│   #bird #nature #robin  │
│   [Add Tag]             │
│                         │
│ 📷 Camera Info          │
│   iPhone 15 Pro         │
│   ƒ/1.8  1/120s  ISO100│
│                         │
│ ⭐ Rating               │
│   ★★★★☆               │
│                         │
│ 💾 File Info            │
│   JPEG • 1.2 MB         │
│   4032×3024 pixels      │
│                         │
│ ── Actions ──           │
│   [⭐ Favorite]         │
│   [➕ Add to Collection]│
│   [🗑️ Delete]           │
│   [📤 Export]           │
│   [ℹ️ More Info]        │
└─────────────────────────┘
```

### When Nothing Selected
```
┌─────────────────────────┐
│   📊 Catalog Stats      │
│                         │
│   164 Photos            │
│   2.1 GB Storage        │
│                         │
│   📅 Date Range         │
│   2015 - 2025           │
│                         │
│   🗺️ Locations          │
│   12 countries          │
│   45 cities             │
│                         │
│   🏷️ Top Tags           │
│   #nature (45)          │
│   #family (32)          │
│   #travel (28)          │
│                         │
│   💥 Needs Attention    │
│   12 Bursts             │
│   8 Duplicates          │
│   23 Untagged           │
└─────────────────────────┘
```

---

## Catalog Settings Screen

**Access:** Click gear icon in sidebar OR Settings → Catalog

```
┌─────────────────────────────────────────────────────────────┐
│ ← Back to Photos              CATALOG SETTINGS              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  GENERAL                                                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Catalog Name: [My Photos_________________________]     │ │
│  │                                                         │ │
│  │ Created: Feb 8, 2026                                   │ │
│  │ Last Scan: 2 hours ago                                 │ │
│  │                                                         │ │
│  │ [🔄 Scan Now]  [📊 View Scan History]                 │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  SOURCE DIRECTORIES                                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ These folders are monitored for photos:                │ │
│  │                                                         │ │
│  │ ✓ /home/irjudson/Pictures           [🗑️] [⚙️]        │ │
│  │   Last scan: 2 hours ago                               │ │
│  │   164 photos • 2.1 GB                                  │ │
│  │                                                         │ │
│  │ ✓ /mnt/synology/Photos              [🗑️] [⚙️]        │ │
│  │   Last scan: Never                                     │ │
│  │   0 photos • 0 GB                                      │ │
│  │                                                         │ │
│  │ [+ Add Folder]                                         │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  SCAN OPTIONS                                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ ☐ Auto-rescan on file changes (watch mode)            │ │
│  │ ☐ Scan subfolders recursively                         │ │
│  │ ☐ Skip hidden files and folders                       │ │
│  │                                                         │ │
│  │ File Types:                                            │ │
│  │ ☑ Images (JPEG, PNG, HEIC, RAW)                       │ │
│  │ ☑ Videos (MP4, MOV, AVI)                              │ │
│  │                                                         │ │
│  │ Exclude Patterns:                                      │ │
│  │ [.DS_Store, Thumbs.db, @eaDir___________________]     │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  PROCESSING                                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ ☑ Extract metadata (EXIF, dates, GPS)                 │ │
│  │ ☑ Generate thumbnails                                  │ │
│  │ ☐ Run duplicate detection after scan                   │ │
│  │ ☐ Run burst detection after scan                       │ │
│  │ ☐ Auto-tag with AI after scan                         │ │
│  │                                                         │ │
│  │ Thumbnail Quality: [Medium ▼]                          │ │
│  │ Max Cache Size: [10 GB__]                             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  STORAGE                                                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Database: PostgreSQL (healthy)                         │ │
│  │ Cache: 450 MB / 10 GB (4.5%)                          │ │
│  │ Previews: 256 MB                                       │ │
│  │ Thumbnails: 194 MB                                     │ │
│  │                                                         │ │
│  │ [🗑️ Clear Cache]  [🔧 Optimize Database]             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  DANGER ZONE                                                 │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ [🔄 Full Rescan] - Reprocess all photos               │ │
│  │ [🗑️ Delete Catalog] - Remove catalog and all data     │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│                              [Cancel]  [Save Changes]        │
└─────────────────────────────────────────────────────────────┘
```

---

## User Flows

### First-Time Setup
1. Launch app → Welcome screen
2. "Create your first catalog" → Name it
3. "Add folders to watch" → Browse/select source dirs
4. "Start initial scan" → Progress indicator
5. → Main view (All Photos) with imported photos

### Daily Use
1. Launch app → Main view (All Photos)
2. Browse/search photos
3. Review smart views (bursts, duplicates)
4. Organize into collections
5. **Never think about folders**

### Add New Source Directory
1. Click gear icon → Catalog Settings
2. Source Directories → Add Folder
3. Browse/select new folder
4. Save → Auto-scan runs
5. ← Back to Photos

### Trigger Manual Rescan
**Option A:** Settings → Catalog → Scan Now
**Option B:** Quick action menu (☰) → Rescan Catalog

---

## Implementation Plan

### Phase 1: Core Navigation (This PR)
- [ ] Left sidebar with primary views
- [ ] "All Photos" view with grid
- [ ] Basic right panel (details)
- [ ] Route structure for views

### Phase 2: Smart Views
- [ ] Bursts view (existing data)
- [ ] Duplicates view (existing data)
- [ ] Recent import view (filter by date)
- [ ] Untagged view (filter by tags)

### Phase 3: Catalog Settings
- [ ] Settings screen component
- [ ] Source directory management UI
- [ ] Scan options configuration
- [ ] Manual rescan trigger

### Phase 4: Advanced Views
- [ ] Timeline view (date hierarchy)
- [ ] Map view (geolocation)
- [ ] Collections (user-created albums)
- [ ] Search with filters

### Phase 5: Polish
- [ ] Favorites/starring
- [ ] Bulk actions (select multiple)
- [ ] Keyboard shortcuts
- [ ] Performance optimization

---

## Current State → New State Migration

### What Changes
| Old | New |
|-----|-----|
| Folder list in main view | Catalog settings screen |
| "Browse by folder" | "Browse all photos" |
| Manual scan button prominent | Hidden in settings |
| Source dirs = primary concept | Source dirs = technical detail |

### What Stays
| Feature | Location |
|---------|----------|
| Photo grid | Main content area |
| Detail panel | Right sidebar |
| Search | Top toolbar |
| Settings | Settings screen |

### What's New
| Feature | Purpose |
|---------|---------|
| Smart views | Quick access to actionable items |
| Timeline view | Browse photos chronologically |
| Map view | Browse photos geographically |
| Collections | User-organized albums |
| Favorites | Quick access to starred photos |

---

## Design Principles

1. **Photos First** - The content (photos) is the star, not the container (folders)
2. **Progressive Disclosure** - Advanced features (settings) hidden until needed
3. **Smart Defaults** - Auto-scan, smart views with counts, sensible defaults
4. **Actionable Intelligence** - Show what needs attention (bursts, duplicates)
5. **Unified Library** - One collection, many ways to view/organize it

---

## Next Steps

1. ✅ Design review (this document)
2. Create Vue components for new layout
3. Implement routing for views
4. Build catalog settings screen
5. Migrate folder management to settings
6. Test with existing data
7. Polish and iterate
