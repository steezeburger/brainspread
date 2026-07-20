// Global confirm / prompt / alert dialog host. Replaces native
// window.confirm, window.prompt, and window.alert so we get our own
// styling and so they don't blur the active textarea on mobile (the
// native ones dismiss the soft keyboard which fires every blur handler
// in the app and can race with the destructive operation that just
// asked for confirmation).
//
// Mount this component once at the root of the app and it registers
// itself onto window.appModals. Any caller can then:
//
//   const ok = await window.appModals.confirm("delete this?");
//   const name = await window.appModals.prompt("page title:");
//   await window.appModals.alert("upload failed");
//   const page = await window.appModals.pickPage({title: "embed on a page"});
//   const choice = await window.appModals.choose({options: [...]});
//
// Each method returns a promise that resolves on user action. pickPage
// resolves with the selected page object (uuid, slug, title, ...) or
// null when the user dismisses. choose renders a stacked list of
// options (plus optional read-only text sections, e.g. two versions of
// a conflicting block) and resolves with the chosen option's value, or
// null on dismiss.

window.AppModals = {
  name: "AppModals",

  data() {
    return {
      // Each entry is { id, kind, opts, resolve }. We allow stacking so
      // a callsite that opens a confirm from inside another modal's
      // callback doesn't get dropped on the floor; the most recent
      // entry is the one rendered.
      queue: [],
      // Local input value for the active prompt dialog, mirrored to
      // <input v-model>. Reset every time a new prompt dialog opens.
      promptValue: "",
      // Page-picker state. Lives at root rather than inside the queue
      // entry so v-model can bind directly. Reset whenever a new
      // pickPage opens or any modal closes.
      pickerQuery: "",
      pickerResults: [],
      pickerSelectedIndex: 0,
      pickerLoading: false,
      _pickerDebounce: null,
      _pickerRequestId: 0,
      _idCounter: 0,
    };
  },

  computed: {
    active() {
      return this.queue.length ? this.queue[this.queue.length - 1] : null;
    },
  },

  watch: {
    active(next, prev) {
      if (next && next.kind === "prompt") {
        this.promptValue = next.opts.defaultValue || "";
        this.$nextTick(() => {
          const input = this.$refs.promptInput;
          if (input) {
            input.focus();
            input.select();
          }
        });
      } else if (next && next.kind === "confirm") {
        this.$nextTick(() => {
          const ok = this.$refs.confirmOk;
          if (ok) ok.focus();
        });
      } else if (next && next.kind === "alert") {
        this.$nextTick(() => {
          const ok = this.$refs.alertOk;
          if (ok) ok.focus();
        });
      } else if (next && next.kind === "choose") {
        this.$nextTick(() => {
          // The component root is a <teleport>, so $el isn't an element —
          // the dialog itself lives under document.body.
          const first = document.querySelector(".app-modal-choose-option");
          if (first) first.focus();
        });
      } else if (
        next &&
        (next.kind === "pickPage" || next.kind === "pickBlock")
      ) {
        this._resetPicker();
        this.$nextTick(() => {
          const input = this.$refs.pickerInput;
          if (input) input.focus();
        });
        // Kick off an initial search so the user sees their most-
        // recently-edited pages without typing. Empty query → recent
        // for pages; block search needs a query, so pickBlock just
        // shows its type-to-search hint.
        this._runPickerSearch("");
      }
      if (!next && prev) {
        this.promptValue = "";
        this._resetPicker();
      }
    },
  },

  mounted() {
    window.appModals = {
      confirm: this.confirm.bind(this),
      prompt: this.prompt.bind(this),
      alert: this.alert.bind(this),
      pickPage: this.pickPage.bind(this),
      pickBlock: this.pickBlock.bind(this),
      choose: this.choose.bind(this),
    };
  },

  beforeUnmount() {
    if (window.appModals && window.appModals.confirm === this.confirm) {
      delete window.appModals;
    }
  },

  methods: {
    confirm(opts) {
      const normalized =
        typeof opts === "string" ? { message: opts } : opts || {};
      return new Promise((resolve) => {
        this.queue.push({
          id: ++this._idCounter,
          kind: "confirm",
          opts: {
            title: normalized.title || "are you sure?",
            message: normalized.message || "",
            confirmLabel: normalized.confirmLabel || "ok",
            cancelLabel: normalized.cancelLabel || "cancel",
            destructive: !!normalized.destructive,
          },
          resolve,
        });
      });
    },

    prompt(opts) {
      const normalized =
        typeof opts === "string" ? { message: opts } : opts || {};
      return new Promise((resolve) => {
        this.queue.push({
          id: ++this._idCounter,
          kind: "prompt",
          opts: {
            title: normalized.title || "",
            message: normalized.message || "",
            defaultValue: normalized.defaultValue || "",
            placeholder: normalized.placeholder || "",
            confirmLabel: normalized.confirmLabel || "ok",
            cancelLabel: normalized.cancelLabel || "cancel",
          },
          resolve,
        });
      });
    },

    alert(opts) {
      const normalized =
        typeof opts === "string" ? { message: opts } : opts || {};
      return new Promise((resolve) => {
        this.queue.push({
          id: ++this._idCounter,
          kind: "alert",
          opts: {
            title: normalized.title || "",
            message: normalized.message || "",
            confirmLabel: normalized.confirmLabel || "ok",
          },
          resolve,
        });
      });
    },

    choose(opts) {
      // Multi-option decision dialog. `options` is a list of
      // {value, label, description?, kind?} rendered as stacked buttons
      // (kind: "primary" | "danger" | default outline). `sections` is an
      // optional list of {label, text} rendered read-only above the
      // options — used by the block-conflict dialog to show both
      // versions. Resolves with the chosen value, or null on
      // dismiss/cancel.
      const normalized = opts || {};
      return new Promise((resolve) => {
        this.queue.push({
          id: ++this._idCounter,
          kind: "choose",
          opts: {
            title: normalized.title || "",
            message: normalized.message || "",
            sections: normalized.sections || [],
            options: normalized.options || [],
            cancelLabel: normalized.cancelLabel || "cancel",
          },
          resolve,
        });
      });
    },

    pickPage(opts) {
      // Typeahead page picker. Resolves with the chosen page object
      // (uuid, slug, title, page_type) or null on dismiss. The caller
      // doesn't have to wire search — we use the existing
      // /api/pages/search/ endpoint via window.apiService.
      //
      // Pass ``pageType`` (e.g. "template") to constrain the results
      // to a single page_type. Both the empty-query "recent" list and
      // the typed-query search honor the filter, so the user only sees
      // candidates the caller actually wants.
      const normalized = opts || {};
      return new Promise((resolve) => {
        this.queue.push({
          id: ++this._idCounter,
          kind: "pickPage",
          opts: {
            title: normalized.title || "pick a page",
            message: normalized.message || "",
            placeholder: normalized.placeholder || "search pages…",
            confirmLabel: normalized.confirmLabel || "select",
            cancelLabel: normalized.cancelLabel || "cancel",
            pageType: normalized.pageType || null,
          },
          resolve,
        });
      });
    },

    pickBlock(opts) {
      // Typeahead block picker — same scaffolding as pickPage but
      // searching block content via /api/blocks/search/. Resolves with
      // {uuid, content, page_title, page_slug, block_type} or null on
      // dismiss. Callers pass ``excludeUuids`` to hide blocks that
      // can't be valid targets (e.g. the block being moved).
      const normalized = opts || {};
      return new Promise((resolve) => {
        this.queue.push({
          id: ++this._idCounter,
          kind: "pickBlock",
          opts: {
            title: normalized.title || "pick a block",
            message: normalized.message || "",
            placeholder: normalized.placeholder || "search blocks…",
            confirmLabel: normalized.confirmLabel || "select",
            cancelLabel: normalized.cancelLabel || "cancel",
            excludeUuids: normalized.excludeUuids || [],
          },
          resolve,
        });
      });
    },

    _resetPicker() {
      this.pickerQuery = "";
      this.pickerResults = [];
      this.pickerSelectedIndex = 0;
      this.pickerLoading = false;
      if (this._pickerDebounce) {
        clearTimeout(this._pickerDebounce);
        this._pickerDebounce = null;
      }
    },

    onPickerInput() {
      // Debounce by 200ms so a fast typer doesn't fire a request per
      // keystroke. The latest-request-id check below also guards against
      // out-of-order responses (slow earlier request landing after a
      // fast later one would otherwise stomp the newer results).
      if (this._pickerDebounce) clearTimeout(this._pickerDebounce);
      const query = this.pickerQuery;
      this._pickerDebounce = setTimeout(() => {
        this._runPickerSearch(query);
      }, 200);
    },

    async _runPickerSearch(query) {
      if (this.active?.kind === "pickBlock") {
        return this._runBlockPickerSearch(query);
      }
      const requestId = ++this._pickerRequestId;
      this.pickerLoading = true;
      const pageType = this.active?.opts?.pageType || null;
      try {
        let pages;
        if (query.trim() === "") {
          // Empty query → server returns pages ordered by most-recently
          // modified. Today's daily note is pinned to the top whenever
          // it's a sensible candidate for the active picker (the
          // typical pickPage use case is embedding views or moving
          // blocks, and the active daily is the overwhelming target).
          // Skipped when the caller has filtered to a non-daily
          // page_type (e.g. the template picker) since today's daily
          // wouldn't match that filter anyway.
          const todayLookup =
            pageType && pageType !== "daily"
              ? Promise.resolve(null)
              : this._fetchTodayDailyPage();
          const [recentResult, todayPage] = await Promise.all([
            window.apiService.getPages(true, 15, 0, pageType),
            todayLookup,
          ]);
          if (requestId !== this._pickerRequestId) return; // stale
          pages =
            (recentResult && recentResult.data && recentResult.data.pages) ||
            [];
          if (todayPage) {
            pages = pages.filter((p) => p.uuid !== todayPage.uuid);
            pages.unshift(todayPage);
          }
        } else {
          const result = await window.apiService.searchPages(
            query.trim(),
            15,
            pageType
          );
          if (requestId !== this._pickerRequestId) return; // stale
          pages = (result && result.data && result.data.pages) || [];
        }
        this.pickerResults = pages;
        // Clamp selectedIndex into range — keep highlight on the first
        // result by default so Enter picks the obvious choice.
        this.pickerSelectedIndex = pages.length ? 0 : -1;
      } catch (err) {
        if (requestId !== this._pickerRequestId) return;
        console.error("pickPage search failed:", err);
        this.pickerResults = [];
        this.pickerSelectedIndex = -1;
      } finally {
        if (requestId === this._pickerRequestId) {
          this.pickerLoading = false;
        }
      }
    },

    async _runBlockPickerSearch(query) {
      // Block search has no "recent" fallback — the endpoint requires a
      // query — so the empty state is a type-to-search hint (see the
      // template's pickBlock empty branch).
      const requestId = ++this._pickerRequestId;
      const trimmed = query.trim();
      if (trimmed === "") {
        this.pickerResults = [];
        this.pickerSelectedIndex = -1;
        this.pickerLoading = false;
        return;
      }
      this.pickerLoading = true;
      const exclude = new Set(this.active?.opts?.excludeUuids || []);
      try {
        const result = await window.apiService.searchBlocks(trimmed, 15);
        if (requestId !== this._pickerRequestId) return; // stale
        const rows = (result && result.data && result.data.results) || [];
        // Normalize to the picker's row shape — the search endpoint
        // calls the id ``block_uuid`` but every consumer (and the
        // v-for :key) expects ``uuid``.
        this.pickerResults = rows
          .filter((b) => !exclude.has(b.block_uuid))
          .map((b) => ({
            uuid: b.block_uuid,
            content: b.content,
            block_type: b.block_type,
            page_title: b.page_title,
            page_slug: b.page_slug,
          }));
        this.pickerSelectedIndex = this.pickerResults.length ? 0 : -1;
      } catch (err) {
        if (requestId !== this._pickerRequestId) return;
        console.error("pickBlock search failed:", err);
        this.pickerResults = [];
        this.pickerSelectedIndex = -1;
      } finally {
        if (requestId === this._pickerRequestId) {
          this.pickerLoading = false;
        }
      }
    },

    async _fetchTodayDailyPage() {
      // Locate the user's daily note for today's date so the picker can
      // pin it to the top of the empty-query list. Goes through the
      // existing search endpoint (constrained to page_type=daily) and
      // verifies an exact slug match, since searchPages does substring
      // matching — a page titled "notes from 2026-05-17" shouldn't be
      // mistaken for the actual daily.
      const now = new Date();
      const slug =
        now.getFullYear() +
        "-" +
        String(now.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(now.getDate()).padStart(2, "0");
      try {
        const result = await window.apiService.searchPages(slug, 5, "daily");
        const pages = (result && result.data && result.data.pages) || [];
        return pages.find((p) => p.slug === slug) || null;
      } catch (_) {
        return null;
      }
    },

    onPickerKeydown(event) {
      const top = this.active;
      if (!top || (top.kind !== "pickPage" && top.kind !== "pickBlock")) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (this.pickerResults.length === 0) return;
        this.pickerSelectedIndex = Math.min(
          this.pickerSelectedIndex + 1,
          this.pickerResults.length - 1
        );
        this._scrollSelectedIntoView();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        if (this.pickerResults.length === 0) return;
        this.pickerSelectedIndex = Math.max(this.pickerSelectedIndex - 1, 0);
        this._scrollSelectedIntoView();
      } else if (event.key === "Enter") {
        event.preventDefault();
        this.onPickerConfirm();
      } else if (event.key === "Escape") {
        event.preventDefault();
        this.onPickerCancel();
      }
    },

    _scrollSelectedIntoView() {
      this.$nextTick(() => {
        const items = this.$el?.querySelectorAll(".app-modal-picker-result");
        const el = items && items[this.pickerSelectedIndex];
        if (el) el.scrollIntoView({ block: "nearest" });
      });
    },

    onPickerConfirm() {
      const idx = this.pickerSelectedIndex;
      const page = this.pickerResults[idx];
      if (!page) return; // nothing to pick, ignore
      this.finish(page);
    },

    onPickerCancel() {
      this.finish(null);
    },

    onPickerResultClick(index) {
      this.pickerSelectedIndex = index;
      this.onPickerConfirm();
    },

    finish(result) {
      const top = this.queue[this.queue.length - 1];
      if (!top) return;
      this.queue = this.queue.slice(0, -1);
      top.resolve(result);
    },

    onConfirm() {
      this.finish(true);
    },
    onCancel() {
      this.finish(false);
    },
    onPromptOk() {
      this.finish(this.promptValue);
    },
    onPromptCancel() {
      // Match window.prompt semantics: cancel returns null.
      this.finish(null);
    },
    onAlertOk() {
      this.finish(undefined);
    },

    onBackdropClick() {
      const top = this.active;
      if (!top) return;
      if (top.kind === "confirm") this.onCancel();
      else if (top.kind === "prompt") this.onPromptCancel();
      else if (top.kind === "alert") this.onAlertOk();
      else if (top.kind === "choose") this.finish(null);
      else if (top.kind === "pickPage" || top.kind === "pickBlock")
        this.onPickerCancel();
    },

    onKeydown(event) {
      const top = this.active;
      if (!top) return;
      // The pickers drive their own keyboard surface (arrows + Enter +
      // Esc) via @keydown on the input — the global Enter-on-button
      // handlers below would otherwise fight Enter-to-pick.
      if (top.kind === "pickPage" || top.kind === "pickBlock") return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (top.kind === "confirm") this.onCancel();
        else if (top.kind === "prompt") this.onPromptCancel();
        else if (top.kind === "alert") this.onAlertOk();
        else if (top.kind === "choose") this.finish(null);
        return;
      }
      if (event.key === "Enter") {
        // Don't intercept Enter inside multiline inputs. The current
        // prompt input is single-line so Enter == submit.
        if (top.kind === "confirm") {
          event.preventDefault();
          this.onConfirm();
        } else if (top.kind === "prompt") {
          event.preventDefault();
          this.onPromptOk();
        } else if (top.kind === "alert") {
          event.preventDefault();
          this.onAlertOk();
        }
      }
    },
  },

  template: `
    <teleport to="body">
      <div
        v-if="active"
        class="app-modal-backdrop"
        @click.self="onBackdropClick"
        @keydown="onKeydown"
        tabindex="-1"
      >
        <div
          v-if="active.kind === 'confirm'"
          class="app-modal app-modal-confirm"
          :class="{ destructive: active.opts.destructive }"
          role="alertdialog"
          aria-modal="true"
        >
          <div class="app-modal-header">{{ active.opts.title }}</div>
          <div v-if="active.opts.message" class="app-modal-body">
            {{ active.opts.message }}
          </div>
          <div class="app-modal-actions">
            <button type="button" class="btn btn-secondary" @click="onCancel">
              {{ active.opts.cancelLabel }}
            </button>
            <button
              type="button"
              ref="confirmOk"
              class="btn"
              :class="active.opts.destructive ? 'btn-danger' : 'btn-primary'"
              @click="onConfirm"
              @keydown="onKeydown"
            >
              {{ active.opts.confirmLabel }}
            </button>
          </div>
        </div>

        <div
          v-else-if="active.kind === 'prompt'"
          class="app-modal app-modal-prompt"
          role="dialog"
          aria-modal="true"
        >
          <div v-if="active.opts.title" class="app-modal-header">
            {{ active.opts.title }}
          </div>
          <div v-if="active.opts.message" class="app-modal-body">
            {{ active.opts.message }}
          </div>
          <input
            ref="promptInput"
            v-model="promptValue"
            type="text"
            class="app-modal-input"
            :placeholder="active.opts.placeholder"
            @keydown="onKeydown"
          />
          <div class="app-modal-actions">
            <button type="button" class="btn btn-secondary" @click="onPromptCancel">
              {{ active.opts.cancelLabel }}
            </button>
            <button type="button" class="btn btn-primary" @click="onPromptOk">
              {{ active.opts.confirmLabel }}
            </button>
          </div>
        </div>

        <div
          v-else-if="active.kind === 'alert'"
          class="app-modal app-modal-alert"
          role="alertdialog"
          aria-modal="true"
        >
          <div v-if="active.opts.title" class="app-modal-header">
            {{ active.opts.title }}
          </div>
          <div class="app-modal-body">{{ active.opts.message }}</div>
          <div class="app-modal-actions">
            <button
              type="button"
              ref="alertOk"
              class="btn btn-primary"
              @click="onAlertOk"
              @keydown="onKeydown"
            >
              {{ active.opts.confirmLabel }}
            </button>
          </div>
        </div>

        <div
          v-else-if="active.kind === 'choose'"
          class="app-modal app-modal-choose"
          role="dialog"
          aria-modal="true"
        >
          <div v-if="active.opts.title" class="app-modal-header">
            {{ active.opts.title }}
          </div>
          <div v-if="active.opts.message" class="app-modal-body">
            {{ active.opts.message }}
          </div>
          <div
            v-for="section in active.opts.sections"
            :key="section.label"
            class="app-modal-choose-section"
          >
            <div class="app-modal-choose-section-label">{{ section.label }}</div>
            <pre class="app-modal-choose-section-text">{{ section.text }}</pre>
          </div>
          <div class="app-modal-choose-options">
            <button
              v-for="option in active.opts.options"
              :key="option.value"
              type="button"
              class="btn app-modal-choose-option"
              :class="option.kind === 'primary' ? 'btn-primary' : option.kind === 'danger' ? 'btn-danger' : 'btn-outline'"
              @click="finish(option.value)"
            >
              <span class="app-modal-choose-option-label">{{ option.label }}</span>
              <span v-if="option.description" class="app-modal-choose-option-desc">{{ option.description }}</span>
            </button>
          </div>
          <div class="app-modal-actions">
            <button type="button" class="btn btn-secondary" @click="finish(null)">
              {{ active.opts.cancelLabel }}
            </button>
          </div>
        </div>

        <div
          v-else-if="active.kind === 'pickPage' || active.kind === 'pickBlock'"
          class="app-modal app-modal-picker"
          role="dialog"
          aria-modal="true"
        >
          <div v-if="active.opts.title" class="app-modal-header">
            {{ active.opts.title }}
          </div>
          <div v-if="active.opts.message" class="app-modal-body">
            {{ active.opts.message }}
          </div>
          <input
            ref="pickerInput"
            v-model="pickerQuery"
            type="text"
            class="app-modal-input"
            :placeholder="active.opts.placeholder"
            @input="onPickerInput"
            @keydown="onPickerKeydown"
            autocomplete="off"
            spellcheck="false"
          />
          <div class="app-modal-picker-results" role="listbox">
            <div v-if="pickerLoading" class="app-modal-picker-empty">
              searching…
            </div>
            <div
              v-else-if="active.kind === 'pickBlock' && !pickerQuery.trim()"
              class="app-modal-picker-empty"
            >
              type to search block content
            </div>
            <div
              v-else-if="!pickerResults.length"
              class="app-modal-picker-empty"
            >
              {{ active.kind === 'pickBlock' ? 'no blocks match' : 'no pages match' }}
            </div>
            <template v-else-if="active.kind === 'pickBlock'">
              <button
                v-for="(blockRow, index) in pickerResults"
                :key="blockRow.uuid"
                type="button"
                class="app-modal-picker-result"
                :class="{ 'is-selected': index === pickerSelectedIndex }"
                @click="onPickerResultClick(index)"
                @mouseenter="pickerSelectedIndex = index"
                role="option"
                :aria-selected="index === pickerSelectedIndex"
              >
                <span class="app-modal-picker-result-title">{{ blockRow.content }}</span>
                <span class="app-modal-picker-result-slug">{{ blockRow.page_title || blockRow.page_slug }}</span>
              </button>
            </template>
            <template v-else>
              <button
                v-for="(page, index) in pickerResults"
                :key="page.uuid"
                type="button"
                class="app-modal-picker-result"
                :class="{ 'is-selected': index === pickerSelectedIndex }"
                @click="onPickerResultClick(index)"
                @mouseenter="pickerSelectedIndex = index"
                role="option"
                :aria-selected="index === pickerSelectedIndex"
              >
                <span class="app-modal-picker-result-title">{{ page.title }}</span>
                <span
                  v-if="page.page_type && page.page_type !== 'page'"
                  class="app-modal-picker-result-type"
                >{{ page.page_type }}</span>
                <span class="app-modal-picker-result-slug">{{ page.slug }}</span>
              </button>
            </template>
          </div>
          <div class="app-modal-actions">
            <button
              type="button"
              class="btn btn-secondary"
              @click="onPickerCancel"
            >
              {{ active.opts.cancelLabel }}
            </button>
            <button
              type="button"
              class="btn btn-primary"
              @click="onPickerConfirm"
              :disabled="pickerSelectedIndex < 0 || !pickerResults.length"
            >
              {{ active.opts.confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </teleport>
  `,
};
