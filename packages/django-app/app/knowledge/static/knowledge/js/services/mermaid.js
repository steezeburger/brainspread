// Mermaid diagram integration for the knowledge app.
//
// Code blocks with language "mermaid" are rendered to an inline SVG via
// the global `mermaid` library loaded from CDN. The block formatter in
// Page.js emits a placeholder element with the source stashed in a
// data attribute; this helper finds those placeholders inside a DOM
// subtree and replaces them with the rendered SVG.

(function () {
  let initialized = false;
  let currentMermaidTheme = null;

  // Map the app's user-facing themes to mermaid's built-in themes. Mermaid
  // ships with `default`, `dark`, `forest`, and `neutral`. Anything that
  // isn't obviously light gets the dark mermaid theme so contrast stays
  // readable on dark backgrounds.
  function mermaidThemeFor(appTheme) {
    if (appTheme === "light") return "default";
    if (appTheme === "forest") return "forest";
    return "dark";
  }

  function ensureInitialized(appTheme) {
    if (!window.mermaid) return false;
    const theme = mermaidThemeFor(appTheme);
    if (initialized && theme === currentMermaidTheme) return true;
    window.mermaid.initialize({
      startOnLoad: false,
      theme,
      // strict mode disables HTML in labels and click events, which keeps
      // user-authored diagrams from injecting markup into the page.
      securityLevel: "strict",
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
    });
    initialized = true;
    currentMermaidTheme = theme;
    return true;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function renderOne(el) {
    const source = el.dataset.mermaidSource || "";
    if (!source.trim()) {
      el.dataset.mermaidRendered = "true";
      return;
    }
    const id = `mermaid-${Math.random().toString(36).slice(2, 11)}`;
    try {
      const { svg } = await window.mermaid.render(id, source);
      el.innerHTML = svg;
      el.dataset.mermaidRendered = "true";
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      el.innerHTML = `<div class="block-mermaid-error">mermaid error: ${escapeHtml(
        msg
      )}</div>`;
      el.dataset.mermaidRendered = "error";
    }
  }

  // Render any mermaid placeholders inside `rootEl` that haven't been
  // processed yet. Safe to call repeatedly — already-rendered diagrams
  // are skipped via the `data-mermaid-rendered` marker. Block components
  // are recursive, so a parent's `$el` overlaps its children's; the
  // "pending" marker is set synchronously to keep two concurrent calls
  // from rendering the same element twice.
  async function renderIn(rootEl, appTheme) {
    if (!rootEl || !ensureInitialized(appTheme)) return;
    const els = rootEl.querySelectorAll(
      ".block-mermaid:not([data-mermaid-rendered])"
    );
    for (const el of els) {
      el.dataset.mermaidRendered = "pending";
      await renderOne(el);
    }
  }

  // Re-render every mermaid diagram on the page. Used after a theme
  // change so existing SVGs pick up the new color palette.
  async function rerenderAll(appTheme) {
    if (!window.mermaid) return;
    initialized = false; // force re-initialize with new theme
    if (!ensureInitialized(appTheme)) return;
    const els = document.querySelectorAll(".block-mermaid");
    for (const el of els) {
      el.removeAttribute("data-mermaid-rendered");
      el.innerHTML = "";
      await renderOne(el);
    }
  }

  window.brainspreadMermaid = {
    renderIn,
    rerenderAll,
  };
})();
