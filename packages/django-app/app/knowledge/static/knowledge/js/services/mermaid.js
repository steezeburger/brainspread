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

  // Mermaid's render() defaults to `select('body')` when no
  // svgContainingElement is passed, then appends a measurement div
  // (`<div id="d{id}"><svg id="{id}">...</svg></div>`). On the success
  // path mermaid removes that div via removeTempElements(); on a render
  // error the cleanup is skipped and the error SVG (the "Syntax error
  // in graph" sad-face) is left visible at the bottom of the page.
  //
  // We give mermaid an offscreen host to measure into so any leak
  // can't surface under the page, and still id-sweep as a belt-and-
  // braces safety net.
  let renderHost = null;
  function getRenderHost() {
    if (renderHost && renderHost.isConnected) return renderHost;
    renderHost = document.createElement("div");
    renderHost.id = "brainspread-mermaid-render-host";
    renderHost.setAttribute("aria-hidden", "true");
    renderHost.style.cssText =
      "position:absolute;left:-99999px;top:-99999px;width:1px;height:1px;overflow:hidden;visibility:hidden;pointer-events:none";
    document.body.appendChild(renderHost);
    return renderHost;
  }

  // After mermaid.render() returns, we put its SVG into the user's
  // placeholder via innerHTML. That SVG carries id="{id}" — the same
  // id the prior cleanup pass used in `getElementById(id).remove()`,
  // which then deleted our legitimate output from inside the
  // .block-mermaid div. (That's the staging-vs-prod divergence: this
  // branch's older code didn't do the destructive sweep.)
  //
  // Scope cleanup to scaffolding mermaid actually leaks: nodes inside
  // our offscreen render host, or stranded as direct children of
  // <body>. Never touch anything inside a .block-mermaid placeholder.
  function isOurPlaceholderDescendant(node) {
    return !!node.closest(".block-mermaid");
  }
  function cleanupOrphans() {
    const host = renderHost && renderHost.isConnected ? renderHost : null;
    if (host) {
      // Mermaid removes its scaffolding on success but not on error;
      // wipe whatever's left inside the host either way so the next
      // render starts clean.
      host.replaceChildren();
    }
    document
      .querySelectorAll(
        'body > div[id^="dmermaid-"], body > svg[id^="mermaid-"], body > iframe[id^="imermaid-"]'
      )
      .forEach((node) => {
        if (!isOurPlaceholderDescendant(node)) node.remove();
      });
  }

  // Mermaid's render mutates a single shared scaffolding host and isn't
  // safe to call concurrently — two overlapping renders interleave their
  // DOM writes and one or both finish with an empty SVG, leaving the
  // user with a blank placeholder until the block re-renders (e.g. on
  // edit-out). Funnel every render through this chain so calls from
  // sibling BlockComponents' mounted hooks queue instead of racing.
  let renderChain = Promise.resolve();
  function serialize(fn) {
    const next = renderChain.then(fn, fn);
    renderChain = next.catch(() => {});
    return next;
  }

  async function renderOne(el) {
    const source = el.dataset.mermaidSource || "";
    if (!source.trim()) {
      el.dataset.mermaidRendered = "true";
      return;
    }
    const id = `mermaid-${Math.random().toString(36).slice(2, 11)}`;
    try {
      const { svg } = await serialize(() =>
        window.mermaid.render(id, source, getRenderHost())
      );
      // Mermaid v11 can resolve with an empty `svg` string instead of
      // throwing when the diagram's labels trip strict-mode sanitization
      // (e.g. literal "<...>" / "<br/>" content inside Note labels).
      // Surface the empty case as a visible error instead of stamping
      // rendered=true with no diagram.
      if (!svg) {
        el.innerHTML =
          '<div class="block-mermaid-error">mermaid produced an empty' +
          " SVG (often: HTML in labels under strict securityLevel).</div>";
        el.dataset.mermaidRendered = "empty";
        return;
      }
      el.innerHTML = svg;
      el.dataset.mermaidRendered = "true";
      // Defensive: if a downstream sanitizer (Trusted Types, an
      // adblocker, a stale service worker) strips the SVG after we
      // assign it, surface that too — without this the user sees the
      // same empty placeholder as the strict-mode case.
      if (!el.querySelector("svg")) {
        el.innerHTML =
          '<div class="block-mermaid-error">mermaid SVG was stripped' +
          " after render (Trusted Types / CSP / adblocker).</div>";
        el.dataset.mermaidRendered = "stripped";
      }
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      el.innerHTML = `<div class="block-mermaid-error">mermaid error: ${escapeHtml(
        msg
      )}</div>`;
      el.dataset.mermaidRendered = "error";
    } finally {
      cleanupOrphans();
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

  // Hover-overlay "open in new tab" button. The button HTML is emitted
  // by the formatters (BlockComponent.assetRenderHtml + Page.js's
  // formatContentWithTags) inside the `.block-mermaid-wrapper`; we
  // listen on the document so the same handler works for both the
  // asset path and the inline-code path, and so newly-rendered blocks
  // pick it up without re-binding.
  function serializeStandaloneSvg(svgEl) {
    // Clone so we can ensure required xmlns attributes without mutating
    // the live DOM. The rendered SVG should already have xmlns set, but
    // not every mermaid version is consistent about xmlns:xlink.
    const clone = svgEl.cloneNode(true);
    if (!clone.getAttribute("xmlns")) {
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    }
    if (!clone.getAttribute("xmlns:xlink")) {
      clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
    }
    const markup = new XMLSerializer().serializeToString(clone);
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + markup;
  }

  function openSvgInNewTab(svgEl) {
    if (!svgEl) return;
    let url;
    try {
      const xml = serializeStandaloneSvg(svgEl);
      const blob = new Blob([xml], { type: "image/svg+xml" });
      url = URL.createObjectURL(blob);
    } catch (e) {
      console.warn("failed to serialize mermaid svg:", e);
      return;
    }
    // Leak-tolerant: the blob is tiny (one SVG) and lives only for the
    // current tab's lifetime. Revoking immediately can race the new
    // tab's load; revoke after a generous delay so the new tab has
    // settled.
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  // Capture phase so we run before the inline-code path's
  // .block-content-display @click (which starts editing) and before the
  // asset path's .block-asset @click.stop (which would otherwise
  // swallow the bubble-phase event entirely).
  document.addEventListener(
    "click",
    (event) => {
      const btn = event.target.closest(".block-mermaid-open");
      if (!btn) return;
      event.preventDefault();
      event.stopPropagation();
      const wrapper = btn.closest(".block-mermaid-wrapper");
      const svg = wrapper && wrapper.querySelector(".block-mermaid svg");
      openSvgInNewTab(svg);
    },
    true
  );

  // Mirror the click capture for keyboard activation. The button is a
  // child of .block-content-display, whose @keydown handler enters
  // edit mode on Enter / Space — that fires before the browser's
  // native button activation, so without this the block would start
  // editing instead of opening the diagram. We stop propagation but
  // do NOT preventDefault, so the browser still synthesizes the click
  // that our click listener above handles.
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const btn = event.target.closest(".block-mermaid-open");
      if (!btn) return;
      event.stopPropagation();
    },
    true
  );
})();
