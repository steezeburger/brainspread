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
    // ISO YYYY-MM-DD when the embed renders inside a daily page; null
    // otherwise. Forwarded to /api/views/run/ as ``context_date`` so a
    // saved view with ``dates_relative_to_daily`` rebases its date
    // tokens to the daily in view rather than the live current date.
    // The server gates on the view's flag, so this is a safe no-op for
    // saved views that haven't opted in.
    contextDate: { type: String, default: null },
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
      // True once a full (row-serializing) fetch has landed. Collapsed
      // embeds fetch count-only, so this stays false until they expand —
      // it's how the expand watcher knows it still needs the rows.
      detailLoaded: false,
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
    // The date-anchor badge: tells the reader whether this embed's date
    // tokens resolved against the daily it's on, or against live today.
    // Falls back to ``null`` until the first fetch lands, since we need
    // the view payload's ``dates_relative_to_daily`` to know which mode
    // we're in. Until then there's nothing to show, which is fine —
    // the header loads in milliseconds and the badge appears with the
    // results.
    dateAnchor() {
      if (!this.result || !this.result.view) return null;
      const rebases = !!this.result.view.dates_relative_to_daily;
      if (rebases && this.contextDate) {
        return {
          kind: "anchored",
          label: this.contextDate,
          tooltip:
            `Date tokens (today / yesterday / N days ago) resolve to ` +
            `${this.contextDate} for this embed — the daily page's date.`,
        };
      }
      if (rebases) {
        return {
          kind: "unanchored",
          label: "today",
          tooltip:
            `This view is set to "Dates relative to daily", but there's ` +
            `no daily page in scope — date tokens fall back to the ` +
            `current date.`,
        };
      }
      return {
        kind: "live",
        label: "live",
        tooltip:
          `Date tokens (today / yesterday / N days ago) resolve to the ` +
          `current date. Turn on "Dates relative to daily" in the saved ` +
          `view editor to anchor them to the daily page instead.`,
      };
    },
  },

  mounted() {
    // Always fetch on mount: expanded embeds load their rows, collapsed
    // embeds load a count-only payload so the header still shows how many
    // blocks the view matches. fetch() picks the mode from `collapsed`.
    this.fetch();
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
      // Expanding a collapsed embed: it only has a count-only payload so
      // far, so fetch the rows. Collapsed embeds still fetch their count
      // on mount, so they don't hammer the full /api/views/run/ path on
      // page load — just the cheap count.
      if (prev && !now && !this.detailLoaded) this.fetch();
    },
    contextDate(now, prev) {
      // ``scope="daily"`` embeds are the same DB row across every daily,
      // so navigating between dailies can reuse this component instance
      // rather than remount it. Refetch so the results (or collapsed
      // count) rebase to the new daily — but only when the view actually
      // cares about context_date. Without the dates_relative_to_daily
      // check we'd re-run every "live today" embed on every daily nav for
      // no visible reason.
      if (now !== prev && this._viewRebases()) {
        this.fetch();
      }
    },
  },

  methods: {
    _viewRebases() {
      // The saved view payload includes ``dates_relative_to_daily`` once
      // the embed has been fetched at least once; before then we'd have
      // nothing to gate on, but the initial fetch ran in mounted() so
      // contextDate changes only matter after that.
      return !!(
        this.result &&
        this.result.view &&
        this.result.view.dates_relative_to_daily
      );
    },
    async fetch() {
      if (!this.savedView || !this.savedView.uuid) {
        this.loading = false;
        this.error = "This embed doesn't reference a saved view.";
        return;
      }
      // Collapsed embeds only need the header count, so skip serializing
      // the matched rows. Expanding later triggers a full fetch (see the
      // collapsed watcher).
      const countOnly = this.collapsed;
      this.loading = true;
      try {
        const r = await window.apiService.runSavedView({
          uuid: this.savedView.uuid,
          limit: 25,
          contextDate: this.contextDate || null,
          countOnly,
        });
        if (r && r.success) {
          this.result = r.data;
          this.detailLoaded = !countOnly;
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
        <span
          v-if="dateAnchor && !collapsed"
          class="block-query-embed-anchor"
          :class="'is-' + dateAnchor.kind"
          :title="dateAnchor.tooltip"
        >
          <svg
            v-if="dateAnchor.kind !== 'live'"
            class="block-query-embed-anchor-icon"
            viewBox="0 0 16 16"
            width="11"
            height="11"
            aria-hidden="true"
            focusable="false"
          ><path fill="currentColor" d="M8 1.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM7.25 5.92V7.5H5.5a.5.5 0 0 0 0 1h1.75v4.97c-1.49-.18-2.62-1.07-3.13-1.91l.72-.43a.4.4 0 0 0-.15-.74L2.5 9.85a.4.4 0 0 0-.5.4v2.34a.4.4 0 0 0 .65.31l.7-.55C4.05 13.55 5.83 14.5 8 14.5s3.95-.95 4.65-2.15l.7.55a.4.4 0 0 0 .65-.31v-2.34a.4.4 0 0 0-.5-.4l-2.19.54a.4.4 0 0 0-.15.74l.72.43c-.51.84-1.64 1.73-3.13 1.91V8.5h1.75a.5.5 0 0 0 0-1H8.75V5.92a2.5 2.5 0 1 0-1.5 0Z"/></svg>
          <span class="block-query-embed-anchor-label">{{ dateAnchor.label }}</span>
        </span>
        <span v-if="result" class="block-query-embed-meta">
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
