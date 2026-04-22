window.HistoricalSidebar = {
  data() {
    return {
      historicalData: null,
      loading: false,
      error: null,
      daysBack: 30,
      limit: 25,
      isOpen: false,
      width: 400,
      isResizing: false,
      minWidth: 300,
      maxWidth: 800,
    };
  },

  mounted() {
    this.loadHistoricalData();
    this.setupResizeListener();
    this.setupClickOutsideListener();
  },

  beforeUnmount() {
    this.removeResizeListener();
    this.removeClickOutsideListener();
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
    },

    formatDate(dateString) {
      return new Date(dateString).toLocaleDateString();
    },

    formatDailyPageDate(dateString) {
      // For daily page dates, treat the date string as a local date to avoid timezone shifts
      // Parse the date string (YYYY-MM-DD format) as local date components
      const parts = dateString.split("-");
      if (parts.length === 3) {
        const year = parseInt(parts[0]);
        const month = parseInt(parts[1]) - 1; // Month is 0-indexed in Date constructor
        const day = parseInt(parts[2]);
        return new Date(year, month, day).toLocaleDateString();
      }
      // Fallback to regular date formatting if parsing fails
      return new Date(dateString).toLocaleDateString();
    },

    formatPageTitle(page) {
      // For daily pages, format the title (which is the date) prettily
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

    // Resize functionality
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
      const newWidth = this.startWidth + deltaX; // Add because dragging right should make left sidebar wider

      // On mobile (768px or less), limit width to 90% of viewport
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

    openPage(page) {
      // Emit event to parent component to navigate to this slug
      // All pages now use the unified /knowledge/page/{slug}/ pattern
      this.$emit("navigate-to-slug", page.slug);
    },

    openBlockPage(block) {
      // Navigate to the page containing this block
      // All pages now use the unified /knowledge/page/{slug}/ pattern
      this.$emit("navigate-to-slug", block.page_slug);
    },

    openTag(tagName) {
      // Navigate to the tag page
      this.$emit("navigate-to-slug", tagName);
    },

    async toggleBlockTodo(block, event) {
      // Prevent navigation to block page when clicking checkbox
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }

      try {
        const result = await window.apiService.toggleBlockTodo(block.uuid);
        if (result.success) {
          // Update the block's type in the local data without reloading
          // This prevents the sidebar from scrolling to the top
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

      // Strip todo-state prefix from display since the checkbox already shows state
      if (
        blockType &&
        ["todo", "done", "later", "wontdo"].includes(blockType)
      ) {
        formatted = formatted.replace(/^(WONTDO|LATER|DONE|TODO)\s*:?\s*/i, "");
      }

      // Extract backtick code spans first to protect them from other formatting
      const codeSegments = [];
      formatted = formatted.replace(/`([^`]+)`/g, (_match, code) => {
        const idx = codeSegments.length;
        codeSegments.push(code);
        return `\x00CODE${idx}\x00`;
      });

      // Extract backslash-escaped characters to protect them from formatting
      const escapedChars = [];
      formatted = formatted.replace(/\\([*_~`\\#>])/g, (_match, char) => {
        const idx = escapedChars.length;
        escapedChars.push(char);
        return `\x00ESC${idx}\x00`;
      });

      // Extract markdown links [text](url) before other transforms can munge
      // the brackets.
      const linkSegments = [];
      formatted = formatted.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        (_match, text, url) => {
          const idx = linkSegments.length;
          linkSegments.push({ text, url });
          return `\x00LINK${idx}\x00`;
        }
      );

      // Format lines starting with > as blockquotes
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

      // Restore escaped characters as literal text
      escapedChars.forEach((char, idx) => {
        formatted = formatted.split(`\x00ESC${idx}\x00`).join(char);
      });

      // Restore code spans as inline code elements
      codeSegments.forEach((code, idx) => {
        const safeCode = code
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
        formatted = formatted
          .split(`\x00CODE${idx}\x00`)
          .join(`<code class="markdown-code">${safeCode}</code>`);
      });

      // Linkify bare URLs (https://, http://, www.).
      formatted = formatted.replace(
        /(^|[\s(])((?:https?:\/\/|www\.)[^\s<>"]+[^\s<>".,;:!?)])/g,
        (_match, lead, url) => {
          const safe = this.safeUrl(url);
          if (!safe) return _match;
          return `${lead}<a class="markdown-link" href="${this.escapeAttr(safe)}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(url)}</a>`;
        }
      );

      // Restore markdown link placeholders as <a> tags.
      linkSegments.forEach(({ text, url }, idx) => {
        const safe = this.safeUrl(url);
        const replacement = safe
          ? `<a class="markdown-link" href="${this.escapeAttr(safe)}" target="_blank" rel="noopener noreferrer">${text}</a>`
          : `[${text}](${this.escapeHtml(url)})`;
        formatted = formatted.split(`\x00LINK${idx}\x00`).join(replacement);
      });

      // Replace hashtags with clickable styled spans
      return formatted.replace(
        /#([a-zA-Z0-9_-]+)/g,
        '<span class="inline-tag clickable-tag" data-tag="$1">#$1</span>'
      );
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
      if (tagName) {
        event.stopPropagation();
        this.openTag(tagName);
      }
    },

    // Click outside to close sidebar
    setupClickOutsideListener() {
      this.clickOutsideHandler = (e) => {
        if (this.isOpen && !this.$el.contains(e.target)) {
          this.isOpen = false;
        }
      };
      document.addEventListener("click", this.clickOutsideHandler);
    },

    removeClickOutsideListener() {
      if (this.clickOutsideHandler) {
        document.removeEventListener("click", this.clickOutsideHandler);
      }
    },
  },

  template: `
    <div class="historical-sidebar-container">
      <!-- Sidebar Toggle Button -->
      <button
        @click="toggleSidebar"
        class="sidebar-toggle-btn"
        :class="{ active: isOpen }"
        title="Toggle History Sidebar"
      >
        <span v-if="isOpen">←</span>
        <span v-else>→</span>
        history
      </button>

      <!-- Sidebar -->
      <div
        v-if="isOpen"
        class="historical-sidebar"
        :style="{ width: width + 'px' }"
      >
        <!-- Resize Handle -->
        <div
          class="sidebar-resize-handle"
          @mousedown="startResize"
          :class="{ resizing: isResizing }"
        ></div>

        <div class="sidebar-content">
          <div class="sidebar-header">
            <h3>history</h3>
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
                <div
                  v-for="page in historicalData.pages"
                  :key="page.uuid"
                  class="sidebar-item page-item clickable"
                  @click="openPage(page)"
                  :title="'Click to open ' + page.title"
                >
                  <div class="page-card-vertical">
                    <!-- First row: title on left, label on right -->
                    <div class="page-header-row">
                      <div class="item-title">{{ formatPageTitle(page) }}</div>
                      <div class="item-type">{{ page.page_type }}</div>
                    </div>
                    
                    <!-- Second row: date (only for non-daily pages) -->
                    <div v-if="page.page_type !== 'daily'" class="page-date-row">
                      <div class="item-date">{{ formatDate(page.modified_at || page.created_at) }}</div>
                    </div>
                    
                    <!-- Content rows: recent blocks -->
                    <div v-if="page.recent_blocks && page.recent_blocks.length" class="page-content-rows" @click="handleTagClick">
                      <div v-for="block in page.recent_blocks.slice(0, 2)" :key="block.uuid" class="block-preview" :class="{ 'completed': block.block_type === 'done' }" v-html="formatContentWithTags(truncateContent(block.content, 60), block.block_type)">
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Recent Blocks -->
            <div v-if="historicalData.blocks && historicalData.blocks.length" class="sidebar-section">
              <h4>Recent Blocks ({{ historicalData.blocks.length }})</h4>
              <div class="sidebar-items">
                <div
                  v-for="block in historicalData.blocks"
                  :key="block.uuid"
                  class="sidebar-item block-item clickable"
                  @click="openBlockPage(block)"
                  :title="'Click to open ' + block.page_title"
                >
                  <div class="item-header">
                    <span class="item-page">{{ block.page_title }}</span>
                  </div>
                  <div class="item-meta">{{ formatTime(block.modified_at || block.created_at) }}</div>
                  <div class="item-content-row" @click="handleTagClick">
                    <span
                      v-if="block.block_type === 'todo' || block.block_type === 'done'"
                      @click="toggleBlockTodo(block, $event)"
                      :class="['block-bullet', block.block_type]"
                      :title="'Toggle ' + (block.block_type === 'done' ? 'undone' : 'done')"
                    >
                      {{ block.block_type === 'done' ? '☑' : '☐' }}
                    </span>
                    <span class="item-content" :class="{ 'completed': block.block_type === 'done' }" v-html="formatContentWithTags(truncateContent(block.content, 100), block.block_type)"></span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
};
