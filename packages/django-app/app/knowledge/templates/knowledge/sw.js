{% load static %}
// PWA service worker for the knowledge SPA.
//
// This is a Django template (not a plain static file) so the cache name
// can be tied to STATIC_VERSION - the same value used for the `?v=`
// cache-busting query strings on every <script>/<link> tag in base.html.
// That way a new deploy gets its own cache namespace and the activate
// handler below cleans up the previous deploy's cache automatically.
//
// Scope: served at /knowledge/sw.js (see knowledge.views.service_worker)
// so it defaults to controlling everything under /knowledge/.
const CACHE_NAME = "brainspread-shell-{{ STATIC_VERSION }}";

// App-shell assets fetched and cached at install time. Keep this in sync
// with the <script>/<link> tags in knowledge/templates/knowledge/base.html
// - anything added there for every page load should probably be listed
// here too. Per-whiteboard-load esm.sh imports (React/tldraw) are NOT
// included: they're versioned dynamically at runtime and too fragile to
// precache, but the generic fetch handler below still caches them
// opportunistically after first use.
const PRECACHE_URLS = [
  "{% static 'knowledge/manifest.json' %}",
  "{% static 'knowledge/icons/icon-192.png' %}",
  "{% static 'knowledge/icons/icon-512.png' %}",
  "{% static 'knowledge/icons/icon-maskable-192.png' %}",
  "{% static 'knowledge/icons/icon-maskable-512.png' %}",
  "{% static 'knowledge/icons/apple-touch-icon.png' %}",
  "{% static 'knowledge/css/app.css' %}?v={{ STATIC_VERSION }}",
  "https://esm.sh/tldraw@3/tldraw.css",
  "https://unpkg.com/vue@3/dist/vue.global.js",
  "https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js",
  "https://cdn.jsdelivr.net/npm/dompurify@3.0.5/dist/purify.min.js",
  "https://cdn.jsdelivr.net/npm/prismjs@1.29.0/components/prism-core.min.js",
  "https://cdn.jsdelivr.net/npm/prismjs@1.29.0/plugins/autoloader/prism-autoloader.min.js",
  "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js",
  "https://cdn.jsdelivr.net/npm/prismjs@1.29.0/themes/prism-tomorrow.min.css",
  "{% static 'knowledge/js/services/api.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/services/mermaid.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/services/csv.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/BlockComponent.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/LoginForm.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/Whiteboard.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/ScheduleBlockPopover.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/BlockChatPopover.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/BlockInfoModal.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/EmbedContextMenu.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/EmbedResultRow.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/QueryEmbedBlock.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/Page.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/TaggedBlockDisplay.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/LeftNav.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/SettingsModal.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/HelpModal.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/ChatHistory.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/ChatPanel.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/ToastNotifications.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/AppModals.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/SpotlightSearch.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/GraphView.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/SavedViewsPage.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/PagesListPage.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/components/TemplatesPage.js' %}?v={{ STATIC_VERSION }}",
  "{% static 'knowledge/js/app.js' %}?v={{ STATIC_VERSION }}",
];

// Same-origin static assets and known vendor CDNs are safe to cache
// indefinitely (cache-first). Everything else - API calls above all -
// must never be served from cache, so it's left untouched below.
const CDN_HOSTS = ["unpkg.com", "cdn.jsdelivr.net", "esm.sh"];

function isPrecacheable(url) {
  if (url.origin === self.location.origin) {
    return url.pathname.startsWith("/static/");
  }
  return CDN_HOSTS.includes(url.hostname);
}

// The SPA shell (index.html) is intentionally served no-cache by
// knowledge.views.index - it references version-pinned asset URLs, so it
// must never be served stale while the network is reachable. This key
// exists only as an offline fallback: the last shell response we saw
// while online, served back when navigation to any SPA route fails
// outright. Share links and reminder-action pages get their own
// (different) templates and are excluded - the cached SPA shell would be
// the wrong page for them.
const SHELL_FALLBACK_REQUEST = new Request("/knowledge/__offline-shell__");

function isSpaNavigation(url) {
  if (url.origin !== self.location.origin) return false;
  if (!url.pathname.startsWith("/knowledge/")) return false;
  if (url.pathname.startsWith("/knowledge/share/")) return false;
  if (url.pathname.startsWith("/knowledge/r/")) return false;
  return true;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.all(
          PRECACHE_URLS.map((url) =>
            cache
              .add(url)
              .catch((err) => console.warn("[sw] precache failed:", url, err))
          )
        )
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (request.mode === "navigate" && isSpaNavigation(url)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          caches
            .open(CACHE_NAME)
            .then((cache) => cache.put(SHELL_FALLBACK_REQUEST, response.clone()));
          return response;
        })
        .catch(() => caches.match(SHELL_FALLBACK_REQUEST))
    );
    return;
  }

  if (!isPrecacheable(url)) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok || response.type === "opaque") {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    })
  );
});
