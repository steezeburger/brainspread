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
 * Each matched block renders as an EmbedResultRow — that component
 * owns the bullet, click-to-cycle-todo, the right-click menu, and
 * the move/schedule/copy-link/delete/info action handlers. This
 * component's job is the embed header, the loading / error / empty
 * states, the saved-view fetch, and listening for cross-component
 * change events so it re-runs the view when a displayed block
 * mutates elsewhere on the page.
 */
window.QueryEmbedBlock = {
  components: {
    EmbedResultRow: window.EmbedResultRow || {},
  },

  props: {
    embed: { type: Object, required: true },
    // All optional so the embed can also render outside the page
    // surface (e.g. preview) without forcing a caller to wire them up.
    onDelete: { type: Function, default: null },
    onToggleCollapsed: { type: Function, default: null },
    onMoveUp: { type: Function, default: null },
    onMoveDown: { type: Function, default: null },
    // Host-page delegates forwarded straight to each EmbedResultRow.
    // Schedule + Block info need a modal that lives on the host;
    // Move-to-today / Move-to-page need to trigger the host's own
    // reload so the moved block shows up on the destination page
    // without a manual refresh. See EmbedResultRow's prop comment.
    onScheduleBlock: { type: Function, default: null },
    onOpenBlockInfo: { type: Function, default: null },
    onMoveBlockToToday: { type: Function, default: null },
    onMoveBlockToPage: { type: Function, default: null },
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
    // Re-run the saved view when any block we might be displaying
    // mutates elsewhere on the page (a different embed's row, the
    // home-page editor, etc.). Our own row actions also broadcast
    // through onRowChanged below; tag the broadcast with
    // `source: this` so the listener skips our own refetch loop.
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

    broadcastChange(uuid) {
      if (!uuid) return;
      document.dispatchEvent(
        new CustomEvent("brainspread:block-changed", {
          detail: { uuid, source: this },
        })
      );
    },

    async onRowChanged(uuid) {
      this.broadcastChange(uuid);
      await this.fetch();
    },

    onRowError(message) {
      this.error = message;
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
          <EmbedResultRow
            v-for="b in result.results"
            :key="b.uuid"
            :block="b"
            :on-schedule-block="onScheduleBlock"
            :on-open-block-info="onOpenBlockInfo"
            :on-move-block-to-today="onMoveBlockToToday"
            :on-move-block-to-page="onMoveBlockToPage"
            :on-changed="onRowChanged"
            @error="onRowError"
          />
        </ul>
      </template>
    </div>
  `,
};
