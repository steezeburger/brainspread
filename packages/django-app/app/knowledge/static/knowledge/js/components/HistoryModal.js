// HistoryModal — block revision history (issue #234). Opened from the
// block context menu's "history" action. Lists BlockRevision rows
// (newest first) with timestamp, source, a one-line summary of what
// changed, and the full old content on expand. Each row can be
// restored, which writes that revision's values back onto the block and
// appends a new revision for the restore itself — so a restore can
// always be undone by restoring the entry it just created.
//
// Props:
//   isOpen  boolean — controls visibility
//   block   object  — the block dict whose history we're showing
// Emits:
//   close     — user dismissed
//   restored  — { block } a restore completed; parent should refresh
window.HistoryModal = {
  name: "HistoryModal",
  props: {
    isOpen: { type: Boolean, default: false },
    block: { type: Object, default: null },
  },
  emits: ["close", "restored"],
  data() {
    return {
      loading: false,
      error: null,
      revisions: [],
      expandedUuids: {},
      restoringUuid: null,
    };
  },
  watch: {
    isOpen(open) {
      if (open) {
        this.expandedUuids = {};
        this.fetchRevisions();
        this.$nextTick(() => this.$refs.closeBtn?.focus());
      }
    },
  },
  methods: {
    async fetchRevisions() {
      if (!this.block?.uuid) return;
      this.loading = true;
      this.error = null;
      try {
        const result = await window.apiService.getBlockRevisions(
          this.block.uuid
        );
        this.revisions = result.success ? result.data || [] : [];
        if (!result.success) {
          this.error = "failed to load history";
        }
      } catch (err) {
        console.error("getBlockRevisions failed:", err);
        this.error = "failed to load history";
      } finally {
        this.loading = false;
      }
    },
    toggleExpanded(uuid) {
      this.expandedUuids = {
        ...this.expandedUuids,
        [uuid]: !this.expandedUuids[uuid],
      };
    },
    // The state that superseded this revision — the next-newer revision
    // in the (newest-first) list, or the live block for the newest row.
    successorFor(index) {
      return index === 0 ? this.block : this.revisions[index - 1];
    },
    summaryFor(revision, index) {
      const successor = this.successorFor(index);
      if (!successor) return "changed";
      const parts = [];
      if ((revision.content || "") !== (successor.content || "")) {
        parts.push(!successor.content ? "content cleared" : "content edited");
      }
      if (revision.block_type !== successor.block_type) {
        parts.push(`type: ${revision.block_type} → ${successor.block_type}`);
      }
      const dueChanged =
        revision.due_at !== successor.due_at ||
        revision.due_at_has_time !== successor.due_at_has_time;
      if (dueChanged) parts.push("due date changed");
      if (revision.completed_at !== successor.completed_at) {
        parts.push("completion changed");
      }
      if (
        JSON.stringify(revision.properties || {}) !==
        JSON.stringify(successor.properties || {})
      ) {
        parts.push("properties changed");
      }
      return parts.length ? parts.join(", ") : "changed";
    },
    sourceLabel(source) {
      const labels = {
        user: "user",
        automation: "automation",
        assistant: "assistant",
        system: "system",
      };
      return labels[source] || source;
    },
    formatTimestamp(value) {
      if (!value) return "";
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return value;
      return (
        d.toLocaleDateString() +
        " " +
        d.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    },
    async restore(revision) {
      if (!this.block?.uuid || this.restoringUuid) return;
      this.restoringUuid = revision.uuid;
      try {
        const result = await window.apiService.restoreBlockRevision(
          this.block.uuid,
          revision.uuid
        );
        if (result.success) {
          this.$emit("restored", { block: result.data });
          await this.fetchRevisions();
        } else {
          this.error = "failed to restore";
        }
      } catch (err) {
        console.error("restoreBlockRevision failed:", err);
        this.error = "failed to restore";
      } finally {
        this.restoringUuid = null;
      }
    },
    onBackdropClick(event) {
      if (event.target === event.currentTarget) this.$emit("close");
    },
    onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        // app.js and Page.js listen for Escape on document to close the
        // left nav / chat panel; keep this keystroke scoped to the modal.
        event.stopPropagation();
        this.$emit("close");
      }
    },
  },
  template: `
    <teleport to="body">
      <div
        v-if="isOpen && block"
        class="app-modal-backdrop"
        @click.self="onBackdropClick"
        @keydown="onKeydown"
        tabindex="-1"
      >
        <div class="app-modal history-modal" role="dialog" aria-modal="true" aria-label="Block history">
          <div class="app-modal-header history-modal-header">
            history
            <button
              type="button"
              ref="closeBtn"
              class="help-close-btn"
              @click="$emit('close')"
              title="Close"
            >×</button>
          </div>

          <div v-if="loading" class="history-empty">loading…</div>
          <div v-else-if="error" class="history-empty history-error">{{ error }}</div>
          <div v-else-if="!revisions.length" class="history-empty">no history yet</div>

          <ul v-else class="history-list">
            <li v-for="(revision, index) in revisions" :key="revision.uuid" class="history-row">
              <div class="history-row-main">
                <button
                  type="button"
                  class="history-expand-btn"
                  @click="toggleExpanded(revision.uuid)"
                  :aria-expanded="!!expandedUuids[revision.uuid]"
                >{{ expandedUuids[revision.uuid] ? '▾' : '▸' }}</button>
                <div class="history-row-info">
                  <div class="history-row-summary">{{ summaryFor(revision, index) }}</div>
                  <div class="history-row-meta">
                    <span>{{ formatTimestamp(revision.created_at) }}</span>
                    <span class="history-row-source">{{ sourceLabel(revision.source) }}</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="btn btn-outline btn-compact history-restore-btn"
                  :disabled="restoringUuid === revision.uuid"
                  @click="restore(revision)"
                >{{ restoringUuid === revision.uuid ? 'restoring…' : 'restore' }}</button>
              </div>
              <div v-if="expandedUuids[revision.uuid]" class="history-row-detail">
                <pre v-if="revision.content" class="history-row-content">{{ revision.content }}</pre>
                <span v-else class="history-row-empty-content">(empty)</span>
              </div>
            </li>
          </ul>

          <div class="app-modal-actions">
            <button
              type="button"
              class="btn btn-primary"
              @click="$emit('close')"
            >close</button>
          </div>
        </div>
      </div>
    </teleport>
  `,
};
