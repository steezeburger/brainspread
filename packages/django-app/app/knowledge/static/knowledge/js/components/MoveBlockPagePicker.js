// MoveBlockPagePicker — modal page picker used by the block context-menu
// "move to page..." action. Reuses the spotlight CSS so the search UX
// matches the rest of the app, but stays a separate component so it
// owns its own state and doesn't tangle with the global spotlight.
//
// Emits:
//   select({uuid, title, slug})  — user picked a page
//   cancel                       — user dismissed
window.MoveBlockPagePicker = {
  name: "MoveBlockPagePicker",
  props: {
    isOpen: { type: Boolean, default: false },
    // Optional: pages we should exclude from results (e.g. the source
    // page — moving to where the block already lives is a no-op).
    excludePageUuids: { type: Array, default: () => [] },
  },
  emits: ["select", "cancel"],
  data() {
    return {
      query: "",
      results: [],
      loading: false,
      selectedIndex: 0,
      searchToken: 0,
      searchTimer: null,
    };
  },
  watch: {
    isOpen(open) {
      if (open) {
        this.query = "";
        this.results = [];
        this.selectedIndex = 0;
        this.$nextTick(() => this.$refs.searchInput?.focus());
        this.runSearch();
      } else {
        if (this.searchTimer) clearTimeout(this.searchTimer);
      }
    },
  },
  methods: {
    onQueryInput(event) {
      this.query = event.target.value;
      this.selectedIndex = 0;
      if (this.searchTimer) clearTimeout(this.searchTimer);
      this.searchTimer = setTimeout(() => this.runSearch(), 120);
    },

    async runSearch() {
      const myToken = ++this.searchToken;
      this.loading = true;
      try {
        // Empty query: show user's recent pages (favorites endpoint
        // returns the user's starred pages; if they have none we
        // fall back to letting the user type a name).
        const q = this.query.trim();
        const result = q
          ? await window.apiService.searchPages(q, 15)
          : await window.apiService.getFavoritedPages();
        if (myToken !== this.searchToken) return;
        if (result && result.success) {
          const pages = q ? result.data?.pages || [] : result.data?.pages || [];
          this.results = pages.filter(
            (p) => !this.excludePageUuids.includes(p.uuid)
          );
        } else {
          this.results = [];
        }
      } catch (err) {
        console.error("page search failed:", err);
        if (myToken === this.searchToken) this.results = [];
      } finally {
        if (myToken === this.searchToken) this.loading = false;
      }
    },

    onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        this.$emit("cancel");
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (this.results.length) {
          this.selectedIndex = (this.selectedIndex + 1) % this.results.length;
        }
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (this.results.length) {
          this.selectedIndex =
            (this.selectedIndex - 1 + this.results.length) %
            this.results.length;
        }
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const picked = this.results[this.selectedIndex];
        if (picked) this.$emit("select", picked);
      }
    },

    onResultClick(index) {
      const picked = this.results[index];
      if (picked) this.$emit("select", picked);
    },

    onOverlayClick(event) {
      if (event.target === event.currentTarget) this.$emit("cancel");
    },
  },
  template: `
    <div
      v-if="isOpen"
      class="spotlight-overlay"
      @click="onOverlayClick"
    >
      <div class="spotlight-modal" role="dialog" aria-label="Move block to page">
        <div class="spotlight-header">
          <div class="spotlight-search-container">
            <svg class="spotlight-search-icon" width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M9 17a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM19 19l-4.35-4.35" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <input
              ref="searchInput"
              type="text"
              class="spotlight-search-input"
              placeholder="move to page..."
              :value="query"
              @input="onQueryInput"
              @keydown="onKeydown"
            />
            <div class="spotlight-shortcut"><kbd>esc</kbd></div>
          </div>
        </div>

        <div class="spotlight-content">
          <div v-if="loading" class="spotlight-loading">
            <div class="loading-spinner"></div>
            <span>Searching…</span>
          </div>
          <div v-else-if="query && !results.length" class="spotlight-no-results">
            <p>No pages match "<strong>{{ query }}</strong>"</p>
          </div>
          <div v-else-if="!query && !results.length" class="spotlight-no-results">
            <p>Type a page title to search.</p>
          </div>
          <div v-else class="spotlight-results">
            <div
              v-for="(page, index) in results"
              :key="page.uuid"
              class="spotlight-result"
              :class="{ selected: index === selectedIndex }"
              @click.stop="onResultClick(index)"
            >
              <div class="spotlight-result-icon">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3z" stroke="currentColor" stroke-width="1.5" fill="none"/>
                  <path d="M5 6h6M5 8h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </div>
              <div class="spotlight-result-content">
                <div class="spotlight-result-title">{{ page.title }}</div>
                <div class="spotlight-result-path">/{{ page.slug }}</div>
              </div>
              <div v-if="page.page_type && page.page_type !== 'page'" class="spotlight-result-type">
                {{ page.page_type }}
              </div>
            </div>
          </div>
        </div>

        <div class="spotlight-footer">
          <div class="spotlight-shortcuts">
            <div class="spotlight-shortcut-item">
              <kbd>↑</kbd><kbd>↓</kbd> to navigate
            </div>
            <div class="spotlight-shortcut-item"><kbd>enter</kbd> to move</div>
            <div class="spotlight-shortcut-item"><kbd>esc</kbd> to close</div>
          </div>
        </div>
      </div>
    </div>
  `,
};
