/**
 * TemplatesPage — browsable list of the user's page templates.
 *
 * Route: /knowledge/templates/ (SPA shell catches the path; app.js
 * mounts this component for currentView === 'templates').
 *
 * Templates are pages with page_type="template" (issue #106). Before
 * this page existed they could only be created via "save as template"
 * on an existing page and used from the left-nav collapsible — this
 * gives them a first-class surface like saved views: list, use, open
 * for editing, plus creating a blank template from scratch.
 */
const TemplatesPage = {
  data() {
    return {
      loading: true,
      error: null,
      templates: [],
    };
  },

  async mounted() {
    await this.reload();
    // Stay fresh when a template is created/renamed elsewhere (e.g.
    // "save as template" in another tab of the SPA shell).
    this._onTemplatesChanged = () => this.reload();
    document.addEventListener("templates:changed", this._onTemplatesChanged);
  },

  beforeUnmount() {
    document.removeEventListener("templates:changed", this._onTemplatesChanged);
  },

  methods: {
    pageUrl(t) {
      return `/knowledge/page/${encodeURIComponent(t.slug)}/`;
    },

    displayTitle(t) {
      return t.title || "untitled template";
    },

    formatModified(t) {
      if (!t.modified_at) return "";
      const d = new Date(t.modified_at);
      if (isNaN(d.getTime())) return "";
      return d.toLocaleDateString();
    },

    async reload() {
      this.loading = true;
      this.error = null;
      try {
        const result = await window.apiService.getTemplates();
        if (result && result.success) {
          this.templates = (result.data && result.data.templates) || [];
        } else {
          this.error = "failed to load templates";
        }
      } catch (err) {
        console.error("TemplatesPage load failed:", err);
        this.error = "failed to load templates";
      } finally {
        this.loading = false;
      }
    },

    async createBlankTemplate() {
      const title = await window.appModals.prompt({
        title: "new template",
        message: "enter a name for the template:",
        placeholder: "template name",
        confirmLabel: "create",
      });
      if (title == null || !title.trim()) return;
      const trimmed = title.trim();
      // Same client-side slugification as app.js createNewPage.
      const slug = trimmed
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-")
        .replace(/-+/g, "-");
      try {
        const result = await window.apiService.createPage(
          trimmed,
          slug,
          true,
          "template"
        );
        if (result && result.success) {
          document.dispatchEvent(new CustomEvent("templates:changed"));
          window.location.href = `/knowledge/page/${slug}/`;
        } else {
          this._toast(
            "failed to create template: " +
              (result?.errors?.title?.[0] ||
                result?.errors?.slug?.[0] ||
                "unknown error"),
            "error"
          );
        }
      } catch (err) {
        console.error("createBlankTemplate failed:", err);
        this._toast("failed to create template", "error");
      }
    },

    async useTemplate(t) {
      // Mirrors app.js useTemplate: clone the template's block tree
      // into a new regular page with a user-chosen title.
      const title = await window.appModals.prompt({
        title: `new page from "${this.displayTitle(t)}"`,
        message: "enter a title for the new page:",
        placeholder: "title",
        defaultValue: t.title,
        confirmLabel: "create",
      });
      if (title == null || !title.trim()) return;
      try {
        const result = await window.apiService.duplicatePage(t.uuid, {
          newTitle: title.trim(),
          newPageType: "page",
        });
        if (result && result.success && result.data?.slug) {
          window.location.href = `/knowledge/page/${result.data.slug}/`;
        } else {
          this._toast(
            "failed to create page from template: " +
              (result?.errors?.non_field_errors?.[0] || "unknown error"),
            "error"
          );
        }
      } catch (err) {
        console.error("useTemplate failed:", err);
        this._toast("failed to create page from template", "error");
      }
    },

    async addToPage(t) {
      // Append this template's block tree onto an existing page —
      // same backend flow as the page menu's "add from template…",
      // approached from the template side instead of the page side.
      if (!window.appModals?.pickPage) {
        console.error("appModals.pickPage is not available");
        return;
      }
      const page = await window.appModals.pickPage({
        title: `add "${this.displayTitle(t)}" to a page`,
        message: "search by page title, or pick from recent:",
        placeholder: "page title…",
        confirmLabel: "add",
      });
      if (!page || !page.uuid) return;
      try {
        const result = await window.apiService.addTemplateBlocksToPage(
          t.uuid,
          page.uuid
        );
        if (result && result.success) {
          window.location.href = `/knowledge/page/${encodeURIComponent(page.slug)}/`;
        } else {
          this._toast(
            "failed to add template blocks: " +
              (result?.errors?.non_field_errors?.[0] || "unknown error"),
            "error"
          );
        }
      } catch (err) {
        console.error("addToPage failed:", err);
        this._toast("failed to add template blocks", "error");
      }
    },

    _toast(message, type = "info") {
      document.dispatchEvent(
        new CustomEvent("brainspread:toast", { detail: { message, type } })
      );
    },
  },

  template: `
    <div class="templates-page">
      <div class="pages-list-header">
        <h1>templates</h1>
        <button type="button" class="btn btn-primary" @click="createBlankTemplate">New template</button>
      </div>
      <p class="templates-page-hint">
        Templates are reusable page skeletons. Use one to start a new
        page from its block tree, or open it to edit the skeleton
        itself. You can also turn any existing page into a template via
        "save as template" in the page menu.
      </p>

      <div v-if="loading" class="loading">Loading templates…</div>
      <div v-else-if="error" class="form-error">{{ error }}</div>
      <div v-else-if="!templates.length" class="empty-state">
        No templates yet. Create one here, or use "save as template"
        from a page menu.
      </div>

      <ul v-else class="templates-list">
        <li v-for="t in templates" :key="t.uuid" class="templates-list-row">
          <a :href="pageUrl(t)" class="templates-list-link">
            <span class="templates-list-name">{{ displayTitle(t) }}</span>
            <span class="templates-list-modified" v-if="formatModified(t)">last modified {{ formatModified(t) }}</span>
          </a>
          <div class="templates-list-actions">
            <button type="button" class="btn btn-compact" @click="useTemplate(t)" :title="'Create a new page from ' + displayTitle(t)">Use</button>
            <button type="button" class="btn btn-compact" @click="addToPage(t)" :title="'Append ' + displayTitle(t) + '\\'s blocks to an existing page'">Add to page…</button>
            <a :href="pageUrl(t)" class="btn btn-compact" :title="'Open ' + displayTitle(t) + ' for editing'">Edit</a>
          </div>
        </li>
      </ul>
    </div>
  `,
};

window.TemplatesPage = TemplatesPage;
