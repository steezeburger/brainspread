const BlockComponent = {
  name: "BlockComponent",
  props: {
    block: {
      type: Object,
      required: true,
    },
    onBlockContentChange: {
      type: Function,
      required: true,
    },
    onBlockKeyDown: {
      type: Function,
      required: true,
    },
    startEditing: {
      type: Function,
      required: true,
    },
    stopEditing: {
      type: Function,
      required: true,
    },
    deleteBlock: {
      type: Function,
      required: true,
    },
    toggleBlockTodo: {
      type: Function,
      required: true,
    },
    formatContentWithTags: {
      type: Function,
      required: true,
    },
    // Context-related props
    isBlockInContext: {
      type: Function,
      default: () => () => false,
    },
    isBlockSelected: {
      type: Function,
      default: () => () => false,
    },
    onBlockAddToContext: {
      type: Function,
      default: () => () => {},
    },
    onBlockRemoveFromContext: {
      type: Function,
      default: () => () => {},
    },
    // Block operations
    indentBlock: {
      type: Function,
      default: () => () => {},
    },
    outdentBlock: {
      type: Function,
      default: () => () => {},
    },
    createBlockAfter: {
      type: Function,
      default: () => () => {},
    },
    createBlockBefore: {
      type: Function,
      default: () => () => {},
    },
    moveBlockUp: {
      type: Function,
      default: () => () => {},
    },
    moveBlockDown: {
      type: Function,
      default: () => () => {},
    },
    moveBlockToToday: {
      type: Function,
      default: () => () => {},
    },
    onBlockPaste: {
      type: Function,
      default: () => () => {},
    },
    onBlockDrop: {
      type: Function,
      default: () => () => {},
    },
    onBlockAttachPick: {
      type: Function,
      default: () => () => {},
    },
    scheduleBlock: {
      type: Function,
      default: () => () => {},
    },
    onBlockSelectClick: {
      type: Function,
      default: () => () => false,
    },
    selectedBlockCount: {
      type: Number,
      default: 0,
    },
    bulkDeleteSelected: {
      type: Function,
      default: () => () => {},
    },
    bulkMoveSelectedToToday: {
      type: Function,
      default: () => () => {},
    },
    selectionMode: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      isCollapsed: this.block.collapsed === true,
      showContextMenu: false,
      contextMenuPosition: { x: 0, y: 0 },
      contextMenuFocusedIndex: -1,
      // Touch tracking for distinguishing taps from scrolls
      touchStartX: null,
      touchStartY: null,
      // Hashtag autocomplete state
      tagSuggestions: [],
      tagQueryStart: -1,
      tagQuery: "",
      tagSelectedIndex: 0,
      tagSearchToken: 0,
      // Web archive state (loaded lazily for embed blocks)
      webArchive: null,
      webArchiveLoading: false,
      // Embed tag chip UI state
      addingEmbedTag: false,
      embedTagInputValue: "",
      embedTagSuggestions: [],
      embedTagSelectedIndex: 0,
      embedTagSearchToken: 0,
    };
  },
  computed: {
    blockInContext() {
      return this.isBlockInContext(this.block.uuid);
    },
    blockSelected() {
      return this.isBlockSelected(this.block.uuid);
    },
    hasChildren() {
      return this.block.children?.length > 0;
    },
    childrenCount() {
      return this.block.children?.length || 0;
    },
    showTagSuggestions() {
      return this.tagQueryStart >= 0 && this.tagSuggestions.length > 0;
    },
    isEmbed() {
      return this.block.content_type === "embed" && !!this.block.media_url;
    },
    hasAsset() {
      return !!(this.block.asset && this.block.asset.uuid);
    },
    assetUrl() {
      if (!this.hasAsset) return "";
      return window.apiService.assetServeUrl(this.block.asset.uuid);
    },
    assetIsImage() {
      return this.hasAsset && this.block.asset.file_type === "image";
    },
    assetDisplayName() {
      if (!this.hasAsset) return "";
      const a = this.block.asset;
      return a.original_filename || `asset-${a.uuid.slice(0, 8)}`;
    },
    assetSizeLabel() {
      if (!this.hasAsset) return "";
      const bytes = this.block.asset.byte_size || 0;
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      if (bytes < 1024 * 1024 * 1024)
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
      return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
    },
    // Block content with trailing hashtags stripped, for blocks where
    // we render the tags as chips. Without this, "caption #travel"
    // would display the inline #travel link AND the chip - two copies
    // of the same tag. Only swaps in for asset blocks; embed blocks
    // already use embedTitle which does the same trick, and plain text
    // blocks should keep inline hashtags as today.
    displayContent() {
      if (this.hasAsset && !this.isEmbed) {
        return this.embedContentParts.title;
      }
      return this.block.content;
    },
    embedHostname() {
      try {
        return new URL(this.block.media_url).hostname.replace(/^www\./, "");
      } catch (_) {
        return this.block.media_url || "";
      }
    },
    embedFaviconUrl() {
      try {
        const u = new URL(this.block.media_url);
        return `${u.origin}/favicon.ico`;
      } catch (_) {
        return "";
      }
    },
    embedContentParts() {
      // Split block.content into a "title" part and a list of trailing
      // hashtag slugs. Trailing tags are rendered as chips so the user can
      // tag a link without polluting the visible label.
      return BlockComponent.parseEmbedContent(this.block.content);
    },
    embedTitle() {
      // After archive capture completes, the backend overwrites
      // block.content with the extracted title. Before that, content is
      // just the URL, so fall back to the hostname for a cleaner card.
      const t = (this.embedContentParts.title || "").trim();
      if (!t) return this.embedHostname;
      if (t === this.block.media_url) return this.embedHostname;
      return t;
    },
    embedTags() {
      return this.embedContentParts.tags;
    },
    showEmbedTagSuggestions() {
      return this.addingEmbedTag && this.embedTagSuggestions.length > 0;
    },
    webArchiveReady() {
      return !!(this.webArchive && this.webArchive.status === "ready");
    },
    webArchiveInFlight() {
      return !!(
        this.webArchive &&
        (this.webArchive.status === "pending" ||
          this.webArchive.status === "in_progress")
      );
    },
    canRequestArchive() {
      // Show the "archive" CTA when we've confirmed there's no archive
      // yet, OR when the previous capture failed (acts as a retry). While
      // the initial lookup is in flight we don't know, so render nothing
      // to avoid a flash of the button that then disappears.
      if (this.webArchiveLoading || !this.block.media_url) return false;
      if (!this.webArchive) return true;
      return this.webArchive.status === "failed";
    },
    archiveButtonLabel() {
      return this.webArchive && this.webArchive.status === "failed"
        ? "retry"
        : "archive";
    },
    scheduledForLabel() {
      // "2026-04-30" -> "apr 30" (or "apr 30, 2027" for non-current year).
      const raw = this.block.scheduled_for;
      if (!raw) return "";
      const [y, m, d] = raw.split("-").map(Number);
      const months = [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
      ];
      const sameYear = y === new Date().getFullYear();
      return sameYear ? `${months[m - 1]} ${d}` : `${months[m - 1]} ${d}, ${y}`;
    },
    reminderTimeLabel() {
      // Formatted per the user's 12h/24h preference, when a pending
      // reminder exists. Empty string otherwise.
      const t = this.block.pending_reminder_time;
      if (!t) return "";
      return window.formatTimeForUser?.(t) || t;
    },
    reminderDateLabel() {
      // Render the reminder date inline on the chip ONLY when it differs
      // from the due date — same date is the implicit common case.
      const r = this.block.pending_reminder_date;
      const d = this.block.scheduled_for;
      if (!r || !d || r === d) return "";
      const [y, m, day] = r.split("-").map(Number);
      const months = [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
      ];
      const sameYear = y === new Date().getFullYear();
      return sameYear
        ? `${months[m - 1]} ${day}`
        : `${months[m - 1]} ${day}, ${y}`;
    },
    isOverdue() {
      const d = this.block.scheduled_for;
      if (!d) return false;
      if (this.block.completed_at) return false;
      if (!["todo", "doing", "later"].includes(this.block.block_type)) {
        return false;
      }
      // en-CA toLocaleDateString gives YYYY-MM-DD in the user's local tz —
      // safest way to compare with the date string from the backend without
      // rolling our own tz handling.
      const todayISO = new Date().toLocaleDateString("en-CA");
      return d < todayISO;
    },
  },
  watch: {
    showContextMenu(val) {
      if (val) {
        this.contextMenuFocusedIndex = 0;
        this.$nextTick(() => {
          this.focusContextMenuItem(0);
        });
      } else {
        this.contextMenuFocusedIndex = -1;
      }
    },
    // For unarchived embeds, block.content holds the raw URL (paste
    // flow). Showing that in the label editor is confusing - the user
    // expects the visible label (hostname). Clear content on edit entry
    // so they get an empty textarea + placeholder; on blur, empty
    // content falls back to the hostname display via embedTitle.
    "block.isEditing"(isEditing) {
      if (
        isEditing &&
        this.isEmbed &&
        this.block.content === this.block.media_url
      ) {
        this.block.content = "";
      }
    },
  },

  mounted() {
    // Listen for the custom event to close menus
    document.addEventListener("closeBlockMenus", this.handleCloseBlockMenus);
    document.addEventListener(
      "openBlockContextMenu",
      this.handleOpenContextMenuEvent
    );
    document.addEventListener(
      "brainspread:archive-updated",
      this.handleArchiveUpdated
    );
    if (this.isEmbed) {
      this.loadWebArchive();
    }
    this.applyContentRenderers();
  },
  updated() {
    // The block-content div uses v-html, so when the block's content
    // changes (edits, type swaps) Vue replaces the inner DOM with a fresh
    // placeholder. Re-run the dynamic renderers so the new DOM picks up
    // mermaid SVGs, syntax highlighting, etc.
    this.applyContentRenderers();
  },
  beforeUnmount() {
    // Clean up event listener
    document.removeEventListener("closeBlockMenus", this.handleCloseBlockMenus);
    document.removeEventListener(
      "openBlockContextMenu",
      this.handleOpenContextMenuEvent
    );
    document.removeEventListener(
      "brainspread:archive-updated",
      this.handleArchiveUpdated
    );
  },
  methods: {
    applyContentRenderers() {
      // Run after v-html replaces the block's display HTML so dynamic
      // renderers (mermaid SVG, Prism syntax highlighting, etc.) can
      // upgrade the static markup. Each renderer is no-op-cheap when
      // its targets aren't present.
      this.renderMermaidIfPresent();
      this.highlightCodeIfPresent();
    },

    renderMermaidIfPresent() {
      // Skip the work if neither the helper nor any placeholder are
      // present. The helper takes care of one-shot mermaid initialization
      // and idempotent rendering.
      if (!window.brainspreadMermaid || !this.$el || this.$el.nodeType !== 1)
        return;
      if (!this.$el.querySelector || !this.$el.querySelector(".block-mermaid"))
        return;
      const appTheme =
        document.documentElement.getAttribute("data-theme") || "dark";
      window.brainspreadMermaid.renderIn(this.$el, appTheme);
    },

    highlightCodeIfPresent() {
      // Apply Prism syntax highlighting to any <code class="language-*">
      // emitted by formatContentWithTags. The autoloader fetches the
      // grammar for each language on first use; calling highlightElement
      // again on an already-tokenized node is a cheap no-op-ish retokenize.
      if (!window.Prism || !this.$el || this.$el.nodeType !== 1) return;
      const codeEls = this.$el.querySelectorAll(
        "pre.block-code > code[class*='language-']"
      );
      codeEls.forEach((el) => {
        try {
          window.Prism.highlightElement(el);
        } catch (_) {
          // Highlighting failures shouldn't take the block down; the
          // un-highlighted code is still legible.
        }
      });
    },

    async loadWebArchive() {
      if (this.webArchiveLoading) return;
      this.webArchiveLoading = true;
      try {
        const result = await window.apiService.getWebArchive(this.block.uuid);
        if (result && result.success && result.data) {
          this.webArchive = result.data;
        }
      } catch (_) {
        // 404 is expected when capture hasn't happened yet; other errors
        // we'd rather ignore than show a scary error in the page.
      } finally {
        this.webArchiveLoading = false;
      }
    },

    handleArchiveUpdated(event) {
      const detail = event?.detail || {};
      if (detail.blockUuid === this.block.uuid) {
        this.loadWebArchive();
      }
    },

    requestArchive() {
      if (!this.block.media_url) return;
      // Page.js owns the capture/poll/toast flow. We just ask for it and
      // optimistically flip local state to "pending" so the button swaps
      // to "capturing…" immediately; the next archive-updated event
      // reconciles with whatever the server returns.
      this.webArchive = { status: "pending" };
      document.dispatchEvent(
        new CustomEvent("brainspread:request-archive", {
          detail: {
            blockUuid: this.block.uuid,
            url: this.block.media_url,
          },
        })
      );
    },

    async openArchivedCopy() {
      if (!this.webArchiveReady) return;
      try {
        const blob = await window.apiService.fetchWebArchiveReadableBlob(
          this.block.uuid
        );
        const objectUrl = URL.createObjectURL(blob);
        // Revoke after the tab had time to load; browsers will keep the
        // object alive while the tab is using it.
        window.open(objectUrl, "_blank", "noopener,noreferrer");
        setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
      } catch (error) {
        console.error("failed to open archived copy:", error);
        document.dispatchEvent(
          new CustomEvent("brainspread:toast", {
            detail: { message: "could not open archive", type: "error" },
          })
        );
      }
    },

    toggleBlockContext() {
      if (this.blockInContext) {
        this.onBlockRemoveFromContext(this.block.uuid);
      } else {
        this.onBlockAddToContext(this.block);
      }
    },
    // Touch handling methods to distinguish taps from scrolls
    handleTouchStart(event) {
      if (event.touches.length === 1) {
        this.touchStartX = event.touches[0].clientX;
        this.touchStartY = event.touches[0].clientY;
      }
    },
    isTapGesture(event) {
      // If we don't have a recorded touch start, assume it's not a valid tap
      if (this.touchStartX === null || this.touchStartY === null) {
        return false;
      }

      const touch = event.changedTouches[0];
      const deltaX = Math.abs(touch.clientX - this.touchStartX);
      const deltaY = Math.abs(touch.clientY - this.touchStartY);

      // Reset touch tracking
      this.touchStartX = null;
      this.touchStartY = null;

      // If the touch moved more than 10 pixels in any direction, it's a scroll not a tap
      const TAP_THRESHOLD = 10;
      return deltaX < TAP_THRESHOLD && deltaY < TAP_THRESHOLD;
    },
    handleContentTouchEnd(event) {
      if (this.isTapGesture(event)) {
        if (event.target.closest(".clickable-tag")) return;
        event.preventDefault();
        this.startEditing(this.block);
      }
    },
    handleTodoTouchEnd(event) {
      if (this.isTapGesture(event)) {
        event.preventDefault();
        if (
          ["todo", "doing", "done", "later", "wontdo"].includes(
            this.block.block_type
          )
        ) {
          this.toggleBlockTodo(this.block);
        }
      }
    },
    async toggleCollapse() {
      const next = !this.isCollapsed;
      const previous = this.isCollapsed;
      this.isCollapsed = next;
      this.block.collapsed = next;
      try {
        const result = await window.apiService.updateBlock(this.block.uuid, {
          collapsed: next,
          parent: this.block.parent ? this.block.parent.uuid : null,
        });
        if (!result || !result.success) {
          throw new Error("updateBlock did not succeed");
        }
      } catch (error) {
        console.error("failed to persist collapsed state:", error);
        this.isCollapsed = previous;
        this.block.collapsed = previous;
      }
    },
    closeOtherMenus() {
      // Dispatch a custom event to close all other menus
      document.dispatchEvent(
        new CustomEvent("closeBlockMenus", { detail: { except: this } })
      );
    },
    handleCloseBlockMenus(event) {
      // Close this menu if the event is not from this component
      if (event.detail.except !== this && this.showContextMenu) {
        this.hideContextMenu();
      }
    },
    showContextMenuAt(event) {
      event.preventDefault();
      event.stopPropagation();

      // Close any other open menus first
      this.closeOtherMenus();

      const menuWidth = 200; // min-width from CSS
      const shadowOffset = 4;
      const viewportWidth = window.innerWidth;
      const isMobile = window.innerWidth <= 768;
      const edgePadding = isMobile ? 20 : 10;
      const bottomPadding = isMobile ? 60 : 10;

      let x = event.clientX;
      let y = event.clientY;

      // Clamp X immediately (we know the menu width upfront)
      if (x + menuWidth + shadowOffset > viewportWidth - edgePadding) {
        x = viewportWidth - menuWidth - shadowOffset - edgePadding;
      }
      x = Math.max(edgePadding, x);

      this.contextMenuPosition = { x, y };
      this.showContextMenu = true;

      // After render, measure the actual menu height and reposition vertically if needed
      this.$nextTick(() => {
        const menuEl = this.$el.querySelector(".block-context-menu");
        if (!menuEl) return;
        const menuHeight = menuEl.offsetHeight;
        const viewportHeight = window.innerHeight;
        if (y + menuHeight + shadowOffset > viewportHeight - bottomPadding) {
          y = viewportHeight - menuHeight - shadowOffset - bottomPadding;
        }
        y = Math.max(edgePadding, y);
        this.contextMenuPosition = { x, y };
      });

      // Add click listener to close menu after a short delay
      setTimeout(() => {
        document.addEventListener("click", this.hideContextMenu);
      }, 10);
    },
    hideContextMenu() {
      this.showContextMenu = false;
      document.removeEventListener("click", this.hideContextMenu);
    },

    hideContextMenuAndRestoreFocus() {
      this.hideContextMenu();
      this.$nextTick(() => {
        const menuBtn = this.$el?.querySelector(".block-menu");
        if (menuBtn) menuBtn.focus();
      });
    },
    getContextMenuItems() {
      return Array.from(
        this.$el?.querySelectorAll(".block-context-menu [role='menuitem']") ||
          []
      );
    },

    focusContextMenuItem(index) {
      const items = this.getContextMenuItems();
      if (items[index]) {
        items[index].focus();
        this.contextMenuFocusedIndex = index;
      }
    },

    handleContextMenuKeydown(event) {
      const items = this.getContextMenuItems();
      if (!items.length) return;

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          this.contextMenuFocusedIndex = Math.min(
            this.contextMenuFocusedIndex + 1,
            items.length - 1
          );
          this.focusContextMenuItem(this.contextMenuFocusedIndex);
          break;
        case "ArrowUp":
          event.preventDefault();
          this.contextMenuFocusedIndex = Math.max(
            this.contextMenuFocusedIndex - 1,
            0
          );
          this.focusContextMenuItem(this.contextMenuFocusedIndex);
          break;
        case "Escape":
        case "Tab":
          event.preventDefault();
          this.hideContextMenu();
          this.$nextTick(() => {
            const menuBtn = this.$el?.querySelector(".block-menu");
            if (menuBtn) menuBtn.focus();
          });
          break;
        case "Home":
          event.preventDefault();
          this.focusContextMenuItem(0);
          break;
        case "End":
          event.preventDefault();
          this.focusContextMenuItem(items.length - 1);
          break;
      }
    },

    async handleBlockDisplayKeydown(event) {
      // Alt+Shift+ArrowUp/Down: move block
      if (event.altKey && event.shiftKey && event.key === "ArrowUp") {
        event.preventDefault();
        const uuid = this.block.uuid;
        await this.moveBlockUp(this.block);
        this.refocusDisplay(uuid);
        return;
      }
      if (event.altKey && event.shiftKey && event.key === "ArrowDown") {
        event.preventDefault();
        const uuid = this.block.uuid;
        await this.moveBlockDown(this.block);
        this.refocusDisplay(uuid);
        return;
      }
      // Cmd/Ctrl+Shift+Backspace: delete block
      if (
        (event.metaKey || event.ctrlKey) &&
        event.shiftKey &&
        event.key === "Backspace"
      ) {
        event.preventDefault();
        this.deleteBlock(this.block);
        return;
      }
      // Cmd/Ctrl+. or Shift+F10: open context menu
      if (
        ((event.metaKey || event.ctrlKey) && event.key === ".") ||
        (event.shiftKey && event.key === "F10")
      ) {
        event.preventDefault();
        this.openContextMenuAtBlock();
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.startEditing(this.block);
      }
    },

    openContextMenuAtBlock() {
      const menuBtn = this.$el?.querySelector(".block-menu");
      if (!menuBtn) return;
      const rect = menuBtn.getBoundingClientRect();

      // Reuse the same positioning logic as showContextMenuAt
      this.closeOtherMenus();

      const menuWidth = 200;
      const shadowOffset = 4;
      const viewportWidth = window.innerWidth;
      const isMobile = window.innerWidth <= 768;
      const edgePadding = isMobile ? 20 : 10;
      const bottomPadding = isMobile ? 60 : 10;

      let x = rect.left;
      let y = rect.bottom;

      if (x + menuWidth + shadowOffset > viewportWidth - edgePadding) {
        x = viewportWidth - menuWidth - shadowOffset - edgePadding;
      }
      x = Math.max(edgePadding, x);

      this.contextMenuPosition = { x, y };
      this.showContextMenu = true;

      this.$nextTick(() => {
        const menuEl = this.$el.querySelector(".block-context-menu");
        if (!menuEl) return;
        const menuHeight = menuEl.offsetHeight;
        const viewportHeight = window.innerHeight;
        if (y + menuHeight + shadowOffset > viewportHeight - bottomPadding) {
          y = viewportHeight - menuHeight - shadowOffset - bottomPadding;
        }
        y = Math.max(edgePadding, y);
        this.contextMenuPosition = { x, y };
      });

      setTimeout(() => {
        document.addEventListener("click", this.hideContextMenu);
      }, 10);
    },

    handleOpenContextMenuEvent(event) {
      if (event.detail?.uuid === this.block.uuid) {
        this.openContextMenuAtBlock();
      }
    },

    refocusDisplay(uuid) {
      this.$nextTick(() => {
        this.$nextTick(() => {
          const display = document.querySelector(
            `[data-block-uuid="${uuid}"] .block-content-display`
          );
          if (display) display.focus();
        });
      });
    },

    // --- Hashtag autocomplete ---
    // Detect a `#query` prefix ending at the cursor. Returns { start, query }
    // or null when the cursor isn't in a hashtag context.
    detectTagContext(value, caret) {
      if (caret == null || caret < 0) return null;
      const upToCaret = value.slice(0, caret);
      // Match an optional hashtag starting after whitespace or at string start.
      // Allow empty query so a bare `#` still triggers suggestions.
      const match = upToCaret.match(/(^|\s)#([a-zA-Z0-9_-]*)$/);
      if (!match) return null;
      const hashIndex = upToCaret.length - match[2].length - 1;
      return { start: hashIndex, query: match[2] };
    },
    closeTagSuggestions() {
      this.tagSuggestions = [];
      this.tagQueryStart = -1;
      this.tagQuery = "";
      this.tagSelectedIndex = 0;
    },
    async updateTagSuggestions(value, caret) {
      const ctx = this.detectTagContext(value, caret);
      if (!ctx) {
        this.closeTagSuggestions();
        return;
      }
      this.tagQueryStart = ctx.start;
      this.tagQuery = ctx.query;

      // Each search gets a monotonically increasing token so stale responses
      // (from slower earlier requests) don't overwrite newer results.
      const token = ++this.tagSearchToken;
      try {
        const result = await window.apiService.searchPages(ctx.query, 8);
        if (token !== this.tagSearchToken) return;
        if (this.tagQueryStart < 0) return;
        const pages = (result && result.data && result.data.pages) || [];
        this.tagSuggestions = pages;
        if (this.tagSelectedIndex >= pages.length) {
          this.tagSelectedIndex = 0;
        }
      } catch (error) {
        console.error("tag search failed:", error);
        if (token === this.tagSearchToken) this.tagSuggestions = [];
      }
    },
    insertTagSuggestion(page) {
      if (!page || this.tagQueryStart < 0) return;
      const textarea = this.$refs.blockTextarea;
      const content = this.block.content || "";
      const caret = textarea ? textarea.selectionEnd : content.length;
      const before = content.slice(0, this.tagQueryStart);
      const after = content.slice(caret);
      const inserted = `#${page.slug} `;
      const newContent = before + inserted + after;
      this.onBlockContentChange(this.block, newContent);
      this.closeTagSuggestions();
      // Restore caret just after the inserted tag+space.
      this.$nextTick(() => {
        if (textarea) {
          const pos = before.length + inserted.length;
          textarea.focus();
          textarea.setSelectionRange(pos, pos);
        }
      });
    },
    handleTextareaInput(event) {
      const value = event.target.value;
      this.onBlockContentChange(this.block, value);
      this.updateTagSuggestions(value, event.target.selectionEnd);
    },
    handleTextareaKeydown(event) {
      if (this.showTagSuggestions) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          event.stopPropagation();
          this.tagSelectedIndex =
            (this.tagSelectedIndex + 1) % this.tagSuggestions.length;
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          event.stopPropagation();
          this.tagSelectedIndex =
            (this.tagSelectedIndex - 1 + this.tagSuggestions.length) %
            this.tagSuggestions.length;
          return;
        }
        if (event.key === "Enter" || event.key === "Tab") {
          const choice = this.tagSuggestions[this.tagSelectedIndex];
          if (choice) {
            event.preventDefault();
            event.stopPropagation();
            this.insertTagSuggestion(choice);
            return;
          }
        }
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          this.closeTagSuggestions();
          return;
        }
      }
      this.onBlockKeyDown(event, this.block);
    },
    handleTextareaBlur() {
      // Delay close so a click on a suggestion item still registers.
      setTimeout(() => this.closeTagSuggestions(), 150);
      this.stopEditing(this.block);
    },

    // --- Embed tag chips ---
    startAddEmbedTag() {
      this.addingEmbedTag = true;
      this.embedTagInputValue = "";
      this.embedTagSuggestions = [];
      this.embedTagSelectedIndex = 0;
      this.$nextTick(() => {
        const input = this.$refs.embedTagInput;
        if (input) input.focus();
      });
    },
    cancelAddEmbedTag() {
      this.addingEmbedTag = false;
      this.embedTagInputValue = "";
      this.embedTagSuggestions = [];
      this.embedTagSelectedIndex = 0;
    },
    handleEmbedTagInputBlur() {
      // Delay so a click on a suggestion still registers before close.
      setTimeout(() => this.cancelAddEmbedTag(), 150);
    },
    async handleEmbedTagInputChange() {
      const raw = (this.embedTagInputValue || "").trim();
      if (!raw) {
        this.embedTagSuggestions = [];
        this.embedTagSelectedIndex = 0;
        return;
      }
      const token = ++this.embedTagSearchToken;
      try {
        const result = await window.apiService.searchPages(raw, 8);
        if (token !== this.embedTagSearchToken) return;
        const pages = (result && result.data && result.data.pages) || [];
        // Hide pages already attached as a trailing tag on this embed.
        const existing = new Set(this.embedTags);
        this.embedTagSuggestions = pages.filter((p) => !existing.has(p.slug));
        if (this.embedTagSelectedIndex >= this.embedTagSuggestions.length) {
          this.embedTagSelectedIndex = 0;
        }
      } catch (error) {
        console.error("embed tag search failed:", error);
        if (token === this.embedTagSearchToken) {
          this.embedTagSuggestions = [];
        }
      }
    },
    handleEmbedTagInputKeydown(event) {
      if (event.key === "ArrowDown" && this.embedTagSuggestions.length) {
        event.preventDefault();
        this.embedTagSelectedIndex =
          (this.embedTagSelectedIndex + 1) % this.embedTagSuggestions.length;
        return;
      }
      if (event.key === "ArrowUp" && this.embedTagSuggestions.length) {
        event.preventDefault();
        this.embedTagSelectedIndex =
          (this.embedTagSelectedIndex - 1 + this.embedTagSuggestions.length) %
          this.embedTagSuggestions.length;
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const choice = this.embedTagSuggestions[this.embedTagSelectedIndex];
        if (choice) {
          this.commitEmbedTag(choice.slug);
        } else {
          this.commitEmbedTag(this.embedTagInputValue);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        this.cancelAddEmbedTag();
        return;
      }
    },
    selectEmbedTagSuggestion(page) {
      this.commitEmbedTag(page.slug);
    },
    commitEmbedTag(rawSlug) {
      const slug = BlockComponent.slugifyTag(rawSlug);
      if (!slug) {
        this.cancelAddEmbedTag();
        return;
      }
      // Reject duplicates - the chip is already there.
      if (this.embedTags.includes(slug)) {
        this.cancelAddEmbedTag();
        return;
      }
      const current = this.block.content || "";
      const sep = current && !/\s$/.test(current) ? " " : "";
      const newContent = `${current}${sep}#${slug}`;
      this.cancelAddEmbedTag();
      this.onBlockContentChange(this.block, newContent);
      // Persist immediately - chips are click-to-commit, not editor input.
      this.persistEmbedContent(newContent);
    },
    removeEmbedTag(slug) {
      const current = this.block.content || "";
      const next = BlockComponent.removeTagFromContent(current, slug);
      if (next === current) return;
      this.onBlockContentChange(this.block, next);
      this.persistEmbedContent(next);
    },
    async persistEmbedContent(newContent) {
      try {
        const result = await window.apiService.updateBlock(this.block.uuid, {
          content: newContent,
          parent: this.block.parent ? this.block.parent.uuid : null,
        });
        if (!result || !result.success) {
          throw new Error("updateBlock did not succeed");
        }
        if (result.data && Array.isArray(result.data.tags)) {
          this.block.tags = result.data.tags;
        }
      } catch (error) {
        console.error("failed to persist embed tags:", error);
      }
    },

    handleContextMenuAction(action) {
      this.hideContextMenu();

      switch (action) {
        case "expand":
          if (this.hasChildren) this.isCollapsed = false;
          break;
        case "collapse":
          if (this.hasChildren) this.isCollapsed = true;
          break;
        case "indent":
          this.indentBlock(this.block);
          break;
        case "outdent":
          this.outdentBlock(this.block);
          break;
        case "delete":
          this.deleteBlock(this.block);
          break;
        case "addToContext":
          this.onBlockAddToContext(this.block);
          break;
        case "removeFromContext":
          this.onBlockRemoveFromContext(this.block.uuid);
          break;
        case "moveUp":
          this.moveBlockUp(this.block);
          break;
        case "moveDown":
          this.moveBlockDown(this.block);
          break;
        case "moveToToday":
          this.moveBlockToToday(this.block);
          break;
        case "newBlockBefore":
          this.createBlockBefore(this.block);
          break;
        case "newBlockAfter":
          this.createBlockAfter(this.block);
          break;
        case "bulkDelete":
          this.bulkDeleteSelected();
          break;
        case "bulkMoveToToday":
          this.bulkMoveSelectedToToday();
          break;
        case "schedule":
          this.scheduleBlock(this.block);
          break;
        case "unschedule":
          this.scheduleBlock(this.block, { clear: true });
          break;
        case "attachFile":
          this.triggerAttachFilePicker();
          break;
      }
    },

    triggerAttachFilePicker() {
      // Forward to the hidden <input type="file"> rendered inside this
      // block; the input's @change calls back into onBlockAttachPick on
      // the page, which posts to /api/assets/ and updates the block.
      const input = this.$refs.assetFileInput;
      if (input) input.click();
    },

    handleBlockDragOver(event) {
      const dt = event.dataTransfer;
      if (!dt) return;
      // Only claim the drop when the drag carries files. Without this,
      // users mid-text-drag would see a no-op cursor change. types
      // contains "Files" for OS file drags (Chrome/Firefox/Safari).
      if (dt.types && Array.from(dt.types).includes("Files")) {
        event.preventDefault();
        event.stopPropagation();
      }
    },

    handleBlockDrop(event) {
      const dt = event.dataTransfer;
      if (!dt || !dt.files || dt.files.length === 0) return;
      // Stop propagation so the page-level drop handler (which would
      // create a new bottom block) doesn't ALSO fire for the same drop.
      event.stopPropagation();
      this.onBlockDrop(event, this.block);
    },

    // Plain click on the block display starts editing. Modifier-clicks
    // (shift, cmd/ctrl) instead toggle selection / extend a range; in that
    // case we bail before calling startEditing. While in selection mode,
    // ANY click toggles selection — editing is suppressed entirely.
    handleDisplayClick(event) {
      if (event.target.closest(".clickable-tag")) return;
      if (
        this.selectionMode ||
        event.shiftKey ||
        event.metaKey ||
        event.ctrlKey
      ) {
        const handled = this.onBlockSelectClick(this.block, event);
        if (handled) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
      }
      this.startEditing(this.block);
    },

    handleSelectToggleClick(event) {
      event.preventDefault();
      event.stopPropagation();
      this.onBlockSelectClick(this.block, event);
    },

    showBulkSelectionActions() {
      return this.blockSelected && this.selectedBlockCount >= 2;
    },
  },
  template: `
    <div class="block-wrapper" :class="{ 'child-block': block.parent, 'in-context': blockInContext, 'selected': blockSelected, 'in-selection-mode': selectionMode }" :data-block-uuid="block.uuid" @dragover="handleBlockDragOver" @drop="handleBlockDrop">
      <div class="block" :class="{ 'has-children': hasChildren, 'is-collapsed': hasChildren && isCollapsed }">
        <button
          v-if="selectionMode"
          type="button"
          class="block-select-toggle"
          :class="{ 'is-selected': blockSelected }"
          :aria-label="blockSelected ? 'Unselect block' : 'Select block'"
          :aria-pressed="blockSelected"
          @click="handleSelectToggleClick($event)"
        >{{ blockSelected ? '●' : '○' }}</button>
        <button
          v-if="hasChildren"
          @click="toggleCollapse"
          class="block-collapse-toggle"
          :class="{ 'collapsed': isCollapsed }"
          :title="isCollapsed ? 'Expand children' : 'Collapse children'"
        >
          {{ isCollapsed ? '▶' : '▼' }}
        </button>
        <div
          class="block-bullet"
          :class="{
            'todo': block.block_type === 'todo',
            'doing': block.block_type === 'doing',
            'done': block.block_type === 'done',
            'later': block.block_type === 'later',
            'wontdo': block.block_type === 'wontdo'
          }"
          @click="selectionMode ? handleSelectToggleClick($event) : (['todo', 'doing', 'done', 'later', 'wontdo'].includes(block.block_type) ? toggleBlockTodo(block) : null)"
          @touchstart="handleTouchStart"
          @touchend="selectionMode ? null : handleTodoTouchEnd($event)"
        >
          <span v-if="block.block_type === 'todo'">☐</span>
          <span v-else-if="block.block_type === 'doing'">◐</span>
          <span v-else-if="block.block_type === 'done'">☑</span>
          <span v-else-if="block.block_type === 'later'">☐</span>
          <span v-else-if="block.block_type === 'wontdo'">⊘</span>
          <span v-else>•</span>
        </div>
        <div v-if="hasAsset && !isEmbed" class="block-asset" @click.stop>
          <img
            v-if="assetIsImage"
            :src="assetUrl"
            :alt="assetDisplayName"
            class="block-asset-image"
            loading="lazy"
          />
          <a
            v-else
            :href="assetUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="block-asset-chip"
            :title="assetDisplayName"
          >
            <span class="block-asset-chip-icon">▤</span>
            <span class="block-asset-chip-name">{{ assetDisplayName }}</span>
            <span class="block-asset-chip-meta">{{ block.asset.file_type }} · {{ assetSizeLabel }}</span>
          </a>
          <!--
            Caption / text input below the image. For chip blocks we
            keep the textarea as a flex sibling of .block-asset (see
            the v-else-if branch further down) so chip + textarea sit
            on the same row. For image blocks the textarea sits
            inline below the image so the user can describe what's in
            the picture without hunting for a target outside the
            image's flex column.
          -->
          <div
            v-if="assetIsImage && !block.isEditing"
            class="block-content-display block-asset-caption"
            :class="{ completed: ['done', 'wontdo'].includes(block.block_type) }"
            tabindex="0"
            role="button"
            :aria-label="'Edit caption: ' + (block.content || 'empty')"
            @click="handleDisplayClick($event)"
            @keydown="handleBlockDisplayKeydown"
            @touchstart="handleTouchStart"
            @touchend="handleContentTouchEnd"
            v-html="formatContentWithTags(displayContent, block.block_type, block.properties) || '<span class=&quot;block-asset-caption-placeholder&quot;>add caption…</span>'"
          ></div>
          <div
            v-else-if="assetIsImage"
            class="block-content-wrapper block-asset-caption-wrapper"
          >
            <textarea
              :value="block.content"
              @input="handleTextareaInput"
              @keydown="handleTextareaKeydown"
              @paste="onBlockPaste($event, block)"
              @blur="handleTextareaBlur"
              class="block-content"
              :class="{ completed: ['done', 'wontdo'].includes(block.block_type) }"
              rows="1"
              placeholder="add caption…"
              ref="blockTextarea"
            ></textarea>
          </div>
          <!--
            Tag chip strip - reuses the embed-tag plumbing (parser,
            state, methods) since it's all just a layer over
            block.content trailing hashtags. Same chips, same "+ tag"
            input, same suggestions; the only difference is where in
            the template they render.
          -->
          <div class="block-embed-tags" @click.stop>
            <a
              v-for="slug in embedTags"
              :key="slug"
              class="block-embed-tag-chip"
              :href="'/knowledge/page/' + slug + '/'"
              :data-tag="slug"
              @click.stop
            >
              <span class="block-embed-tag-chip-label">#{{ slug }}</span>
              <button
                type="button"
                class="block-embed-tag-chip-remove"
                :aria-label="'Remove tag ' + slug"
                title="Remove tag"
                @click.stop.prevent="removeEmbedTag(slug)"
              >×</button>
            </a>
            <div v-if="addingEmbedTag" class="block-embed-tag-input-wrapper">
              <input
                ref="embedTagInput"
                type="text"
                class="block-embed-tag-input"
                placeholder="tag…"
                v-model="embedTagInputValue"
                @input="handleEmbedTagInputChange"
                @keydown="handleEmbedTagInputKeydown"
                @blur="handleEmbedTagInputBlur"
              />
              <div
                v-if="showEmbedTagSuggestions"
                class="tag-suggestions block-embed-tag-suggestions"
                @mousedown.prevent
                role="listbox"
              >
                <button
                  v-for="(page, idx) in embedTagSuggestions"
                  :key="page.uuid || page.slug"
                  type="button"
                  role="option"
                  :aria-selected="idx === embedTagSelectedIndex"
                  class="tag-suggestion-item"
                  :class="{ 'is-selected': idx === embedTagSelectedIndex }"
                  @click="selectEmbedTagSuggestion(page)"
                  @mouseenter="embedTagSelectedIndex = idx"
                >
                  <span class="tag-suggestion-slug">#{{ page.slug }}</span>
                  <span v-if="page.title && page.title !== page.slug" class="tag-suggestion-title">{{ page.title }}</span>
                </button>
              </div>
            </div>
            <button
              v-else
              type="button"
              class="block-embed-tag-add"
              title="Add a tag"
              @click.stop="startAddEmbedTag"
            >+ tag</button>
          </div>
        </div>
        <input
          ref="assetFileInput"
          type="file"
          class="block-asset-file-input"
          style="display: none;"
          @change="onBlockAttachPick($event, block)"
        />
        <div
          v-if="isEmbed"
          class="block-embed-card"
          tabindex="0"
          :aria-label="'Embed: ' + embedTitle + ' — ' + block.media_url"
        >
          <img
            v-if="embedFaviconUrl"
            class="block-embed-favicon"
            :src="embedFaviconUrl"
            alt=""
            @error="$event.target.style.display='none'"
          />
          <div class="block-embed-body">
            <textarea
              v-if="block.isEditing"
              :value="block.content"
              @input="handleTextareaInput"
              @keydown="handleTextareaKeydown"
              @blur="handleTextareaBlur"
              class="block-embed-title-input"
              rows="1"
              placeholder="label this link…"
              ref="blockTextarea"
            ></textarea>
            <div
              v-else
              class="block-embed-title block-embed-title-clickable"
              tabindex="0"
              role="button"
              :aria-label="'Edit label: ' + embedTitle"
              @click.stop="startEditing(block)"
              @keydown="handleBlockDisplayKeydown"
            >{{ embedTitle }}</div>
            <div class="block-embed-host">
              <span class="block-embed-url">{{ block.media_url }}</span>
              <span v-if="webArchive && (webArchive.status === 'pending' || webArchive.status === 'in_progress')" class="block-embed-status">· capturing…</span>
              <span v-else-if="webArchive && webArchive.status === 'failed'" class="block-embed-status block-embed-status-failed">· capture failed</span>
            </div>
            <div class="block-embed-tags" @click.stop>
              <a
                v-for="slug in embedTags"
                :key="slug"
                class="block-embed-tag-chip"
                :href="'/knowledge/page/' + slug + '/'"
                :data-tag="slug"
                @click.stop
              >
                <span class="block-embed-tag-chip-label">#{{ slug }}</span>
                <button
                  type="button"
                  class="block-embed-tag-chip-remove"
                  :aria-label="'Remove tag ' + slug"
                  title="Remove tag"
                  @click.stop.prevent="removeEmbedTag(slug)"
                >×</button>
              </a>
              <div v-if="addingEmbedTag" class="block-embed-tag-input-wrapper">
                <input
                  ref="embedTagInput"
                  type="text"
                  class="block-embed-tag-input"
                  placeholder="tag…"
                  v-model="embedTagInputValue"
                  @input="handleEmbedTagInputChange"
                  @keydown="handleEmbedTagInputKeydown"
                  @blur="handleEmbedTagInputBlur"
                />
                <div
                  v-if="showEmbedTagSuggestions"
                  class="tag-suggestions block-embed-tag-suggestions"
                  @mousedown.prevent
                  role="listbox"
                >
                  <button
                    v-for="(page, idx) in embedTagSuggestions"
                    :key="page.uuid || page.slug"
                    type="button"
                    role="option"
                    :aria-selected="idx === embedTagSelectedIndex"
                    class="tag-suggestion-item"
                    :class="{ 'is-selected': idx === embedTagSelectedIndex }"
                    @click="selectEmbedTagSuggestion(page)"
                    @mouseenter="embedTagSelectedIndex = idx"
                  >
                    <span class="tag-suggestion-slug">#{{ page.slug }}</span>
                    <span v-if="page.title && page.title !== page.slug" class="tag-suggestion-title">{{ page.title }}</span>
                  </button>
                </div>
              </div>
              <button
                v-else
                type="button"
                class="block-embed-tag-add"
                title="Add a tag"
                @click.stop="startAddEmbedTag"
              >+ tag</button>
            </div>
          </div>
          <button
            v-if="canRequestArchive"
            type="button"
            class="block-embed-link block-embed-link-text"
            :title="archiveButtonLabel === 'retry' ? 'Retry capture' : 'Archive this page for later'"
            @click.stop="requestArchive"
          >{{ archiveButtonLabel }}</button>
          <button
            v-else-if="webArchiveReady"
            type="button"
            class="block-embed-link block-embed-link-text"
            title="Open saved archive"
            @click.stop="openArchivedCopy"
          >open archive</button>
          <a
            :href="block.media_url"
            target="_blank"
            rel="noopener noreferrer"
            class="block-embed-link"
            title="Open original"
            @click.stop
          >↗</a>
        </div>
        <!--
          Outer display chain: skipped for image-asset blocks because
          the caption renders INSIDE .block-asset above (so it stacks
          below the image instead of getting squeezed off to the
          right of it as a flex sibling).
        -->
        <div
          v-else-if="!block.isEditing && !(hasAsset && assetIsImage)"
          class="block-content-display"
          :class="{ 'completed': ['done', 'wontdo'].includes(block.block_type) }"
          tabindex="0"
          role="button"
          :aria-label="'Edit block: ' + (block.content || 'empty block')"
          @click="handleDisplayClick($event)"
          @keydown="handleBlockDisplayKeydown"
          @touchstart="handleTouchStart"
          @touchend="handleContentTouchEnd"
          v-html="formatContentWithTags(displayContent, block.block_type, block.properties)"
        ></div>
        <div
          v-else-if="!(hasAsset && assetIsImage)"
          class="block-content-wrapper"
        >
          <textarea
            :value="block.content"
            @input="handleTextareaInput"
            @keydown="handleTextareaKeydown"
            @paste="onBlockPaste($event, block)"
            @blur="handleTextareaBlur"
            class="block-content"
            :class="{ 'completed': ['done', 'wontdo'].includes(block.block_type) }"
            rows="1"
            placeholder="start writing..."
            ref="blockTextarea"
          ></textarea>
          <div
            v-if="showTagSuggestions"
            class="tag-suggestions"
            @mousedown.prevent
            role="listbox"
          >
            <button
              v-for="(page, idx) in tagSuggestions"
              :key="page.uuid || page.slug"
              type="button"
              role="option"
              :aria-selected="idx === tagSelectedIndex"
              class="tag-suggestion-item"
              :class="{ 'is-selected': idx === tagSelectedIndex }"
              @click="insertTagSuggestion(page)"
              @mouseenter="tagSelectedIndex = idx"
            >
              <span class="tag-suggestion-slug">#{{ page.slug }}</span>
              <span v-if="page.title && page.title !== page.slug" class="tag-suggestion-title">{{ page.title }}</span>
            </button>
          </div>
        </div>
        <button
          v-if="hasChildren && isCollapsed"
          @click="toggleCollapse"
          class="block-collapsed-indicator"
          :title="'Expand ' + childrenCount + ' hidden ' + (childrenCount === 1 ? 'block' : 'blocks')"
          :aria-label="'Expand ' + childrenCount + ' hidden ' + (childrenCount === 1 ? 'block' : 'blocks')"
        >… {{ childrenCount }}</button>
        <button
          v-if="block.scheduled_for"
          type="button"
          class="block-due-pill"
          :class="{ 'overdue': isOverdue }"
          @click.stop="scheduleBlock(block)"
          :title="'Scheduled ' + block.scheduled_for + (reminderTimeLabel ? ' · reminder at ' + reminderTimeLabel : '') + (isOverdue ? ' (overdue)' : '') + ' — click to change'"
        ><svg class="block-due-icon" viewBox="0 0 16 16" width="11" height="11" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><rect x="2" y="3" width="12" height="11" rx="1"/><line x1="2" y1="6.5" x2="14" y2="6.5"/><line x1="5.5" y1="1.5" x2="5.5" y2="4.5"/><line x1="10.5" y1="1.5" x2="10.5" y2="4.5"/></g></svg> {{ scheduledForLabel }}<span v-if="reminderTimeLabel"> · <svg class="block-due-icon" viewBox="0 0 16 16" width="11" height="11" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><circle cx="8" cy="8" r="6.25"/><polyline points="8,4.5 8,8 11,9.5"/></g></svg> <span v-if="reminderDateLabel">{{ reminderDateLabel }} </span>{{ reminderTimeLabel }}</span></button>
        <button
          v-else
          type="button"
          class="block-due-add"
          @click.stop="scheduleBlock(block)"
          title="Schedule this block"
          aria-label="Schedule this block"
        ><svg class="block-due-icon" viewBox="0 0 16 16" width="11" height="11" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><rect x="2" y="3" width="12" height="11" rx="1"/><line x1="2" y1="6.5" x2="14" y2="6.5"/><line x1="5.5" y1="1.5" x2="5.5" y2="4.5"/><line x1="10.5" y1="1.5" x2="10.5" y2="4.5"/></g></svg></button>
        <button
          @click="showContextMenuAt($event)"
          @contextmenu="showContextMenuAt($event)"
          class="block-menu"
          title="Block options"
        >⋮</button>
      </div>
      
      <!-- Context Menu -->
      <div v-if="showContextMenu" class="block-context-menu" :style="{ left: contextMenuPosition.x + 'px', top: contextMenuPosition.y + 'px' }" @click.stop @keydown="handleContextMenuKeydown" role="menu">
        <button class="context-menu-item" role="menuitem" tabindex="-1" v-if="hasChildren && isCollapsed" @click="handleContextMenuAction('expand')">
          <span class="context-menu-icon">▶</span>
          <span>expand</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" v-if="hasChildren && !isCollapsed" @click="handleContextMenuAction('collapse')">
          <span class="context-menu-icon">▼</span>
          <span>collapse</span>
        </button>
        <div class="context-menu-separator" v-if="hasChildren"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('indent')">
          <span class="context-menu-icon">→</span>
          <span>indent</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('outdent')">
          <span class="context-menu-icon">←</span>
          <span>outdent</span>
        </button>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('moveUp')">
          <span class="context-menu-icon">↑</span>
          <span>move up</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('moveDown')">
          <span class="context-menu-icon">↓</span>
          <span>move down</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('moveToToday')">
          <span class="context-menu-icon">⇨</span>
          <span>move to today's daily</span>
        </button>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('newBlockBefore')">
          <span class="context-menu-icon">+</span>
          <span>new block before</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('newBlockAfter')">
          <span class="context-menu-icon">+</span>
          <span>new block after</span>
        </button>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('attachFile')">
          <span class="context-menu-icon">▤</span>
          <span>attach file…</span>
        </button>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('schedule')">
          <span class="context-menu-icon"><svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><rect x="2" y="3" width="12" height="11" rx="1"/><line x1="2" y1="6.5" x2="14" y2="6.5"/><line x1="5.5" y1="1.5" x2="5.5" y2="4.5"/><line x1="10.5" y1="1.5" x2="10.5" y2="4.5"/></g></svg></span>
          <span>{{ block.scheduled_for ? 'reschedule...' : 'schedule...' }}</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" v-if="block.scheduled_for" @click="handleContextMenuAction('unschedule')">
          <span class="context-menu-icon">✕</span>
          <span>clear schedule</span>
        </button>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" v-if="!blockInContext" @click="handleContextMenuAction('addToContext')">
          <span class="context-menu-icon">+</span>
          <span>add to ai context</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" v-if="blockInContext" @click="handleContextMenuAction('removeFromContext')">
          <span class="context-menu-icon">-</span>
          <span>remove from ai context</span>
        </button>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item context-menu-danger" role="menuitem" tabindex="-1" @click="handleContextMenuAction('delete')">
          <span class="context-menu-icon">×</span>
          <span>delete</span>
        </button>
        <template v-if="showBulkSelectionActions()">
          <div class="context-menu-separator"></div>
          <button class="context-menu-item" role="menuitem" tabindex="-1" @click="handleContextMenuAction('bulkMoveToToday')">
            <span class="context-menu-icon">⇨</span>
            <span>move {{ selectedBlockCount }} selected to today</span>
          </button>
          <button class="context-menu-item context-menu-danger" role="menuitem" tabindex="-1" @click="handleContextMenuAction('bulkDelete')">
            <span class="context-menu-icon">×</span>
            <span>delete {{ selectedBlockCount }} selected</span>
          </button>
        </template>
      </div>
      
      <!-- Recursively render children -->
      <div v-if="block.children && block.children.length && !isCollapsed" class="block-children">
        <BlockComponent
          v-for="child in block.children"
          :key="child.uuid"
          :block="child"
          :onBlockContentChange="onBlockContentChange"
          :onBlockKeyDown="onBlockKeyDown"
          :startEditing="startEditing"
          :stopEditing="stopEditing"
          :deleteBlock="deleteBlock"
          :toggleBlockTodo="toggleBlockTodo"
          :formatContentWithTags="formatContentWithTags"
          :isBlockInContext="isBlockInContext"
          :isBlockSelected="isBlockSelected"
          :onBlockAddToContext="onBlockAddToContext"
          :onBlockRemoveFromContext="onBlockRemoveFromContext"
          :indentBlock="indentBlock"
          :outdentBlock="outdentBlock"
          :createBlockAfter="createBlockAfter"
          :createBlockBefore="createBlockBefore"
          :moveBlockUp="moveBlockUp"
          :moveBlockDown="moveBlockDown"
          :moveBlockToToday="moveBlockToToday"
          :onBlockPaste="onBlockPaste"
          :onBlockDrop="onBlockDrop"
          :onBlockAttachPick="onBlockAttachPick"
          :scheduleBlock="scheduleBlock"
          :onBlockSelectClick="onBlockSelectClick"
          :selectedBlockCount="selectedBlockCount"
          :bulkDeleteSelected="bulkDeleteSelected"
          :bulkMoveSelectedToToday="bulkMoveSelectedToToday"
          :selectionMode="selectionMode"
        />
      </div>
    </div>
  `,
};

