/**
 * EmbedContextMenu — block actions menu for embedded saved-view results.
 *
 * Reuses BlockComponent's brutalist .block-context-menu styling.
 * Owns its own open state + viewport-clamped positioning so callers
 * just wire one ref method (`openAt(block, event)`) and an `action`
 * listener. Items are fixed; the only knobs are which optional ones
 * to show via `canSchedule` / `canBlockInfo` — those depend on whether
 * the caller has the matching popover wired up (schedule and
 * block-info both need a modal that lives on a host page).
 *
 * Inline content edits + tree-structural actions (indent / outdent /
 * move up/down) stay deliberately out of scope: this menu is for
 * surfaces that show blocks from elsewhere, so anything that would
 * mutate the block's relationship to its source page (other than
 * "move to") doesn't belong here.
 */
window.EmbedContextMenu = {
  name: "EmbedContextMenu",
  props: {
    canSchedule: { type: Boolean, default: true },
    canBlockInfo: { type: Boolean, default: true },
  },
  emits: ["action"],

  data() {
    return {
      block: null, // null = menu hidden
      position: { x: 0, y: 0 },
    };
  },

  mounted() {
    // Cross-instance dismiss: when any other EmbedContextMenu opens,
    // close ourselves. Without this, opening a menu in one embed
    // leaves a menu in another embed still visible — clicks that
    // open the second menu call stopPropagation so the first menu's
    // document.click close handler never fires.
    this._onCloseOthers = (ev) => {
      if (ev.detail?.except !== this && this.block) this.close();
    };
    document.addEventListener("embed-menu:close-others", this._onCloseOthers);
  },

  beforeUnmount() {
    if (this._onCloseOthers) {
      document.removeEventListener(
        "embed-menu:close-others",
        this._onCloseOthers
      );
    }
    this.close();
  },

  methods: {
    openAt(block, event) {
      if (!block) return;
      event.preventDefault();
      event.stopPropagation();

      document.dispatchEvent(
        new CustomEvent("embed-menu:close-others", {
          detail: { except: this },
        })
      );

      // Mirrors BlockComponent.showContextMenuAt — fixed-positioned at
      // the click point, then clamped to the viewport with extra
      // mobile padding so the menu never tucks under the soft
      // keyboard / browser chrome.
      const menuWidth = 200;
      const shadowOffset = 4;
      const isMobile = window.innerWidth <= 768;
      const edgePadding = isMobile ? 20 : 10;
      const bottomPadding = isMobile ? 60 : 10;

      let x = event.clientX;
      let y = event.clientY;
      const vw = window.innerWidth;
      if (x + menuWidth + shadowOffset > vw - edgePadding) {
        x = vw - menuWidth - shadowOffset - edgePadding;
      }
      x = Math.max(edgePadding, x);

      this.position = { x, y };
      this.block = block;

      this.$nextTick(() => {
        const el = this.$el?.querySelector?.(".block-context-menu");
        if (!el) return;
        const h = el.offsetHeight;
        const vh = window.innerHeight;
        let ny = y;
        if (ny + h + shadowOffset > vh - bottomPadding) {
          ny = vh - h - shadowOffset - bottomPadding;
        }
        ny = Math.max(edgePadding, ny);
        if (ny !== this.position.y) {
          this.position = { x, y: ny };
        }
      });

      // Capture-phase outside-click handler so we run BEFORE the
      // target element's own click handlers. Without this, tapping
      // a result row / regular block / link while the menu is open
      // both closes the menu AND fires the row's click (starts
      // editing the block, follows the link). On mobile there's
      // often no empty space to tap "between" items, so the menu
      // becomes effectively un-dismissable except by picking one of
      // its own items. The setTimeout is BlockComponent's pattern —
      // without it the same click that opened us would trigger an
      // immediate close.
      setTimeout(() => {
        document.addEventListener("click", this.handleOutsideClick, true);
      }, 10);
    },

    handleOutsideClick(event) {
      // Clicks inside any context menu must reach their own
      // handlers (item @click drives the action emit + the menu's
      // own close). The @click.stop on the menu root only
      // suppresses bubble, but we're in capture phase so we have
      // to identify inside-menu clicks ourselves. Use a closest()
      // check on the shared `.block-context-menu` class rather
      // than `$el.contains` — $el is unreliable when v-if is at
      // the template root (it can resolve to the comment-node
      // placeholder), and the class check is what we actually mean
      // semantically anyway.
      const target = event.target;
      if (target && target.closest && target.closest(".block-context-menu")) {
        return;
      }
      // Outside click: consume the event so the target's own click
      // handler (block-edit, link nav, row toggle) never runs, then
      // close the menu.
      event.preventDefault();
      event.stopPropagation();
      this.close();
    },

    close() {
      this.block = null;
      document.removeEventListener("click", this.handleOutsideClick, true);
    },

    onAction(action) {
      const b = this.block;
      this.close();
      if (!b) return;
      this.$emit("action", { action, block: b });
    },
  },

  template: `
    <div
      v-if="block"
      class="block-context-menu"
      :style="{ left: position.x + 'px', top: position.y + 'px' }"
      @click.stop
      role="menu"
    >
      <button class="context-menu-item" role="menuitem" tabindex="-1" @click="onAction('moveToToday')">
        <span class="context-menu-icon">⇨</span>
        <span>move to today's daily</span>
      </button>
      <button class="context-menu-item" role="menuitem" tabindex="-1" @click="onAction('moveToPage')">
        <span class="context-menu-icon">→</span>
        <span>move to page…</span>
      </button>
      <button class="context-menu-item" role="menuitem" tabindex="-1" @click="onAction('copyLink')">
        <span class="context-menu-icon">↗</span>
        <span>copy link to block</span>
      </button>
      <template v-if="canSchedule">
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="onAction('schedule')">
          <span class="context-menu-icon">◷</span>
          <span>{{ block.scheduled_for ? 'reschedule…' : 'schedule…' }}</span>
        </button>
        <button v-if="block.scheduled_for" class="context-menu-item" role="menuitem" tabindex="-1" @click="onAction('unschedule')">
          <span class="context-menu-icon">×</span>
          <span>clear schedule</span>
        </button>
      </template>
      <template v-if="canBlockInfo">
        <div class="context-menu-separator"></div>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="onAction('blockInfo')">
          <span class="context-menu-icon">i</span>
          <span>block info…</span>
        </button>
      </template>
      <div class="context-menu-separator"></div>
      <button class="context-menu-item context-menu-danger" role="menuitem" tabindex="-1" @click="onAction('delete')">
        <span class="context-menu-icon">×</span>
        <span>delete</span>
      </button>
    </div>
  `,
};
