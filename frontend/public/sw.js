/* Tempo PWA service worker: app-shell caching for offline use.
 * - Navigation requests: network-first, fall back to the cached shell when
 *   offline (so the PWA still opens without connectivity).
 * - Hashed static assets (/_expo/...): cache-first, they are immutable.
 * - The backend API is never cached here; data sync/offline queueing is a
 *   Phase 6 concern handled in the app layer. */
const CACHE_NAME = "tempo-shell-v1";
const SHELL_ROUTES = ["/"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ROUTES))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // backend API: network only
  if (url.pathname.startsWith("/api/")) return;

  const isStaticAsset = url.pathname.startsWith("/_expo/") || /\.(js|css|png|jpg|jpeg|svg|woff2?|ttf|ico|json)$/.test(url.pathname);

  if (isStaticAsset) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            return response;
          }),
      ),
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/")));
  }
});