// Parse embed-block content into a "title" portion and an array of trailing
// hashtag slugs. Trailing tags are stripped from the displayed title and
// rendered as chips on the embed card so the visible label stays clean.
BlockComponent.parseEmbedContent = function parseEmbedContent(content) {
  if (!content) return { title: "", tags: [] };
  const original = content;
  // Match a trailing run of `#tag` tokens. Either the first token sits at the
  // very start of the string, or every token is preceded by whitespace.
  const trailingRe = /(?:^|\s)#[a-zA-Z0-9_-]+(?:\s+#[a-zA-Z0-9_-]+)*\s*$/;
  const match = original.match(trailingRe);
  if (!match) return { title: original.trim(), tags: [] };
  const tagPart = match[0];
  const titlePart = original.slice(0, original.length - tagPart.length).trim();
  const tagMatches = tagPart.match(/#([a-zA-Z0-9_-]+)/g) || [];
  const seen = new Set();
  const tags = [];
  tagMatches.forEach((t) => {
    const slug = t.slice(1);
    if (!seen.has(slug)) {
      seen.add(slug);
      tags.push(slug);
    }
  });
  return { title: titlePart, tags };
};

// Convert a free-text input into a tag slug compatible with the existing
// hashtag regex (alphanumerics, underscore, hyphen). Spaces become hyphens.
BlockComponent.slugifyTag = function slugifyTag(raw) {
  if (!raw) return "";
  return String(raw)
    .trim()
    .toLowerCase()
    .replace(/^#+/, "")
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]/g, "")
    .replace(/^[-_]+|[-_]+$/g, "");
};

// Remove a `#slug` from content. Strips a single preceding whitespace
// character along with the tag so we don't leave a stray space behind.
// Slugs are [a-zA-Z0-9_-], none of which need regex escaping.
BlockComponent.removeTagFromContent = function removeTagFromContent(
  content,
  slug
) {
  if (!content || !slug) return content;
  const re = new RegExp(`(^|\\s)#${slug}(?![a-zA-Z0-9_-])`, "g");
  return content.replace(re, "").trimEnd();
};

// Make it available globally
window.BlockComponent = BlockComponent;
