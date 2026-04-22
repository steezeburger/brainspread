// Whiteboard component — renders a tldraw whiteboard for whiteboard-type
// pages. tldraw is a React library; we load React + tldraw via ESM from
// esm.sh and mount it into a DOM node that Vue manages.
//
// IMPORTANT: the React root, tldraw editor, and store subscription must NOT
// become Vue reactive proxies — Vue's proxying of tldraw's internal signals
// causes an infinite render loop (React error #185). We keep them off of
// `data()` and assign them to the component instance as plain properties,
// additionally wrapping with Vue.markRaw as a belt-and-suspenders measure.

const WHITEBOARD_SAVE_DEBOUNCE_MS = 1500;

const REACT_VERSION = "18";
const TLDRAW_VERSION = "3";

const markRaw = (val) => (Vue && Vue.markRaw ? Vue.markRaw(val) : val);

const Whiteboard = {
  props: {
    page: {
      type: Object,
      required: true,
    },
  },
  emits: ["page-updated"],
  data() {
    return {
      isLoadingLib: true,
      saveStatus: "idle",
      loadError: null,
    };
  },
  created() {
    // Non-reactive instance state. Declared here (not in data()) so Vue does
    // NOT wrap them in reactive proxies — tldraw relies on reference identity
    // of its editor/store/atoms internally.
    this._reactRoot = null;
    this._saveTimer = null;
    this._editor = null;
    this._unsubscribeStore = null;
    this._tldrawApi = null;
    this._lastSavedPayload = null;
    this._boundVisibilityHandler = this.handleVisibilityChange.bind(this);
    this._boundBeforeUnloadHandler = this.handleBeforeUnload.bind(this);
    this._boundThemeObserver = null;
  },
  async mounted() {
    document.addEventListener("visibilitychange", this._boundVisibilityHandler);
    window.addEventListener("beforeunload", this._boundBeforeUnloadHandler);

    try {
      await this.loadAndMountTldraw();
    } catch (err) {
      console.error("Failed to load tldraw:", err);
      this.loadError = err.message || String(err);
    } finally {
      this.isLoadingLib = false;
    }
  },
  beforeUnmount() {
    document.removeEventListener(
      "visibilitychange",
      this._boundVisibilityHandler
    );
    window.removeEventListener("beforeunload", this._boundBeforeUnloadHandler);

    if (this._boundThemeObserver) {
      this._boundThemeObserver.disconnect();
      this._boundThemeObserver = null;
    }

    if (this._saveTimer) {
      clearTimeout(this._saveTimer);
      this.flushSave();
    }
    if (this._unsubscribeStore) {
      try {
        this._unsubscribeStore();
      } catch (err) {
        console.warn("Failed to unsubscribe tldraw store:", err);
      }
    }
    if (this._reactRoot) {
      try {
        this._reactRoot.unmount();
      } catch (err) {
        console.warn("Failed to unmount tldraw react root:", err);
      }
    }
  },
  methods: {
    async loadAndMountTldraw() {
      const deps = `deps=react@${REACT_VERSION},react-dom@${REACT_VERSION}`;
      const [reactMod, reactDomClient, tldrawMod] = await Promise.all([
        import(`https://esm.sh/react@${REACT_VERSION}`),
        import(
          `https://esm.sh/react-dom@${REACT_VERSION}/client?deps=react@${REACT_VERSION}`
        ),
        import(`https://esm.sh/tldraw@${TLDRAW_VERSION}?${deps}`),
      ]);

      const React = reactMod.default || reactMod;
      const { createRoot } = reactDomClient;
      const { Tldraw, getSnapshot, loadSnapshot } = tldrawMod;

      this._tldrawApi = markRaw({ getSnapshot, loadSnapshot });

      const container = this.$refs.whiteboardContainer;
      if (!container) {
        throw new Error("Whiteboard container ref missing");
      }

      this._reactRoot = markRaw(createRoot(container));
      this._reactRoot.render(
        React.createElement(Tldraw, {
          onMount: this.onTldrawMount,
        })
      );
    },

    onTldrawMount(editor) {
      this._editor = markRaw(editor);

      this.applyThemeToEditor();
      this.watchThemeChanges();

      const snapshot = this.parseStoredSnapshot(this.page.whiteboard_snapshot);
      if (snapshot) {
        try {
          this._tldrawApi.loadSnapshot(editor.store, snapshot);
        } catch (err) {
          console.warn(
            "Failed to load whiteboard snapshot; starting fresh:",
            err
          );
        }
      }

      try {
        this._unsubscribeStore = editor.store.listen(
          () => {
            try {
              this.scheduleSave();
            } catch (err) {
              console.error("Whiteboard scheduleSave threw:", err);
            }
          },
          { source: "user", scope: "document" }
        );
      } catch (err) {
        // Fallback if the filter signature doesn't match this tldraw version
        console.warn(
          "Store filter subscribe failed, falling back to unfiltered:",
          err
        );
        this._unsubscribeStore = editor.store.listen(() => this.scheduleSave());
      }
    },

    applyThemeToEditor() {
      if (!this._editor) return;
      const appTheme =
        document.documentElement.getAttribute("data-theme") || "light";
      const colorScheme = appTheme === "dark" ? "dark" : "light";
      try {
        this._editor.user.updateUserPreferences({ colorScheme });
      } catch (err) {
        console.warn("Failed to set tldraw color scheme:", err);
      }
    },

    watchThemeChanges() {
      // Mirror app theme changes into tldraw while the whiteboard is open.
      if (this._boundThemeObserver) return;
      const observer = new MutationObserver(() => this.applyThemeToEditor());
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
      this._boundThemeObserver = observer;
    },

    parseStoredSnapshot(rawSnapshot) {
      if (!rawSnapshot || !rawSnapshot.trim()) return null;
      try {
        return JSON.parse(rawSnapshot);
      } catch (err) {
        console.warn("Stored whiteboard snapshot is not valid JSON:", err);
        return null;
      }
    },

    scheduleSave() {
      if (this._saveTimer) {
        clearTimeout(this._saveTimer);
      }
      this.saveStatus = "pending";
      this._saveTimer = setTimeout(() => {
        this.flushSave();
      }, WHITEBOARD_SAVE_DEBOUNCE_MS);
    },

    buildPayload() {
      if (!this._editor || !this._tldrawApi) return null;
      try {
        const snapshot = this._tldrawApi.getSnapshot(this._editor.store);
        return JSON.stringify(snapshot);
      } catch (err) {
        console.error("Failed to snapshot whiteboard:", err);
        return null;
      }
    },

    async flushSave() {
      this._saveTimer = null;
      const payload = this.buildPayload();
      if (payload === null) {
        this.saveStatus = "error";
        return;
      }
      if (payload === this._lastSavedPayload) {
        this.saveStatus = "saved";
        return;
      }

      this.saveStatus = "saving";
      try {
        const result = await window.apiService.updatePage(this.page.uuid, {
          whiteboard_snapshot: payload,
        });
        if (result.success) {
          this._lastSavedPayload = payload;
          this.saveStatus = "saved";
          this.$emit("page-updated", result.data);
        } else {
          this.saveStatus = "error";
          console.error("Whiteboard save failed:", result.errors);
        }
      } catch (err) {
        this.saveStatus = "error";
        console.error("Whiteboard save error:", err);
      }
    },

    handleVisibilityChange() {
      // Flush pending edits when the tab is backgrounded so a swipe-away on
      // iPad doesn't drop the last 1.5s of work.
      if (document.visibilityState === "hidden") {
        if (this._saveTimer) clearTimeout(this._saveTimer);
        this.flushSave();
      }
    },

    handleBeforeUnload() {
      // Best-effort flush on navigation/close. Modern browsers may still
      // cancel the in-flight fetch; a proper sendBeacon upgrade is a
      // follow-up, but for now this catches the common "tab close with a
      // second of pending edits" case.
      if (this._saveTimer) clearTimeout(this._saveTimer);
      this.flushSave();
    },
  },

  template: `
    <div class="whiteboard-page">
      <div v-if="isLoadingLib" class="whiteboard-loading">loading whiteboard...</div>
      <div v-if="loadError" class="whiteboard-error">
        failed to load whiteboard: {{ loadError }}
      </div>
      <div class="whiteboard-status" :class="'whiteboard-status-' + saveStatus">
        <span v-if="saveStatus === 'pending'">•</span>
        <span v-else-if="saveStatus === 'saving'">saving…</span>
        <span v-else-if="saveStatus === 'saved'">saved</span>
        <span v-else-if="saveStatus === 'error'">save failed</span>
      </div>
      <div ref="whiteboardContainer" class="whiteboard-container"></div>
    </div>
  `,
};

window.Whiteboard = Whiteboard;
