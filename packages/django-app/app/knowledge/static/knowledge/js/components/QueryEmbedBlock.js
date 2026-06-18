/**
 * QueryEmbedBlock — inline render of a SavedView's matched blocks.
 *
 * Embeds were originally Block(block_type='query'); they're now their
 * own concept (PageEmbeddedView, see knowledge.models.page_embedded_view).
 * The component takes one ``embed`` prop ({uuid, order, collapsed,
 * saved_view: {uuid,name,slug}}) plus optional callbacks for
 * delete / toggle-collapse / move-up / move-down. The parent Page
 * handles persistence (POST/DELETE/PUT to /api/embeds/) and refreshes
 * its own embedded_views state after each call.
 *
 * Result rows surface the block's todo-state bullet; clicking the
 * bullet cycles the block's state in place via the same endpoint
 * BlockComponent uses. The text portion remains a navigation link to
 * the source page — inline content edits still require clicking
 * through to the block on its home page.
 */
window.QueryEmbedBlock = {
  props: {
    embed: { type: Object, required: true },
    // All optional so the embed can also render outside the page
    // surface (e.g. preview) without forcing a caller to wire them up.
    onDelete: { type: Function, default: null },
    onToggleCollapsed: { type: Function, default: null },
    onMoveUp: { type: Function, default: null },
    onMoveDown: { type: Function, default: null },
    // Schedule needs the ScheduleBlockPopover, which lives on the host
    // page (Page.js). Caller wires this to open its popover for the
    // given block; the embed hides the schedule action when the
    // callback isn't provided.
    onScheduleBlock: { type: Function, default: null },
  },

  data() {
    return {
      loading: true,
      error: null,
      result: null, // {view, count, results, truncated}
      // Per-row context menu — one menu is rendered for the whole
      // embed and positioned at the click point; `menuBlock` is the
      // result row it was opened for.
      menuBlock: null,
      menuPosition: { x: 0, y: 0 },
    };
  },

  computed: {
    savedView() {
      return this.embed && this.embed.saved_view;
    },
    viewLink() {
      if (!this.savedView) return "#";
      return `/knowledge/views/${encodeURIComponent(this.savedView.slug)}/`;
    },
    title() {
      if (this.savedView && this.savedView.name) return this.savedView.name;
      return "Saved view";
    },
    collapsed() {
      return !!(this.embed && this.embed.collapsed);
    },
  },

  mounted() {
    if (!this.collapsed) this.fetch();
    // Re-run the saved view when any embed action elsewhere on the
    // page mutates a block we might be displaying. The toggle bullet
    // and the row context-menu actions all broadcast this event.
    // We tag our own broadcasts with `source: this` so the local
    // action path (which already refetches synchronously) doesn't
    // also trigger a redundant fetch from the listener.
    this._onBlocksChanged = (ev) => {
      const uuid = ev?.detail?.uuid;
      if (!uuid || ev?.detail?.source === this) return;
      if (this.collapsed || !this.result?.results) return;
      if (this.result.results.some((b) => b.uuid === uuid)) {
        this.fetch();
      }
    };
    document.addEventListener(
      "brainspread:block-changed",
      this._onBlocksChanged
    );
  },

  beforeUnmount() {
    if (this._onBlocksChanged) {
      document.removeEventListener(
        "brainspread:block-changed",
        this._onBlocksChanged
      );
    }
    this.closeRowMenu();
  },

  watch: {
    collapsed(now, prev) {
      // Lazy-load when the user expands a previously-collapsed embed,
      // so collapsed embeds don't all hammer /api/views/run/ on page
      // load.
      if (prev && !now && !this.result) this.fetch();
    },
  },

  methods: {
    async fetch() {
      if (!this.savedView || !this.savedView.uuid) {
        this.loading = false;
        this.error = "This embed doesn't reference a saved view.";
        return;
      }
      this.loading = true;
      try {
        const r = await window.apiService.runSavedView({
          uuid: this.savedView.uuid,
          limit: 25,
        });
        if (r && r.success) {
          this.result = r.data;
          this.error = null;
        } else {
          const errs = (r && r.errors) || {};
          this.error =
            (errs.non_field_errors && errs.non_field_errors[0]) ||
            "Failed to run saved view";
        }
      } catch (err) {
        console.error("runSavedView failed:", err);
        this.error = String(err);
      } finally {
        this.loading = false;
      }
    },
    blockHref(b) {
      if (!b || !b.page_slug) return "#";
      return `/knowledge/page/${encodeURIComponent(b.page_slug)}/#block-${
        b.uuid
      }`;
    },
    blockLabel(b) {
      const c = (b.content || "").trim();
      if (!c) return "(empty block)";
      return c.length > 200 ? c.slice(0, 200) + "…" : c;
    },
    isTodoType(b) {
      return ["todo", "doing", "done", "later", "wontdo"].includes(
        b && b.block_type
      );
    },
    bulletSymbol(b) {
      switch (b && b.block_type) {
        case "todo":
        case "later":
          return "☐";
        case "doing":
          return "◐";
        case "done":
          return "☑";
        case "wontdo":
          return "⊘";
        default:
          return "•";
      }
    },
    async toggleTodo(b) {
      if (!this.isTodoType(b)) return;
      try {
        const r = await window.apiService.toggleBlockTodo(b.uuid);
        if (r && r.success && r.data) {
          // Mutate in place so the bullet + meta update without
          // refetching the whole embed. The row stays visible even
          // when the new state falls outside the saved view's filter
          // — gives the user immediate "yes that worked" feedback;
          // a real refresh happens on the next fetch.
          b.block_type = r.data.block_type;
          b.completed_at = r.data.completed_at;
          b.content = r.data.content;
          this.broadcastChange(b.uuid);
        } else {
          const errs = (r && r.errors) || {};
          this.error =
            (errs.non_field_errors && errs.non_field_errors[0]) ||
            "Failed to toggle todo";
        }
      } catch (err) {
        console.error("toggleBlockTodo failed:", err);
        this.error = "failed to toggle todo. please try again.";
      }
    },
    openRowMenu(b, event) {
      if (!b) return;
      event.preventDefault();
      event.stopPropagation();

      // Match BlockComponent.showContextMenuAt — fixed-positioned at
      // the click point, clamped to viewport with mobile padding so
      // the menu never hides under the soft keyboard / browser chrome.
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

      this.menuPosition = { x, y };
      this.menuBlock = b;

      this.$nextTick(() => {
        const el = this.$el?.querySelector(".block-context-menu");
        if (!el) return;
        const h = el.offsetHeight;
        const vh = window.innerHeight;
        let ny = y;
        if (ny + h + shadowOffset > vh - bottomPadding) {
          ny = vh - h - shadowOffset - bottomPadding;
        }
        ny = Math.max(edgePadding, ny);
        if (ny !== this.menuPosition.y) {
          this.menuPosition = { x, y: ny };
        }
      });

      // Same delayed listener BlockComponent uses so this click
      // doesn't immediately close its own menu.
      setTimeout(() => {
        document.addEventListener("click", this.closeRowMenu);
      }, 10);
    },

    closeRowMenu() {
      this.menuBlock = null;
      document.removeEventListener("click", this.closeRowMenu);
    },

    broadcastChange(uuid) {
      if (!uuid) return;
      document.dispatchEvent(
        new CustomEvent("brainspread:block-changed", {
          detail: { uuid, source: this },
        })
      );
    },

    async menuAction(action) {
      const b = this.menuBlock;
      this.closeRowMenu();
      if (!b) return;
      switch (action) {
        case "moveToToday":
          await this.actionMoveToToday(b);
          break;
        case "moveToPage":
          await this.actionMoveToPage(b);
          break;
        case "schedule":
          this.actionSchedule(b, { clear: false });
          break;
        case "unschedule":
          this.actionSchedule(b, { clear: true });
          break;
        case "delete":
          await this.actionDelete(b);
          break;
      }
    },

    async actionMoveToToday(b) {
      try {
        const r = await window.apiService.moveBlockToDaily(b.uuid);
        if (!r || !r.success) {
          throw new Error(
            r?.errors?.non_field_errors?.[0] || "move to today failed"
          );
        }
        this.broadcastChange(b.uuid);
        await this.fetch();
      } catch (err) {
        console.error("moveBlockToDaily failed:", err);
        this.error = "failed to move block to today";
      }
    },

    async actionMoveToPage(b) {
      if (!window.appModals?.pickPage) {
        console.error("appModals.pickPage is not available");
        return;
      }
      const target = await window.appModals.pickPage({
        title: "move block to page",
        placeholder: "search pages…",
        confirmLabel: "move",
      });
      if (!target) return;
      try {
        const r = await window.apiService.moveBlockToPage(b.uuid, target.uuid);
        if (!r || !r.success) {
          throw new Error(r?.errors?.non_field_errors?.[0] || "move failed");
        }
        this.broadcastChange(b.uuid);
        await this.fetch();
      } catch (err) {
        console.error("moveBlockToPage failed:", err);
        this.error = `failed to move block: ${err.message || err}`;
      }
    },

    actionSchedule(b, opts) {
      // The schedule UX needs the ScheduleBlockPopover — that lives on
      // the host page (Page.js), so defer to its handler if wired.
      // We refresh on the broadcast event after the host's save path.
      if (!this.onScheduleBlock) return;
      this.onScheduleBlock(b, opts || {});
    },

    async actionDelete(b) {
      const confirmed = await (window.appModals?.confirm?.({
        title: "delete block?",
        message: "this will also delete any child blocks and cannot be undone.",
        confirmLabel: "delete",
        destructive: true,
      }) ?? Promise.resolve(window.confirm("Delete this block?")));
      if (!confirmed) return;
      try {
        const r = await window.apiService.deleteBlock(b.uuid);
        if (!r || !r.success) {
          throw new Error(r?.errors?.non_field_errors?.[0] || "delete failed");
        }
        this.broadcastChange(b.uuid);
        await this.fetch();
      } catch (err) {
        console.error("deleteBlock failed:", err);
        this.error = `failed to delete block: ${err.message || err}`;
      }
    },

    onRemoveClick() {
      if (!this.onDelete) return;
      this.onDelete(this.embed);
    },
    onToggleClick() {
      if (!this.onToggleCollapsed) return;
      this.onToggleCollapsed(this.embed);
    },
    onMoveUpClick() {
      if (!this.onMoveUp) return;
      this.onMoveUp(this.embed);
    },
    onMoveDownClick() {
      if (!this.onMoveDown) return;
      this.onMoveDown(this.embed);
    },
  },

  template: `
    <div class="block-query-embed" :class="{ 'is-collapsed': collapsed }" :data-embed-uuid="embed.uuid">
      <div class="block-query-embed-header">
        <button
          v-if="onToggleCollapsed"
          type="button"
          class="block-query-embed-toggle"
          @click="onToggleClick"
          :title="collapsed ? 'Expand' : 'Collapse'"
          :aria-label="collapsed ? 'Expand embed' : 'Collapse embed'"
        >{{ collapsed ? '▶' : '▼' }}</button>
        <a class="block-query-embed-title" :href="viewLink">≡ {{ title }}</a>
        <span v-if="result && !collapsed" class="block-query-embed-meta">
          {{ result.count }}<span v-if="result.truncated">+ truncated</span>
        </span>
        <span class="block-query-embed-actions">
          <button
            v-if="onMoveUp"
            type="button"
            class="block-query-embed-iconbtn"
            @click="onMoveUpClick"
            title="Move up"
            aria-label="Move embed up"
          >↑</button>
          <button
            v-if="onMoveDown"
            type="button"
            class="block-query-embed-iconbtn"
            @click="onMoveDownClick"
            title="Move down"
            aria-label="Move embed down"
          >↓</button>
          <button
            v-if="onDelete"
            type="button"
            class="block-query-embed-iconbtn"
            @click="onRemoveClick"
            title="Remove embed from page"
            aria-label="Remove embed from page"
          >×</button>
        </span>
      </div>
      <template v-if="!collapsed">
        <div v-if="loading" class="block-query-embed-empty">Loading…</div>
        <div v-else-if="error" class="block-query-embed-empty">{{ error }}</div>
        <div v-else-if="!result || !result.results.length" class="block-query-embed-empty">
          No matches.
        </div>
        <ul v-else class="result-list">
          <li v-for="b in result.results" :key="b.uuid">
            <div class="result-row" @contextmenu="openRowMenu(b, $event)">
              <div
                class="block-bullet"
                :class="{
                  'todo': b.block_type === 'todo',
                  'doing': b.block_type === 'doing',
                  'done': b.block_type === 'done',
                  'later': b.block_type === 'later',
                  'wontdo': b.block_type === 'wontdo'
                }"
                @click.stop="isTodoType(b) ? toggleTodo(b) : null"
                :title="isTodoType(b) ? 'Cycle todo state' : ''"
                :role="isTodoType(b) ? 'button' : null"
                :aria-label="isTodoType(b) ? 'Cycle todo state' : null"
              >{{ bulletSymbol(b) }}</div>
              <a :href="blockHref(b)" class="result-row-link">
                <span class="result-content">{{ blockLabel(b) }}</span>
                <span class="result-meta">
                  <span v-if="b.block_type" class="result-block-type">{{ b.block_type }}</span>
                  <span v-if="b.scheduled_for"> · due {{ b.scheduled_for }}</span>
                  <span v-if="b.completed_at"> · done {{ b.completed_at.split('T')[0] }}</span>
                  <span v-if="b.page_title"> · {{ b.page_title }}</span>
                </span>
              </a>
              <button
                type="button"
                class="block-menu result-row-menu-btn"
                @click="openRowMenu(b, $event)"
                @contextmenu="openRowMenu(b, $event)"
                title="Block options"
                aria-label="Block options"
              >⋮</button>
            </div>
          </li>
        </ul>
      </template>
      <div
        v-if="menuBlock"
        class="block-context-menu"
        :style="{ left: menuPosition.x + 'px', top: menuPosition.y + 'px' }"
        @click.stop
        role="menu"
      >
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="menuAction('moveToToday')">
          <span class="context-menu-icon">⇨</span>
          <span>move to today's daily</span>
        </button>
        <button class="context-menu-item" role="menuitem" tabindex="-1" @click="menuAction('moveToPage')">
          <span class="context-menu-icon">→</span>
          <span>move to page…</span>
        </button>
        <template v-if="onScheduleBlock">
          <div class="context-menu-separator"></div>
          <button class="context-menu-item" role="menuitem" tabindex="-1" @click="menuAction('schedule')">
            <span class="context-menu-icon">◷</span>
            <span>{{ menuBlock.scheduled_for ? 'reschedule…' : 'schedule…' }}</span>
          </button>
          <button v-if="menuBlock.scheduled_for" class="context-menu-item" role="menuitem" tabindex="-1" @click="menuAction('unschedule')">
            <span class="context-menu-icon">×</span>
            <span>clear schedule</span>
          </button>
        </template>
        <div class="context-menu-separator"></div>
        <button class="context-menu-item context-menu-danger" role="menuitem" tabindex="-1" @click="menuAction('delete')">
          <span class="context-menu-icon">×</span>
          <span>delete</span>
        </button>
      </div>
    </div>
  `,
};
