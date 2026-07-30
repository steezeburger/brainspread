// Minimal service worker so the app meets PWA installability criteria on
// Android/Chrome (which requires a registered service worker with a fetch
// handler before it will offer "Add to Home screen"). It intentionally
// does no caching - the index shell is already served no-cache (see
// knowledge.views.index) and API responses must always hit the network,
// so this just passes every request straight through.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
