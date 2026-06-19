/**
 * EmbedResultRow — one block row in a saved-view result list.
 *
 * Used by every surface that renders blocks from elsewhere as a
 * flat list (QueryEmbedBlock on pages, SavedViewsPage). Owns the
 * row template, the bullet + click-to-cycle-todo behavior, the
 * action handlers behind the EmbedContextMenu, and the menu itself.
 *
 * Parents pass the block + optional host-page-modal callbacks
 * (`onScheduleBlock`, `onOpenBlockInfo`) and listen for `@changed`
 * (uuid) to refresh their own state + dispatch the cross-component
 * `brainspread:block-changed` event. Errors surface via `@error`
 * (message) so the parent's error banner stays the single error
 * surface — the row itself is intentionally stateless beyond the
 * shared context menu.
 *
 * This intentionally stops short of editing / tree-structural
 * behaviors (indent / outdent / add-child / drag). Those live in
 * BlockComponent because they only make sense inside a block's
 * home page; embed rows are display-only links into that home page.
 */
window.EmbedResultRow = {
  name: "EmbedResultRow",

  components: {
    EmbedContextMenu: window.EmbedContextMenu || {},
  },

  props: {
    block: { type: Object, required: true },
    // Schedule + Block info both need a modal that lives on a host
    // surface (Page.js / SavedViewsPage own the popover instances).
    // The menu hides the matching item when the callback is missing.
    onScheduleBlock: { type: Function, default: null },
    onOpenBlockInfo: { type: Function, default: null },
  },

  emits: ["changed", "error"],

  methods: {
    blockHref(b) {
      if (!b || !b.page_slug) return "#";
      return `/knowledge/page/${encodeURIComponent(b.page_slug)}/#block-${b.uuid}`;
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

    async toggleTodo() {
      const b = this.block;
      if (!this.isTodoType(b)) return;
      try {
        const r = await window.apiService.toggleBlockTodo(b.uuid);
        if (r && r.success && r.data) {
          // Mutate the prop in place so the bullet + meta update
          // without forcing a parent refetch. The row stays visible
          // even when the new state falls outside the saved view's
          // filter — gives immediate feedback; a real refresh
          // happens on the next fetch via the changed listener.
          b.block_type = r.data.block_type;
          b.completed_at = r.data.completed_at;
          b.content = r.data.content;
          this.$emit("changed", b.uuid);
        } else {
          const errs = (r && r.errors) || {};
          this.$emit(
            "error",
            (errs.non_field_errors && errs.non_field_errors[0]) ||
              "failed to toggle todo"
          );
        }
      } catch (err) {
        console.error("toggleBlockTodo failed:", err);
        this.$emit("error", "failed to toggle todo. please try again.");
      }
    },

    openRowMenu(event) {
      this.$refs.rowMenu?.openAt(this.block, event);
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
        this.$emit("changed", b.uuid);
      } catch (err) {
        console.error("moveBlockToDaily failed:", err);
        this.$emit("error", "failed to move block to today");
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
        this.$emit("changed", b.uuid);
      } catch (err) {
        console.error("moveBlockToPage failed:", err);
        this.$emit("error", `failed to move block: ${err.message || err}`);
      }
    },

    async actionCopyLink(b) {
      if (!b.page_slug) {
        this.$emit("error", "could not build block link");
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
        this.$emit("error", "could not copy link");
      }
    },

    actionSchedule(b, opts) {
      if (!this.onScheduleBlock) return;
      this.onScheduleBlock(b, opts || {});
      // No `changed` here — the host's popover fires
      // brainspread:block-changed on save, which the parent listens
      // to directly. Emitting `changed` here would refetch on cancel.
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
        this.$emit("changed", b.uuid);
      } catch (err) {
        console.error("deleteBlock failed:", err);
        this.$emit("error", `failed to delete block: ${err.message || err}`);
      }
    },
  },

  template: `
    <li>
      <div class="result-row" @contextmenu="openRowMenu($event)">
        <div
          class="block-bullet"
          :class="{
            'todo': block.block_type === 'todo',
            'doing': block.block_type === 'doing',
            'done': block.block_type === 'done',
            'later': block.block_type === 'later',
            'wontdo': block.block_type === 'wontdo'
          }"
          @click.stop="isTodoType(block) ? toggleTodo() : null"
          :title="isTodoType(block) ? 'Cycle todo state' : ''"
          :role="isTodoType(block) ? 'button' : null"
          :aria-label="isTodoType(block) ? 'Cycle todo state' : null"
        >{{ bulletSymbol(block) }}</div>
        <a :href="blockHref(block)" class="result-row-link">
          <span class="result-content">{{ blockLabel(block) }}</span>
          <span class="result-meta">
            <span v-if="block.block_type" class="result-block-type">{{ block.block_type }}</span>
            <span v-if="block.scheduled_for"> · due {{ block.scheduled_for }}</span>
            <span v-if="block.completed_at"> · done {{ block.completed_at.split('T')[0] }}</span>
            <span v-if="block.page_title"> · {{ block.page_title }}</span>
          </span>
        </a>
        <button
          type="button"
          class="block-menu result-row-menu-btn"
          @click="openRowMenu($event)"
          @contextmenu="openRowMenu($event)"
          title="Block options"
          aria-label="Block options"
        >⋮</button>
      </div>
      <EmbedContextMenu
        ref="rowMenu"
        :can-schedule="!!onScheduleBlock"
        :can-block-info="!!onOpenBlockInfo"
        @action="onMenuAction"
      />
    </li>
  `,
};
