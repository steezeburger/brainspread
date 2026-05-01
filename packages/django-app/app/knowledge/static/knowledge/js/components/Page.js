// Page Component - Complete page handler with data loading and rendering
const Page = {
  components: {
    BlockComponent: window.BlockComponent || {},
    Whiteboard: window.Whiteboard || {},
    ScheduleBlockPopover: window.ScheduleBlockPopover || {},
  },
  props: {
    chatContextBlocks: {
      type: Array,
      default: () => [],
    },
    isBlockInContext: {
      type: Function,
      default: () => () => false,
    },
  },
  emits: [
    "block-add-to-context",
    "block-remove-from-context",
    "visible-blocks-changed",
    "page-loaded",
  ],
  data() {
    return {
      // Page data
      pageSlug: this.getSlugFromURL(),
      currentDate: this.getDateFromURL(),
      page: null,
      directBlocks: [], // Blocks that belong directly to this page
      referencedBlocks: [], // Blocks from other pages that reference this page
      overdueBlocks: [], // Dated blocks past their due date (today's daily only)
      schedulePopoverOpen: false,
      schedulePopoverBlock: null,
      schedulePopoverInitialDate: "",
      schedulePopoverInitialReminderDate: "",
      schedulePopoverInitialTime: "",
      loading: false,
      error: null,
      // Page title editing
      isEditingTitle: false,
      newTitle: "",
      // Page menu
      showPageMenu: false,
      // Date selector for daily pages
      selectedDate: null,
      // Track blocks being deleted to prevent save conflicts
      deletingBlocks: new Set(),
      isNavigating: false,
      isIndentingOrOutdenting: false,
      lastEditingBlockUuid: null,
      // Block selection (Cmd+A escalation)
      selectionAnchorUuid: null,
      selectionLevel: 0,
      selectedBlockUuids: new Set(),
      // Multi-select mode: opt-in via the page's ⋮ menu. When on, plain
      // clicks on a block toggle it in/out of the selection instead of
      // entering edit mode, and a sticky toolbar shows bulk actions.
      selectionMode: false,
    };
  },

  computed: {
    isDaily() {
      return this.page?.page_type === "daily";
    },

    isWhiteboard() {
      return this.page?.page_type === "whiteboard";
    },

    pageTitle() {
      return this.page?.title || "untitled page";
    },

    totalDirectBlocks() {
      return this.directBlocks.length;
    },

    totalReferencedBlocks() {
      return this.referencedBlocks.length;
    },

    hasReferencedBlocks() {
      return this.referencedBlocks.length > 0;
    },

    selectedBlockCount() {
      return this.selectedBlockUuids.size;
    },

    totalOverdueBlocks() {
      return this.overdueBlocks.length;
    },

    hasOverdueBlocks() {
      return this.overdueBlocks.length > 0;
    },
  },

  async mounted() {
    // Add document click handler for closing menus
    document.addEventListener("click", this.handleDocumentClick);
    // Restore focus when window/tab regains focus
    window.addEventListener("focus", this.handleWindowFocus);
    // Global keydown for Escape to close page menus
    document.addEventListener("keydown", this.handlePageGlobalKeydown);
    // Selection escalation and copy
    document.addEventListener("keydown", this.handleSelectionKeydown);
    document.addEventListener("copy", this.handleSelectionCopy);
    // Spotlight command: new block
    document.addEventListener(
      "spotlight:new-block",
      this.handleSpotlightNewBlock
    );
    // Spotlight commands: bulk actions on the current selection
    document.addEventListener(
      "spotlight:bulk-delete",
      this.handleBulkDeleteSelected
    );
    document.addEventListener(
      "spotlight:bulk-move-to-today",
      this.handleBulkMoveSelectedToToday
    );
    // Re-enter editing after the AI chat panel closes (restores block focus).
    document.addEventListener(
      "resume-block-editing",
      this.handleResumeBlockEditing
    );
    // AI chat write tools dispatch this when they touch a page; reload
    // silently if it's the page we're viewing so the user sees the new
    // state without refreshing.
    window.addEventListener(
      "brainspread:notes-modified",
      this.handleNotesModified
    );
    // Embed cards fire this when the user clicks "archive". Archiving is
    // opt-in - we don't capture on paste/drop/save, only on request.
    document.addEventListener(
      "brainspread:request-archive",
      this.handleRequestArchive
    );
    // Load page data
    await this.loadPage();
  },

  beforeUnmount() {
    // Clean up event listeners
    document.removeEventListener("click", this.handleDocumentClick);
    window.removeEventListener("focus", this.handleWindowFocus);
    document.removeEventListener("keydown", this.handlePageGlobalKeydown);
    document.removeEventListener("keydown", this.handleSelectionKeydown);
    document.removeEventListener("copy", this.handleSelectionCopy);
    document.removeEventListener(
      "spotlight:new-block",
      this.handleSpotlightNewBlock
    );
    document.removeEventListener(
      "spotlight:bulk-delete",
      this.handleBulkDeleteSelected
    );
    document.removeEventListener(
      "spotlight:bulk-move-to-today",
      this.handleBulkMoveSelectedToToday
    );
    document.removeEventListener(
      "resume-block-editing",
      this.handleResumeBlockEditing
    );
    window.removeEventListener(
      "brainspread:notes-modified",
      this.handleNotesModified
    );
    document.removeEventListener(
      "brainspread:request-archive",
      this.handleRequestArchive
    );
  },

  methods: {
    getSlugFromURL() {
      const pathParts = window.location.pathname.split("/");
      const pageIndex = pathParts.indexOf("page");
      if (pageIndex !== -1 && pathParts[pageIndex + 1]) {
        return decodeURIComponent(pathParts[pageIndex + 1]);
      }
      return null;
    },

    getDateFromURL() {
      const slug = this.getSlugFromURL();
      if (slug && /^\d{4}-\d{2}-\d{2}$/.test(slug)) {
        return slug;
      }
      return null;
    },

    handleNotesModified(event) {
      // AI chat edited blocks / pages. Reload silently if the affected set
      // includes this page. Debounce so bursts of tool calls (common with
      // auto-approve) only trigger one reload.
      if (!this.page || !this.page.uuid) return;
      const pages = event?.detail?.page_uuids || [];
      if (!pages.includes(this.page.uuid)) return;
      if (this._notesModifiedTimer) {
        clearTimeout(this._notesModifiedTimer);
      }
      this._notesModifiedTimer = setTimeout(() => {
        this._notesModifiedTimer = null;
        // If the user is actively typing in a block on this page, skip
        // the reload — clobbering an in-progress edit would be worse than
        // showing stale state. They'll see the AI's changes the next time
        // they finish editing (which saves and reloads).
        const active = document.activeElement;
        if (
          active &&
          active.tagName === "TEXTAREA" &&
          this.$el &&
          this.$el.contains(active)
        ) {
          return;
        }
        this.loadPage({ silent: true });
      }, 300);
    },

    async loadPage({ silent = false } = {}) {
      if (!silent) this.loading = true;
      this.error = null;

      try {
        let result;

        // Use unified page loading - all pages go through the same API
        if (this.currentDate) {
          result = await window.apiService.getPageWithBlocks(
            null,
            this.currentDate
          );
        } else {
          result = await window.apiService.getPageWithBlocks(
            null,
            null,
            this.pageSlug
          );
        }

        if (result.success) {
          this.page = result.data.page;
          this.directBlocks = this.setupParentReferences(
            result.data.direct_blocks || []
          );
          this.referencedBlocks = result.data.referenced_blocks || [];
          this.overdueBlocks = result.data.overdue_blocks || [];
          this.$emit("page-loaded", this.page);
          // Flatten the block tree for consumers (e.g. ChatPanel's
          // ctx picker) that want a single list of every block on
          // the page, not just the root level.
          this.$emit(
            "visible-blocks-changed",
            this.flattenBlockTree(this.directBlocks)
          );
        } else {
          this.error = "failed to load page";
        }

        if (this.page) {
          this.newTitle = this.page.title || "";
          this.initializeDateSelector();
        }
      } catch (error) {
        console.error("failed to load page:", error);
        this.error = "failed to load page. does it exist?";
      } finally {
        this.loading = false;
      }
    },

    setupParentReferences(blocks, parent = null) {
      return blocks.map((blockData) => {
        const block = {
          ...blockData,
          parent: parent,
          children: [],
        };

        if (blockData.children && blockData.children.length > 0) {
          block.children = this.setupParentReferences(
            blockData.children,
            block
          );
        }

        return block;
      });
    },

    flattenBlockTree(blocks) {
      // Pre-order walk: root first, then its descendants, then the
      // next sibling. ChatPanel's ctx picker uses this list so users
      // can attach a deeply-nested block to context without first
      // expanding it on the page.
      const out = [];
      const walk = (items) => {
        for (const block of items || []) {
          out.push(block);
          if (block.children && block.children.length) {
            walk(block.children);
          }
        }
      };
      walk(blocks);
      return out;
    },

    async createBlock(
      content = "",
      parent = null,
      order = null,
      autoFocus = true
    ) {
      if (!this.page) return;

      try {
        const blockOrder = order !== null ? order : this.getNextOrder(parent);
        const result = await window.apiService.createBlock({
          page: this.page.uuid,
          content: content,
          parent: parent?.uuid ?? null,
          block_type: "bullet",
          content_type: "text",
          order: blockOrder,
        });

        if (result.success) {
          const newBlock = {
            uuid: result.data.uuid || `temp-${Date.now()}`,
            content: result.data.content || content,
            content_type: result.data.content_type || "text",
            block_type: result.data.block_type || "bullet",
            order: result.data.order || blockOrder,
            parent: parent,
            children: [],
            isEditing: false,
            collapsed: result.data.collapsed || false,
            properties: result.data.properties || {},
            media_url: result.data.media_url || "",
            media_metadata: result.data.media_metadata || {},
          };

          if (parent) {
            if (!parent.children) parent.children = [];
            parent.children.push(newBlock);
            parent.children.sort((a, b) => a.order - b.order);
          } else {
            this.directBlocks.push(newBlock);
            this.directBlocks.sort((a, b) => a.order - b.order);
          }

          if (autoFocus) {
            newBlock.isEditing = true;
            this.$nextTick(() => {
              this.$nextTick(() => {
                const textarea = document.querySelector(
                  `[data-block-uuid="${newBlock.uuid}"] textarea`
                );
                if (textarea) {
                  textarea.focus();
                  textarea.setSelectionRange(
                    textarea.value.length,
                    textarea.value.length
                  );
                }
              });
            });
          }
        }

        return result;
      } catch (error) {
        console.error("failed to create block:", error);
        this.error = "failed to create block";
        return { success: false };
      }
    },

    async updateBlock(block, newContent, skipReload = false) {
      try {
        const result = await window.apiService.updateBlock(block.uuid, {
          content: newContent,
          parent: block.parent ? block.parent.uuid : null,
        });

        if (result.success) {
          block.content = newContent;
          if (result.data && result.data.block_type) {
            block.block_type = result.data.block_type;
          }
          // Inline URL detection on save: if the user typed (or pasted
          // without the paste handler firing, e.g. mobile) a bare URL,
          // promote the block to an embed so the card renders. Archiving
          // is opt-in via the card's "archive" button.
          const trimmed = (newContent || "").trim();
          if (this.isBareUrl(trimmed) && block.content_type !== "embed") {
            block.content_type = "embed";
            block.media_url = trimmed;
            // Persist the embed flag so re-renders don't regress; don't
            // await - we don't want to block the caller's flow (e.g. Enter
            // to create next block).
            window.apiService
              .updateBlock(block.uuid, {
                content_type: "embed",
                media_url: trimmed,
              })
              .catch((err) => console.error("embed flag save failed", err));
          }
          if (!skipReload) {
            await this.loadPage();
          }
        }
      } catch (error) {
        console.error("failed to update block:", error);
        this.error = "failed to update block";
      }
    },

    async deleteBlock(block) {
      const confirmed = confirm(
        `are you sure you want to delete this block? this will also delete any child blocks and cannot be undone.`
      );

      if (!confirmed) return;

      try {
        const result = await window.apiService.deleteBlock(block.uuid);
        if (result.success) {
          await this.loadPage();
        }
      } catch (error) {
        console.error("failed to delete block:", error);
        this.error = "failed to delete block";
      }
    },

    async deleteEmptyBlock(block) {
      // Mark block as being deleted to prevent save conflicts
      this.deletingBlocks.add(block.uuid);

      // Find the previous block to focus after deletion
      const previousBlock = this.findPreviousBlock(block);

      try {
        await this.deleteBlock(block);

        // Focus the previous block if it exists
        if (previousBlock) {
          this.$nextTick(() => {
            this.startEditing(previousBlock);
            // Position cursor at the end of the previous block
            this.$nextTick(() => {
              const textarea = document.querySelector(
                `[data-block-uuid="${previousBlock.uuid}"] textarea`
              );
              if (textarea) {
                textarea.focus();
                textarea.setSelectionRange(
                  textarea.value.length,
                  textarea.value.length
                );
              }
            });
          });
        }
      } catch (error) {
        console.error("Failed to delete empty block:", error);
        // Remove from deleting set on error
        this.deletingBlocks.delete(block.uuid);
      } finally {
        // Clean up tracking after a delay to ensure blur events have processed
        setTimeout(() => {
          this.deletingBlocks.delete(block.uuid);
        }, 100);
      }
    },

    findPreviousBlock(currentBlock) {
      const allBlocks = this.getAllBlocks();
      const currentIndex = allBlocks.findIndex(
        (b) => b.uuid === currentBlock.uuid
      );
      return currentIndex > 0 ? allBlocks[currentIndex - 1] : null;
    },

    async toggleBlockTodo(block) {
      try {
        const result = await window.apiService.toggleBlockTodo(block.uuid);
        if (result.success) {
          block.block_type = result.data.block_type;
          block.content = result.data.content;
          this.error = null;
        } else {
          this.error =
            result.errors?.non_field_errors?.[0] || "Failed to toggle todo";
        }
      } catch (error) {
        console.error("failed to toggle block todo:", error);
        this.error = "failed to toggle todo. please try again.";
      }
    },

    getNextOrder(parent) {
      const siblings = parent ? parent.children : this.directBlocks;
      return siblings.length > 0
        ? Math.max(...siblings.map((b) => b.order)) + 1
        : 0;
    },

    async createBlockAfter(currentBlock) {
      const newOrder = currentBlock.order + 1;
      const siblings = currentBlock.parent
        ? currentBlock.parent.children
        : this.directBlocks;

      const blocksToShift = siblings.filter(
        (block) => block.uuid !== currentBlock.uuid && block.order >= newOrder
      );

      try {
        const reorderPayload = blocksToShift.map((block) => {
          block.order = block.order + 1;
          return { uuid: block.uuid, order: block.order };
        });

        if (reorderPayload.length > 0) {
          const result = await window.apiService.reorderBlocks(reorderPayload);
          if (!result.success) throw new Error("failed to reorder blocks");
        }

        await this.createBlock("", currentBlock.parent, newOrder);
      } catch (error) {
        console.error("failed to create block after:", error);
        this.error = "failed to create block";
      }
    },

    async createBlockBefore(currentBlock) {
      const newOrder = currentBlock.order;
      const siblings = currentBlock.parent
        ? currentBlock.parent.children
        : this.directBlocks;

      const blocksToShift = siblings.filter((block) => block.order >= newOrder);

      try {
        const reorderPayload = blocksToShift.map((block) => {
          block.order = block.order + 1;
          return { uuid: block.uuid, order: block.order };
        });

        if (reorderPayload.length > 0) {
          const result = await window.apiService.reorderBlocks(reorderPayload);
          if (!result.success) throw new Error("failed to reorder blocks");
        }

        await this.createBlock("", currentBlock.parent, newOrder);
      } catch (error) {
        console.error("failed to create block before:", error);
        this.error = "failed to create block";
      }
    },

    async moveBlockUp(block) {
      const siblings = block.parent ? block.parent.children : this.directBlocks;
      const currentIndex = siblings.findIndex((b) => b.uuid === block.uuid);

      // Can't move up if already at the top
      if (currentIndex <= 0) return;

      try {
        // Save current content first
        await this.updateBlock(block, block.content, true);

        // Get the block above this one
        const blockAbove = siblings[currentIndex - 1];

        // Swap their orders
        const tempOrder = block.order;
        block.order = blockAbove.order;
        blockAbove.order = tempOrder;

        const result = await window.apiService.reorderBlocks([
          { uuid: block.uuid, order: block.order },
          { uuid: blockAbove.uuid, order: blockAbove.order },
        ]);

        if (!result.success) throw new Error("reorder failed");

        // Update local state - re-sort siblings
        siblings.sort((a, b) => a.order - b.order);

        // Refresh page data without unmounting blocks (preserves focus)
        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("failed to move block up:", error);
        this.error = "failed to move block up";
      }
    },

    async moveBlockDown(block) {
      const siblings = block.parent ? block.parent.children : this.directBlocks;
      const currentIndex = siblings.findIndex((b) => b.uuid === block.uuid);

      // Can't move down if already at the bottom
      if (currentIndex >= siblings.length - 1) return;

      try {
        // Save current content first
        await this.updateBlock(block, block.content, true);

        // Get the block below this one
        const blockBelow = siblings[currentIndex + 1];

        // Swap their orders
        const tempOrder = block.order;
        block.order = blockBelow.order;
        blockBelow.order = tempOrder;

        const result = await window.apiService.reorderBlocks([
          { uuid: block.uuid, order: block.order },
          { uuid: blockBelow.uuid, order: blockBelow.order },
        ]);

        if (!result.success) throw new Error("reorder failed");

        // Update local state - re-sort siblings
        siblings.sort((a, b) => a.order - b.order);

        // Refresh page data without unmounting blocks (preserves focus)
        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("failed to move block down:", error);
        this.error = "failed to move block down";
      }
    },

    async moveBlockToToday(block) {
      try {
        // Save in-progress edits before moving
        if (block.isEditing) {
          await this.updateBlock(block, block.content, true);
        }

        const result = await window.apiService.moveBlockToDaily(block.uuid);

        if (!result.success) {
          throw new Error("move to today failed");
        }

        const targetTitle = result.data?.target_page?.title || "today";
        if (result.data?.moved) {
          this.$parent?.addToast?.(`moved block to ${targetTitle}`, "success");
        } else {
          this.$parent?.addToast?.(
            result.data?.message || "block already on today's daily",
            "info"
          );
        }

        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("failed to move block to today:", error);
        this.error = "failed to move block to today";
        this.$parent?.addToast?.("failed to move block to today", "error");
      }
    },

    onBlockContentChange(block, newContent) {
      // Just update the local content, don't save yet
      block.content = newContent;
    },

    async onBlockKeyDown(event, block) {
      // Alt+Shift+ArrowUp/Down: move block
      if (event.altKey && event.shiftKey && event.key === "ArrowUp") {
        event.preventDefault();
        const cursorPos = event.target.selectionStart;
        const wasEditing = block.isEditing;
        await this.moveBlockUp(block);
        this.restoreBlockFocus(block.uuid, wasEditing, cursorPos);
        return;
      }
      if (event.altKey && event.shiftKey && event.key === "ArrowDown") {
        event.preventDefault();
        const cursorPos = event.target.selectionStart;
        const wasEditing = block.isEditing;
        await this.moveBlockDown(block);
        this.restoreBlockFocus(block.uuid, wasEditing, cursorPos);
        return;
      }
      // Cmd/Ctrl+Shift+Backspace: delete block
      if (
        (event.metaKey || event.ctrlKey) &&
        event.shiftKey &&
        event.key === "Backspace"
      ) {
        event.preventDefault();
        await this.deleteBlock(block);
        return;
      }
      // Cmd/Ctrl+. or Shift+F10: open context menu for this block
      if (
        ((event.metaKey || event.ctrlKey) && event.key === ".") ||
        (event.shiftKey && event.key === "F10")
      ) {
        event.preventDefault();
        document.dispatchEvent(
          new CustomEvent("openBlockContextMenu", {
            detail: { uuid: block.uuid },
          })
        );
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        await this.updateBlock(block, block.content, true);
        block.isEditing = false;
        // Return focus to the display element so tab navigation continues
        this.$nextTick(() => {
          const display = document.querySelector(
            `[data-block-uuid="${block.uuid}"] .block-content-display`
          );
          if (display) display.focus();
        });
        return;
      } else if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        // Save current block before creating new one
        await this.updateBlock(block, block.content, true);
        await this.createBlockAfter(block);
      } else if (
        event.key === "Backspace" &&
        block.content.trim() === "" &&
        event.target.selectionStart === 0
      ) {
        event.preventDefault();
        // If block has children (is a parent), delete it and go to previous block
        if (block.children && block.children.length > 0) {
          await this.deleteEmptyBlock(block);
        } else if (block.parent) {
          // If block has no children but has a parent, unindent it
          await this.outdentBlock(block);
        } else {
          // If block is at root level with no children, delete it
          await this.deleteEmptyBlock(block);
        }
      } else if (event.key === " " || event.key === "Spacebar") {
        // Handle double-space indentation for mobile users (mobile might use "Spacebar" instead of " ")
        const textarea = event.target;
        const currentContent = textarea.value;
        const cursorPos = textarea.selectionStart;

        // Check if the previous character is also a space (double-space) AND we're at the beginning of the block
        if (
          cursorPos > 0 &&
          currentContent[cursorPos - 1] === " " &&
          cursorPos <= 2
        ) {
          event.preventDefault();
          // Remove the current space that would be added and the previous space
          const newContent =
            currentContent.slice(0, cursorPos - 1) +
            currentContent.slice(cursorPos);
          block.content = newContent;

          // Update textarea value and cursor position
          textarea.value = newContent;
          textarea.setSelectionRange(cursorPos - 1, cursorPos - 1);

          // Save current content and indent the block
          await this.updateBlock(block, newContent, true);
          await this.indentBlock(block);
        }
      } else if (event.key === "Tab") {
        event.preventDefault();
        if (event.shiftKey) {
          // Outdent - move block to parent's level
          await this.outdentBlock(block);
        } else {
          // Indent - make this block a child of the previous sibling
          await this.indentBlock(block);
        }
      } else if (event.key === "ArrowDown") {
        const textarea = event.target;
        const cursorPos = textarea.selectionStart;
        const value = textarea.value;

        // For single line content, check if cursor is at end
        if (value.indexOf("\n") === -1) {
          // Single line - if cursor is at end, move to next block
          if (cursorPos === value.length) {
            event.preventDefault();
            this.focusNextBlock(block);
          }
        } else {
          // Multi-line content
          const lines = value.substr(0, cursorPos).split("\n");
          const currentLine = lines.length - 1;
          const totalLines = value.split("\n").length;

          // If cursor is on the last line, move to next block
          if (currentLine === totalLines - 1) {
            event.preventDefault();
            this.focusNextBlock(block);
          }
        }
      } else if (event.key === "ArrowUp") {
        const textarea = event.target;
        const cursorPos = textarea.selectionStart;
        const value = textarea.value;

        // For single line content, check if cursor is at beginning
        if (value.indexOf("\n") === -1) {
          // Single line - if cursor is at beginning, move to previous block
          if (cursorPos === 0) {
            event.preventDefault();
            this.focusPreviousBlock(block);
          }
        } else {
          // Multi-line content
          const lines = value.substr(0, cursorPos).split("\n");
          const currentLine = lines.length - 1;

          // If cursor is on the first line, move to previous block
          if (currentLine === 0) {
            event.preventDefault();
            this.focusPreviousBlock(block);
          }
        }
      }
    },

    addNewBlock() {
      this.createBlock("");
    },

    async indentBlock(block) {
      // Find the previous sibling block to make it the parent
      const previousSibling = this.findPreviousSibling(block);
      if (!previousSibling) return; // Can't indent if no previous sibling

      this.isIndentingOrOutdenting = true;
      try {
        // Save current content first
        await this.updateBlock(block, block.content, true);

        // Update the block's parent and order
        const newOrder = this.getNextChildOrder(previousSibling);
        const result = await window.apiService.updateBlock(block.uuid, {
          parent: previousSibling.uuid,
          order: newOrder,
        });

        if (result.success) {
          // Update local state
          this.removeBlockFromCurrentParent(block);

          // Add to new parent's children
          if (!previousSibling.children) previousSibling.children = [];
          block.parent = previousSibling;
          block.order = newOrder;
          previousSibling.children.push(block);
          previousSibling.children.sort((a, b) => a.order - b.order);

          // Re-enter editing mode (blur may have fired during DOM update) and focus
          this.$nextTick(() => {
            block.isEditing = true;
            this.$nextTick(() => {
              this.isIndentingOrOutdenting = false;
              const textarea = document.querySelector(
                `[data-block-uuid="${block.uuid}"] textarea`
              );
              if (textarea) textarea.focus();
            });
          });
        }
      } catch (error) {
        this.isIndentingOrOutdenting = false;
        console.error("Failed to indent block:", error);
      }
    },

    async outdentBlock(block) {
      if (!block.parent) return; // Already at root level

      this.isIndentingOrOutdenting = true;
      try {
        // Save current content first
        await this.updateBlock(block, block.content, true);

        // Move to parent's level, right after parent
        const grandparent = block.parent.parent;
        const newOrder = block.parent.order + 1;

        // Update orders of siblings that come after the parent
        await this.updateSiblingOrders(grandparent, newOrder);

        const result = await window.apiService.updateBlock(block.uuid, {
          parent: grandparent ? grandparent.uuid : null,
          order: newOrder,
        });

        if (result.success) {
          // Update local state
          this.removeBlockFromCurrentParent(block);

          // Add to new parent level
          block.parent = grandparent;
          block.order = newOrder;

          if (grandparent) {
            if (!grandparent.children) grandparent.children = [];
            grandparent.children.push(block);
            grandparent.children.sort((a, b) => a.order - b.order);
          } else {
            this.directBlocks.push(block);
            this.directBlocks.sort((a, b) => a.order - b.order);
          }

          // Re-enter editing mode (blur may have fired during DOM update) and focus
          this.$nextTick(() => {
            block.isEditing = true;
            this.$nextTick(() => {
              this.isIndentingOrOutdenting = false;
              const textarea = document.querySelector(
                `[data-block-uuid="${block.uuid}"] textarea`
              );
              if (textarea) textarea.focus();
            });
          });
        }
      } catch (error) {
        this.isIndentingOrOutdenting = false;
        console.error("Failed to outdent block:", error);
      }
    },

    findPreviousSibling(block) {
      const siblings = block.parent ? block.parent.children : this.directBlocks;
      const currentIndex = siblings.findIndex((b) => b.uuid === block.uuid);
      return currentIndex > 0 ? siblings[currentIndex - 1] : null;
    },

    getNextChildOrder(parentBlock) {
      if (!parentBlock.children || parentBlock.children.length === 0) return 0;
      return Math.max(...parentBlock.children.map((child) => child.order)) + 1;
    },

    removeBlockFromCurrentParent(block) {
      if (block.parent) {
        const parentChildren = block.parent.children || [];
        const index = parentChildren.findIndex(
          (child) => child.uuid === block.uuid
        );
        if (index !== -1) {
          parentChildren.splice(index, 1);
        }
      } else {
        const index = this.directBlocks.findIndex((b) => b.uuid === block.uuid);
        if (index !== -1) {
          this.directBlocks.splice(index, 1);
        }
      }
    },

    async updateSiblingOrders(parent, fromOrder) {
      const siblings = parent ? parent.children : this.directBlocks;
      const reorderPayload = [];

      for (const sibling of siblings) {
        if (sibling.order >= fromOrder) {
          sibling.order += 1;
          reorderPayload.push({ uuid: sibling.uuid, order: sibling.order });
        }
      }

      if (reorderPayload.length === 0) return;

      const result = await window.apiService.reorderBlocks(reorderPayload);
      if (!result.success) throw new Error("failed to reorder siblings");
    },

    formatContentWithTags(content, blockType = null, properties = null) {
      if (!content) return "";

      // Code blocks render as <pre><code> with content escaped and no other
      // markdown formatting applied. Mermaid is a special case: the source
      // is stashed on a placeholder element which BlockComponent renders
      // to SVG via the mermaid library after mount.
      if (blockType === "code") {
        const escapeHtml = (s) =>
          s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const lang = properties?.language || "";
        const langBadge = lang
          ? `<span class="block-code-lang">${escapeHtml(lang)}</span>`
          : "";
        if (lang.toLowerCase() === "mermaid") {
          // Encode the source via attribute escaping. Quotes are the only
          // characters that need extra handling beyond the standard set
          // since the value sits inside a double-quoted attribute.
          const attrEscaped = escapeHtml(content).replace(/"/g, "&quot;");
          return `<div class="block-mermaid-wrapper">${langBadge}<div class="block-mermaid" data-mermaid-source="${attrEscaped}"></div></div>`;
        }
        const escaped = escapeHtml(content);
        return `<div class="block-code-wrapper">${langBadge}<pre class="block-code"><code>${escaped}</code></pre></div>`;
      }

      let formatted = content;

      // Strip todo-state prefix from display since the checkbox already shows state
      if (
        blockType &&
        ["todo", "doing", "done", "later", "wontdo"].includes(blockType)
      ) {
        formatted = formatted.replace(
          /^(WONTDO|LATER|DOING|DONE|TODO)\s*:?\s*/i,
          ""
        );
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
      // the brackets. Stored as placeholders and restored as <a> tags at the
      // end so emphasis/etc inside the link text still gets formatted.
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

      // Replace all bold and italic markdown ***text*** with styled spans (must be first)
      formatted = formatted.replace(
        /\*\*\*(.+?)\*\*\*/g,
        '<span class="markdown-bold-italic">$1</span>'
      );

      // Replace bold markdown **text** with styled spans
      formatted = formatted.replace(
        /\*\*(.+?)\*\*/g,
        '<span class="markdown-bold">$1</span>'
      );

      // Replace bold markdown __text__ with styled spans
      formatted = formatted.replace(
        /__(.+?)__/g,
        '<span class="markdown-bold">$1</span>'
      );

      // Replace italic markdown *text* with styled spans (single asterisks)
      formatted = formatted.replace(
        /\*([^*]+?)\*/g,
        '<span class="markdown-italic">$1</span>'
      );

      // Replace italic markdown _text_ with styled spans (single underscores)
      formatted = formatted.replace(
        /_([^_]+?)_/g,
        '<span class="markdown-italic">$1</span>'
      );

      // Replace strikethrough markdown ~~text~~ with styled spans
      formatted = formatted.replace(
        /~~(.+?)~~/g,
        '<span class="markdown-strikethrough">$1</span>'
      );

      // Replace highlight markdown ==text== with styled spans
      formatted = formatted.replace(
        /==(.+?)==/g,
        '<span class="markdown-highlight">$1</span>'
      );

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

      // Linkify bare URLs (https://, http://, www.) that aren't already
      // wrapped in a markdown link placeholder.
      formatted = formatted.replace(
        /(^|[\s(])((?:https?:\/\/|www\.)[^\s<>"]+[^\s<>".,;:!?)])/g,
        (_match, lead, url) => {
          const safe = this.safeUrl(url);
          if (!safe) return _match;
          return `${lead}<a class="markdown-link" href="${this.escapeAttr(safe)}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(url)}</a>`;
        }
      );

      // Restore markdown link placeholders as <a> tags. URL is escaped into
      // the href attribute; unsafe schemes fall back to plain text.
      linkSegments.forEach(({ text, url }, idx) => {
        const safe = this.safeUrl(url);
        const replacement = safe
          ? `<a class="markdown-link" href="${this.escapeAttr(safe)}" target="_blank" rel="noopener noreferrer">${text}</a>`
          : `[${text}](${this.escapeHtml(url)})`;
        formatted = formatted.split(`\x00LINK${idx}\x00`).join(replacement);
      });

      // Replace hashtags with clickable anchor elements so browsers support cmd+click, middle-click, right-click → open in new tab
      formatted = formatted.replace(
        /#([a-zA-Z0-9_-]+)/g,
        '<a class="inline-tag clickable-tag" href="/knowledge/page/$1/" data-tag="$1">#$1</a>'
      );

      // Restore escaped characters as literal text (done last so escaped `#`
      // doesn't get re-matched by the hashtag regex).
      escapedChars.forEach((char, idx) => {
        formatted = formatted.split(`\x00ESC${idx}\x00`).join(char);
      });

      return formatted;
    },

    safeUrl(rawUrl) {
      if (!rawUrl) return null;
      const trimmed = String(rawUrl).trim();
      if (!trimmed) return null;
      // Block dangerous schemes outright.
      if (/^(javascript|data|vbscript|file):/i.test(trimmed)) return null;
      // Bare www. → assume https.
      if (/^www\./i.test(trimmed)) return "https://" + trimmed;
      // Trusted schemes pass through.
      if (/^(https?:|mailto:|tel:|\/|#)/i.test(trimmed)) return trimmed;
      // Anything else (e.g. some.com without scheme) → treat as https.
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

    handleWindowFocus() {
      if (this.lastEditingBlockUuid) {
        const block = this.getAllBlocks().find(
          (b) => b.uuid === this.lastEditingBlockUuid
        );
        if (block) {
          this.startEditing(block);
        }
      }
    },

    handleResumeBlockEditing(event) {
      const uuid = event?.detail?.uuid;
      if (!uuid) return;
      const block = this.getAllBlocks().find((b) => b.uuid === uuid);
      if (block) this.startEditing(block);
    },

    startEditing(block) {
      this.lastEditingBlockUuid = block.uuid;
      // Clear any block selection when entering edit mode
      if (this.selectionAnchorUuid) {
        this.clearBlockSelection();
      }
      // Stop editing all other blocks first (save them)
      const allBlocks = this.getAllBlocks();
      allBlocks.forEach((b) => {
        if (b.uuid !== block.uuid && b.isEditing) {
          this.updateBlock(b, b.content, true); // Save without reload
          b.isEditing = false;
        }
      });

      block.isEditing = true;
      this.$nextTick(() => {
        // Focus the specific textarea for this block
        const blockElement = document.querySelector(
          `[data-block-uuid="${block.uuid}"] textarea`
        );
        if (blockElement) {
          blockElement.focus();
        }
      });
    },

    async stopEditing(block) {
      // Don't stop editing if we're navigating between blocks
      if (this.isNavigating) {
        this.isNavigating = false;
        return;
      }

      // Don't stop editing during indent/outdent; content is already saved there
      if (this.isIndentingOrOutdenting) {
        return;
      }

      // Don't try to save blocks that are being deleted
      if (this.deletingBlocks.has(block.uuid)) {
        block.isEditing = false;
        return;
      }

      // Close the editor immediately on blur. If startEditing runs during
      // the save await (e.g. restoreBlockFocus after a move), it will set
      // isEditing=true again, which we leave alone.
      block.isEditing = false;
      await this.updateBlock(block, block.content, true);
    },

    getAllBlocks() {
      // Get all blocks in document order (flattened tree)
      const result = [];
      const addBlocks = (blocks) => {
        for (const block of blocks) {
          result.push(block);
          if (block.children && block.children.length) {
            addBlocks(block.children);
          }
        }
      };
      addBlocks(this.directBlocks);
      return result;
    },

    restoreBlockFocus(uuid, wasEditing, cursorPos) {
      this.$nextTick(() => {
        this.$nextTick(() => {
          const newBlock = this.getAllBlocks().find((b) => b.uuid === uuid);
          if (!newBlock) return;
          if (wasEditing) {
            this.startEditing(newBlock);
            if (typeof cursorPos === "number") {
              this.$nextTick(() => {
                const textarea = document.querySelector(
                  `[data-block-uuid="${uuid}"] textarea`
                );
                if (textarea) {
                  textarea.setSelectionRange(cursorPos, cursorPos);
                }
              });
            }
          } else {
            const display = document.querySelector(
              `[data-block-uuid="${uuid}"] .block-content-display`
            );
            if (display) display.focus();
          }
        });
      });
    },

    focusNextBlock(currentBlock) {
      const allBlocks = this.getAllBlocks();
      const currentIndex = allBlocks.findIndex(
        (b) => b.uuid === currentBlock.uuid
      );

      if (currentIndex >= 0 && currentIndex < allBlocks.length - 1) {
        const nextBlock = allBlocks[currentIndex + 1];
        this.isNavigating = true;
        this.startEditing(nextBlock);
      }
    },

    focusPreviousBlock(currentBlock) {
      const allBlocks = this.getAllBlocks();
      const currentIndex = allBlocks.findIndex(
        (b) => b.uuid === currentBlock.uuid
      );

      if (currentIndex > 0) {
        const previousBlock = allBlocks[currentIndex - 1];
        this.isNavigating = true;
        this.startEditing(previousBlock);
      }
    },

    // Page management methods
    togglePageMenu() {
      this.showPageMenu = !this.showPageMenu;
      if (this.showPageMenu) {
        this.$nextTick(() => {
          const firstItem = this.$el?.querySelector(
            ".context-menu-container .context-menu .context-menu-item"
          );
          if (firstItem) firstItem.focus();
        });
      }
    },

    closePageMenu() {
      this.showPageMenu = false;
    },

    closePageMenuAndRestoreFocus() {
      this.closePageMenu();
      this.$nextTick(() => {
        const menuBtn = this.$el?.querySelector(".context-menu-btn");
        if (menuBtn) menuBtn.focus();
      });
    },

    handlePageMenuKeydown(event) {
      const items = Array.from(
        this.$el?.querySelectorAll(
          ".context-menu-container .context-menu .context-menu-item"
        ) || []
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
        case "Escape":
        case "Tab":
          event.preventDefault();
          this.closePageMenuAndRestoreFocus();
          break;
        case "Home":
          event.preventDefault();
          items[0].focus();
          break;
        case "End":
          event.preventDefault();
          items[items.length - 1].focus();
          break;
      }
    },

    handlePageGlobalKeydown(event) {
      if (event.key === "Escape") {
        if (this.showPageMenu) {
          this.closePageMenuAndRestoreFocus();
        } else if (this.selectionMode) {
          this.exitSelectionMode();
        } else if (this.selectionAnchorUuid) {
          this.clearBlockSelection();
        }
        return;
      }
      // Cmd/Ctrl+Shift+; opens the schedule popover for the currently
      // focused block. (Cmd+Shift+D is Chrome's "bookmark all tabs" — the
      // semicolon has no obvious mnemonic but doesn't fight any browser.)
      // Falls back to the last-edited block if focus has already left the
      // textarea.
      if (
        (event.metaKey || event.ctrlKey) &&
        event.shiftKey &&
        event.key === ";"
      ) {
        const block = this.findFocusedOrLastEditingBlock();
        if (!block) return;
        event.preventDefault();
        this.scheduleBlock(block);
      }
    },

    findFocusedOrLastEditingBlock() {
      // Prefer the block whose textarea / display element actually has focus.
      const active = document.activeElement;
      const wrapper = active?.closest?.("[data-block-uuid]");
      const focusedUuid = wrapper?.getAttribute("data-block-uuid");
      const uuid = focusedUuid || this.lastEditingBlockUuid;
      if (!uuid) return null;
      return this.getAllBlocks().find((b) => b.uuid === uuid) || null;
    },

    handleSpotlightNewBlock() {
      this.addNewBlock();
    },

    handleDocumentClick(event) {
      const contextMenuContainer = event.target.closest(
        ".context-menu-container"
      );
      if (!contextMenuContainer && this.showPageMenu) {
        this.closePageMenu();
      }
      // Clear block selection when clicking outside any block
      if (this.selectionAnchorUuid) {
        const clickedBlock = event.target.closest("[data-block-uuid]");
        if (!clickedBlock) {
          this.clearBlockSelection();
        }
      }
    },

    async deletePage() {
      if (!this.page) return;

      const confirmed = confirm(
        `Are you sure you want to delete the page "${this.page.title}"? This will also delete all direct blocks and cannot be undone.`
      );

      if (!confirmed) return;

      try {
        const result = await window.apiService.deletePage(this.page.uuid);
        if (result.success) {
          this.closePageMenu();
          // Navigate to today's page after deletion
          const today = new Date();
          const year = today.getFullYear();
          const month = String(today.getMonth() + 1).padStart(2, "0");
          const day = String(today.getDate()).padStart(2, "0");
          const todayString = `${year}-${month}-${day}`;
          window.location.href = `/knowledge/page/${todayString}/`;
        } else {
          this.error = "failed to delete page";
        }
      } catch (error) {
        console.error("failed to delete page:", error);
        this.error = "failed to delete page";
      }
    },

    async scheduleBlock(block, { clear = false } = {}) {
      if (!block) return;

      if (clear) {
        await this._submitSchedule(block, "", "", "");
        return;
      }

      this.schedulePopoverBlock = block;
      this.schedulePopoverInitialDate = block.scheduled_for || "";
      this.schedulePopoverInitialReminderDate =
        block.pending_reminder_date || "";
      this.schedulePopoverInitialTime = block.pending_reminder_time || "";
      this.schedulePopoverOpen = true;
    },

    onSchedulePopoverSave({ scheduledFor, reminderDate, reminderTime }) {
      const block = this.schedulePopoverBlock;
      this.schedulePopoverOpen = false;
      this.schedulePopoverBlock = null;
      if (!block) return;
      this._submitSchedule(block, scheduledFor, reminderDate, reminderTime);
    },

    onSchedulePopoverCancel() {
      this.schedulePopoverOpen = false;
      this.schedulePopoverBlock = null;
    },

    async _submitSchedule(block, scheduledFor, reminderDate, reminderTime) {
      try {
        const result = await window.apiService.scheduleBlock(
          block.uuid,
          scheduledFor,
          reminderDate,
          reminderTime
        );
        if (result.success) {
          let msg;
          if (!scheduledFor) {
            msg = "schedule cleared";
          } else if (reminderTime) {
            const formatted =
              window.formatTimeForUser?.(reminderTime) || reminderTime;
            const onDate =
              reminderDate && reminderDate !== scheduledFor
                ? ` on ${reminderDate}`
                : "";
            msg = `scheduled for ${scheduledFor} · remind${onDate} at ${formatted}`;
          } else {
            msg = `scheduled for ${scheduledFor}`;
          }
          this.$parent?.addToast?.(msg, "success");
          await this.loadPage({ silent: true });
        } else {
          this.$parent?.addToast?.("failed to schedule block", "error");
        }
      } catch (err) {
        console.error("scheduleBlock failed:", err);
        this.$parent?.addToast?.("failed to schedule block", "error");
      }
    },

    async moveUndoneTodos() {
      if (!this.page) return;

      try {
        const targetDate = this.isDaily
          ? this.currentDate || this.page.date
          : null;
        const result = await window.apiService.moveUndoneTodos(targetDate);

        if (result.success) {
          this.closePageMenu();
          const movedCount = result.data.moved_count;
          const message = result.data.message;

          if (movedCount > 0) {
            this.$parent.addToast(
              `moved ${movedCount} undone TODOs to ${this.page.title}`,
              "success"
            );
            // Reload the page to show the moved todos
            await this.loadPage();
          } else {
            this.$parent.addToast(
              message || "no undone TODOs found to move",
              "info"
            );
          }
        } else {
          this.error = "failed to move undone TODOs";
          this.$parent.addToast("failed to move undone TODOs", "error");
        }
      } catch (error) {
        console.error("failed to move undone TODOs:", error);
        this.error = "failed to move undone TODOs";
        this.$parent.addToast("failed to move undone TODOs", "error");
      }
    },

    // Title editing methods
    startEditingTitle() {
      this.isEditingTitle = true;
      this.newTitle = this.page?.title || "";
      this.$nextTick(() => {
        const input = this.$refs.titleInput;
        if (input) {
          input.focus();
          input.select();
        }
      });
    },

    cancelEditingTitle() {
      this.isEditingTitle = false;
      this.newTitle = this.page?.title || "";
    },

    onWhiteboardPageUpdated(updatedPage) {
      if (this.page && updatedPage) {
        this.page.modified_at = updatedPage.modified_at;
      }
    },

    async updatePageTitle() {
      if (!this.page || !this.newTitle.trim()) {
        this.isEditingTitle = false;
        this.newTitle = this.page?.title || "";
        return;
      }

      try {
        const oldSlug = this.page.slug;
        const result = await window.apiService.updatePage(this.page.uuid, {
          title: this.newTitle.trim(),
        });

        if (result.success) {
          this.page.title = this.newTitle.trim();
          this.page.slug = result.data.slug;
          this.isEditingTitle = false;
          this.$parent.addToast("page title updated successfully", "success");

          // Redirect to new URL if slug changed
          if (oldSlug !== result.data.slug) {
            window.location.href = `/knowledge/page/${encodeURIComponent(result.data.slug)}/`;
          }
        } else {
          this.error = "failed to update page title";
        }
      } catch (error) {
        console.error("failed to update page title:", error);
        this.error = "failed to update page title";
      }
    },

    // Date navigation methods
    onDateChange() {
      if (this.selectedDate) {
        window.location.href = `/knowledge/page/${this.selectedDate}/`;
      }
    },

    initializeDateSelector() {
      if (this.isDaily && this.page?.date) {
        this.selectedDate = this.page.date;
      }
    },

    formatDate(dateString) {
      const [year, month, day] = dateString.split("-");
      const date = new Date(parseInt(year), parseInt(month) - 1, parseInt(day));
      return date.toLocaleDateString();
    },

    // Context management methods
    onBlockAddToContext(block) {
      this.$emit("block-add-to-context", block);
    },

    onBlockRemoveFromContext(blockId) {
      this.$emit("block-remove-from-context", blockId);
    },

    // Markdown list paste handling
    parseMarkdownList(text) {
      if (!text) return [];

      const lines = text.replace(/\r\n?/g, "\n").split("\n");
      const items = [];
      let sawFirstNonEmpty = false;

      // Code fence state
      let codeFenceOpen = false;
      let codeFenceIndentStr = "";
      let codeFenceIndent = 0;
      let codeFenceLang = "";
      let codeFenceLines = [];

      const finishCodeFence = () => {
        // Strip the fence's leading whitespace from each collected line
        const stripped = codeFenceLines.map((l) =>
          l.startsWith(codeFenceIndentStr)
            ? l.slice(codeFenceIndentStr.length)
            : l
        );
        const item = {
          indent: codeFenceIndent,
          content: stripped.join("\n"),
          blockType: "code",
        };
        if (codeFenceLang) item.language = codeFenceLang;
        items.push(item);
        codeFenceOpen = false;
        codeFenceIndentStr = "";
        codeFenceIndent = 0;
        codeFenceLang = "";
        codeFenceLines = [];
      };

      for (const line of lines) {
        // Check for fence markers (``` optionally followed by a language)
        const fenceMatch = line.match(/^([ \t]*)```(.*)$/);

        if (codeFenceOpen) {
          if (fenceMatch) {
            // Closing fence — regardless of language suffix
            finishCodeFence();
          } else {
            codeFenceLines.push(line);
          }
          continue;
        }

        if (fenceMatch) {
          // Opening fence: only intercept if we've started processing a list
          if (!sawFirstNonEmpty) return [];
          const leading = fenceMatch[1];
          codeFenceOpen = true;
          codeFenceIndentStr = leading;
          codeFenceIndent = leading.replace(/\t/g, "  ").length;
          codeFenceLang = fenceMatch[2].trim();
          codeFenceLines = [];
          sawFirstNonEmpty = true;
          continue;
        }

        if (!line.trim()) continue;

        const leadingMatch = line.match(/^[ \t]*/);
        const leading = leadingMatch ? leadingMatch[0] : "";
        const rest = line.slice(leading.length);

        // Normalize tabs to 2 spaces for indent calculation
        const indent = leading.replace(/\t/g, "  ").length;

        const unorderedMatch = rest.match(/^([-*+])\s+(.*)$/);
        const orderedMatch = rest.match(/^\d+[.)]\s+(.*)$/);

        let content = null;
        if (unorderedMatch) {
          content = unorderedMatch[2];
        } else if (orderedMatch) {
          content = orderedMatch[1];
        } else {
          // Only intercept pastes that start with a list item; if the first
          // non-empty line isn't a list item, defer to native paste behavior.
          if (!sawFirstNonEmpty) return [];
          continue;
        }

        sawFirstNonEmpty = true;

        let blockType = "bullet";
        const taskMatch = content.match(/^\[([ xX])\]\s*(.*)$/);
        if (taskMatch) {
          blockType = taskMatch[1].toLowerCase() === "x" ? "done" : "todo";
          const prefix = blockType === "done" ? "DONE" : "TODO";
          content = taskMatch[2].trim() ? `${prefix} ${taskMatch[2]}` : prefix;
        }

        items.push({ indent, content, blockType });
      }

      // Unterminated fence at EOF — still flush as a code block
      if (codeFenceOpen) finishCodeFence();

      return items;
    },

    buildBlockTree(items) {
      if (!items.length) return [];

      const uniqueIndents = [...new Set(items.map((i) => i.indent))].sort(
        (a, b) => a - b
      );
      const indentToLevel = new Map(
        uniqueIndents.map((indent, idx) => [indent, idx])
      );

      const roots = [];
      const stack = [];

      for (const item of items) {
        const level = indentToLevel.get(item.indent);
        const node = {
          content: item.content,
          blockType: item.blockType,
          language: item.language || null,
          children: [],
        };

        while (stack.length && stack[stack.length - 1].level >= level) {
          stack.pop();
        }

        if (stack.length === 0) {
          roots.push(node);
        } else {
          stack[stack.length - 1].node.children.push(node);
        }

        stack.push({ node, level });
      }

      return roots;
    },

    async createBlockFromTree(node, parentUuid, order) {
      if (!this.page) return null;

      const payload = {
        page: this.page.uuid,
        content: node.content,
        parent: parentUuid,
        block_type: node.blockType,
        content_type: "text",
        order: order,
      };
      if (node.blockType === "code" && node.language) {
        payload.properties = { language: node.language };
      }

      const result = await window.apiService.createBlock(payload);

      if (!result.success) return null;

      const createdUuid = result.data.uuid;

      for (let i = 0; i < node.children.length; i++) {
        await this.createBlockFromTree(node.children[i], createdUuid, i);
      }

      return createdUuid;
    },

    // ---- Web archive helpers --------------------------------------------
    isBareUrl(text) {
      if (!text) return false;
      // Single token, http(s), no whitespace. Strict so inline URLs in text
      // don't accidentally trigger capture on paste.
      return /^https?:\/\/[^\s<>"']+$/i.test(text);
    },

    emitToast(message, type = "info", duration = 4000) {
      document.dispatchEvent(
        new CustomEvent("brainspread:toast", {
          detail: { message, type, duration },
        })
      );
    },

    // Pull a File out of a ClipboardEvent if there is one. Items come in
    // two flavours: DataTransferItemList (most browsers, including for
    // screenshots) and FileList (drag-drop, some older paths). Items
    // includes plain text/html too, so filter to "file" kind.
    extractClipboardFile(clipboardData) {
      if (clipboardData.items && clipboardData.items.length) {
        for (const item of clipboardData.items) {
          if (item.kind === "file") {
            const f = item.getAsFile();
            if (f) return f;
          }
        }
      }
      if (clipboardData.files && clipboardData.files.length) {
        return clipboardData.files[0];
      }
      return null;
    },

    // Map an asset's file_type onto Block.content_type so the rendering
    // code knows how to lay it out.
    contentTypeForAsset(asset) {
      switch (asset?.file_type) {
        case "image":
          return "image";
        case "video":
          return "video";
        case "audio":
          return "audio";
        default:
          return "file";
      }
    },

    // Upload a file and attach the resulting Asset to `block`. If the
    // block is empty, the asset replaces it; otherwise we insert a new
    // block right after as a sibling.
    async attachFileToBlock(block, file) {
      const toastId = this.emitToast(`uploading ${file.name || "file"}…`);
      try {
        const res = await window.apiService.uploadAsset(file, {
          assetType: "block_attachment",
        });
        if (!res.success || !res.data) {
          throw new Error("upload failed");
        }
        const asset = res.data;
        const blockIsEmpty = !block.content || block.content.trim() === "";
        if (blockIsEmpty) {
          const updateResult = await window.apiService.updateBlock(block.uuid, {
            asset: asset.uuid,
            content_type: this.contentTypeForAsset(asset),
          });
          if (!updateResult.success) throw new Error("attach failed");
          await this.loadPage({ silent: true });
        } else {
          await this.attachFileToNewBlockAfter(block, asset);
        }
      } catch (e) {
        this.emitToast(e.message || "upload failed", "error");
      } finally {
        void toastId;
      }
    },

    // Create a new sibling block right after `anchorBlock` carrying the
    // freshly-uploaded asset. Mirrors the shift-and-insert dance already
    // used by the markdown-list paste path.
    async attachFileToNewBlockAfter(anchorBlock, asset) {
      const parentUuid = anchorBlock.parent ? anchorBlock.parent.uuid : null;
      const siblings = anchorBlock.parent
        ? anchorBlock.parent.children
        : this.directBlocks;

      const blocksToShift = siblings.filter(
        (b) => b.uuid !== anchorBlock.uuid && b.order > anchorBlock.order
      );
      if (blocksToShift.length > 0) {
        const reorderPayload = blocksToShift.map((b) => ({
          uuid: b.uuid,
          order: b.order + 1,
        }));
        const reorderResult =
          await window.apiService.reorderBlocks(reorderPayload);
        if (!reorderResult.success) throw new Error("failed to reorder blocks");
      }

      const createResult = await window.apiService.createBlock({
        page: this.page.uuid,
        parent: parentUuid,
        order: anchorBlock.order + 1,
        content: "",
        content_type: this.contentTypeForAsset(asset),
        asset: asset.uuid,
      });
      if (!createResult.success) throw new Error("failed to create block");
      await this.loadPage({ silent: true });
    },

    // Drag-drop entrypoint. The block template attaches @drop to the
    // block's outer wrapper and lets the browser's default dragover keep
    // the drop target alive. Only the first dropped file is used; this
    // matches how paste works and keeps the UX predictable.
    async onBlockDrop(event, block) {
      const files = event.dataTransfer?.files;
      if (!files || files.length === 0) return;
      event.preventDefault();
      await this.attachFileToBlock(block, files[0]);
    },

    // Hidden-input fallback for the explicit "attach" affordance in the
    // block popover. The popover opens the picker; the input's @change
    // funnels back through here.
    async onBlockAttachPick(event, block) {
      const files = event.target?.files;
      if (!files || files.length === 0) return;
      try {
        await this.attachFileToBlock(block, files[0]);
      } finally {
        // Reset so picking the same file twice still fires @change.
        event.target.value = "";
      }
    },

    async handleUrlPaste(block, url) {
      // Empty block: promote it to an embed in place. Otherwise append a
      // sibling embed block after the current one (matches paste-as-list
      // behaviour for consistency).
      const blockIsEmpty = !block.content || block.content.trim() === "";
      let targetBlock = block;

      try {
        if (blockIsEmpty) {
          const result = await window.apiService.updateBlock(block.uuid, {
            content: url,
            content_type: "embed",
            media_url: url,
          });
          if (!result.success) throw new Error("update block failed");
          block.content = url;
          block.content_type = "embed";
          block.media_url = url;
        } else {
          const parentUuid = block.parent ? block.parent.uuid : null;
          const newOrder = block.order + 1;
          const siblings = block.parent
            ? block.parent.children
            : this.directBlocks;
          const blocksToShift = siblings.filter(
            (b) => b.uuid !== block.uuid && b.order >= newOrder
          );
          if (blocksToShift.length > 0) {
            const reorderPayload = blocksToShift.map((b) => ({
              uuid: b.uuid,
              order: b.order + 1,
            }));
            const reorderResult =
              await window.apiService.reorderBlocks(reorderPayload);
            if (!reorderResult.success) throw new Error("reorder failed");
          }
          const createResult = await window.apiService.createBlock({
            page: this.page.uuid,
            parent: parentUuid,
            content: url,
            content_type: "embed",
            block_type: "bullet",
            media_url: url,
            order: newOrder,
          });
          if (!createResult.success) throw new Error("create block failed");
          targetBlock = { uuid: createResult.data.uuid };
        }
        // Archiving is opt-in - user clicks "archive" on the embed card.
        void targetBlock;
      } catch (error) {
        console.error("url paste failed:", error);
        this.emitToast("could not save URL", "error");
      }
    },

    async handleUrlDrop(event) {
      // Accept URLs from browser drag-drop AND file drops at the page
      // level. File drops create a new block at the bottom carrying the
      // attached asset; per-block drops route through onBlockDrop instead.
      const dt = event.dataTransfer;
      if (!dt) return;

      if (dt.files && dt.files.length > 0) {
        event.preventDefault();
        await this.handlePageFileDrop(dt.files[0]);
        return;
      }

      let url = dt.getData("text/uri-list") || dt.getData("text/plain") || "";
      url = (url || "").split(/[\r\n]/)[0].trim();
      if (!this.isBareUrl(url)) return;

      event.preventDefault();

      try {
        const newOrder = this.getNextOrder(null);
        const createResult = await window.apiService.createBlock({
          page: this.page.uuid,
          parent: null,
          content: url,
          content_type: "embed",
          block_type: "bullet",
          media_url: url,
          order: newOrder,
        });
        if (!createResult.success) throw new Error("create block failed");
        // Archiving is opt-in - user clicks "archive" on the embed card.
        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("url drop failed:", error);
        this.emitToast("could not save dropped URL", "error");
      }
    },

    async handlePageFileDrop(file) {
      const toastId = this.emitToast(`uploading ${file.name || "file"}…`);
      try {
        const res = await window.apiService.uploadAsset(file, {
          assetType: "block_attachment",
        });
        if (!res.success || !res.data) throw new Error("upload failed");
        const asset = res.data;
        const newOrder = this.getNextOrder(null);
        const createResult = await window.apiService.createBlock({
          page: this.page.uuid,
          parent: null,
          content: "",
          content_type: this.contentTypeForAsset(asset),
          asset: asset.uuid,
          order: newOrder,
        });
        if (!createResult.success) throw new Error("create block failed");
        await this.loadPage({ silent: true });
      } catch (e) {
        this.emitToast(e.message || "upload failed", "error");
      } finally {
        void toastId;
      }
    },

    handleUrlDragOver(event) {
      const dt = event.dataTransfer;
      if (!dt) return;
      // Claim the event for URLs (keep existing behavior) AND for files,
      // so the browser doesn't show "drop disallowed" while the user is
      // mid-drag. Plain text drags inside the page still pass through.
      const hasUrl =
        dt.types &&
        (Array.from(dt.types).includes("text/uri-list") ||
          Array.from(dt.types).includes("text/plain"));
      const hasFile = dt.types && Array.from(dt.types).includes("Files");
      if (hasUrl || hasFile) {
        event.preventDefault();
      }
    },

    async triggerWebArchiveCapture(blockUuid, url) {
      const toastId = this.emitToast(`archiving ${url}…`);
      try {
        const result = await window.apiService.captureWebArchive(
          blockUuid,
          url
        );
        if (!result.success) {
          this.emitToast("archive capture failed", "error");
          return;
        }
        // Poll for completion. Capture usually finishes in 2-5s; give up
        // after ~30s so a slow site doesn't spin the UI forever.
        const finalStatus = await this.pollWebArchiveUntilDone(blockUuid);
        // Let open BlockComponents refresh their cached archive state so
        // the "view archive" button lights up without a page reload.
        document.dispatchEvent(
          new CustomEvent("brainspread:archive-updated", {
            detail: { blockUuid, status: finalStatus },
          })
        );
        if (finalStatus === "ready") {
          this.emitToast("archive saved", "success", 3000);
          await this.loadPage({ silent: true });
        } else if (finalStatus === "failed") {
          this.emitToast("archive capture failed", "error");
        }
        // "pending"/"in_progress" fall through - user can reload later.
      } catch (error) {
        console.error("capture web archive failed:", error);
        this.emitToast("archive capture failed", "error");
      }
      // toastId currently unused by app.js (auto-dismiss by duration), kept
      // for when we add dismissal-by-id support.
      void toastId;
    },

    async pollWebArchiveUntilDone(
      blockUuid,
      { maxAttempts = 15, intervalMs = 2000 } = {}
    ) {
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        try {
          const result = await window.apiService.getWebArchive(blockUuid);
          if (result && result.success && result.data) {
            const status = result.data.status;
            if (status === "ready" || status === "failed") return status;
          }
        } catch (error) {
          // 404 while we wait for the row to settle - just keep trying.
          console.debug("web archive poll error", error);
        }
      }
      return "pending";
    },

    handleRequestArchive(event) {
      const detail = event?.detail || {};
      if (!detail.blockUuid || !detail.url) return;
      this.triggerWebArchiveCapture(detail.blockUuid, detail.url);
    },

    async onBlockPaste(event, block) {
      const clipboardData = event.clipboardData || window.clipboardData;
      if (!clipboardData) return;

      // Image / file paste. Screenshots and copy-image-from-browser land in
      // clipboardData.items as type "image/*" with no plain-text counterpart;
      // bare-text-attached-files land in .files. Take whichever we find.
      const file = this.extractClipboardFile(clipboardData);
      if (file) {
        event.preventDefault();
        await this.attachFileToBlock(block, file);
        return;
      }

      const text = clipboardData.getData("text/plain");
      if (!text) return;

      // URL paste gets first shot. If the clipboard is a bare URL, create an
      // embed block and kick off an archive capture in the background.
      const trimmed = text.trim();
      if (this.isBareUrl(trimmed)) {
        event.preventDefault();
        await this.handleUrlPaste(block, trimmed);
        return;
      }

      const items = this.parseMarkdownList(text);
      if (items.length === 0) return;

      event.preventDefault();

      const tree = this.buildBlockTree(items);
      if (tree.length === 0) return;

      try {
        const blockIsEmpty = !block.content || block.content.trim() === "";
        const parentUuid = block.parent ? block.parent.uuid : null;
        const siblings = block.parent
          ? block.parent.children
          : this.directBlocks;

        if (blockIsEmpty) {
          // Use current block as first item, insert remaining roots as siblings
          const firstItem = tree[0];
          const remainingRoots = tree.slice(1);

          // Shift subsequent siblings by the number of additional root items
          if (remainingRoots.length > 0) {
            const blocksToShift = siblings.filter(
              (b) => b.uuid !== block.uuid && b.order > block.order
            );
            if (blocksToShift.length > 0) {
              const reorderPayload = blocksToShift.map((b) => ({
                uuid: b.uuid,
                order: b.order + remainingRoots.length,
              }));
              const reorderResult =
                await window.apiService.reorderBlocks(reorderPayload);
              if (!reorderResult.success) {
                throw new Error("failed to reorder blocks");
              }
            }
          }

          // Update current block with first item content and block_type
          const updatePayload = {
            content: firstItem.content,
            block_type: firstItem.blockType,
            parent: parentUuid,
          };
          if (firstItem.blockType === "code" && firstItem.language) {
            updatePayload.properties = { language: firstItem.language };
          }
          const updateResult = await window.apiService.updateBlock(
            block.uuid,
            updatePayload
          );
          if (!updateResult.success) {
            throw new Error("failed to update block");
          }

          // Create children of first item under current block
          for (let i = 0; i < firstItem.children.length; i++) {
            await this.createBlockFromTree(
              firstItem.children[i],
              block.uuid,
              i
            );
          }

          // Create remaining roots as siblings after current block
          for (let i = 0; i < remainingRoots.length; i++) {
            await this.createBlockFromTree(
              remainingRoots[i],
              parentUuid,
              block.order + 1 + i
            );
          }
        } else {
          // Insert all root items as siblings after current block
          const blocksToShift = siblings.filter(
            (b) => b.uuid !== block.uuid && b.order > block.order
          );
          if (blocksToShift.length > 0) {
            const reorderPayload = blocksToShift.map((b) => ({
              uuid: b.uuid,
              order: b.order + tree.length,
            }));
            const reorderResult =
              await window.apiService.reorderBlocks(reorderPayload);
            if (!reorderResult.success) {
              throw new Error("failed to reorder blocks");
            }
          }

          for (let i = 0; i < tree.length; i++) {
            await this.createBlockFromTree(
              tree[i],
              parentUuid,
              block.order + 1 + i
            );
          }
        }

        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("failed to paste markdown list:", error);
        this.error = "failed to paste markdown list";
      }
    },

    // Block selection (Cmd+A escalation) and markdown copy
    isBlockSelected(uuid) {
      return this.selectedBlockUuids.has(uuid);
    },

    collectSubtreeUuids(block, out) {
      out.add(block.uuid);
      if (block.children) {
        for (const child of block.children) {
          this.collectSubtreeUuids(child, out);
        }
      }
    },

    computeSelectionUuids(anchorUuid, level) {
      const anchor = this.getAllBlocks().find((b) => b.uuid === anchorUuid);
      if (!anchor) return { uuids: new Set(), reachedPage: false };

      let scope = anchor;
      for (let i = 0; i < level; i++) {
        if (!scope.parent) {
          const uuids = new Set();
          for (const b of this.directBlocks) {
            this.collectSubtreeUuids(b, uuids);
          }
          return { uuids, reachedPage: true };
        }
        scope = scope.parent;
      }

      const uuids = new Set();
      this.collectSubtreeUuids(scope, uuids);
      // If the scope is a root block and its subtree already covers all
      // direct blocks, flag as reachedPage so next escalation is a no-op.
      const reachedPage =
        !scope.parent &&
        this.directBlocks.length === 1 &&
        this.directBlocks[0].uuid === scope.uuid;
      return { uuids, reachedPage };
    },

    setBlockSelection(anchorBlock, level) {
      const { uuids } = this.computeSelectionUuids(anchorBlock.uuid, level);
      this.selectionAnchorUuid = anchorBlock.uuid;
      this.selectionLevel = level;
      this.selectedBlockUuids = uuids;
    },

    clearBlockSelection() {
      if (!this.selectionAnchorUuid && this.selectedBlockUuids.size === 0) {
        return;
      }
      this.selectionAnchorUuid = null;
      this.selectionLevel = 0;
      this.selectedBlockUuids = new Set();
    },

    expandBlockSelection() {
      if (!this.selectionAnchorUuid) return false;
      const nextLevel = this.selectionLevel + 1;
      const { uuids, reachedPage } = this.computeSelectionUuids(
        this.selectionAnchorUuid,
        nextLevel
      );
      // If the computed selection didn't change size or we hit the page,
      // stop escalating.
      if (
        uuids.size === this.selectedBlockUuids.size &&
        [...uuids].every((u) => this.selectedBlockUuids.has(u))
      ) {
        return false;
      }
      this.selectionLevel = nextLevel;
      this.selectedBlockUuids = uuids;
      if (reachedPage) {
        // Mark level so future expansions don't try to go higher
        this.selectionLevel = nextLevel;
      }
      return true;
    },

    handleSelectionKeydown(event) {
      const isCmdA =
        (event.metaKey || event.ctrlKey) &&
        (event.key === "a" || event.key === "A");
      if (!isCmdA) return;
      if (event.shiftKey || event.altKey) return;

      const active = document.activeElement;
      const tag = active?.tagName;

      // Don't hijack inside non-block inputs/textareas (e.g. page title, chat)
      if (tag === "INPUT") return;
      const isBlockTextarea =
        tag === "TEXTAREA" && active.classList.contains("block-content");

      if (tag === "TEXTAREA" && !isBlockTextarea) return;

      if (isBlockTextarea) {
        const isEmpty = active.value.length === 0;
        const isFullySelected =
          active.selectionStart === 0 &&
          active.selectionEnd === active.value.length &&
          active.value.length > 0;
        if (!isEmpty && !isFullySelected) {
          // Let native Cmd+A select all text in the textarea first
          return;
        }
        // Escalate: select the current block + its descendants
        const wrapper = active.closest("[data-block-uuid]");
        if (!wrapper) return;
        const uuid = wrapper.dataset.blockUuid;
        const block = this.getAllBlocks().find((b) => b.uuid === uuid);
        if (!block) return;
        event.preventDefault();
        if (block.isEditing) block.isEditing = false;
        active.blur();
        this.setBlockSelection(block, 0);
        return;
      }

      if (this.selectionAnchorUuid) {
        event.preventDefault();
        this.expandBlockSelection();
        return;
      }
    },

    serializeBlockToMarkdown(block, depth, lines) {
      const indent = "  ".repeat(depth);

      if (block.block_type === "code") {
        const lang = block.properties?.language || "";
        lines.push(`${indent}\`\`\`${lang}`);
        const codeLines = (block.content || "").split("\n");
        for (const cl of codeLines) {
          lines.push(`${indent}${cl}`);
        }
        lines.push(`${indent}\`\`\``);
      } else {
        let content = block.content || "";
        let prefix = "- ";
        if (block.block_type === "todo") {
          content = content.replace(/^TODO\s*:?\s*/i, "");
          prefix = "- [ ] ";
        } else if (block.block_type === "done") {
          content = content.replace(/^DONE\s*:?\s*/i, "");
          prefix = "- [x] ";
        }
        lines.push(`${indent}${prefix}${content}`);
      }

      if (block.children) {
        for (const child of block.children) {
          if (this.selectedBlockUuids.has(child.uuid)) {
            this.serializeBlockToMarkdown(child, depth + 1, lines);
          }
        }
      }
    },

    serializeSelectedBlocksAsMarkdown() {
      if (this.selectedBlockUuids.size === 0) return "";
      // Find "top" blocks in selection — blocks whose parent is not selected
      const topBlocks = [];
      const walk = (blocks) => {
        for (const b of blocks) {
          if (this.selectedBlockUuids.has(b.uuid)) {
            const parentSelected =
              b.parent && this.selectedBlockUuids.has(b.parent.uuid);
            if (!parentSelected) topBlocks.push(b);
          }
          if (b.children?.length) walk(b.children);
        }
      };
      walk(this.directBlocks);

      const lines = [];
      for (const b of topBlocks) {
        this.serializeBlockToMarkdown(b, 0, lines);
      }
      return lines.join("\n");
    },

    handleSelectionCopy(event) {
      if (this.selectedBlockUuids.size === 0) return;
      const active = document.activeElement;
      // Don't hijack copy when user is inside a textarea/input with text selected
      if (
        active &&
        (active.tagName === "TEXTAREA" || active.tagName === "INPUT") &&
        active.selectionStart !== active.selectionEnd
      ) {
        return;
      }
      const markdown = this.serializeSelectedBlocksAsMarkdown();
      if (!markdown) return;
      event.preventDefault();
      event.clipboardData.setData("text/plain", markdown);
    },

    // Click + Shift-click selects a contiguous range of blocks in document
    // order; Cmd/Ctrl-click toggles a single block in/out of the selection.
    // While in selection mode, plain clicks also toggle. Returns true when
    // the click was consumed for selection so callers can skip starting an
    // edit. Plain clicks outside selection mode return false.
    handleBlockSelectClick(block, event) {
      if (!event) return false;

      // The first block touched in a selection becomes the anchor for any
      // subsequent shift-click range expansion.
      if (event.shiftKey && this.selectionAnchorUuid) {
        const all = this.getAllBlocks();
        const anchorIdx = all.findIndex(
          (b) => b.uuid === this.selectionAnchorUuid
        );
        const targetIdx = all.findIndex((b) => b.uuid === block.uuid);
        if (anchorIdx === -1 || targetIdx === -1) return false;
        const [start, end] =
          anchorIdx <= targetIdx
            ? [anchorIdx, targetIdx]
            : [targetIdx, anchorIdx];
        const uuids = new Set();
        for (let i = start; i <= end; i++) uuids.add(all[i].uuid);
        this.selectedBlockUuids = uuids;
        this.selectionLevel = 0;
        this.blurActiveEditor();
        return true;
      }

      if (event.shiftKey) {
        // No anchor yet — treat shift-click like a fresh anchor click.
        this.selectionAnchorUuid = block.uuid;
        this.selectionLevel = 0;
        this.selectedBlockUuids = new Set([block.uuid]);
        this.blurActiveEditor();
        return true;
      }

      if (event.metaKey || event.ctrlKey || this.selectionMode) {
        const next = new Set(this.selectedBlockUuids);
        if (next.has(block.uuid)) {
          next.delete(block.uuid);
        } else {
          next.add(block.uuid);
        }
        this.selectedBlockUuids = next;
        if (next.size === 0) {
          this.selectionAnchorUuid = null;
        } else if (
          !this.selectionAnchorUuid ||
          !next.has(this.selectionAnchorUuid)
        ) {
          this.selectionAnchorUuid = block.uuid;
        }
        this.selectionLevel = 0;
        this.blurActiveEditor();
        return true;
      }

      return false;
    },

    blurActiveEditor() {
      const active = document.activeElement;
      if (
        active &&
        active.tagName === "TEXTAREA" &&
        active.classList.contains("block-content")
      ) {
        active.blur();
      }
    },

    handleBulkDeleteSelected() {
      this.bulkDeleteSelected();
    },

    handleBulkMoveSelectedToToday() {
      this.bulkMoveSelectedToToday();
    },

    enterSelectionMode() {
      this.selectionMode = true;
      this.closePageMenu();
    },

    exitSelectionMode() {
      this.selectionMode = false;
      this.clearBlockSelection();
    },

    toggleSelectionMode() {
      if (this.selectionMode) {
        this.exitSelectionMode();
      } else {
        this.enterSelectionMode();
      }
    },

    async bulkDeleteSelected() {
      const uuids = [...this.selectedBlockUuids];
      if (uuids.length === 0) {
        this.$parent?.addToast?.("no blocks selected", "info");
        return;
      }

      const confirmed = confirm(
        `delete ${uuids.length} selected block${uuids.length === 1 ? "" : "s"}? this also deletes any child blocks and cannot be undone.`
      );
      if (!confirmed) return;

      try {
        const result = await window.apiService.bulkDeleteBlocks(uuids);
        if (!result || !result.success) {
          throw new Error("bulk delete failed");
        }
        const count = result.data?.deleted_count ?? uuids.length;
        this.$parent?.addToast?.(
          `deleted ${count} block${count === 1 ? "" : "s"}`,
          "success"
        );
        this.clearBlockSelection();
        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("failed to bulk-delete blocks:", error);
        this.error = "failed to delete selected blocks";
        this.$parent?.addToast?.("failed to delete selected blocks", "error");
      }
    },

    async bulkMoveSelectedToToday() {
      const uuids = [...this.selectedBlockUuids];
      if (uuids.length === 0) {
        this.$parent?.addToast?.("no blocks selected", "info");
        return;
      }

      try {
        const result = await window.apiService.bulkMoveBlocks(uuids);
        if (!result || !result.success) {
          throw new Error("bulk move failed");
        }
        const moved = result.data?.moved_count ?? 0;
        const targetTitle = result.data?.target_page?.title || "today";
        if (moved > 0) {
          this.$parent?.addToast?.(
            `moved ${moved} block${moved === 1 ? "" : "s"} to ${targetTitle}`,
            "success"
          );
        } else {
          this.$parent?.addToast?.(
            "selected blocks already on the target page",
            "info"
          );
        }
        this.clearBlockSelection();
        await this.loadPage({ silent: true });
      } catch (error) {
        console.error("failed to bulk-move blocks:", error);
        this.error = "failed to move selected blocks";
        this.$parent?.addToast?.("failed to move selected blocks", "error");
      }
    },
  },

  template: `
    <div class="page-page">
      <!-- Loading State -->
      <div v-if="loading" class="loading">
        Loading page...
      </div>

      <!-- Error State -->
      <div v-if="error" class="error">
        {{ error }}
      </div>

      <!-- Whiteboard Page (full-screen tldraw) -->
      <div v-else-if="page && isWhiteboard" class="page-content page-content-whiteboard">
        <div class="page-header whiteboard-page-header">
          <div class="page-title-container page-header-flex">
            <div class="page-header-flex-left">
              <div v-if="!isEditingTitle" class="page-title-display">
                <h1 class="page-title-text" tabindex="0" role="button" aria-label="Edit page title" @click="startEditingTitle" @keydown.enter.prevent="startEditingTitle" @keydown.space.prevent="startEditingTitle">{{ page.title || 'Untitled Whiteboard' }}</h1>
              </div>
              <div v-else class="page-title-edit">
                <input
                  ref="titleInput"
                  v-model="newTitle"
                  @keyup.enter="updatePageTitle"
                  @keyup.escape="cancelEditingTitle"
                  class="form-control page-title-input"
                  placeholder="enter whiteboard title"
                />
                <button @click="updatePageTitle" class="btn btn-success save-title-btn" title="Save title">✓</button>
                <button @click="cancelEditingTitle" class="btn btn-outline cancel-title-btn" title="Cancel">✗</button>
              </div>
              <span class="page-type-badge">whiteboard</span>
            </div>
            <div class="page-actions">
              <div class="context-menu-container">
                <button @click="togglePageMenu" class="btn btn-outline context-menu-btn" title="Whiteboard options" :aria-expanded="showPageMenu" aria-haspopup="menu">⋮</button>
                <div v-if="showPageMenu" class="context-menu" @click.stop @keydown="handlePageMenuKeydown" role="menu">
                  <button @click="startEditingTitle" class="context-menu-item" role="menuitem">edit title</button>
                  <button @click="deletePage" class="context-menu-item context-menu-danger" role="menuitem">delete whiteboard</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <Whiteboard :page="page" @page-updated="onWhiteboardPageUpdated" />
      </div>

      <!-- Page Content -->
      <div v-else-if="page" class="page-content">
        <!-- Page Header -->
        <div class="page-header">
          <div class="page-title-container">
            <!-- Daily Note Header -->
            <div v-if="isDaily" class="daily-note-title current-note page-header-flex">
              <div class="title-left">
                <input
                  type="date"
                  v-model="selectedDate"
                  @change="onDateChange"
                  class="date-picker"
                  title="Navigate to date"
                />
              </div>
              <div class="header-controls">
                <div class="context-menu-container">
                  <button @click="togglePageMenu" class="btn btn-outline context-menu-btn" title="Daily note options" :aria-expanded="showPageMenu" aria-haspopup="menu">
                    ⋮
                  </button>
                  <div v-if="showPageMenu" class="context-menu" @click.stop @keydown="handlePageMenuKeydown" role="menu">
                    <button @click="moveUndoneTodos" class="context-menu-item" :disabled="loading" role="menuitem">
                      move undone TODOs here
                    </button>
                    <button @click="enterSelectionMode" class="context-menu-item" role="menuitem">
                      <span class="context-menu-icon">◉</span>
                      <span>select multiple</span>
                    </button>
                    <button @click="deletePage" class="context-menu-item context-menu-danger" role="menuitem">
                       <span class="context-menu-icon">×</span>
                       <span>delete</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            
            <!-- Regular Page Title (Editable) -->
            <div v-else class="page-title-container page-header-flex">
              <div class="page-header-flex-left">
                <div v-if="!isEditingTitle" class="page-title-display">
                  <h1 class="page-title-text" tabindex="0" role="button" aria-label="Edit page title" @click="startEditingTitle" @keydown.enter.prevent="startEditingTitle" @keydown.space.prevent="startEditingTitle">{{ page.title || 'Untitled Page' }}</h1>
                </div>
                <div v-else class="page-title-edit">
                  <input
                    ref="titleInput"
                    v-model="newTitle"
                    @keyup.enter="updatePageTitle"
                    @keyup.escape="cancelEditingTitle"
                    class="form-control page-title-input"
                    placeholder="enter page title"
                  />
                  <button @click="updatePageTitle" class="btn btn-success save-title-btn" title="Save title">
                    ✓
                  </button>
                  <button @click="cancelEditingTitle" class="btn btn-outline cancel-title-btn" title="Cancel">
                    ✗
                  </button>
                </div>
              </div>
              <div class="page-actions">
                <div class="context-menu-container">
                  <button @click="togglePageMenu" class="btn btn-outline context-menu-btn" title="Page options" :aria-expanded="showPageMenu" aria-haspopup="menu">
                    ⋮
                  </button>
                  <div v-if="showPageMenu" class="context-menu" @click.stop @keydown="handlePageMenuKeydown" role="menu">
                    <button @click="startEditingTitle" class="context-menu-item" role="menuitem">
                      edit title
                    </button>
                    <button @click="enterSelectionMode" class="context-menu-item" role="menuitem">
                      <span class="context-menu-icon">◉</span>
                      <span>select multiple</span>
                    </button>
                    <button @click="deletePage" class="context-menu-item context-menu-danger" role="menuitem">
                      delete page
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Selection Mode Toolbar -->
        <div v-if="selectionMode" class="selection-toolbar" role="toolbar" aria-label="Selection actions">
          <div class="selection-toolbar-status">
            <span class="selection-toolbar-count">{{ selectedBlockCount }}</span>
            <span class="selection-toolbar-label">selected</span>
          </div>
          <div class="selection-toolbar-actions">
            <button
              type="button"
              class="btn btn-outline selection-toolbar-action"
              :disabled="selectedBlockCount === 0"
              @click="bulkMoveSelectedToToday"
              title="Move selected blocks to today's daily note"
            >move to today</button>
            <button
              type="button"
              class="btn btn-outline selection-toolbar-action selection-toolbar-danger"
              :disabled="selectedBlockCount === 0"
              @click="bulkDeleteSelected"
              title="Delete selected blocks"
            >delete</button>
            <button
              type="button"
              class="btn btn-outline selection-toolbar-done"
              @click="exitSelectionMode"
              title="Exit selection mode (Esc)"
            >done</button>
          </div>
        </div>

        <!-- Overdue Section (today's daily page only) -->
        <div v-if="hasOverdueBlocks" class="overdue-section">
          <h3 class="overdue-title">
            {{ totalOverdueBlocks }} overdue
          </h3>
          <div class="overdue-blocks-container">
            <div v-for="block in overdueBlocks" :key="block.uuid" class="referenced-block-wrapper overdue-block-wrapper" :class="{ 'in-context': isBlockInContext(block.uuid) }" :data-block-uuid="block.uuid">
              <div class="block-meta">
                <span v-if="block.scheduled_for" class="overdue-due-date">due {{ formatDate(block.scheduled_for) }}</span>
                <span class="page-title clickable" @click="goToPage(block.page_slug)">{{ block.page_type === 'daily' ? formatDate(block.page_title) : block.page_title }}</span>
              </div>
              <BlockComponent
                :block="block"
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
                :onBlockPaste="onBlockPaste"
                :onBlockDrop="onBlockDrop"
                :onBlockAttachPick="onBlockAttachPick"
                :scheduleBlock="scheduleBlock"
              />
            </div>
          </div>
        </div>

        <!-- Direct Blocks Section -->
        <div class="direct-blocks-section">
          <div
            class="blocks-container"
            @dragover="handleUrlDragOver"
            @drop="handleUrlDrop"
          >
            <BlockComponent
              v-for="block in directBlocks"
              :key="block.uuid"
              :block="block"
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
              :onBlockSelectClick="handleBlockSelectClick"
              :selectedBlockCount="selectedBlockCount"
              :bulkDeleteSelected="bulkDeleteSelected"
              :bulkMoveSelectedToToday="bulkMoveSelectedToToday"
              :selectionMode="selectionMode"
            />
            <button @click="addNewBlock" class="add-block-btn">
              + add new block
            </button>
          </div>
        </div>

        <!-- Linked References Section -->
        <div v-if="hasReferencedBlocks" class="linked-references-section">
          <h3 class="linked-references-title">
            {{ totalReferencedBlocks }} linked reference{{ totalReferencedBlocks !== 1 ? 's' : '' }}
          </h3>
          
          <div class="referenced-blocks-container">
            <div v-for="block in referencedBlocks" :key="block.uuid" class="referenced-block-wrapper" :class="{ 'in-context': isBlockInContext(block.uuid) }" :data-block-uuid="block.uuid">
              <div class="block-meta">
                <a class="page-title clickable" :href="'/knowledge/page/' + encodeURIComponent(block.page_slug) + '/'">{{ block.page_type === 'daily' ? formatDate(block.page_title) : block.page_title }}</a>
                <span v-if="block.page_date" class="page-date">{{ formatDate(block.page_date) }}</span>
              </div>
              <BlockComponent
                :block="block"
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
                :onBlockPaste="onBlockPaste"
                :onBlockDrop="onBlockDrop"
                :onBlockAttachPick="onBlockAttachPick"
                :scheduleBlock="scheduleBlock"
              />
            </div>
          </div>
        </div>

      </div>

      <!-- Schedule popover (issue #59 phase 4) -->
      <ScheduleBlockPopover
        :is-open="schedulePopoverOpen"
        :initial-date="schedulePopoverInitialDate"
        :initial-reminder-date="schedulePopoverInitialReminderDate"
        :initial-time="schedulePopoverInitialTime"
        @save="onSchedulePopoverSave"
        @cancel="onSchedulePopoverCancel"
      />
    </div>
  `,
};

// Register component globally
window.Page = Page;
