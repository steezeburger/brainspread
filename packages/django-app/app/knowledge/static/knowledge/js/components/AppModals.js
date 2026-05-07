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
//
// Each method returns a promise that resolves on user action.

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
      }
      if (!next && prev) {
        this.promptValue = "";
      }
    },
  },

  mounted() {
    window.appModals = {
      confirm: this.confirm.bind(this),
      prompt: this.prompt.bind(this),
      alert: this.alert.bind(this),
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
    },

    onKeydown(event) {
      const top = this.active;
      if (!top) return;
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
      </div>
    </teleport>
  `,
};
