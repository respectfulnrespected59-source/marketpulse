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
const SHELL_VERSION = "mp-shell-v20";
const SHELL_ASSETS = [
  "/",
  "/app",
  "/index.html",
  "/landing/landing.css",
  "/landing/landing.js",
  "/brand.css",
  "/styles.css",
  "/app.js",
  "/chart.js",
  "/chart-tools.js",
  "/learn.js",
  "/panels.js",
  "/home.js",
  "/license.js",
  "/wizards.js",
  "/paper.js",
  "/options-paper.js",
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

  // Navigations: network-first (freshest HTML), fall back to cached page offline.
  // Each page is cached under its OWN path: "/" is the landing and "/app" is the
  // app, so caching every navigation under one key would let a landing visit
  // overwrite the app shell and open the installed app on the marketing page.
  if (req.mode === "navigate") {
    const key = url.pathname === "/app/" ? "/app" : url.pathname;
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(SHELL_VERSION).then((c) => c.put(key, copy));
          }
          return res;
        })
        // Offline: the page's own copy, else the app shell. The landing gets no
        // fallback on purpose: an offline visitor shouldn't be dropped into the app.
        .catch(() =>
          caches.match(key).then((hit) => hit || (key === "/" ? undefined : caches.match("/app")))
        )
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
