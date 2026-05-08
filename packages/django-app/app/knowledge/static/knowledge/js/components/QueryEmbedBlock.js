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
