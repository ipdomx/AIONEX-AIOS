const CACHE = "aionex-aios-v1.6.0";
const CORE = [
  "/ar/",
  "/offline.html",
  "/manifest.webmanifest",
  "/icons/aionex-192.png",
  "/icons/aionex-512.png",
  "/brand/aionex-mark.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(CORE)));
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isApi(url) {
  return (
    url.pathname.startsWith("/api/") || url.pathname.startsWith("/api/v1/")
  );
}

function isCacheableAsset(request, url) {
  return (
    request.method === "GET" &&
    url.origin === self.location.origin &&
    !isApi(url) &&
    ["script", "style", "image", "font", "manifest"].includes(
      request.destination,
    )
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || isApi(url)) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            const copy = response.clone();
            event.waitUntil(
              caches.open(CACHE).then((cache) => cache.put(request, copy)),
            );
          }
          return response;
        })
        .catch(
          async () =>
            (await caches.match(request)) || caches.match("/offline.html"),
        ),
    );
    return;
  }

  if (isCacheableAsset(request, url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone();
              event.waitUntil(
                caches.open(CACHE).then((cache) => cache.put(request, copy)),
              );
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      }),
    );
  }
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data?.json() || {};
  } catch {
    data = { body: event.data?.text() || "" };
  }
  const title = data.title || "AIONEX AIOS";
  const options = {
    body: data.body || data.message || "AIONEX notification",
    icon: "/icons/aionex-192.png",
    badge: "/icons/aionex-192.png",
    data: { url: data.url || "/ar/notifications/" },
    tag: data.tag || data.notification_id || "aionex-notification",
    renotify: Boolean(data.renotify),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destination = new URL(
    event.notification.data?.url || "/ar/notifications/",
    self.location.origin,
  ).href;
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then(async (clients) => {
        for (const client of clients) {
          if (
            client.url.startsWith(self.location.origin) &&
            "focus" in client
          ) {
            await client.navigate(destination);
            return client.focus();
          }
        }
        return self.clients.openWindow(destination);
      }),
  );
});
