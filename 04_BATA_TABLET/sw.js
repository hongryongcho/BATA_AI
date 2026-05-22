const CACHE = 'bata-tablet-v1';
const SHELL = ['/tablet/', '/tablet/app.js', '/tablet/style.css', '/tablet/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // MQTT WebSocket 요청은 캐시 제외
  if (e.request.url.includes('ws://') || e.request.url.includes('wss://')) return;
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
