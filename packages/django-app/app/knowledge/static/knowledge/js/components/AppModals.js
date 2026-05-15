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
//
// Each method returns a promise that resolves on user action. pickPage
// resolves with the selected page object (uuid, slug, title, ...) or
// null when the user dismisses.

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
      } else if (next && next.kind === "pickPage") {
        this._resetPicker();
        this.$nextTick(() => {
          const input = this.$refs.pickerInput;
          if (input) input.focus();
        });
        // Kick off an initial search so the user sees their most-
        // recently-edited pages without typing. Empty query → recent.
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

    pickPage(opts) {
      // Typeahead page picker. Resolves with the chosen page object
      // (uuid, slug, title, page_type) or null on dismiss. The caller
      // doesn't have to wire search — we use the existing
      // /api/pages/search/ endpoint via window.apiService.
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
      const requestId = ++this._pickerRequestId;
      this.pickerLoading = true;
      try {
        // Empty query → server defaults to recent pages, which is the
        // friendliest landing state. The endpoint accepts an empty
        // query string and falls back to a chronological page list.
        const result =
          query.trim() === ""
            ? await window.apiService.getPages(true, 15, 0)
            : await window.apiService.searchPages(query.trim(), 15);
        if (requestId !== this._pickerRequestId) return; // stale
        const pages = (result && result.data && result.data.pages) || [];
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

    onPickerKeydown(event) {
      const top = this.active;
      if (!top || top.kind !== "pickPage") return;
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
      else if (top.kind === "pickPage") this.onPickerCancel();
    },

    onKeydown(event) {
      const top = this.active;
      if (!top) return;
      // pickPage drives its own keyboard surface (arrows + Enter +
      // Esc) via @keydown on the input — the global Enter-on-button
      // handlers below would otherwise fight Enter-to-pick.
      if (top.kind === "pickPage") return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (top.kind === "confirm") this.onCancel();
        else if (top.kind === "prompt") this.onPromptCancel();
        else if (top.kind === "alert") this.onAlertOk();
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
          v-else-if="active.kind === 'pickPage'"
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
              v-else-if="!pickerResults.length"
              class="app-modal-picker-empty"
            >
              no pages match
            </div>
            <button
              v-else
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
