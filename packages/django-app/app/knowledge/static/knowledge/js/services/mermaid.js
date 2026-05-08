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
  let waitForMermaidPromise = null;

  // How long to wait for the CDN script to define `window.mermaid`
  // before giving up and rendering a visible error in the placeholder.
  // The script tag is synchronous in `base.html`, so on every well-
  // behaved network this is instant — but on slow/blocked networks
  // (corporate proxies, adblockers, prod CDN edge issues) it can race
  // the first BlockComponent.mounted call. We poll for it briefly
  // instead of failing silently the way the original code did.
  const MERMAID_LOAD_TIMEOUT_MS = 4000;
  const MERMAID_POLL_INTERVAL_MS = 50;

  // Map the app's user-facing themes to mermaid's built-in themes.
  // Mermaid ships with `default` (dark-on-light), `dark`
  // (light-on-dark), `forest`, and `neutral`. Pick the variant whose
  // foreground contrasts with the app theme's background — picking the
  // wrong one leaves the diagram lines almost invisible (e.g. earthy's
  // cream background under mermaid's dark theme).
  const LIGHT_BG_THEMES = new Set(["light", "earthy"]);

  function mermaidThemeFor(appTheme) {
    if (appTheme === "forest") return "forest";
    if (LIGHT_BG_THEMES.has(appTheme)) return "default";
    return "dark";
  }

  // Resolve once `window.mermaid` becomes available, or after the
  // timeout. Memoized so concurrent renders share the same poll loop.
  function waitForMermaid() {
    if (window.mermaid) return Promise.resolve(true);
    if (waitForMermaidPromise) return waitForMermaidPromise;
    waitForMermaidPromise = new Promise((resolve) => {
      const start = Date.now();
      const tick = () => {
        if (window.mermaid) {
          resolve(true);
          return;
        }
        if (Date.now() - start >= MERMAID_LOAD_TIMEOUT_MS) {
          resolve(false);
          return;
        }
        setTimeout(tick, MERMAID_POLL_INTERVAL_MS);
      };
      tick();
    });
    return waitForMermaidPromise;
  }

  async function ensureInitialized(appTheme) {
    const ok = await waitForMermaid();
    if (!ok) return false;
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

  function renderLoadFailure(el) {
    el.innerHTML =
      '<div class="block-mermaid-error">mermaid library failed to load' +
      " (CDN blocked or offline). Refresh once the network is back to" +
      " try again.</div>";
    el.dataset.mermaidRendered = "load-failed";
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
      // Mermaid v11 can resolve with an empty `svg` string instead of
      // throwing when the diagram's labels trip strict-mode sanitization
      // (e.g. literal "<...>" / "<br/>" content inside Note labels). The
      // original code happily wrote "" and stamped data-mermaid-rendered=
      // true, so on prod you saw an empty placeholder with no clue why.
      // Surface the empty case as a visible error instead.
      if (!svg) {
        el.innerHTML =
          '<div class="block-mermaid-error">mermaid produced an empty' +
          " SVG (often: HTML in labels under strict securityLevel, or a" +
          " Trusted Types policy stripping the output). Check the diagram" +
          " for &lt;...&gt; / &lt;br/&gt; in labels.</div>";
        el.dataset.mermaidRendered = "empty";
        return;
      }
      el.innerHTML = svg;
      el.dataset.mermaidRendered = "true";
      // Defensive: if some downstream sanitizer (Trusted Types, an
      // adblocker, or a stale service worker) strips the SVG after we
      // assign it, surface that too. Without this the user sees the same
      // empty placeholder as the strict-mode case.
      if (!el.querySelector("svg")) {
        el.innerHTML =
          '<div class="block-mermaid-error">mermaid SVG was stripped' +
          " after render (Trusted Types / CSP / adblocker). Check the" +
          " browser console for a Trusted-Types policy violation.</div>";
        el.dataset.mermaidRendered = "stripped";
      }
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
    if (!rootEl) return;
    // Snapshot pending elements BEFORE awaiting so we still mark them
    // as load-failed below if the mermaid library never shows up. The
    // original code returned silently on missing-mermaid, which left
    // empty placeholders with no clue what went wrong.
    const els = Array.from(
      rootEl.querySelectorAll(".block-mermaid:not([data-mermaid-rendered])")
    );
    for (const el of els) {
      el.dataset.mermaidRendered = "pending";
    }
    const ready = await ensureInitialized(appTheme);
    if (!ready) {
      for (const el of els) renderLoadFailure(el);
      return;
    }
    for (const el of els) {
      await renderOne(el);
    }
  }

  // Re-render every mermaid diagram on the page. Used after a theme
  // change so existing SVGs pick up the new color palette.
  async function rerenderAll(appTheme) {
    initialized = false; // force re-initialize with new theme
    const ready = await ensureInitialized(appTheme);
    const els = document.querySelectorAll(".block-mermaid");
    if (!ready) {
      for (const el of els) {
        // Only stamp placeholders that never got an SVG; leave the
        // already-rendered ones alone since their old SVG is still
        // (visually) better than a "library failed" error.
        if (el.dataset.mermaidRendered !== "true") renderLoadFailure(el);
      }
      return;
    }
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
