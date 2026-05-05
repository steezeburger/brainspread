window.LeftNav = {
  props: {
    user: {
      type: Object,
      default: null,
    },
  },

  emits: [
    "navigate-to-slug",
    "open-search",
    "create-page",
    "create-whiteboard",
    "navigate-graph",
    "navigate-today",
    "open-settings",
    "open-help",
    "logout",
  ],

  data() {
    const isMobile = typeof window !== "undefined" && window.innerWidth <= 768;
    // Persist the open/closed pref so a refresh doesn't blow away the
    // user's choice. First visit (no saved value) still defaults to
    // open on desktop, closed on mobile.
    let isOpen = !isMobile;
    try {
      const saved =
        typeof window !== "undefined" && window.localStorage
          ? window.localStorage.getItem("brainspread.leftNavOpen")
          : null;
      if (saved === "1") isOpen = true;
      else if (saved === "0") isOpen = false;
    } catch (_) {
      // localStorage can throw in private mode / disabled-cookie setups.
      // Fall back to the viewport default.
    }
    let favoritesExpanded = true;
    try {
      const savedFavExpanded =
        typeof window !== "undefined" && window.localStorage
          ? window.localStorage.getItem("brainspread.leftNavFavoritesExpanded")
          : null;
      if (savedFavExpanded === "0") favoritesExpanded = false;
    } catch (_) {
      // ignore localStorage failures
    }
    return {
      historicalData: null,
      loading: false,
      error: null,
      daysBack: 30,
      limit: 25,
      isOpen,
      width: 320,
      isResizing: false,
      minWidth: 240,
      maxWidth: 800,
      recentExpanded: true,
      favorites: [],
      favoritesLoading: false,
      favoritesError: null,
      favoritesExpanded,
    };
  },

  computed: {
    shortcutHint() {
      const isMac =
        typeof navigator !== "undefined" &&
        /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
      return isMac ? "⌘K" : "Ctrl+K";
    },
    todaySlug() {
      const today = new Date();
      const year = today.getFullYear();
      const month = String(today.getMonth() + 1).padStart(2, "0");
      const day = String(today.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    },
    todayHref() {
      return this.pageUrl(this.todaySlug);
    },
  },

  mounted() {
    this.loadHistoricalData();
    this.loadFavorites();
    this.setupResizeListener();
    // The page header dispatches this when a user stars/unstars the
    // current page so the Favorites list refreshes without a reload.
    this.handleFavoritesChanged = () => this.loadFavorites();
    document.addEventListener("favorites:changed", this.handleFavoritesChanged);
    // Close the nav when the user clicks outside it. Mobile already
    // handles this via the backdrop overlay; this covers desktop. The
    // listener is attached/detached by the isOpen watcher so the click
    // that opens the nav doesn't immediately close it.
    this.handleOutsideClick = (event) => {
      if (this.$el && this.$el.contains(event.target)) return;
      this.toggleSidebar();
    };
    if (this.isOpen) {
      this.attachOutsideClickHandler();
    }
  },

  beforeUnmount() {
    this.removeResizeListener();
    if (this.handleFavoritesChanged) {
      document.removeEventListener(
        "favorites:changed",
        this.handleFavoritesChanged
      );
    }
    this.detachOutsideClickHandler();
  },

  watch: {
    isOpen(value) {
      if (value) {
        this.attachOutsideClickHandler();
      } else {
        this.detachOutsideClickHandler();
      }
    },
  },

  methods: {
    async loadHistoricalData() {
      this.loading = true;
      this.error = null;

      try {
        const result = await window.apiService.getHistoricalData(
          this.daysBack,
          this.limit
        );

        if (result.success) {
          this.historicalData = result.data;
        } else {
          this.error = "failed to load historical data";
        }
      } catch (error) {
        console.error("error loading historical data:", error);
        this.error = error.message || "failed to load historical data";
      } finally {
        this.loading = false;
      }
    },

    async updateFilter() {
      await this.loadHistoricalData();
    },

    toggleSidebar() {
      this.isOpen = !this.isOpen;
      try {
        if (typeof window !== "undefined" && window.localStorage) {
          window.localStorage.setItem(
            "brainspread.leftNavOpen",
            this.isOpen ? "1" : "0"
          );
        }
      } catch (_) {
        // localStorage can throw in private mode; the toggle still
        // works for the current session, just won't persist.
      }
    },

    attachOutsideClickHandler() {
      // Defer so the click that just opened the nav (the rail toggle
      // click) finishes bubbling before we start listening — otherwise
      // that same click would close the nav we just opened.
      setTimeout(() => {
        if (!this.isOpen) return;
        document.addEventListener("click", this.handleOutsideClick);
      }, 0);
    },

    detachOutsideClickHandler() {
      document.removeEventListener("click", this.handleOutsideClick);
    },

    toggleRecent() {
      this.recentExpanded = !this.recentExpanded;
    },

    toggleFavorites() {
      this.favoritesExpanded = !this.favoritesExpanded;
      try {
        if (typeof window !== "undefined" && window.localStorage) {
          window.localStorage.setItem(
            "brainspread.leftNavFavoritesExpanded",
            this.favoritesExpanded ? "1" : "0"
          );
        }
      } catch (_) {
        // localStorage can throw in private mode; toggle still works for
        // the current session.
      }
    },

    async loadFavorites() {
      this.favoritesLoading = true;
      this.favoritesError = null;
      try {
        const result = await window.apiService.getFavoritedPages();
        if (result.success) {
          this.favorites = result.data?.pages || [];
        } else {
          this.favoritesError = "failed to load favorites";
        }
      } catch (error) {
        console.error("error loading favorites:", error);
        this.favoritesError = error.message || "failed to load favorites";
      } finally {
        this.favoritesLoading = false;
      }
    },

    formatDate(dateString) {
      return new Date(dateString).toLocaleDateString();
    },

    formatDailyPageDate(dateString) {
      const parts = dateString.split("-");
      if (parts.length === 3) {
        const year = parseInt(parts[0]);
        const month = parseInt(parts[1]) - 1;
        const day = parseInt(parts[2]);
        return new Date(year, month, day).toLocaleDateString();
      }
      return new Date(dateString).toLocaleDateString();
    },

    formatPageTitle(page) {
      if (page.page_type === "daily") {
        return this.formatDailyPageDate(page.title);
      }
      return page.title;
    },

    formatTime(dateString) {
      return new Date(dateString).toLocaleTimeString();
    },

    truncateContent(content, maxLength = 100) {
      if (!content) return "";
      return content.length > maxLength
        ? content.substring(0, maxLength) + "..."
        : content;
    },

    setupResizeListener() {
      this.resizeHandler = (e) => this.handleMouseMove(e);
      this.stopResizeHandler = () => this.stopResize();
    },

    removeResizeListener() {
      if (this.resizeHandler) {
        document.removeEventListener("mousemove", this.resizeHandler);
        document.removeEventListener("mouseup", this.stopResizeHandler);
      }
    },

    startResize(e) {
      this.isResizing = true;
      this.startX = e.clientX;
      this.startWidth = this.width;

      document.addEventListener("mousemove", this.resizeHandler);
      document.addEventListener("mouseup", this.stopResizeHandler);

      e.preventDefault();
    },

    handleMouseMove(e) {
      if (!this.isResizing) return;

      const deltaX = e.clientX - this.startX;
      const newWidth = this.startWidth + deltaX;

      const isMobile = window.innerWidth <= 768;
      const effectiveMaxWidth = isMobile ? window.innerWidth : this.maxWidth;

      if (newWidth >= this.minWidth && newWidth <= effectiveMaxWidth) {
        this.width = newWidth;
      }
    },

    stopResize() {
      this.isResizing = false;
      document.removeEventListener("mousemove", this.resizeHandler);
      document.removeEventListener("mouseup", this.stopResizeHandler);
    },

    pageUrl(slug) {
      return `/knowledge/page/${encodeURIComponent(slug)}/`;
    },

    shouldDeferToBrowser(event) {
      if (!event) return false;
      if (event.defaultPrevented) return true;
      if (event.button !== undefined && event.button !== 0) return true;
      return !!(
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      );
    },

    handleNavClick(event, slug) {
      if (this.shouldDeferToBrowser(event)) return;
      event.preventDefault();
      this.$emit("navigate-to-slug", slug);
    },

    onTodayClick(event) {
      if (this.shouldDeferToBrowser(event)) return;
      event.preventDefault();
      this.$emit("navigate-today");
    },

    onGraphClick(event) {
      if (this.shouldDeferToBrowser(event)) return;
      event.preventDefault();
      this.$emit("navigate-graph");
    },

    onSearchClick() {
      this.$emit("open-search");
    },

    onCreatePageClick() {
      this.$emit("create-page");
    },

    onCreateWhiteboardClick() {
      this.$emit("create-whiteboard");
    },

    onSettingsClick() {
      this.$emit("open-settings");
    },

    onHelpClick() {
      this.$emit("open-help");
    },

    onLogoutClick() {
      this.$emit("logout");
    },

    handleFooterKeydown(event) {
      const items = Array.from(
        this.$el.querySelectorAll(".leftnav-footer .leftnav-item")
      );
      if (!items.length) return;
      const currentIndex = items.indexOf(document.activeElement);

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          items[Math.min(currentIndex + 1, items.length - 1)].focus();
          break;
        case "ArrowUp":
          event.preventDefault();
          items[Math.max(currentIndex - 1, 0)].focus();
          break;
      }
    },

    async toggleBlockTodo(block, event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }

      try {
        const result = await window.apiService.toggleBlockTodo(block.uuid);
        if (result.success) {
          block.block_type = result.data.block_type;
          block.content = result.data.content;
        }
      } catch (error) {
        console.error("error toggling todo:", error);
      }
    },

    formatContentWithTags(content, blockType = null) {
      if (!content) return "";

      let formatted = content;

      if (
        blockType &&
        ["todo", "doing", "done", "later", "wontdo"].includes(blockType)
      ) {
        formatted = formatted.replace(
          /^(WONTDO|LATER|DOING|DONE|TODO)\s*:?\s*/i,
          ""
        );
      }

      const codeSegments = [];
      formatted = formatted.replace(/`([^`]+)`/g, (_match, code) => {
        const idx = codeSegments.length;
        codeSegments.push(code);
        return `\x00CODE${idx}\x00`;
      });

      const escapedChars = [];
      formatted = formatted.replace(/\\([*_~`\\#>])/g, (_match, char) => {
        const idx = escapedChars.length;
        escapedChars.push(char);
        return `\x00ESC${idx}\x00`;
      });

      const linkSegments = [];
      formatted = formatted.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        (_match, text, url) => {
          const idx = linkSegments.length;
          linkSegments.push({ text, url });
          return `\x00LINK${idx}\x00`;
        }
      );

      formatted = formatted.replace(
        /^>\s?(.+)/gm,
        '<span class="markdown-quote">$1</span>'
      );

      formatted = formatted.replace(
        /\*\*\*(.+?)\*\*\*/g,
        '<span class="markdown-bold-italic">$1</span>'
      );
      formatted = formatted.replace(
        /\*\*(.+?)\*\*/g,
        '<span class="markdown-bold">$1</span>'
      );
      formatted = formatted.replace(
        /__(.+?)__/g,
        '<span class="markdown-bold">$1</span>'
      );
      formatted = formatted.replace(
        /\*([^*]+?)\*/g,
        '<span class="markdown-italic">$1</span>'
      );
      formatted = formatted.replace(
        /_([^_]+?)_/g,
        '<span class="markdown-italic">$1</span>'
      );
      formatted = formatted.replace(
        /~~(.+?)~~/g,
        '<span class="markdown-strikethrough">$1</span>'
      );
      formatted = formatted.replace(
        /==(.+?)==/g,
        '<span class="markdown-highlight">$1</span>'
      );

      codeSegments.forEach((code, idx) => {
        const safeCode = code
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
        formatted = formatted
          .split(`\x00CODE${idx}\x00`)
          .join(`<code class="markdown-code">${safeCode}</code>`);
      });

      formatted = formatted.replace(
        /(^|[\s(])((?:https?:\/\/|www\.)[^\s<>"]+[^\s<>".,;:!?)])/g,
        (_match, lead, url) => {
          const safe = this.safeUrl(url);
          if (!safe) return _match;
          return `${lead}<a class="markdown-link" href="${this.escapeAttr(safe)}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(url)}</a>`;
        }
      );

      linkSegments.forEach(({ text, url }, idx) => {
        const safe = this.safeUrl(url);
        const replacement = safe
          ? `<a class="markdown-link" href="${this.escapeAttr(safe)}" target="_blank" rel="noopener noreferrer">${text}</a>`
          : `[${text}](${this.escapeHtml(url)})`;
        formatted = formatted.split(`\x00LINK${idx}\x00`).join(replacement);
      });

      formatted = formatted.replace(
        /#([a-zA-Z0-9_-]+)/g,
        (_m, tag) =>
          `<a class="inline-tag clickable-tag" href="${this.escapeAttr(
            this.pageUrl(tag)
          )}" data-tag="${tag}">#${tag}</a>`
      );

      escapedChars.forEach((char, idx) => {
        formatted = formatted.split(`\x00ESC${idx}\x00`).join(char);
      });

      return formatted;
    },

    safeUrl(rawUrl) {
      if (!rawUrl) return null;
      const trimmed = String(rawUrl).trim();
      if (!trimmed) return null;
      if (/^(javascript|data|vbscript|file):/i.test(trimmed)) return null;
      if (/^www\./i.test(trimmed)) return "https://" + trimmed;
      if (/^(https?:|mailto:|tel:|\/|#)/i.test(trimmed)) return trimmed;
      if (/^[a-z0-9.-]+\.[a-z]{2,}/i.test(trimmed)) return "https://" + trimmed;
      return null;
    },

    escapeAttr(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    },

    escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    },

    handleTagClick(event) {
      const tagName = event.target.getAttribute("data-tag");
      if (!tagName) return;
      event.stopPropagation();
      if (this.shouldDeferToBrowser(event)) return;
      event.preventDefault();
      this.$emit("navigate-to-slug", tagName);
    },
  },

  template: `
    <div class="leftnav-container" :class="{ 'is-open': isOpen, 'is-collapsed': !isOpen }">
      <!-- Backdrop for mobile drawer (CSS hides on desktop). -->
      <div
        v-if="isOpen"
        class="leftnav-backdrop"
        @click="toggleSidebar"
        aria-hidden="true"
      ></div>

      <!-- Collapsed rail. CSS collapses extras on mobile so only the toggle
           is visible. -->
      <aside
        v-if="!isOpen"
        class="leftnav-rail"
        aria-label="Collapsed primary navigation"
      >
        <button
          type="button"
          class="leftnav-rail-btn leftnav-rail-toggle"
          @click="toggleSidebar"
          title="Open sidebar"
          aria-label="Open sidebar"
        >→</button>
        <button
          type="button"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onSearchClick"
          :title="'Search (' + shortcutHint + ')'"
          aria-label="Search"
        >⌕</button>
        <a
          :href="todayHref"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onTodayClick"
          @auxclick="onTodayClick"
          title="Today"
          aria-label="Today"
        >▤</a>
        <button
          type="button"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onCreatePageClick"
          title="New page"
          aria-label="New page"
        >+</button>
        <a
          href="/knowledge/graph/"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onGraphClick"
          @auxclick="onGraphClick"
          title="Graph"
          aria-label="Graph"
        >◉</a>
        <div class="leftnav-rail-spacer leftnav-rail-action"></div>
        <button
          type="button"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onSettingsClick"
          title="Settings"
          aria-label="Settings"
        >⚙</button>
        <button
          type="button"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onHelpClick"
          title="Help"
          aria-label="Help"
        >?</button>
        <button
          type="button"
          class="leftnav-rail-btn leftnav-rail-action"
          @click="onLogoutClick"
          title="Logout"
          aria-label="Logout"
        >⏻</button>
      </aside>

      <!-- Sidebar -->
      <aside
        v-if="isOpen"
        class="leftnav historical-sidebar"
        :style="{ width: width + 'px' }"
        aria-label="Primary navigation"
      >
        <!-- Resize Handle -->
        <div
          class="sidebar-resize-handle"
          @mousedown="startResize"
          :class="{ resizing: isResizing }"
        ></div>

        <div class="leftnav-content">
          <!-- Brand -->
          <a href="/knowledge/" class="leftnav-brand brand-link">brainspread</a>

          <!-- Header -->
          <div class="leftnav-header">
            <button
              @click="toggleSidebar"
              class="leftnav-collapse-btn"
              title="Collapse sidebar"
              aria-label="Collapse sidebar"
            >←</button>
            <button
              @click="onSearchClick"
              class="leftnav-search"
              title="Search and commands"
              aria-label="Open search"
            >
              <span class="leftnav-search-label">search</span>
              <kbd class="leftnav-kbd">{{ shortcutHint }}</kbd>
            </button>
          </div>

          <!-- Primary nav -->
          <nav class="leftnav-section leftnav-primary" aria-label="Primary">
            <a
              :href="todayHref"
              class="leftnav-item"
              @click="onTodayClick"
              @auxclick="onTodayClick"
              title="Go to today's daily note"
            >
              <span class="leftnav-icon" aria-hidden="true">→</span>
              <span class="leftnav-label">today</span>
            </a>
            <button
              type="button"
              class="leftnav-item"
              @click="onCreatePageClick"
              title="Create a new page"
            >
              <span class="leftnav-icon" aria-hidden="true">+</span>
              <span class="leftnav-label">new page</span>
            </button>
            <button
              type="button"
              class="leftnav-item"
              @click="onCreateWhiteboardClick"
              title="Create a new whiteboard"
            >
              <span class="leftnav-icon" aria-hidden="true">✎</span>
              <span class="leftnav-label">new whiteboard</span>
            </button>
            <a
              href="/knowledge/graph/"
              class="leftnav-item"
              @click="onGraphClick"
              @auxclick="onGraphClick"
              title="View the knowledge graph"
            >
              <span class="leftnav-icon" aria-hidden="true">◉</span>
              <span class="leftnav-label">graph</span>
            </a>
          </nav>

          <!-- Favorites (collapsible) -->
          <section class="leftnav-section leftnav-favorites" aria-label="Favorites">
            <button
              type="button"
              class="leftnav-section-toggle"
              @click="toggleFavorites"
              :aria-expanded="favoritesExpanded"
            >
              <span class="leftnav-chevron" :class="{ open: favoritesExpanded }" aria-hidden="true">▸</span>
              <span>favorites</span>
              <span v-if="favorites.length" class="leftnav-section-count">{{ favorites.length }}</span>
            </button>

            <div v-if="favoritesExpanded" class="leftnav-favorites-body">
              <div v-if="favoritesLoading" class="sidebar-loading">
                Loading...
              </div>
              <div v-else-if="favoritesError" class="sidebar-error">
                {{ favoritesError }}
              </div>
              <div v-else-if="!favorites.length" class="leftnav-empty">
                No favorites yet. Star a page from its menu.
              </div>
              <div v-else class="leftnav-favorites-list">
                <a
                  v-for="page in favorites"
                  :key="page.uuid"
                  :href="pageUrl(page.slug)"
                  class="leftnav-item leftnav-favorite-item"
                  @click="handleNavClick($event, page.slug)"
                  @auxclick="handleNavClick($event, page.slug)"
                  :title="'Open ' + page.title"
                >
                  <span class="leftnav-icon" aria-hidden="true">★</span>
                  <span class="leftnav-label">{{ formatPageTitle(page) }}</span>
                </a>
              </div>
            </div>
          </section>

          <!-- Recent (collapsible) -->
          <section class="leftnav-section leftnav-recent" aria-label="Recent">
            <button
              type="button"
              class="leftnav-section-toggle"
              @click="toggleRecent"
              :aria-expanded="recentExpanded"
            >
              <span class="leftnav-chevron" :class="{ open: recentExpanded }" aria-hidden="true">▸</span>
              <span>recent</span>
            </button>

            <div v-if="recentExpanded" class="leftnav-recent-body">
              <div class="filter-controls">
                <label>
                  Days:
                  <select v-model="daysBack" @change="updateFilter">
                    <option value="7">7</option>
                    <option value="30">30</option>
                    <option value="90">90</option>
                  </select>
                </label>
                <label>
                  Limit:
                  <select v-model="limit" @change="updateFilter">
                    <option value="15">15</option>
                    <option value="25">25</option>
                    <option value="50">50</option>
                  </select>
                </label>
              </div>

              <div v-if="loading" class="sidebar-loading">
                Loading...
              </div>

              <div v-else-if="error" class="sidebar-error">
                {{ error }}
              </div>

              <div v-else-if="historicalData" class="sidebar-data">
                <div class="date-range">
                  {{ formatDate(historicalData.date_range.start) }} -
                  {{ formatDate(historicalData.date_range.end) }}
                </div>

                <!-- Recent Pages -->
                <div v-if="historicalData.pages && historicalData.pages.length" class="sidebar-section">
                  <h4>Recent Pages ({{ historicalData.pages.length }})</h4>
                  <div class="sidebar-items">
                    <a
                      v-for="page in historicalData.pages"
                      :key="page.uuid"
                      :href="pageUrl(page.slug)"
                      class="sidebar-item page-item clickable"
                      @click="handleNavClick($event, page.slug)"
                      @auxclick="handleNavClick($event, page.slug)"
                      :title="'Click to open ' + page.title + ' (Cmd/Ctrl-click for new tab)'"
                    >
                      <div class="page-card-vertical">
                        <div class="page-header-row">
                          <div class="item-title">{{ formatPageTitle(page) }}</div>
                          <div class="item-type">{{ page.page_type }}</div>
                        </div>

                        <div v-if="page.page_type !== 'daily'" class="page-date-row">
                          <div class="item-date">{{ formatDate(page.modified_at || page.created_at) }}</div>
                        </div>

                        <div v-if="page.recent_blocks && page.recent_blocks.length" class="page-content-rows" @click="handleTagClick">
                          <div v-for="block in page.recent_blocks.slice(0, 2)" :key="block.uuid" class="block-preview" :class="{ 'completed': block.block_type === 'done' }" v-html="formatContentWithTags(truncateContent(block.content, 60), block.block_type)">
                          </div>
                        </div>
                      </div>
                    </a>
                  </div>
                </div>

                <!-- Recent Blocks -->
                <div v-if="historicalData.blocks && historicalData.blocks.length" class="sidebar-section">
                  <h4>Recent Blocks ({{ historicalData.blocks.length }})</h4>
                  <div class="sidebar-items">
                    <a
                      v-for="block in historicalData.blocks"
                      :key="block.uuid"
                      :href="pageUrl(block.page_slug)"
                      class="sidebar-item block-item clickable"
                      @click="handleNavClick($event, block.page_slug)"
                      @auxclick="handleNavClick($event, block.page_slug)"
                      :title="'Click to open ' + block.page_title + ' (Cmd/Ctrl-click for new tab)'"
                    >
                      <div class="item-header">
                        <span class="item-page">{{ block.page_title }}</span>
                      </div>
                      <div class="item-meta">{{ formatTime(block.modified_at || block.created_at) }}</div>
                      <div class="item-content-row" @click="handleTagClick">
                        <span
                          v-if="block.block_type === 'todo' || block.block_type === 'doing' || block.block_type === 'done'"
                          @click="toggleBlockTodo(block, $event)"
                          :class="['block-bullet', block.block_type]"
                          :title="'Toggle ' + (block.block_type === 'done' ? 'undone' : 'done')"
                        >
                          <span v-if="block.block_type === 'doing'">◐</span>
                          <span v-else>{{ block.block_type === 'done' ? '☑' : '☐' }}</span>
                        </span>
                        <span class="item-content" :class="{ 'completed': block.block_type === 'done' }" v-html="formatContentWithTags(truncateContent(block.content, 100), block.block_type)"></span>
                      </div>
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- Footer -->
          <footer class="leftnav-footer" @keydown="handleFooterKeydown">
            <div v-if="user?.email" class="leftnav-user" :title="user.email">
              {{ user.email }}
            </div>
            <button type="button" class="leftnav-item" @click="onSettingsClick">
              <span class="leftnav-icon" aria-hidden="true">⚙</span>
              <span class="leftnav-label">settings</span>
            </button>
            <button type="button" class="leftnav-item" @click="onHelpClick">
              <span class="leftnav-icon" aria-hidden="true">?</span>
              <span class="leftnav-label">help</span>
            </button>
            <button type="button" class="leftnav-item" @click="onLogoutClick">
              <span class="leftnav-icon" aria-hidden="true">⏻</span>
              <span class="leftnav-label">logout</span>
            </button>
          </footer>
        </div>
      </aside>
    </div>
  `,
};
