// BlockInfoModal — read-only metadata modal for the block context-menu's
// "block info" action. Surfaces fields that aren't otherwise visible in
// the UI (created/modified timestamps, uuid, raw properties, etc.) so a
// user can inspect a block's provenance without falling back to the
// network panel or the Django shell.
//
// Props:
//   isOpen     boolean — controls visibility
//   block      object  — the block dict whose info we're showing
// Emits:
//   close — user dismissed
//   save-completed-at — { iso } user saved a corrected completion time
window.BlockInfoModal = {
  name: "BlockInfoModal",
  props: {
    isOpen: { type: Boolean, default: false },
    block: { type: Object, default: null },
  },
  emits: ["close", "save-completed-at"],
  data() {
    return {
      uuidCopied: false,
      uuidCopyTimer: null,
      editingCompleted: false,
      completedDraft: "",
    };
  },
  computed: {
    // completed_at only carries meaning for terminal blocks; gate editing
    // to those so we never stamp a completion time on an open todo.
    isTerminal() {
      return ["done", "wontdo"].includes(this.block?.block_type);
    },
    createdAtPretty() {
      return this.formatTimestamp(this.block?.created_at);
    },
    createdViaPretty() {
      // Human labels for the provenance stamp. Unknown/missing values
      // (older rows predating the field) render as "web".
      const labels = { web: "web app", ai_chat: "ai chat", mcp: "mcp" };
      const v = this.block?.created_via;
      return labels[v] || labels.web;
    },
    modifiedAtPretty() {
      return this.formatTimestamp(this.block?.modified_at);
    },
    scheduledForPretty() {
      const d = this.block?.due_date;
      if (!d) return "";
      const t = this.block?.due_time;
      return t ? `${d} ${t}` : d;
    },
    completedAtPretty() {
      return this.formatTimestamp(this.block?.completed_at);
    },
    propertiesPretty() {
      const props = this.block?.properties;
      if (!props || !Object.keys(props).length) return "";
      try {
        return JSON.stringify(props, null, 2);
      } catch (_) {
        return String(props);
      }
    },
    tagSlugs() {
      const tags = this.block?.tags || [];
      return tags.map((t) => t.name).filter(Boolean);
    },
    hasAsset() {
      return !!this.block?.asset?.uuid;
    },
  },
  watch: {
    isOpen(open) {
      if (open) {
        this.uuidCopied = false;
        this.cancelEditCompleted();
        this.$nextTick(() => this.$refs.closeBtn?.focus());
      } else if (this.uuidCopyTimer) {
        clearTimeout(this.uuidCopyTimer);
        this.uuidCopyTimer = null;
      }
    },
    // Parent reassigns the block object after a successful save; drop out
    // of edit mode so the refreshed timestamp shows.
    block() {
      this.cancelEditCompleted();
    },
  },
  methods: {
    // datetime-local wants "YYYY-MM-DDTHH:MM" in local wall-clock time.
    toDatetimeLocal(value) {
      if (!value) return "";
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return "";
      const pad = (n) => String(n).padStart(2, "0");
      return (
        `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
        `T${pad(d.getHours())}:${pad(d.getMinutes())}`
      );
    },
    startEditCompleted() {
      this.completedDraft = this.toDatetimeLocal(this.block?.completed_at);
      this.editingCompleted = true;
    },
    cancelEditCompleted() {
      this.editingCompleted = false;
      this.completedDraft = "";
    },
    saveCompleted() {
      if (!this.completedDraft) return;
      // The input is local wall-clock; toISOString() converts to the UTC
      // instant the backend stores. A naive value would otherwise be read
      // in server time, drifting the saved moment.
      const d = new Date(this.completedDraft);
      if (Number.isNaN(d.getTime())) return;
      this.editingCompleted = false;
      this.$emit("save-completed-at", { iso: d.toISOString() });
    },
    formatTimestamp(value) {
      // Block info is a debug-leaning surface, so render the full
      // timestamp (date + time + seconds) in the user's locale rather
      // than the "today vs. older" abbreviation we use in the chat
      // history. Seeing seconds matters when two edits land close
      // together.
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
    async copyUuid() {
      const uuid = this.block?.uuid;
      if (!uuid) return;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(uuid);
        } else {
          // execCommand fallback for http:// staging.
          const ta = document.createElement("textarea");
          ta.value = uuid;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
        this.uuidCopied = true;
        if (this.uuidCopyTimer) clearTimeout(this.uuidCopyTimer);
        this.uuidCopyTimer = setTimeout(() => {
          this.uuidCopied = false;
          this.uuidCopyTimer = null;
        }, 1500);
      } catch (err) {
        console.warn("failed to copy uuid:", err);
      }
    },
    onBackdropClick(event) {
      if (event.target === event.currentTarget) this.$emit("close");
    },
    onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
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
        <div class="app-modal block-info-modal" role="dialog" aria-modal="true" aria-label="Block info">
          <div class="app-modal-header">block info</div>

          <dl class="block-info-list">
            <dt>uuid</dt>
            <dd class="block-info-uuid">
              <code>{{ block.uuid }}</code>
              <button
                type="button"
                class="block-info-copy-btn"
                @click="copyUuid"
                :title="uuidCopied ? 'copied' : 'copy uuid'"
              >{{ uuidCopied ? 'copied' : 'copy' }}</button>
            </dd>

            <dt>block type</dt>
            <dd>{{ block.block_type }}</dd>

            <dt v-if="block.content_type && block.content_type !== 'text'">content type</dt>
            <dd v-if="block.content_type && block.content_type !== 'text'">{{ block.content_type }}</dd>

            <dt>order</dt>
            <dd>{{ block.order }}</dd>

            <dt>created</dt>
            <dd>{{ createdAtPretty }}</dd>

            <dt>created via</dt>
            <dd>{{ createdViaPretty }}</dd>

            <dt>modified</dt>
            <dd>{{ modifiedAtPretty }}</dd>

            <template v-if="scheduledForPretty">
              <dt>due</dt>
              <dd>{{ scheduledForPretty }}</dd>
            </template>

            <template v-if="isTerminal">
              <dt>completed</dt>
              <dd>
                <div v-if="!editingCompleted" class="block-info-completed">
                  <span>{{ completedAtPretty || 'not set' }}</span>
                  <button
                    type="button"
                    class="block-info-copy-btn"
                    @click="startEditCompleted"
                  >edit</button>
                </div>
                <div v-else class="block-info-completed">
                  <input
                    type="datetime-local"
                    class="block-info-datetime-input"
                    v-model="completedDraft"
                  />
                  <button
                    type="button"
                    class="block-info-copy-btn"
                    :disabled="!completedDraft"
                    @click="saveCompleted"
                  >save</button>
                  <button
                    type="button"
                    class="block-info-copy-btn"
                    @click="cancelEditCompleted"
                  >cancel</button>
                </div>
              </dd>
            </template>
            <template v-else-if="completedAtPretty">
              <dt>completed</dt>
              <dd>{{ completedAtPretty }}</dd>
            </template>

            <template v-if="block.page_title">
              <dt>page</dt>
              <dd>{{ block.page_title }}<span v-if="block.page_slug"> · /{{ block.page_slug }}</span></dd>
            </template>

            <template v-if="block.parent_block_uuid">
              <dt>parent</dt>
              <dd><code>{{ block.parent_block_uuid }}</code></dd>
            </template>

            <template v-if="tagSlugs.length">
              <dt>tags</dt>
              <dd>{{ tagSlugs.join(', ') }}</dd>
            </template>

            <template v-if="hasAsset">
              <dt>asset</dt>
              <dd>{{ block.asset.original_filename || block.asset.uuid }}</dd>
            </template>

            <template v-if="propertiesPretty">
              <dt>properties</dt>
              <dd><pre class="block-info-properties">{{ propertiesPretty }}</pre></dd>
            </template>
          </dl>

          <div class="app-modal-actions">
            <button
              type="button"
              ref="closeBtn"
              class="btn btn-primary"
              @click="$emit('close')"
            >close</button>
          </div>
        </div>
      </div>
    </teleport>
  `,
};
