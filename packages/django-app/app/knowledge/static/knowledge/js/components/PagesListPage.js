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

      // Trash (issue #122) — a tab alongside the page-type filters
      // rather than its own page/nav entry, since it's really just
      // another way of listing pages (plus blocks, which is why it
      // gets its own data bucket instead of reusing `pages`).
      trash: { pages: [], blocks: [] },
      restoringUuids: [],
      // Separate from `error` on purpose: `error` gates the whole
      // loading/error/content v-else-if chain, so reusing it for a
      // single failed restore would blank out the rest of the trash
      // list behind the message instead of just flagging that one row.
      restoreError: null,
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
        { id: "trash", label: "trash" },
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
      if (this.typeFilter === "trash") {
        const count = this.trash.pages.length + this.trash.blocks.length;
        return `${count} item${count === 1 ? "" : "s"}`;
      }
      if (this.isSearching) {
        return `${this.pages.length} match${this.pages.length === 1 ? "" : "es"}`;
      }
      return `${this.totalCount} page${this.totalCount === 1 ? "" : "s"}`;
    },
  },

  async mounted() {
    await this.reload();
    // Deleting a page/block anywhere in the app dispatches this; only
    // matters here while the trash tab is the active view.
    this.handleTrashChanged = () => {
      if (this.typeFilter === "trash") this.reload();
    };
    document.addEventListener("trash:changed", this.handleTrashChanged);
  },

  beforeUnmount() {
    if (this.searchTimeout) clearTimeout(this.searchTimeout);
    if (this.handleTrashChanged) {
      document.removeEventListener("trash:changed", this.handleTrashChanged);
    }
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
      this.restoreError = null;
      const seq = ++this.requestSeq;
      try {
        if (this.typeFilter === "trash") {
          const result = await window.apiService.getTrash();
          if (seq !== this.requestSeq) return;
          if (result && result.success) {
            this.trash = {
              pages: result.data?.pages || [],
              blocks: result.data?.blocks || [],
            };
            this.hasMore = false;
          } else {
            this.error = "failed to load trash";
          }
          return;
        }
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
        this.error =
          this.typeFilter === "trash"
            ? "failed to load trash"
            : "failed to load pages";
      } finally {
        if (seq === this.requestSeq) this.loading = false;
      }
    },

    formatDeletedAt(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (isNaN(d.getTime())) return "";
      return d.toLocaleDateString();
    },

    truncateContent(content, maxLength = 80) {
      if (!content) return "";
      return content.length > maxLength
        ? content.substring(0, maxLength) + "…"
        : content;
    },

    // Pulls the first message out of a DRF-style {field: [messages]}
    // errors object — restore can fail with a specific, useful reason
    // (e.g. "this block's page is also in Trash — restore the page
    // first"), attached to whichever field's clean_*() raised it, not
    // always non_field_errors. Falls back to a generic message when
    // the response carries nothing usable.
    firstErrorMessage(result, fallback) {
      const errors = result && result.errors;
      if (errors && typeof errors === "object") {
        for (const key of Object.keys(errors)) {
          const messages = errors[key];
          if (Array.isArray(messages) && messages.length) {
            return messages[0];
          }
        }
      }
      return fallback;
    },

    async onRestorePage(page) {
      if (this.restoringUuids.includes(page.uuid)) return;
      this.restoringUuids.push(page.uuid);
      this.restoreError = null;
      try {
        const result = await window.apiService.restorePage(page.uuid);
        if (result.success) {
          this.trash.pages = this.trash.pages.filter(
            (p) => p.uuid !== page.uuid
          );
          document.dispatchEvent(new CustomEvent("favorites:changed"));
        } else {
          this.restoreError = this.firstErrorMessage(
            result,
            "failed to restore page"
          );
        }
      } catch (err) {
        console.error("failed to restore page:", err);
        this.restoreError = "failed to restore page";
      } finally {
        this.restoringUuids = this.restoringUuids.filter(
          (u) => u !== page.uuid
        );
      }
    },

    async onRestoreBlock(block) {
      if (this.restoringUuids.includes(block.uuid)) return;
      this.restoringUuids.push(block.uuid);
      this.restoreError = null;
      try {
        const result = await window.apiService.restoreBlock(block.uuid);
        if (result.success) {
          this.trash.blocks = this.trash.blocks.filter(
            (b) => b.uuid !== block.uuid
          );
        } else {
          this.restoreError = this.firstErrorMessage(
            result,
            "failed to restore block"
          );
        }
      } catch (err) {
        console.error("failed to restore block:", err);
        this.restoreError = "failed to restore block";
      } finally {
        this.restoringUuids = this.restoringUuids.filter(
          (u) => u !== block.uuid
        );
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
        <div v-if="typeFilter !== 'trash'" class="pages-list-search">
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
        <label v-if="typeFilter !== 'trash'" class="pages-list-order">
          <span class="pages-list-order-label">sort</span>
          <select v-model="orderBy" @change="onOrderChange" :disabled="isSearching">
            <option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="loading">{{ typeFilter === 'trash' ? 'Loading trash…' : 'Loading pages…' }}</div>
      <div v-else-if="error" class="form-error">{{ error }}</div>

      <template v-else-if="typeFilter === 'trash'">
        <div v-if="restoreError" class="form-error pages-list-trash-error">
          {{ restoreError }}
          <button
            type="button"
            class="pages-list-trash-error-dismiss"
            @click="restoreError = null"
            aria-label="Dismiss"
          >×</button>
        </div>
        <div v-if="!trash.pages.length && !trash.blocks.length" class="empty-state">
          Trash is empty. Deleted pages and blocks show up here for 30 days.
        </div>
        <template v-else>
          <div v-if="trash.pages.length" class="pages-list-trash-section">
            <h2 class="pages-list-trash-heading">pages</h2>
            <ul class="pages-list">
              <li v-for="page in trash.pages" :key="page.uuid">
                <div class="pages-list-trash-row">
                  <span class="pages-list-trash-label" :title="page.title">
                    {{ displayTitle(page) }}
                    <span class="pages-list-trash-meta">deleted {{ formatDeletedAt(page.deleted_at) }}</span>
                  </span>
                  <button
                    type="button"
                    class="pages-list-trash-restore"
                    :disabled="restoringUuids.includes(page.uuid)"
                    @click="onRestorePage(page)"
                    title="Restore this page"
                  >restore</button>
                </div>
              </li>
            </ul>
          </div>

          <div v-if="trash.blocks.length" class="pages-list-trash-section">
            <h2 class="pages-list-trash-heading">blocks</h2>
            <ul class="pages-list">
              <li v-for="block in trash.blocks" :key="block.uuid">
                <div class="pages-list-trash-row">
                  <span class="pages-list-trash-label" :title="block.content">
                    {{ truncateContent(block.content || '(empty block)') }}
                    <span class="pages-list-trash-meta">on {{ block.page_title || 'untitled page' }} · deleted {{ formatDeletedAt(block.deleted_at) }}</span>
                  </span>
                  <button
                    type="button"
                    class="pages-list-trash-restore"
                    :disabled="restoringUuids.includes(block.uuid)"
                    @click="onRestoreBlock(block)"
                    title="Restore this block"
                  >restore</button>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </template>

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
