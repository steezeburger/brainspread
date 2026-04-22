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
    onBlockPaste: {
      type: Function,
      default: () => () => {},
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
  },

  mounted() {
    // Listen for the custom event to close menus
    document.addEventListener("closeBlockMenus", this.handleCloseBlockMenus);
    document.addEventListener(
      "openBlockContextMenu",
      this.handleOpenContextMenuEvent
    );
  },
  beforeUnmount() {
    // Clean up event listener
    document.removeEventListener("closeBlockMenus", this.handleCloseBlockMenus);
    document.removeEventListener(
      "openBlockContextMenu",
      this.handleOpenContextMenuEvent
    );
  },
  methods: {
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
        case "newBlockBefore":
          this.createBlockBefore(this.block);
          break;
        case "newBlockAfter":
          this.createBlockAfter(this.block);
          break;
      }
    },
  },
  template: `
    <div class="block-wrapper" :class="{ 'child-block': block.parent, 'in-context': blockInContext, 'selected': blockSelected }" :data-block-uuid="block.uuid">
      <div class="block" :class="{ 'has-children': hasChildren, 'is-collapsed': hasChildren && isCollapsed }">
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
          @click="['todo', 'doing', 'done', 'later', 'wontdo'].includes(block.block_type) ? toggleBlockTodo(block) : null"
          @touchstart="handleTouchStart"
          @touchend="handleTodoTouchEnd"
        >
          <span v-if="block.block_type === 'todo'">☐</span>
          <span v-else-if="block.block_type === 'doing'">◐</span>
          <span v-else-if="block.block_type === 'done'">☑</span>
          <span v-else-if="block.block_type === 'later'">☐</span>
          <span v-else-if="block.block_type === 'wontdo'">⊘</span>
          <span v-else>•</span>
        </div>
        <div
          v-if="!block.isEditing"
          class="block-content-display"
          :class="{ 'completed': ['done', 'wontdo'].includes(block.block_type) }"
          tabindex="0"
          role="button"
          :aria-label="'Edit block: ' + (block.content || 'empty block')"
          @click="$event.target.closest('.clickable-tag') || startEditing(block)"
          @keydown="handleBlockDisplayKeydown"
          @touchstart="handleTouchStart"
          @touchend="handleContentTouchEnd"
          v-html="formatContentWithTags(block.content, block.block_type, block.properties)"
        ></div>
        <div v-else class="block-content-wrapper">
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
          :onBlockPaste="onBlockPaste"
        />
      </div>
    </div>
  `,
};

// Make it available globally
window.BlockComponent = BlockComponent;
