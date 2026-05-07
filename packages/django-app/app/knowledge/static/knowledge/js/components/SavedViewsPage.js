/**
 * SavedViewsPage — list / run / edit a user's saved views (issue #60).
 *
 * Routes:
 *   /knowledge/views/           — index, lists every view + new-view form
 *   /knowledge/views/<slug>/    — detail, runs the view + edit affordances
 *
 * The "structured" filter builder is intentionally a JSON textarea for
 * v1 — the engine validates the spec (predicates + ops + date tokens)
 * server-side and surfaces the error inline. A visual builder belongs
 * in a follow-up; today's surface lets a user build / save / run /
 * clone / delete views with full predicate coverage.
 */
const SavedViewsPage = {
  props: {
    initialSlug: { type: String, default: null },
  },

  data() {
    return {
      loading: true,
      views: [],
      activeSlug: this.initialSlug,
      // null when nothing is selected; otherwise the active view dict.
      activeView: null,
      runResult: null, // {view, count, results, truncated}
      running: false,
      saving: false,
      saveError: null,
      runError: null,

      // Editor buffer — kept distinct from activeView so we can roll
      // back / detect dirty state without poking at the persisted view.
      editing: false,
      editor: this._emptyEditor(),
      editorErrors: {}, // {field: msg}

      // Inline "new view" toggle on the index.
      creating: false,
    };
  },

  computed: {
    isOnIndex() {
      return !this.activeSlug;
    },
    canEdit() {
      return this.activeView && !this.activeView.is_system;
    },
    canDelete() {
      return this.activeView && !this.activeView.is_system;
    },
    filterPretty() {
      if (!this.activeView) return "";
      try {
        return JSON.stringify(this.activeView.filter, null, 2);
      } catch (_) {
        return "";
      }
    },
    sortPretty() {
      if (!this.activeView) return "";
      try {
        return JSON.stringify(this.activeView.sort || [], null, 2);
      } catch (_) {
        return "";
      }
    },
  },

  watch: {
    activeSlug(newSlug) {
      if (newSlug) {
        this.loadActive(newSlug);
      } else {
        this.activeView = null;
        this.runResult = null;
        this.editing = false;
      }
    },
  },

  async mounted() {
    await this.loadList();
    if (this.activeSlug) {
      await this.loadActive(this.activeSlug);
    }
    window.addEventListener("popstate", this.onPopState);
  },

  beforeUnmount() {
    window.removeEventListener("popstate", this.onPopState);
  },

  methods: {
    _emptyEditor() {
      return {
        view_uuid: null,
        name: "",
        slug: "",
        description: "",
        filter: '{\n  "block_type": "todo"\n}',
        sort: "[]",
      };
    },

    onPopState() {
      // Resync activeSlug from the URL when the back/forward buttons fire.
      this.activeSlug = this._slugFromPath();
    },

    _slugFromPath() {
      const m = window.location.pathname.match(
        /^\/knowledge\/views\/([^\/]+)\/?$/
      );
      return m ? decodeURIComponent(m[1]) : null;
    },

    async loadList() {
      this.loading = true;
      try {
        const result = await window.apiService.listSavedViews();
        if (result && result.success) {
          this.views = (result.data && result.data.views) || [];
        }
      } catch (err) {
        console.error("listSavedViews failed:", err);
      } finally {
        this.loading = false;
      }
    },

    async loadActive(slug) {
      this.runResult = null;
      this.runError = null;
      this.editing = false;
      try {
        const got = await window.apiService.getSavedView({ slug });
        if (!got || !got.success) {
          this.activeView = null;
          this.runError = "View not found";
          return;
        }
        this.activeView = got.data;
        this._populateEditor(this.activeView);
        await this.runActive();
      } catch (err) {
        console.error("loadActive failed:", err);
        this.runError = String(err);
      }
    },

    _populateEditor(view) {
      this.editor = {
        view_uuid: view.uuid,
        name: view.name,
        slug: view.slug,
        description: view.description || "",
        filter: JSON.stringify(view.filter || {}, null, 2),
        sort: JSON.stringify(view.sort || [], null, 2),
      };
      this.editorErrors = {};
      this.saveError = null;
    },

    async runActive() {
      if (!this.activeView) return;
      this.running = true;
      this.runError = null;
      try {
        const result = await window.apiService.runSavedView({
          uuid: this.activeView.uuid,
        });
        if (result && result.success) {
          this.runResult = result.data;
        } else {
          const errs = (result && result.errors) || {};
          this.runError =
            (errs.non_field_errors && errs.non_field_errors[0]) ||
            "Failed to run view";
        }
      } catch (err) {
        console.error("runSavedView failed:", err);
        this.runError = String(err);
      } finally {
        this.running = false;
      }
    },

    selectSlug(slug) {
      const url = `/knowledge/views/${encodeURIComponent(slug)}/`;
      if (window.location.pathname !== url) {
        window.history.pushState({}, "", url);
      }
      this.activeSlug = slug;
    },

    backToIndex() {
      if (window.location.pathname !== "/knowledge/views/") {
        window.history.pushState({}, "", "/knowledge/views/");
      }
      this.activeSlug = null;
    },

    startEditing() {
      if (!this.canEdit) return;
      this._populateEditor(this.activeView);
      this.editing = true;
    },

    cancelEditing() {
      this.editing = false;
      this.saveError = null;
      this.editorErrors = {};
      if (this.activeView) this._populateEditor(this.activeView);
    },

    _validateEditorJson() {
      const errs = {};
      let filterParsed, sortParsed;
      try {
        filterParsed = JSON.parse(this.editor.filter);
        if (!filterParsed || typeof filterParsed !== "object" || Array.isArray(filterParsed)) {
          errs.filter = "filter must be a JSON object";
        }
      } catch (e) {
        errs.filter = `filter is not valid JSON (${e.message})`;
      }
      const sortRaw = (this.editor.sort || "").trim();
      if (sortRaw === "") {
        sortParsed = [];
      } else {
        try {
          sortParsed = JSON.parse(sortRaw);
          if (!Array.isArray(sortParsed)) {
            errs.sort = "sort must be a JSON array";
          }
        } catch (e) {
          errs.sort = `sort is not valid JSON (${e.message})`;
        }
      }
      if (!this.editor.name.trim()) {
        errs.name = "name is required";
      }
      this.editorErrors = errs;
      if (Object.keys(errs).length) return null;
      return { filter: filterParsed, sort: sortParsed };
    },

    async saveEdits() {
      const parsed = this._validateEditorJson();
      if (!parsed) return;
      this.saving = true;
      this.saveError = null;
      try {
        const payload = {
          view_uuid: this.editor.view_uuid,
          name: this.editor.name.trim(),
          description: this.editor.description.trim(),
          filter: parsed.filter,
          sort: parsed.sort,
        };
        if (this.editor.slug.trim()) {
          payload.slug = this.editor.slug.trim();
        }
        const result = await window.apiService.updateSavedView(payload);
        if (result && result.success) {
          this.activeView = result.data;
          this.editing = false;
          await this.loadList();
          // If the slug changed, re-route.
          if (this.activeView.slug !== this.activeSlug) {
            this.selectSlug(this.activeView.slug);
          } else {
            await this.runActive();
          }
        } else {
          this.saveError = this._formatErrors(result && result.errors);
        }
      } catch (err) {
        this.saveError = String(err);
      } finally {
        this.saving = false;
      }
    },

    async createView() {
      const parsed = this._validateEditorJson();
      if (!parsed) return;
      this.saving = true;
      this.saveError = null;
      try {
        const payload = {
          name: this.editor.name.trim(),
          description: this.editor.description.trim(),
          filter: parsed.filter,
          sort: parsed.sort,
        };
        if (this.editor.slug.trim()) {
          payload.slug = this.editor.slug.trim();
        }
        const result = await window.apiService.createSavedView(payload);
        if (result && result.success) {
          await this.loadList();
          this.creating = false;
          this.selectSlug(result.data.slug);
        } else {
          this.saveError = this._formatErrors(result && result.errors);
        }
      } catch (err) {
        this.saveError = String(err);
      } finally {
        this.saving = false;
      }
    },

    async duplicateActive() {
      if (!this.activeView) return;
      try {
        const result = await window.apiService.duplicateSavedView(
          this.activeView.uuid
        );
        if (result && result.success) {
          await this.loadList();
          this.selectSlug(result.data.slug);
        }
      } catch (err) {
        console.error("duplicate failed:", err);
      }
    },

    async deleteActive() {
      if (!this.canDelete) return;
      const ok = await this._confirm(
        `Delete view "${this.activeView.name}"? This can't be undone.`
      );
      if (!ok) return;
      try {
        const result = await window.apiService.deleteSavedView(
          this.activeView.uuid
        );
        if (result && result.success) {
          await this.loadList();
          this.backToIndex();
        }
      } catch (err) {
        console.error("delete failed:", err);
      }
    },

    async embedOnToday() {
      // Create a query-block on today's daily page that embeds this view.
      // Useful for "I want this view to appear as a section on today" —
      // saves the user from manually typing the right block_type +
      // query_view_uuid combo.
      if (!this.activeView) return;
      try {
        // Resolve / create today's daily so we have a target page.
        const pageResult = await window.apiService.getPageWithBlocks();
        const pageUuid =
          pageResult && pageResult.data && pageResult.data.page
            ? pageResult.data.page.uuid
            : null;
        if (!pageUuid) {
          console.error("Could not resolve today's daily page");
          return;
        }
        const blockResult = await window.apiService.createBlock({
          page: pageUuid,
          block_type: "query",
          query_view: this.activeView.uuid,
          content: "",
          order: 9999, // append at the end; the API trusts this and slots in
        });
        if (blockResult && blockResult.success) {
          // Hop to today so the user sees the embed land.
          window.location.href = `/knowledge/page/${pageResult.data.page.slug}/#block-${blockResult.data.uuid}`;
        }
      } catch (err) {
        console.error("embedOnToday failed:", err);
      }
    },

    async _confirm(msg) {
      // App-wide AppModals dialog if available; falls back to native.
      if (window.brainspreadConfirm) {
        return await window.brainspreadConfirm(msg);
      }
      return window.confirm(msg);
    },

    _formatErrors(errors) {
      if (!errors) return "Save failed";
      if (errors.non_field_errors && errors.non_field_errors[0]) {
        return errors.non_field_errors[0];
      }
      const parts = [];
      Object.entries(errors).forEach(([k, v]) => {
        if (Array.isArray(v)) parts.push(`${k}: ${v[0]}`);
        else parts.push(`${k}: ${v}`);
      });
      return parts.join(" • ") || "Save failed";
    },

    showCreate() {
      this.creating = true;
      this.editor = this._emptyEditor();
      this.editorErrors = {};
      this.saveError = null;
    },

    cancelCreate() {
      this.creating = false;
      this.saveError = null;
      this.editorErrors = {};
    },

    blockHref(block) {
      if (!block || !block.page_slug) return "#";
      return `/knowledge/page/${encodeURIComponent(block.page_slug)}/#block-${
        block.uuid
      }`;
    },

    blockLabel(block) {
      if (!block) return "";
      const content = (block.content || "").trim();
      if (content) return content.length > 200 ? content.slice(0, 200) + "…" : content;
      return "(empty block)";
    },
  },

  template: `
    <div class="saved-views-page">
      <div v-if="loading" class="loading">Loading views…</div>

      <!-- Index: list + new-view form -->
      <div v-else-if="isOnIndex">
        <div class="saved-views-header">
          <h1>Saved views</h1>
          <button class="btn btn-primary" @click="showCreate" v-if="!creating">+ New view</button>
        </div>

        <div v-if="creating" class="saved-view-editor">
          <h2>New view</h2>
          <div class="form-row">
            <label>Name</label>
            <input v-model="editor.name" type="text" maxlength="200" />
            <div v-if="editorErrors.name" class="form-error">{{ editorErrors.name }}</div>
          </div>
          <div class="form-row">
            <label>Slug (optional — auto from name)</label>
            <input v-model="editor.slug" type="text" maxlength="200" />
          </div>
          <div class="form-row">
            <label>Description</label>
            <input v-model="editor.description" type="text" maxlength="500" />
          </div>
          <div class="form-row">
            <label>Filter (JSON)</label>
            <textarea v-model="editor.filter" rows="10" spellcheck="false"></textarea>
            <div v-if="editorErrors.filter" class="form-error">{{ editorErrors.filter }}</div>
          </div>
          <div class="form-row">
            <label>Sort (JSON, optional)</label>
            <textarea v-model="editor.sort" rows="4" spellcheck="false"></textarea>
            <div v-if="editorErrors.sort" class="form-error">{{ editorErrors.sort }}</div>
          </div>
          <div class="form-row form-actions">
            <button class="btn btn-primary" @click="createView" :disabled="saving">
              {{ saving ? "Saving…" : "Create view" }}
            </button>
            <button class="btn" @click="cancelCreate">Cancel</button>
          </div>
          <div v-if="saveError" class="form-error">{{ saveError }}</div>
          <div class="saved-view-help">
            <p>Filter spec is JSON. Examples:</p>
            <pre>{
  "all": [
    { "block_type": { "in": ["todo", "doing"] } },
    { "scheduled_for": { "lt": "today" } },
    { "completed_at": { "is_null": true } }
  ]
}</pre>
            <p>Predicates: block_type, scheduled_for, completed_at, has_tag, has_property, property_eq, content_contains. Combinators: all, any. Date tokens: today, tomorrow, yesterday, "N days ago", "N days from now", or YYYY-MM-DD.</p>
          </div>
        </div>

        <div v-else class="saved-view-list">
          <div v-if="!views.length" class="empty-state">No saved views yet.</div>
          <ul v-else>
            <li v-for="v in views" :key="v.uuid">
              <a href="#" @click.prevent="selectSlug(v.slug)">
                <span class="view-name">{{ v.name }}</span>
                <span v-if="v.is_system" class="system-pill">system</span>
                <span v-if="v.description" class="view-description">{{ v.description }}</span>
              </a>
            </li>
          </ul>
        </div>
      </div>

      <!-- Detail: run + edit a single view -->
      <div v-else class="saved-view-detail">
        <a href="#" class="back-link" @click.prevent="backToIndex">&larr; All views</a>

        <div v-if="!activeView" class="empty-state">
          <span v-if="runError">{{ runError }}</span>
          <span v-else>Loading view…</span>
        </div>

        <template v-else>
          <div class="saved-views-header">
            <h1>
              {{ activeView.name }}
              <span v-if="activeView.is_system" class="system-pill">system</span>
            </h1>
            <div class="header-actions">
              <button class="btn" @click="runActive" :disabled="running">
                {{ running ? "Running…" : "Run" }}
              </button>
              <button class="btn" @click="duplicateActive">Duplicate</button>
              <button class="btn" @click="embedOnToday" title="Add this view to today's daily page as a block">Embed on today</button>
              <button class="btn" v-if="canEdit && !editing" @click="startEditing">Edit</button>
              <button class="btn btn-danger" v-if="canDelete" @click="deleteActive">Delete</button>
            </div>
          </div>
          <p v-if="activeView.description" class="saved-view-desc">{{ activeView.description }}</p>

          <div v-if="!editing" class="saved-view-spec">
            <details>
              <summary>Filter spec</summary>
              <pre>{{ filterPretty }}</pre>
              <pre v-if="sortPretty && sortPretty !== '[]'">sort: {{ sortPretty }}</pre>
            </details>
          </div>

          <div v-if="editing" class="saved-view-editor">
            <div class="form-row">
              <label>Name</label>
              <input v-model="editor.name" type="text" maxlength="200" />
              <div v-if="editorErrors.name" class="form-error">{{ editorErrors.name }}</div>
            </div>
            <div class="form-row">
              <label>Slug</label>
              <input v-model="editor.slug" type="text" maxlength="200" />
            </div>
            <div class="form-row">
              <label>Description</label>
              <input v-model="editor.description" type="text" maxlength="500" />
            </div>
            <div class="form-row">
              <label>Filter (JSON)</label>
              <textarea v-model="editor.filter" rows="10" spellcheck="false"></textarea>
              <div v-if="editorErrors.filter" class="form-error">{{ editorErrors.filter }}</div>
            </div>
            <div class="form-row">
              <label>Sort (JSON)</label>
              <textarea v-model="editor.sort" rows="4" spellcheck="false"></textarea>
              <div v-if="editorErrors.sort" class="form-error">{{ editorErrors.sort }}</div>
            </div>
            <div class="form-row form-actions">
              <button class="btn btn-primary" @click="saveEdits" :disabled="saving">
                {{ saving ? "Saving…" : "Save" }}
              </button>
              <button class="btn" @click="cancelEditing">Cancel</button>
            </div>
            <div v-if="saveError" class="form-error">{{ saveError }}</div>
          </div>

          <div class="saved-view-results">
            <h3>
              Results <span v-if="runResult"> ({{ runResult.count }}<span v-if="runResult.truncated">+ truncated</span>)</span>
            </h3>
            <div v-if="runError" class="form-error">{{ runError }}</div>
            <div v-else-if="!runResult" class="empty-state">Loading…</div>
            <div v-else-if="!runResult.results.length" class="empty-state">No matches.</div>
            <ul v-else class="result-list">
              <li v-for="b in runResult.results" :key="b.uuid">
                <a :href="blockHref(b)" class="result-row">
                  <span class="result-content">{{ blockLabel(b) }}</span>
                  <span class="result-meta">
                    <span v-if="b.block_type" class="result-block-type">{{ b.block_type }}</span>
                    <span v-if="b.scheduled_for"> · due {{ b.scheduled_for }}</span>
                    <span v-if="b.completed_at"> · done {{ b.completed_at.split('T')[0] }}</span>
                    <span v-if="b.page_title"> · {{ b.page_title }}</span>
                  </span>
                </a>
              </li>
            </ul>
          </div>
        </template>
      </div>
    </div>
  `,
};

window.SavedViewsPage = SavedViewsPage;
