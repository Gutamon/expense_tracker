/* 帳本 PWA service worker — app-shell offline fallback + installability.
   VERSION is derived from the mtime of every template/static file (see main_routes.py),
   so any code change automatically produces a new SW version — the browser detects the
   changed bytes, installs it, and activate wipes every previous cache. No manual bump. */
const VERSION = '{{ version }}';
const SHELL_CACHE = 'shell-' + VERSION;
const RUNTIME_CACHE = 'runtime-' + VERSION;

// Same-origin static essentials worth having available offline. Deliberately NOT
// '/': on a fresh install '/' returns the onboarding page, and precaching it would
// freeze that first-run screen as the offline fallback forever — making the app look
// like it "starts over" whenever the network/tunnel is unreachable. Real navigations
// are cached at runtime (below) after a successful network fetch instead.
const SHELL_ASSETS = [
  '/static/css/globals.css',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      // Tolerate individual failures (e.g. no-store on '/') so install never blocks.
      .then((cache) => Promise.allSettled(SHELL_ASSETS.map((u) => cache.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
            .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  // Live data — always hit the network, never serve stale figures.
  if (sameOrigin && url.pathname.startsWith('/api/')) return;

  // Page navigations: network-first, fall back to cached page, then the shell.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match('/')))
    );
    return;
  }

  // Static assets: stale-while-revalidate.
  if (sameOrigin && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const network = fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        }).catch(() => cached);
        return cached || network;
      })
    );
  }
});
