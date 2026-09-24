/* Service Worker สำหรับ Pipeline Remote PWA */
const CACHE_NAME = "pipeline-remote-v1";
const ASSETS = [
  "/remote",
  "/static/manifest-remote.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) return caches.delete(key);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // สำหรับ WebSocket และ API calls ให้วิ่งตรงเข้าเครือข่ายเสมอ
  if (event.request.url.includes("/api/") || event.request.url.includes("/ws/")) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
