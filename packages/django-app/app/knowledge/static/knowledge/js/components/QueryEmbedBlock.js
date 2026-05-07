/**
 * QueryEmbedBlock — inline render of a SavedView's matched blocks
 * (issue #60). Used when a Block has block_type='query' and a
 * `query_view_uuid`. The component fetches /api/views/run/ on mount
 * and renders the result list with a link out to the standalone view
 * page.
 *
 * Kept deliberately light — no editing affordances on the embed
 * itself; users tweak the underlying view from /knowledge/views/.
 */
window.QueryEmbedBlock = {
  props: {
    block: { type: Object, required: true },
    // Parent's delete handler — same one BlockComponent uses, so the
    // confirm dialog + page reload are consistent across block types.
    // Optional so the embed can also render outside the page surface
    // (e.g. preview) without forcing the caller to wire it up.
    onDelete: { type: Function, default: null },
  },

  data() {
    return {
      loading: true,
      error: null,
      result: null, // {view, count, results, truncated}
    };
  },

  computed: {
    viewUuid() {
      return this.block && this.block.query_view_uuid;
    },
    viewLink() {
      if (!this.result || !this.result.view) return "#";
      return `/knowledge/views/${encodeURIComponent(this.result.view.slug)}/`;
    },
    title() {
      if (this.result && this.result.view) return this.result.view.name;
      return "Saved view";
    },
  },

  mounted() {
    this.fetch();
  },

  methods: {
    async fetch() {
      if (!this.viewUuid) {
        this.loading = false;
        this.error = "This block doesn't reference a saved view.";
        return;
      }
      try {
        const r = await window.apiService.runSavedView({
          uuid: this.viewUuid,
          limit: 25,
        });
        if (r && r.success) {
          this.result = r.data;
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
    async onRemoveClick() {
      if (!this.onDelete) return;
      try {
        await this.onDelete(this.block);
      } catch (err) {
        console.error("remove embed failed:", err);
      }
    },
  },

  template: `
    <div class="block-query-embed" :data-block-uuid="block.uuid">
      <div class="block-query-embed-header">
        <a class="block-query-embed-title" :href="viewLink">≡ {{ title }}</a>
        <span v-if="result" class="block-query-embed-meta">
          {{ result.count }}<span v-if="result.truncated">+ truncated</span>
        </span>
        <button
          v-if="onDelete"
          type="button"
          class="block-query-embed-remove"
          @click="onRemoveClick"
          title="Remove embed from page"
          aria-label="Remove embed from page"
        >×</button>
      </div>
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
    </div>
  `,
};
