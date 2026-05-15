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
window.BlockInfoModal = {
  name: "BlockInfoModal",
  props: {
    isOpen: { type: Boolean, default: false },
    block: { type: Object, default: null },
  },
  emits: ["close"],
  data() {
    return {
      uuidCopied: false,
      uuidCopyTimer: null,
    };
  },
  computed: {
    createdAtPretty() {
      return this.formatTimestamp(this.block?.created_at);
    },
    modifiedAtPretty() {
      return this.formatTimestamp(this.block?.modified_at);
    },
    scheduledForPretty() {
      return this.block?.scheduled_for || "";
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
        this.$nextTick(() => this.$refs.closeBtn?.focus());
      } else if (this.uuidCopyTimer) {
        clearTimeout(this.uuidCopyTimer);
        this.uuidCopyTimer = null;
      }
    },
  },
  methods: {
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

            <dt>modified</dt>
            <dd>{{ modifiedAtPretty }}</dd>

            <template v-if="scheduledForPretty">
              <dt>scheduled for</dt>
              <dd>{{ scheduledForPretty }}</dd>
            </template>

            <template v-if="completedAtPretty">
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
