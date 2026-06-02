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
 * The result list itself is read-only — clicking a row jumps to that
 * block on its source page so the user can interact with it there.
 */
window.QueryEmbedBlock = {
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
    if (!this.collapsed) this.fetch();
  },

  watch: {
    collapsed(now, prev) {
      // Lazy-load when the user expands a previously-collapsed embed,
      // so collapsed embeds don't all hammer /api/views/run/ on page
      // load.
      if (prev && !now && !this.result) this.fetch();
    },
    contextDate(now, prev) {
      // ``scope="daily"`` embeds are the same DB row across every daily,
      // so navigating between dailies can reuse this component instance
      // rather than remount it. Refetch so the results rebase to the
      // new daily — but only when the view actually cares about
      // context_date. Without the dates_relative_to_daily check we'd
      // re-run every "live today" embed on every daily nav for no
      // visible reason.
      if (now !== prev && !this.collapsed && this._viewRebases()) {
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
      this.loading = true;
      try {
        const r = await window.apiService.runSavedView({
          uuid: this.savedView.uuid,
          limit: 25,
          contextDate: this.contextDate || null,
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
            <a :href="blockHref(b)" class="result-row">
              <span class="result-content">{{ blockLabel(b) }}</span>
              <span class="result-meta">
                <span v-if="b.block_type" class="result-block-type">{{ b.block_type }}</span>
                <span v-if="b.scheduled_for"> · due {{ b.scheduled_for }}</span>
                <span v-if="b.completed_at"> · done {{ b.completed_at.split('T')[0] }}</span>
                <span v-if="b.page_title"> · {{ b.page_title }}</span>
              </span>
            </a>
          </li>
        </ul>
      </template>
    </div>
  `,
};
