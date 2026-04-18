// Page Component - Complete page handler with data loading and rendering
const Page = {
  components: {
    BlockComponent: window.BlockComponent || {},
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
  ],
  data() {
    return {
      // Page data
      pageSlug: this.getSlugFromURL(),
      currentDate: this.getDateFromURL(),
      page: null,
      directBlocks: [], // Blocks that belong directly to this page
      referencedBlocks: [], // Blocks from other pages that reference this page
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
    };
  },

  computed: {
    isDaily() {
      return this.page?.page_type === "daily";
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
  },

  async mounted() {
    // Add event delegation for clickable hashtags in content
    document.addEventListener("click", this.handleTagClick);
    document.addEventListener("touchend", this.handleTagClick);
    // Add document click handler for closing menus
    document.addEventListener("click", this.handleDocumentClick);
    // Load page data
    await this.loadPage();
  },

  beforeUnmount() {
    // Clean up event listeners
    document.removeEventListener("click", this.handleTagClick);
    document.removeEventListener("touchend", this.handleTagClick);
    document.removeEventListener("click", this.handleDocumentClick);
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

    async loadPage() {
      this.loading = true;
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

      // Find all blocks that need to be shifted (same parent, order >= newOrder)
      const blocksToShift = siblings.filter(
        (block) => block.uuid !== currentBlock.uuid && block.order >= newOrder
      );

      // Shift existing blocks down by updating their orders
      for (const block of blocksToShift) {
        block.order = block.order + 1;
        await window.apiService.updateBlock(block.uuid, {
          order: block.order,
          parent: block.parent ? block.parent.uuid : null,
        });
      }

      // Create the new block at the desired position
      await this.createBlock("", currentBlock.parent, newOrder);
    },

    async createBlockBefore(currentBlock) {
      const newOrder = currentBlock.order;
      const siblings = currentBlock.parent
        ? currentBlock.parent.children
        : this.directBlocks;

      // Find all blocks that need to be shifted (same parent, order >= newOrder)
      const blocksToShift = siblings.filter((block) => block.order >= newOrder);

      // Shift existing blocks down by updating their orders
      for (const block of blocksToShift) {
        block.order = block.order + 1;
        await window.apiService.updateBlock(block.uuid, {
          order: block.order,
          parent: block.parent ? block.parent.uuid : null,
        });
      }

      // Create the new block at the desired position
      await this.createBlock("", currentBlock.parent, newOrder);
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

        // Update both blocks' orders in the API
        await window.apiService.updateBlock(block.uuid, {
          order: block.order,
          parent: block.parent ? block.parent.uuid : null,
        });

        await window.apiService.updateBlock(blockAbove.uuid, {
          order: blockAbove.order,
          parent: blockAbove.parent ? blockAbove.parent.uuid : null,
        });

        // Update local state - re-sort siblings
        siblings.sort((a, b) => a.order - b.order);

        // Refresh page data to ensure consistency
        await this.loadPage();
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

        // Update both blocks' orders in the API
        await window.apiService.updateBlock(block.uuid, {
          order: block.order,
          parent: block.parent ? block.parent.uuid : null,
        });

        await window.apiService.updateBlock(blockBelow.uuid, {
          order: blockBelow.order,
          parent: blockBelow.parent ? blockBelow.parent.uuid : null,
        });

        // Update local state - re-sort siblings
        siblings.sort((a, b) => a.order - b.order);

        // Refresh page data to ensure consistency
        await this.loadPage();
      } catch (error) {
        console.error("failed to move block down:", error);
        this.error = "failed to move block down";
      }
    },

    onBlockContentChange(block, newContent) {
      // Just update the local content, don't save yet
      block.content = newContent;
    },

    async onBlockKeyDown(event, block) {
      if (event.key === "Enter" && !event.shiftKey) {
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

          // Focus the block again
          this.$nextTick(() => {
            const textarea = document.querySelector(
              `[data-block-uuid="${block.uuid}"] textarea`
            );
            if (textarea) textarea.focus();
          });
        }
      } catch (error) {
        console.error("Failed to indent block:", error);
      }
    },

    async outdentBlock(block) {
      if (!block.parent) return; // Already at root level

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

          // Focus the block again
          this.$nextTick(() => {
            const textarea = document.querySelector(
              `[data-block-uuid="${block.uuid}"] textarea`
            );
            if (textarea) textarea.focus();
          });
        }
      } catch (error) {
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
      for (const sibling of siblings) {
        if (sibling.order >= fromOrder) {
          sibling.order += 1;
          await window.apiService.updateBlock(sibling.uuid, {
            order: sibling.order,
            parent: sibling.parent ? sibling.parent.uuid : null,
          });
        }
      }
    },

    formatContentWithTags(content) {
      if (!content) return "";

      let formatted = content;

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

      // Replace hashtags with clickable styled spans
      return formatted.replace(
        /#([a-zA-Z0-9_-]+)/g,
        '<span class="inline-tag clickable-tag" data-tag="$1">#$1</span>'
      );
    },

    handleTagClick(event) {
      // Check if the clicked element is a clickable tag
      if (event.target.classList.contains("clickable-tag")) {
        event.preventDefault();
        event.stopPropagation();
        const tagName = event.target.getAttribute("data-tag");
        if (tagName) {
          this.goToTag(tagName);
        }
      }
    },

    goToTag(tagName) {
      // Navigate to the tag page with full page redirect
      const url = `/knowledge/page/${encodeURIComponent(tagName)}/`;
      window.location.href = url;
    },

    goToPage(pageSlug) {
      // Navigate to a page by slug with full page redirect
      const url = `/knowledge/page/${encodeURIComponent(pageSlug)}/`;
      window.location.href = url;
    },

    startEditing(block) {
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

      // Don't try to save blocks that are being deleted
      if (this.deletingBlocks.has(block.uuid)) {
        block.isEditing = false;
        return;
      }

      // Save the block when user stops editing (blur event)
      // Skip reload to preserve cursor positions of other blocks
      await this.updateBlock(block, block.content, true);
      block.isEditing = false;
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
    },

    closePageMenu() {
      this.showPageMenu = false;
    },

    handleDocumentClick(event) {
      const contextMenuContainer = event.target.closest(
        ".context-menu-container"
      );
      if (!contextMenuContainer && this.showPageMenu) {
        this.closePageMenu();
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
                  <button @click="togglePageMenu" class="btn btn-outline context-menu-btn" title="Daily note options">
                    ⋮
                  </button>
                  <div v-if="showPageMenu" class="context-menu" @click.stop>
                    <button @click="moveUndoneTodos" class="context-menu-item" :disabled="loading">
                      move undone TODOs here
                    </button>
                    <button @click="deletePage" class="context-menu-item context-menu-danger">
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
                  <h1 class="page-title-text" @click="startEditingTitle">{{ page.title || 'Untitled Page' }}</h1>
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
                  <button @click="togglePageMenu" class="btn btn-outline context-menu-btn" title="Page options">
                    ⋮
                  </button>
                  <div v-if="showPageMenu" class="context-menu" @click.stop>
                    <button @click="startEditingTitle" class="context-menu-item">
                      edit title
                    </button>
                    <button @click="deletePage" class="context-menu-item context-menu-danger">
                      delete page
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Direct Blocks Section -->
        <div class="direct-blocks-section">
          <div class="blocks-container">
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
              :onBlockAddToContext="onBlockAddToContext"
              :onBlockRemoveFromContext="onBlockRemoveFromContext"
              :indentBlock="indentBlock"
              :outdentBlock="outdentBlock"
              :createBlockAfter="createBlockAfter"
              :createBlockBefore="createBlockBefore"
              :moveBlockUp="moveBlockUp"
              :moveBlockDown="moveBlockDown"
            />
            <button @click="addNewBlock" class="add-block-btn">
              + add new block
            </button>
          </div>
        </div>

        <!-- Linked References Section -->
        <div v-if="hasReferencedBlocks" class="linked-references-section">
          <h3 class="linked-references-title">
            {{ totalReferencedBlocks }} Linked Reference{{ totalReferencedBlocks !== 1 ? 's' : '' }}
          </h3>
          
          <div class="referenced-blocks-container">
            <div v-for="block in referencedBlocks" :key="block.uuid" class="referenced-block-wrapper" :class="{ 'in-context': isBlockInContext(block.uuid) }" :data-block-uuid="block.uuid">
              <div class="block-meta">
                <span class="page-title clickable" @click="goToPage(block.page_slug)">{{ block.page_type === 'daily' ? formatDate(block.page_title) : block.page_title }}</span>
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
                :onBlockAddToContext="onBlockAddToContext"
                :onBlockRemoveFromContext="onBlockRemoveFromContext"
                :indentBlock="indentBlock"
                :outdentBlock="outdentBlock"
                :createBlockAfter="createBlockAfter"
                :createBlockBefore="createBlockBefore"
                :moveBlockUp="moveBlockUp"
                :moveBlockDown="moveBlockDown"
              />
            </div>
          </div>
        </div>

      </div>
    </div>
  `,
};

// Register component globally
window.Page = Page;
