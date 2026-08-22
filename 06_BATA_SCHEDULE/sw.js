self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : { title: 'BATAGOTA Schedule', body: '알림 시간입니다.' };
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    tag: data.tag,
    icon: '/icon.svg',
    badge: '/icon.svg',
    renotify: true,
    silent: true,
    requireInteraction: true
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(openClients => {
    if (openClients.length) return openClients[0].focus();
    return clients.openWindow('/');
  }));
});
