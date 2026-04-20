// Canvas component — renders a tldraw whiteboard for canvas-type pages.
// tldraw is a React library; we load React + tldraw via ESM from esm.sh
// and mount it into a DOM node that Vue manages.
//
// IMPORTANT: the React root, tldraw editor, and store subscription must NOT
// become Vue reactive proxies — Vue's proxying of tldraw's internal signals
// causes an infinite render loop (React error #185). We keep them off of
// `data()` and assign them to the component instance as plain properties,
// additionally wrapping with Vue.markRaw as a belt-and-suspenders measure.

const CANVAS_SAVE_DEBOUNCE_MS = 1500;

const REACT_VERSION = "18";
const TLDRAW_VERSION = "3";

const markRaw = (val) => (Vue && Vue.markRaw ? Vue.markRaw(val) : val);

const Canvas = {
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
  },
  async mounted() {
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

      const container = this.$refs.canvasContainer;
      if (!container) {
        throw new Error("Canvas container ref missing");
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

      const snapshot = this.parseStoredSnapshot(this.page.content);
      if (snapshot) {
        try {
          this._tldrawApi.loadSnapshot(editor.store, snapshot);
        } catch (err) {
          console.warn("Failed to load canvas snapshot; starting fresh:", err);
        }
      }

      try {
        this._unsubscribeStore = editor.store.listen(
          () => {
            try {
              this.scheduleSave();
            } catch (err) {
              console.error("Canvas scheduleSave threw:", err);
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

    parseStoredSnapshot(content) {
      if (!content || !content.trim()) return null;
      try {
        return JSON.parse(content);
      } catch (err) {
        console.warn("Stored canvas content is not valid JSON:", err);
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
      }, CANVAS_SAVE_DEBOUNCE_MS);
    },

    async flushSave() {
      this._saveTimer = null;
      if (!this._editor || !this._tldrawApi) return;

      let payload;
      try {
        const snapshot = this._tldrawApi.getSnapshot(this._editor.store);
        payload = JSON.stringify(snapshot);
      } catch (err) {
        console.error("Failed to snapshot canvas:", err);
        this.saveStatus = "error";
        return;
      }

      this.saveStatus = "saving";
      try {
        const result = await window.apiService.updatePage(this.page.uuid, {
          content: payload,
        });
        if (result.success) {
          this.saveStatus = "saved";
          this.$emit("page-updated", result.data);
        } else {
          this.saveStatus = "error";
          console.error("Canvas save failed:", result.errors);
        }
      } catch (err) {
        this.saveStatus = "error";
        console.error("Canvas save error:", err);
      }
    },
  },

  template: `
    <div class="canvas-page">
      <div v-if="isLoadingLib" class="canvas-loading">loading canvas...</div>
      <div v-if="loadError" class="canvas-error">
        failed to load canvas: {{ loadError }}
      </div>
      <div class="canvas-status" :class="'canvas-status-' + saveStatus">
        <span v-if="saveStatus === 'pending'">•</span>
        <span v-else-if="saveStatus === 'saving'">saving…</span>
        <span v-else-if="saveStatus === 'saved'">saved</span>
        <span v-else-if="saveStatus === 'error'">save failed</span>
      </div>
      <div ref="canvasContainer" class="canvas-container"></div>
    </div>
  `,
};

window.Canvas = Canvas;
