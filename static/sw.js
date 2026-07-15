/* MarketPulse service worker.
 *
 * Strategy is deliberate for a *finance* app:
 *   - App SHELL (html/css/js/icons)  -> NETWORK-FIRST, cache fallback.
 *     Always ships the freshest code when online (critical: stale JS could
 *     mean stale money logic), but still opens offline from the cache like a
 *     native app.
 *   - /api/* (live prices, signals)  -> NETWORK-ONLY, never cached.
 *     Serving a stale price offline would be dishonest and dangerous, so we
 *     let a data request fail and the UI shows its normal "couldn't load"
 *     state instead of pretending old numbers are current.
 *
 * Bump SHELL_VERSION on any shell asset change to invalidate old caches.
 */
const SHELL_VERSION = "mp-shell-v7";
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/quickfill.js",
  "/vendor/big.min.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_VERSION).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Never touch live market data -- always straight to network.
  if (url.pathname.startsWith("/api/")) return;

  // Only handle our own origin's shell requests.
  if (url.origin !== self.location.origin) return;

  // Navigations: network-first (freshest HTML), fall back to cached shell offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL_VERSION).then((c) => c.put("/index.html", copy));
          return res;
        })
        .catch(() => caches.match("/index.html"))
    );
    return;
  }

  // Static assets: network-first (fresh code beats stale money logic),
  // fall back to cache only when offline.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(SHELL_VERSION).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
