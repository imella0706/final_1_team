const CACHE_PREFIX = "brandmate-shell-";
const CACHE_NAME = `${CACHE_PREFIX}20260729-v1`;
const APP_SHELL_PATHS = [
  "./",
  "./index.html",
  "./styles.css?v=mobile-fit-20260727",
  "./app.js?v=pwa-20260729-models",
  "./manifest.webmanifest",
  "./icons/apple-touch-icon.png",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-maskable-192.png",
  "./icons/icon-maskable-512.png",
];

const APP_SHELL_URLS = APP_SHELL_PATHS.map(
  (path) => new URL(path, self.registration.scope).href,
);
const APP_SHELL_URL_SET = new Set(APP_SHELL_URLS);

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isApiPath(pathname) {
  return pathname === "/api" || pathname.startsWith("/api/") || pathname.includes("/api/");
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);

  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic") {
      await cache.put(request, response.clone()).catch(() => undefined);
    }
    return response;
  } catch (error) {
    const cachedResponse = await cache.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.origin !== self.location.origin ||
    isApiPath(url.pathname) ||
    !APP_SHELL_URL_SET.has(url.href)
  ) {
    return;
  }

  event.respondWith(networkFirst(request));
});
