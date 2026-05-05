// SpotlightSearch Component
window.SpotlightSearch = {
  props: {
    isOpen: {
      type: Boolean,
      default: false,
    },
    query: {
      type: String,
      default: "",
    },
    results: {
      type: Array,
      default: () => [],
    },
    loading: {
      type: Boolean,
      default: false,
    },
    selectedIndex: {
      type: Number,
      default: 0,
    },
  },

  emits: ["close", "query-changed", "navigate", "keydown"],

  watch: {
    isOpen(newValue) {
      if (newValue) {
        document.body.style.overflow = "hidden";
        this.$nextTick(() => {
          this.focusInput();
        });
      } else {
        document.body.style.overflow = "";
      }
    },
    selectedIndex() {
      this.scrollSelectedIntoView();
    },
    results() {
      this.$nextTick(() => this.scrollSelectedIntoView());
    },
  },

  methods: {
    focusInput() {
      const input = this.$refs.searchInput;
      if (input) {
        input.focus();
      }
    },

    handleOverlayClick(event) {
      if (event.target === event.currentTarget) {
        this.$emit("close");
      }
    },

    handleInputChange(event) {
      this.$emit("query-changed", event.target.value);
    },

    handleKeydown(event) {
      if (event.key === "Tab") {
        const modal = this.$el?.querySelector(".spotlight-modal");
        if (!modal) return;
        const focusable = Array.from(
          modal.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        );
        if (!focusable.length) return;
        if (focusable.length === 1) {
          event.preventDefault();
          focusable[0].focus();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
      this.$emit("keydown", event);
    },

    handleResultClick(index) {
      this.$emit("navigate", index);
    },

    scrollSelectedIntoView() {
      this.$nextTick(() => {
        const items = this.$el?.querySelectorAll(".spotlight-result");
        const selected = items && items[this.selectedIndex];
        if (!selected) return;
        selected.scrollIntoView({ block: "nearest" });
      });
    },

    highlightQuery(text, query) {
      if (!query || !text) return text;

      const regex = new RegExp(
        `(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`,
        "gi"
      );
      return text.replace(regex, "<mark>$1</mark>");
    },
  },

  template: `
    <div v-if="isOpen" class="spotlight-overlay" @click="handleOverlayClick">
      <div class="spotlight-modal">
        <div class="spotlight-header">
          <div class="spotlight-search-container">
            <svg class="spotlight-search-icon" width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M9 17a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM19 19l-4.35-4.35" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <input
              ref="searchInput"
              type="text"
              class="spotlight-search-input"
              placeholder="search pages..."
              :value="query"
              @input="handleInputChange"
              @keydown="handleKeydown"
            />
            <div class="spotlight-shortcut">
              <kbd>esc</kbd>
            </div>
          </div>
        </div>

        <div class="spotlight-content">
          <div v-if="loading" class="spotlight-loading">
            <div class="loading-spinner"></div>
            <span>Searching...</span>
          </div>

          <div v-else-if="query && results.length === 0" class="spotlight-no-results">
            <p>no results for "<strong>{{ query }}</strong>"</p>
          </div>

          <div v-else-if="results.length > 0" class="spotlight-results">
            <div
              v-for="(result, index) in results"
              :key="result.type === 'command' ? result.commandId : (result.type === 'block' ? result.blockUuid : result.slug)"
              class="spotlight-result"
              :class="{ 'selected': index === selectedIndex, 'spotlight-command': result.type === 'command' }"
              @click.stop="handleResultClick(index)"
            >
              <div class="spotlight-result-icon spotlight-command-icon" v-if="result.type === 'command'">
                {{ result.icon }}
              </div>
              <div class="spotlight-result-icon" v-else-if="result.type === 'block'">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <circle cx="3" cy="4.5" r="1" fill="currentColor"/>
                  <circle cx="3" cy="8" r="1" fill="currentColor"/>
                  <circle cx="3" cy="11.5" r="1" fill="currentColor"/>
                  <path d="M6 4.5h8M6 8h8M6 11.5h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </div>
              <div class="spotlight-result-icon" v-else-if="result.pageType === 'whiteboard'">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M2 3h12v10H2z" stroke="currentColor" stroke-width="1.5" fill="none"/>
                  <path d="M4 10l2-3 2 2 3-4 1 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                </svg>
              </div>
              <div class="spotlight-result-icon" v-else>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3z" stroke="currentColor" stroke-width="1.5" fill="none"/>
                  <path d="M5 6h6M5 8h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </div>
              <div class="spotlight-result-content">
                <div class="spotlight-result-title" v-html="highlightQuery(result.title, query)"></div>
                <div class="spotlight-result-snippet" v-if="result.type === 'command'">{{ result.description }}</div>
                <div class="spotlight-result-snippet" v-else-if="result.snippet" v-html="highlightQuery(result.snippet, query)"></div>
                <div class="spotlight-result-path" v-if="result.type === 'page'">{{ result.url }}</div>
                <div class="spotlight-result-path" v-else-if="result.type === 'block' && result.pageTitle">in {{ result.pageTitle }}</div>
              </div>
              <div class="spotlight-result-type" v-if="result.type === 'command'">command</div>
              <div class="spotlight-result-type" v-else-if="result.type === 'block'">block</div>
              <div class="spotlight-result-type" v-else-if="result.pageType && result.pageType !== 'page'">{{ result.pageType }}</div>
            </div>
          </div>
        </div>

        <div class="spotlight-footer">
          <div class="spotlight-shortcuts">
            <div class="spotlight-shortcut-item">
              <kbd>↑</kbd><kbd>↓</kbd> to navigate
            </div>
            <div class="spotlight-shortcut-item">
              <kbd>enter</kbd> to select
            </div>
            <div class="spotlight-shortcut-item">
              <kbd>esc</kbd> to close
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};
