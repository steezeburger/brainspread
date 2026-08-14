/**
 * PagesListPage — browsable list of every page the user owns
 * (issue #133).
 *
 * Route: /knowledge/pages/ (SPA shell catches the path; app.js mounts
 * this component for currentView === 'pages').
 *
 * The list is server-paginated through the existing
 * /knowledge/api/pages/list/ endpoint (max 100 per fetch, "load more"
 * appends) with page_type filter tabs and an order select. Typing in
 * the search box switches to /knowledge/api/pages/search/ — a
 * title/slug match capped at 20 rows, which is plenty for narrowing.
 */
const PagesListPage = {
  data() {
    return {
      loading: true,
      loadingMore: false,
      error: null,
      pages: [],
      totalCount: 0,
      hasMore: false,

      // "all" is a UI-only sentinel — it maps to omitting page_type.
      typeFilter: "all",
      orderBy: "modified",
      searchQuery: "",
      searchTimeout: null,
      // Bumped per load so a stale response (user changed filters
      // while a fetch was in flight) can't clobber newer results.
      requestSeq: 0,
    };
  },

  computed: {
    typeFilters() {
      return [
        { id: "all", label: "all" },
        { id: "page", label: "pages" },
        { id: "daily", label: "dailies" },
        { id: "whiteboard", label: "whiteboards" },
        { id: "template", label: "templates" },
      ];
    },

    orderOptions() {
      return [
        { id: "modified", label: "recently modified" },
        { id: "title", label: "title" },
        { id: "date", label: "date" },
      ];
    },

    isSearching() {
      return this.searchQuery.trim().length > 0;
    },

    countLabel() {
      if (this.loading) return "";
      if (this.isSearching) {
        return `${this.pages.length} match${this.pages.length === 1 ? "" : "es"}`;
      }
      return `${this.totalCount} page${this.totalCount === 1 ? "" : "s"}`;
    },
  },

  async mounted() {
    await this.reload();
  },

  beforeUnmount() {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
  },

  methods: {
    pageUrl(page) {
      return `/knowledge/page/${encodeURIComponent(page.slug)}/`;
    },

    displayTitle(page) {
      return page.title || "untitled page";
    },

    formatModified(page) {
      if (!page.modified_at) return "";
      const d = new Date(page.modified_at);
      if (isNaN(d.getTime())) return "";
      return d.toLocaleDateString();
    },

    setTypeFilter(id) {
      if (this.typeFilter === id) return;
      this.typeFilter = id;
      // "date" ordering is the natural default for a dailies-only
      // list; snap to it unless the user is mid-search (search
      // results have their own relevance ordering).
      if (id === "daily" && this.orderBy === "modified") {
        this.orderBy = "date";
      }
      this.reload();
    },

    onOrderChange() {
      this.reload();
    },

    onSearchInput() {
      if (this.searchTimeout) clearTimeout(this.searchTimeout);
      this.searchTimeout = setTimeout(() => this.reload(), 300);
    },

    clearSearch() {
      this.searchQuery = "";
      this.reload();
    },

    async reload() {
      this.loading = true;
      this.error = null;
      const seq = ++this.requestSeq;
      try {
        const result = this.isSearching
          ? await this._fetchSearch()
          : await this._fetchList(0);
        if (seq !== this.requestSeq) return;
        if (result && result.success) {
          this.pages = result.data.pages || [];
          this.totalCount = result.data.total_count || this.pages.length;
          this.hasMore = !this.isSearching && !!result.data.has_more;
        } else {
          this.error = "failed to load pages";
        }
      } catch (err) {
        if (seq !== this.requestSeq) return;
        console.error("PagesListPage load failed:", err);
        this.error = "failed to load pages";
      } finally {
        if (seq === this.requestSeq) this.loading = false;
      }
    },

    async loadMore() {
      if (this.loadingMore || !this.hasMore || this.isSearching) return;
      this.loadingMore = true;
      const seq = ++this.requestSeq;
      try {
        const result = await this._fetchList(this.pages.length);
        if (seq !== this.requestSeq) return;
        if (result && result.success) {
          this.pages = this.pages.concat(result.data.pages || []);
          this.totalCount = result.data.total_count || this.totalCount;
          this.hasMore = !!result.data.has_more;
        } else {
          this.error = "failed to load more pages";
        }
      } catch (err) {
        if (seq !== this.requestSeq) return;
        console.error("PagesListPage loadMore failed:", err);
        this.error = "failed to load more pages";
      } finally {
        this.loadingMore = false;
      }
    },

    _fetchList(offset) {
      const pageType = this.typeFilter === "all" ? null : this.typeFilter;
      // published_only=false — this surface's whole point is "the
      // full list", so unpublished pages are included too.
      return window.apiService.getPages(
        false,
        100,
        offset,
        pageType,
        this.orderBy
      );
    },

    _fetchSearch() {
      const pageType = this.typeFilter === "all" ? null : this.typeFilter;
      return window.apiService.searchPages(
        this.searchQuery.trim(),
        20,
        pageType
      );
    },
  },

  template: `
    <div class="pages-list-page">
      <div class="pages-list-header">
        <h1>all pages</h1>
        <span class="pages-list-count">{{ countLabel }}</span>
      </div>

      <div class="pages-list-controls">
        <div class="pages-list-search">
          <input
            v-model="searchQuery"
            @input="onSearchInput"
            type="text"
            class="pages-list-search-input"
            placeholder="filter by title…"
            aria-label="Filter pages by title"
          />
          <button
            v-if="isSearching"
            type="button"
            class="pages-list-search-clear"
            @click="clearSearch"
            title="Clear filter"
            aria-label="Clear filter"
          >×</button>
        </div>
        <div class="pages-list-type-filters" role="group" aria-label="Filter by page type">
          <button
            v-for="f in typeFilters"
            :key="f.id"
            type="button"
            class="pages-list-type-btn"
            :class="{ 'is-active': typeFilter === f.id }"
            @click="setTypeFilter(f.id)"
          >{{ f.label }}</button>
        </div>
        <label class="pages-list-order">
          <span class="pages-list-order-label">sort</span>
          <select v-model="orderBy" @change="onOrderChange" :disabled="isSearching">
            <option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="loading">Loading pages…</div>
      <div v-else-if="error" class="form-error">{{ error }}</div>
      <div v-else-if="!pages.length" class="empty-state">
        <span v-if="isSearching">No pages match "{{ searchQuery.trim() }}".</span>
        <span v-else>No pages yet.</span>
      </div>

      <ul v-else class="pages-list">
        <li v-for="page in pages" :key="page.uuid">
          <a :href="pageUrl(page)" class="pages-list-row">
            <span class="pages-list-title">
              <span v-if="page.favorited" class="pages-list-star" aria-hidden="true">★</span>
              {{ displayTitle(page) }}
            </span>
            <span class="pages-list-meta">
              <span class="page-type-badge">{{ page.page_type }}</span>
              <span class="pages-list-modified" :title="'last modified ' + formatModified(page)">{{ formatModified(page) }}</span>
            </span>
          </a>
        </li>
      </ul>

      <div v-if="!loading && hasMore" class="pages-list-more">
        <button
          type="button"
          class="btn"
          @click="loadMore"
          :disabled="loadingMore"
        >{{ loadingMore ? "loading…" : "load more" }}</button>
      </div>
    </div>
  `,
};

window.PagesListPage = PagesListPage;
