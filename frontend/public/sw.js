/* MOSI PLAN Service Worker: App-Shell-Cache, Offline-Fallback, Web-Push. API-Antworten werden nie gecacht. */
const CACHE = "mosi-shell-v1";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icons/icon-192.png"])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put("/", copy)); return r; }).catch(() => caches.match("/")));
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; })));
  }
});
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: "MOSI PLAN", body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "MOSI PLAN", { body: d.body || "", tag: d.tag, icon: "/icons/icon-192.png", badge: "/icons/icon-192.png", data: { link: d.link || "/" } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const link = (e.notification.data && e.notification.data.link) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window" }).then((cs) => {
    const c = cs.find((x) => "focus" in x);
    if (c) { c.navigate(link); return c.focus(); }
    return self.clients.openWindow(link);
  }));
});
