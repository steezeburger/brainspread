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

  components: {
    ScheduleBlockPopover: window.ScheduleBlockPopover || {},
    BlockInfoModal: window.BlockInfoModal || {},
    EmbedResultRow: window.EmbedResultRow || {},
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

      // Set when ``_maybePrefillFromQuery`` found an existing view whose
      // filter matches the clicked property — drives the dismissible
      // "you already have a view for this" banner above the editor.
      prefillMatch: null,

      // Schedule popover state — mirrors Page.js. SavedViewsPage owns
      // its own popover so the schedule action works on this surface
      // without depending on a host page.
      schedulePopoverOpen: false,
      schedulePopoverBlock: null,
      schedulePopoverInitialDate: "",
      schedulePopoverInitialReminderDate: "",
      schedulePopoverInitialTime: "",

      // Block info modal — same rationale as the schedule popover.
      blockInfoModalOpen: false,
      blockInfoModalBlock: null,
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
    // In-app cheatsheet, rendered next to both the create-view and
    // edit-view forms. Content is fully static — v-html is safe here
    // and lets us share one definition between the two editor sites
    // without dragging in a sub-component.
    cheatsheetHtml() {
      return `
<details class="saved-view-cheatsheet">
  <summary>Filter &amp; sort cheatsheet (click to expand)</summary>

  <h4>Predicates</h4>
  <table class="cheat-table">
    <tr><th><code>block_type</code></th><td>
      Shorthand <code>"todo"</code> or op-dict <code>{"eq": "todo"}</code> /
      <code>{"in": ["todo","doing","later"]}</code>.
    </td></tr>
    <tr><th><code>has_tag</code></th><td>
      Slug string (no <code>#</code>). Matches blocks tagged with that
      page <em>or</em> living on it. To require two tags, list both
      under <code>all</code>.
    </td></tr>
    <tr><th><code>scheduled_for</code></th><td>
      Date predicate. Ops: <code>is_null</code> (bool), <code>eq</code>,
      <code>lt</code>, <code>lte</code>, <code>gt</code>, <code>gte</code>,
      <code>between</code> (<code>[start, end]</code>). Values are date
      tokens or <code>YYYY-MM-DD</code>.
    </td></tr>
    <tr><th><code>completed_at</code></th><td>
      Same ops as <code>scheduled_for</code> — compares the moment a
      block transitioned to done / wontdo.
    </td></tr>
    <tr><th><code>has_property</code></th><td>
      Key string. Matches blocks with that <code>key:: value</code>
      property set (any value).
    </td></tr>
    <tr><th><code>property_eq</code></th><td>
      <code>{"key": "&lt;k&gt;", &lt;op&gt;: &lt;arg&gt;, ...}</code>.
      Ops: <code>eq</code>, <code>ne</code>, <code>in</code>,
      <code>not_in</code>, <code>contains</code>, <code>starts_with</code>,
      <code>ends_with</code>. Multiple ops on one predicate AND together.
      Property values are stored as strings.
    </td></tr>
    <tr><th><code>content_contains</code></th><td>
      Substring match on the block's text content (case-insensitive).
    </td></tr>
    <tr><th><code>page_type</code></th><td>
      Shorthand <code>"page"</code> / <code>"daily"</code> /
      <code>"template"</code> / <code>"whiteboard"</code>, or op-dict
      <code>{"in": ["daily", "page"]}</code>. Template-page blocks are
      excluded by default (treated as scaffolding); mention
      <code>page_type</code> anywhere in the filter to opt them back in.
    </td></tr>
  </table>

  <h4>Combinators</h4>
  <p>
    <code>all</code> / <code>any</code> take a non-empty array of
    sub-specs (AND / OR). <code>not</code> takes a single sub-spec.
    Combinators nest freely.
  </p>

  <h4>Date tokens</h4>
  <p>
    <code>today</code>, <code>tomorrow</code>, <code>yesterday</code>,
    <code>"N days ago"</code>, <code>"N days from now"</code>,
    <code>today+Nd</code>, <code>today-Nd</code>, or a literal
    <code>YYYY-MM-DD</code>. Tokens resolve at compile time against
    your timezone.
  </p>

  <h4>Sort</h4>
  <p>
    Array of <code>{"field": "...", "dir": "asc"|"desc"}</code>.
    <strong>Use <code>dir</code>, not <code>direction</code></strong>
    — unknown keys are silently ignored.
  </p>
  <p>
    Fields: <code>scheduled_for</code>, <code>completed_at</code>,
    <code>created_at</code>, <code>modified_at</code>, <code>order</code>,
    <code>block_type</code>, or <code>properties.&lt;key&gt;</code>.
    Property sort is lexicographic — works naturally for ISO dates
    stored as properties.
  </p>
  <p>
    Default sort (when the array is empty / omitted) is
    <code>created_at desc</code> — newest first.
  </p>

  <h4>Examples</h4>

  <p>Open <code>#brainspread</code> bugs, newest first:</p>
  <pre>{
  "all": [
    { "has_tag": "brainspread" },
    { "has_tag": "bugs" },
    { "block_type": { "in": ["todo", "doing", "later"] } }
  ]
}</pre>
  <pre>[{ "field": "created_at", "dir": "desc" }]</pre>

  <p>High-priority work items, by due date then creation:</p>
  <pre>{
  "all": [
    { "has_tag": "work" },
    { "property_eq": { "key": "priority", "eq": "high" } }
  ]
}</pre>
  <pre>[
  { "field": "scheduled_for", "dir": "asc" },
  { "field": "created_at",   "dir": "asc" }
]</pre>

  <p>Overdue, but not snoozed:</p>
  <pre>{
  "all": [
    { "block_type": { "in": ["todo", "doing", "later"] } },
    { "scheduled_for": { "lt": "today" } },
    { "completed_at": { "is_null": true } },
    { "not": { "has_tag": "snoozed" } }
  ]
}</pre>

  <h4>Examples with OR (<code>any</code>)</h4>

  <p>Anything tagged either project, due in the next 7 days:</p>
  <pre>{
  "all": [
    { "any": [
        { "has_tag": "brainspread" },
        { "has_tag": "homelab" }
      ] },
    { "scheduled_for": { "between": ["today", "today+7d"] } }
  ]
}</pre>

  <p>Needs attention — high priority <em>or</em> overdue <em>or</em>
  flagged as a blocker:</p>
  <pre>{
  "all": [
    { "block_type": { "in": ["todo", "doing", "later"] } },
    { "any": [
        { "property_eq": { "key": "priority", "in": ["high", "critical"] } },
        { "scheduled_for": { "lt": "today" } },
        { "has_tag": "blocker" }
      ] }
  ]
}</pre>

  <p>"Anything finished this week" — done <em>or</em> wontdo:</p>
  <pre>{
  "all": [
    { "block_type": { "in": ["done", "wontdo"] } },
    { "completed_at": { "gte": "7 days ago" } }
  ]
}</pre>
  <pre>[{ "field": "completed_at", "dir": "desc" }]</pre>

  <p>Inbox-style triage list — open blocks with no tag <em>and</em> no
  due date. Uses two <code>not</code>s under <code>all</code>:</p>
  <pre>{
  "all": [
    { "block_type": { "in": ["todo", "doing", "later"] } },
    { "scheduled_for": { "is_null": true } },
    { "not": { "any": [
        { "has_tag": "work" },
        { "has_tag": "personal" },
        { "has_tag": "errand" }
      ] } }
  ]
}</pre>

  <p>Search-style view — any block whose content or tag mentions
  "deploy", that's still open:</p>
  <pre>{
  "all": [
    { "block_type": { "in": ["todo", "doing", "later"] } },
    { "any": [
        { "content_contains": "deploy" },
        { "has_tag": "deploy" }
      ] }
  ]
}</pre>
</details>`;
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
    } else {
      // ?property_key=K&property_value=V on the index drops the user
      // into "creating" mode with a property_eq filter prefilled —
      // the landing target for property-chip clicks in block content.
      this._maybePrefillFromQuery();
    }
    window.addEventListener("popstate", this.onPopState);

    // Refresh the visible saved-view when a block displayed in it is
    // mutated from elsewhere (e.g. an embed on another tab fired the
    // same event). Skips refresh if the changed block isn't in our
    // current results to avoid pointless re-runs.
    this._onBlocksChanged = (ev) => {
      const uuid = ev?.detail?.uuid;
      if (!uuid || ev?.detail?.source === this) return;
      if (!this.runResult?.results) return;
      if (this.runResult.results.some((b) => b.uuid === uuid)) {
        this.refreshResults();
      }
    };
    document.addEventListener(
      "brainspread:block-changed",
      this._onBlocksChanged
    );
  },

  beforeUnmount() {
    window.removeEventListener("popstate", this.onPopState);
    if (this._onBlocksChanged) {
      document.removeEventListener(
        "brainspread:block-changed",
        this._onBlocksChanged
      );
    }
  },

  methods: {
    _emptyEditor() {
      return {
        view_uuid: null,
        name: "",
        slug: "",
        description: "",
        filter: '{\n  "block_type": "todo"\n}',
        // Pre-fill with newest-first sort so a freshly-created view
        // is immediately useful — matches the backend's empty-sort
        // default and saves the user a copy-paste from the cheatsheet.
        sort: '[\n  { "field": "created_at", "dir": "desc" }\n]',
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
      // While editing, "Run" should show results for the draft spec
      // the user is currently typing — not the spec last persisted.
      // The draft path goes through the preview endpoint so we don't
      // have to save first.
      if (this.editing) {
        return this._previewEditorDraft();
      }
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

    async _previewEditorDraft() {
      // Validate the editor JSON first so the user gets the same inline
      // error feedback as Save (rather than a generic API error). When
      // the draft is invalid we bail without clobbering the previous
      // run results.
      const parsed = this._validateEditorJson();
      if (!parsed) return;
      this.running = true;
      this.runError = null;
      try {
        const result = await window.apiService.previewSavedView({
          filter: parsed.filter,
          sort: parsed.sort,
        });
        if (result && result.success) {
          // Preview response lacks a 'view' field (no view to preview
          // against); the results UI only needs count / results /
          // truncated, which preview supplies.
          this.runResult = result.data;
        } else {
          const errs = (result && result.errors) || {};
          this.runError =
            (errs.non_field_errors && errs.non_field_errors[0]) ||
            (errs.filter && errs.filter[0]) ||
            (errs.sort && errs.sort[0]) ||
            "Failed to preview view";
        }
      } catch (err) {
        console.error("previewSavedView failed:", err);
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
        if (
          !filterParsed ||
          typeof filterParsed !== "object" ||
          Array.isArray(filterParsed)
        ) {
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

    async togglePinned() {
      // Toggle the pinned flag and dispatch pinned-views:changed so the
      // left-nav's pinned-views section refreshes without a reload.
      if (!this.activeView) return;
      const nextPinned = !this.activeView.pinned;
      try {
        const result = await window.apiService.setSavedViewPinned(
          this.activeView.uuid,
          nextPinned
        );
        if (result && result.success) {
          this.activeView = result.data;
          // Keep the local list in sync so a back-trip to the index
          // shows the new pin state without an extra refetch.
          const idx = this.views.findIndex(
            (v) => v.uuid === this.activeView.uuid
          );
          if (idx >= 0) this.views.splice(idx, 1, this.activeView);
          document.dispatchEvent(new CustomEvent("pinned-views:changed"));
          this._toast(
            nextPinned
              ? `pinned "${this.activeView.name}" to left nav`
              : `unpinned "${this.activeView.name}"`,
            "success"
          );
        } else {
          this._toast(
            this._formatErrors(result && result.errors) || "pin toggle failed",
            "error"
          );
        }
      } catch (err) {
        console.error("togglePinned failed:", err);
        this._toast(`pin toggle failed: ${err}`, "error");
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

    async embedOnPage() {
      // Pin this saved view onto a user-chosen page as a
      // PageEmbeddedView. Opens the typeahead page picker; the user
      // sees their recent pages by default and can search by title.
      // The backend command is idempotent on (page, saved_view) — a
      // second click returns the existing embed rather than creating
      // a duplicate.
      if (!this.activeView) return;

      const page = await window.appModals.pickPage({
        title: `embed "${this.activeView.name}" on a page`,
        message: "search by page title, or pick from recent:",
        placeholder: "page title…",
        confirmLabel: "embed",
      });
      // null = user dismissed the dialog
      if (!page || !page.uuid) return;

      try {
        const r = await window.apiService.createPageEmbeddedView(
          page.uuid,
          this.activeView.uuid
        );
        if (r && r.success) {
          window.location.href = `/knowledge/page/${page.slug}/`;
          return;
        }
        // The create command short-circuits to the existing embed on
        // duplicate (idempotent), so a non-success here is a real
        // failure, not the "already embedded" case.
        this._toast(
          this._formatErrors(r && r.errors) || "Embed failed",
          "error"
        );
      } catch (err) {
        console.error("embedOnPage failed:", err);
        this._toast(`Embed failed: ${err}`, "error");
      }
    },

    _toast(message, type = "info", duration = 4000) {
      document.dispatchEvent(
        new CustomEvent("brainspread:toast", {
          detail: { message, type, duration },
        })
      );
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

    _maybePrefillFromQuery() {
      const params = new URLSearchParams(window.location.search);
      const key = params.get("property_key");
      const value = params.get("property_value");
      if (!key || !value) return;
      this.creating = true;
      this.editor = this._emptyEditor();
      this.editor.name = `${key} = ${value}`;
      this.editor.filter = JSON.stringify(
        { property_eq: { key, value } },
        null,
        2
      );
      this.editorErrors = {};
      this.saveError = null;
      this.prefillMatch = this._findPropertyEqView(key, value);
    },

    _findPropertyEqView(key, value) {
      // Match an existing view whose top-level filter is a single
      // ``property_eq`` on (key, value). Handles both the legacy
      // ``{key, value}`` shorthand and the op-dict ``{key, eq}`` shape
      // so views saved either way are detected. Deeper structural
      // matches (e.g. a ``property_eq`` nested inside an ``all``) aren't
      // worth the complexity — the chip-click path produces top-level
      // ``property_eq``, so that's what's most likely to duplicate.
      if (!Array.isArray(this.views)) return null;
      for (const v of this.views) {
        const f = v && v.filter;
        if (!f || typeof f !== "object" || Array.isArray(f)) continue;
        const pe = f.property_eq;
        if (!pe || typeof pe !== "object" || pe.key !== key) continue;
        const eqVal = "eq" in pe ? pe.eq : pe.value;
        if (eqVal === value) return v;
      }
      return null;
    },

    openPrefillMatch() {
      if (!this.prefillMatch) return;
      const slug = this.prefillMatch.slug;
      this.prefillMatch = null;
      this.creating = false;
      this.selectSlug(slug);
    },

    dismissPrefillMatch() {
      this.prefillMatch = null;
    },

    cancelCreate() {
      this.creating = false;
      this.saveError = null;
      this.editorErrors = {};
      this.prefillMatch = null;
    },

    broadcastChange(uuid) {
      if (!uuid) return;
      document.dispatchEvent(
        new CustomEvent("brainspread:block-changed", {
          detail: { uuid, source: this },
        })
      );
    },

    async refreshResults() {
      // Re-runs the active saved view so the results list reflects
      // backend changes. Called from onRowChanged below and from the
      // brainspread:block-changed event listener.
      if (!this.activeView || !this.activeView.uuid) return;
      try {
        const r = await window.apiService.runSavedView({
          uuid: this.activeView.uuid,
          limit: 100,
        });
        if (r && r.success) {
          this.runResult = r.data;
          this.runError = null;
        }
      } catch (err) {
        console.error("runSavedView refresh failed:", err);
      }
    },

    async onRowChanged(uuid) {
      this.broadcastChange(uuid);
      await this.refreshResults();
    },

    onRowError(message) {
      this.runError = message;
    },

    // ── Host-page modal owners (wired into EmbedResultRow as
    // onScheduleBlock + onOpenBlockInfo). Schedule + block info
    // both render their own popover/modal at this level so the
    // saved-views page can stand alone without a parent surface.

    openBlockInfoModal(b) {
      this.blockInfoModalBlock = b;
      this.blockInfoModalOpen = true;
    },

    closeBlockInfoModal() {
      this.blockInfoModalOpen = false;
      this.blockInfoModalBlock = null;
    },

    scheduleBlock(b, { clear = false } = {}) {
      if (clear) {
        this._submitSchedule(b, "", "", "");
        return;
      }
      this.schedulePopoverBlock = b;
      this.schedulePopoverInitialDate = b.scheduled_for || "";
      this.schedulePopoverInitialReminderDate = b.pending_reminder_date || "";
      this.schedulePopoverInitialTime = b.pending_reminder_time || "";
      this.schedulePopoverOpen = true;
    },

    onSchedulePopoverSave({ scheduledFor, reminderDate, reminderTime }) {
      const b = this.schedulePopoverBlock;
      this.schedulePopoverOpen = false;
      this.schedulePopoverBlock = null;
      if (!b) return;
      this._submitSchedule(b, scheduledFor, reminderDate, reminderTime);
    },

    onSchedulePopoverCancel() {
      this.schedulePopoverOpen = false;
      this.schedulePopoverBlock = null;
    },

    async _submitSchedule(block, scheduledFor, reminderDate, reminderTime) {
      try {
        const r = await window.apiService.scheduleBlock(
          block.uuid,
          scheduledFor,
          reminderDate,
          reminderTime
        );
        if (!r || !r.success) {
          throw new Error(
            r?.errors?.non_field_errors?.[0] || "failed to schedule"
          );
        }
        this.broadcastChange(block.uuid);
        await this.refreshResults();
      } catch (err) {
        console.error("scheduleBlock failed:", err);
        this.runError = `failed to schedule: ${err.message || err}`;
      }
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
          <div v-if="prefillMatch" class="prefill-match-banner">
            <span>
              View <strong>{{ prefillMatch.name }}</strong> already filters this property.
            </span>
            <button class="btn btn-primary" @click="openPrefillMatch">Open it</button>
            <button class="btn" @click="dismissPrefillMatch">Dismiss</button>
          </div>
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
          <div class="saved-view-help" v-html="cheatsheetHtml"></div>
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
            <h1 class="saved-view-title-row">
              <button
                type="button"
                class="page-favorite-toggle"
                :class="{ 'is-favorited': activeView.pinned }"
                @click="togglePinned"
                :title="activeView.pinned ? 'Unpin from left nav' : 'Pin to left nav'"
                :aria-pressed="activeView.pinned"
              >{{ activeView.pinned ? '★' : '☆' }}</button>
              <span class="saved-view-title-text">{{ activeView.name }}</span>
              <span v-if="activeView.is_system" class="system-pill">system</span>
            </h1>
            <div class="header-actions">
              <button class="btn" @click="runActive" :disabled="running" :title="editing ? 'Preview the current editor draft (does not save)' : 'Run the saved view'">
                {{ running ? "Running…" : editing ? "Preview" : "Run" }}
              </button>
              <button class="btn" @click="duplicateActive">Duplicate</button>
              <button class="btn" @click="embedOnPage" title="Embed this view on a page (defaults to today's daily note)">Embed…</button>
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
            <div class="saved-view-help" v-html="cheatsheetHtml"></div>
          </div>

          <div class="saved-view-results">
            <h3>
              Results <span v-if="runResult"> ({{ runResult.count }}<span v-if="runResult.truncated">+ truncated</span>)</span>
            </h3>
            <div v-if="runError" class="form-error">{{ runError }}</div>
            <div v-else-if="!runResult" class="empty-state">Loading…</div>
            <div v-else-if="!runResult.results.length" class="empty-state">No matches.</div>
            <ul v-else class="result-list">
              <EmbedResultRow
                v-for="b in runResult.results"
                :key="b.uuid"
                :block="b"
                :on-schedule-block="scheduleBlock"
                :on-open-block-info="openBlockInfoModal"
                @changed="onRowChanged"
                @error="onRowError"
              />
            </ul>
          </div>
        </template>
      </div>

      <ScheduleBlockPopover
        :is-open="schedulePopoverOpen"
        :initial-date="schedulePopoverInitialDate"
        :initial-reminder-date="schedulePopoverInitialReminderDate"
        :initial-time="schedulePopoverInitialTime"
        @save="onSchedulePopoverSave"
        @cancel="onSchedulePopoverCancel"
      />

      <BlockInfoModal
        :is-open="blockInfoModalOpen"
        :block="blockInfoModalBlock"
        @close="closeBlockInfoModal"
      />
    </div>
  `,
};

window.SavedViewsPage = SavedViewsPage;
