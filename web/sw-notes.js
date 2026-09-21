/* ตัวช่วยตอนเน็ตสะดุดของหน้าโน้ต (/notes)
 *
 * **ห้ามแคชอะไรที่ขึ้นต้นด้วย /api/** เพราะโน้ตเป็นของที่แก้จากคอมได้ตลอด
 * ถ้าแคชไว้ มือถือจะเห็นของเก่าแล้วนึกว่าโน้ตที่เพิ่งพิมพ์บนคอมหายไป
 * ซึ่งแยกไม่ออกจาก "ข้อมูลหายจริง"
 *
 * แคชเฉพาะเปลือกหน้า (html/css/js/ไอคอน) เพื่อให้เปิดแอปขึ้นมาไม่จอขาว
 */
const CACHE = "notes-shell-v1";
const SHELL = [
  "/notes",
  "/static/notes-base.css",
  "/static/notes.css",
  "/static/notes-app.js",
  "/static/notes-ui.js",
  "/static/icons/notes-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;          // ข้อมูลต้องสดเสมอ
  if (event.request.method !== "GET") return;
  // เอาของใหม่ก่อนเสมอ ใช้ของในแคชเฉพาะตอนเน็ตไม่มา
  event.respondWith(
    fetch(event.request)
      .then((answer) => {
        const copy = answer.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
        return answer;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: true })),
  );
});
