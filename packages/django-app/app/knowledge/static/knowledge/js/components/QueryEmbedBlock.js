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
 * BlockComponent uses. Right-click (or the hover ⋮) opens an
 * EmbedContextMenu — see that component for the action list. Inline
 * content edits still require clicking through to the source page.
 */
window.QueryEmbedBlock = {
  components: {
    EmbedContextMenu: window.EmbedContextMenu || {},
  },

  props: {
    embed: { type: Object, required: true },
    // All optional so the embed can also render outside the page
    // surface (e.g. preview) without forcing a caller to wire them up.
    onDelete: { type: Function, default: null },
    onToggleCollapsed: { type: Function, default: null },
    onMoveUp: { type: Function, default: null },
    onMoveDown: { type: Function, default: null },
    // Schedule + Block info both need a modal that lives on the host
    // page (Page.js owns the ScheduleBlockPopover / BlockInfoModal
    // instances). Caller wires these to open its modal for the given
    // block; the embed hides the matching menu items when the
    // callback isn't provided.
    onScheduleBlock: { type: Function, default: null },
    onOpenBlockInfo: { type: Function, default: null },
  },

  data() {
    return {
      loading: true,
      error: null,
      result: null, // {view, count, results, truncated}
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
      this.$refs.rowMenu?.openAt(b, event);
    },

    broadcastChange(uuid) {
      if (!uuid) return;
      document.dispatchEvent(
        new CustomEvent("brainspread:block-changed", {
          detail: { uuid, source: this },
        })
      );
    },

    async onMenuAction({ action, block }) {
      if (!block) return;
      switch (action) {
        case "moveToToday":
          await this.actionMoveToToday(block);
          break;
        case "moveToPage":
          await this.actionMoveToPage(block);
          break;
        case "copyLink":
          await this.actionCopyLink(block);
          break;
        case "schedule":
          this.actionSchedule(block, { clear: false });
          break;
        case "unschedule":
          this.actionSchedule(block, { clear: true });
          break;
        case "blockInfo":
          this.actionBlockInfo(block);
          break;
        case "delete":
          await this.actionDelete(block);
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

    async actionCopyLink(b) {
      if (!b.page_slug) {
        this.error = "could not build block link";
        return;
      }
      const url = `${window.location.origin}/knowledge/page/${encodeURIComponent(b.page_slug)}/#block-${b.uuid}`;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(url);
          return;
        }
      } catch (err) {
        console.warn("clipboard API failed, falling back:", err);
      }
      // execCommand fallback for http:// contexts where the async
      // clipboard API is gated. Mirrors Page.js copyBlockLink.
      try {
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } catch (err) {
        console.error("clipboard fallback failed:", err);
        this.error = "could not copy link";
      }
    },

    actionSchedule(b, opts) {
      // ScheduleBlockPopover lives on the host page (Page.js); defer
      // to its handler when wired. The host dispatches the block-
      // changed event after save, which routes us back through the
      // shared listener for refresh.
      if (!this.onScheduleBlock) return;
      this.onScheduleBlock(b, opts || {});
    },

    actionBlockInfo(b) {
      if (!this.onOpenBlockInfo) return;
      this.onOpenBlockInfo(b);
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
      <EmbedContextMenu
        ref="rowMenu"
        :can-schedule="!!onScheduleBlock"
        :can-block-info="!!onOpenBlockInfo"
        @action="onMenuAction"
      />
    </div>
  `,
};
