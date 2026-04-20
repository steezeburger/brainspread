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
  },
  data() {
    return {
      isCollapsed: false,
      showContextMenu: false,
      contextMenuPosition: { x: 0, y: 0 },
      contextMenuFocusedIndex: -1,
      // Touch tracking for distinguishing taps from scrolls
      touchStartX: null,
      touchStartY: null,
    };
  },
  computed: {
    blockInContext() {
      return this.isBlockInContext(this.block.uuid);
    },
    hasChildren() {
      return this.block.children?.length > 0;
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
  },
  beforeUnmount() {
    // Clean up event listener
    document.removeEventListener("closeBlockMenus", this.handleCloseBlockMenus);
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
          ["todo", "done", "later", "wontdo"].includes(this.block.block_type)
        ) {
          this.toggleBlockTodo(this.block);
        }
      }
    },
    toggleCollapse() {
      this.isCollapsed = !this.isCollapsed;
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
        this.$el?.querySelectorAll(".block-context-menu [role='menuitem']") || []
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

    handleBlockDisplayKeydown(event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.startEditing(this.block);
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
    <div class="block-wrapper" :class="{ 'child-block': block.parent, 'in-context': blockInContext }" :data-block-uuid="block.uuid">
      <div class="block" :class="{ 'has-children': hasChildren }">
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
            'done': block.block_type === 'done',
            'later': block.block_type === 'later',
            'wontdo': block.block_type === 'wontdo'
          }"
          @click="['todo', 'done', 'later', 'wontdo'].includes(block.block_type) ? toggleBlockTodo(block) : null"
          @touchstart="handleTouchStart"
          @touchend="handleTodoTouchEnd"
        >
          <span v-if="block.block_type === 'todo'">☐</span>
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
          v-html="formatContentWithTags(block.content, block.block_type)"
        ></div>
        <textarea
          v-else
          :value="block.content"
          @input="onBlockContentChange(block, $event.target.value)"
          @keydown="onBlockKeyDown($event, block)"
          @blur="stopEditing(block)"
          class="block-content"
          :class="{ 'completed': ['done', 'wontdo'].includes(block.block_type) }"
          rows="1"
          placeholder="start writing..."
          ref="blockTextarea"
        ></textarea>
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
  `,
};

// Make it available globally
window.BlockComponent = BlockComponent;
