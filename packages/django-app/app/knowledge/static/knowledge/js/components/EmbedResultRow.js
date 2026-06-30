/**
 * EmbedResultRow — one block row in a saved-view result list.
 *
 * Used by every surface that renders blocks from elsewhere as a
 * flat list (QueryEmbedBlock on pages, SavedViewsPage). Owns the
 * row template, the bullet + click-to-cycle-todo behavior, the
 * action handlers behind the EmbedContextMenu, and the menu itself.
 *
 * Parents pass the block + optional host-page-modal callbacks
 * (`onScheduleBlock`, `onOpenBlockInfo`) and an `onChanged(uuid)`
 * async callback the row awaits after every mutation. The await
 * matters: the parent typically refetches the saved view inside
 * onChanged, and the row needs to wait on that before yielding —
 * otherwise the user can re-open the menu before the prop has been
 * replaced with the fresh block, and pick up stale page_slug etc.
 * Errors surface via `@error` (message) so the parent's error
 * banner stays the single error surface — the row itself is
 * intentionally stateless beyond the shared context menu.
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
    // Host-page delegates. Schedule + Block info both need a modal
    // that lives on the host (Page.js / SavedViewsPage own those).
    // Move-to-today / Move-to-page also delegate when provided so
    // the host can reload its own block list — otherwise the moved
    // block lands on the page silently and the user sees nothing
    // until refresh. When a callback is missing, the row falls back
    // to its own implementation (used by SavedViewsPage, which has
    // no host page to update).
    onScheduleBlock: { type: Function, default: null },
    onOpenBlockInfo: { type: Function, default: null },
    onMoveBlockToToday: { type: Function, default: null },
    onMoveBlockToPage: { type: Function, default: null },
    // Awaitable refresh hook. Each action calls this after the
    // backend mutation completes, and waits on the returned promise
    // before yielding control back to the user — so by the time the
    // user can open the menu again the row's `block` prop has been
    // updated by the parent's refetch (otherwise a fast click would
    // capture stale page_slug etc. from the pre-mutation block).
    onChanged: { type: Function, default: null },
  },

  emits: ["error"],

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
    isCompleted(b) {
      return ["done", "wontdo"].includes(b && b.block_type);
    },
    renderContent(b) {
      // Escape first, then linkify #hashtags into the same clickable
      // anchors the page block tree uses (.inline-tag .clickable-tag →
      // /knowledge/page/<tag>/). Rendered via v-html, so escaping is
      // what keeps block content from injecting markup. This is the
      // reason the content sits in its own <span> rather than inside the
      // block link — anchors can't nest.
      let text = this.blockLabel(b);
      // The bullet already conveys todo state, so strip a leading
      // TODO/DOING/DONE/LATER/WONTDO marker from the text — same as the
      // page block tree's formatContentWithTags.
      if (this.isTodoType(b)) {
        text = text.replace(/^(WONTDO|LATER|DOING|DONE|TODO)\s*:?\s*/i, "");
      }
      const escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      return escaped.replace(
        /#([a-zA-Z0-9_-]+)/g,
        '<a class="inline-tag clickable-tag" href="/knowledge/page/$1/" data-tag="$1">#$1</a>'
      );
    },
    openBlock(event) {
      // Clicking a hashtag inside the content navigates to that tag via
      // its own anchor — let it through. Any other click on the content
      // opens the source block, preserving the old whole-row-is-a-link
      // behavior (the meta line is also a real link for keyboard / open
      // in new tab).
      if (event.target.closest("a")) return;
      const href = this.blockHref(this.block);
      if (!href || href === "#") return;
      if (event.metaKey || event.ctrlKey) {
        window.open(href, "_blank", "noopener");
        return;
      }
      window.location.href = href;
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
          await this.notifyChanged(b.uuid);
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

    async notifyChanged(uuid) {
      if (this.onChanged) await this.onChanged(uuid);
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
      // Defer to the host when wired so the host page reloads its
      // own block list — otherwise the moved block lands on the page
      // silently and the user has to refresh to see it.
      if (this.onMoveBlockToToday) {
        await this.onMoveBlockToToday(b);
        await this.notifyChanged(b.uuid);
        return;
      }
      try {
        const r = await window.apiService.moveBlockToDaily(b.uuid);
        if (!r || !r.success) {
          throw new Error(
            r?.errors?.non_field_errors?.[0] || "move to today failed"
          );
        }
        await this.notifyChanged(b.uuid);
      } catch (err) {
        console.error("moveBlockToDaily failed:", err);
        this.$emit("error", "failed to move block to today");
      }
    },

    async actionMoveToPage(b) {
      // Same delegation reasoning as actionMoveToToday — host owns
      // the picker + reload when present.
      if (this.onMoveBlockToPage) {
        await this.onMoveBlockToPage(b);
        await this.notifyChanged(b.uuid);
        return;
      }
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
        await this.notifyChanged(b.uuid);
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
        await this.notifyChanged(b.uuid);
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
        <div class="result-row-link">
          <span class="result-content" :class="{ completed: isCompleted(block) }" @click="openBlock" v-html="renderContent(block)"></span>
          <a :href="blockHref(block)" class="result-meta">
            <span v-if="block.block_type" class="result-block-type">{{ block.block_type }}</span>
            <span v-if="block.completed_at"> · done {{ block.completed_at.split('T')[0] }}</span>
            <span v-if="block.page_title"> · {{ block.page_title }}</span>
          </a>
        </div>
        <span v-if="block.due_date" class="result-due">due {{ block.due_date }}<template v-if="block.due_time"> {{ block.due_time }}</template></span>
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
