// Self-destructing service worker.
//
// This app does NOT use a service worker. But an older build (or the
// upstream project this was forked from) may have registered one that is
// still installed in visitors' browsers, sitting in front of the network
// and serving a cached index.html/assets that ignore HTTP no-store headers
// — trapping users on an old bundle whose chunk files no longer exist on
// the server (the endless "Loading new version" / failed dynamic import
// loop that survives reloads).
//
// The browser fetches THIS file directly from the network on its periodic
// service-worker update check (the SW script itself bypasses the SW cache),
// so shipping a real /sw.js that unregisters itself and purges Cache Storage
// is what actually frees a trapped browser. Once unregistered, subsequent
// loads go straight to the network and pick up the current build.
self.addEventListener('install', function () {
  self.skipWaiting()
})

self.addEventListener('activate', function (event) {
  event.waitUntil(
    (async function () {
      try {
        const keys = await caches.keys()
        await Promise.all(keys.map((k) => caches.delete(k)))
      } catch (e) {
        // ignore
      }
      try {
        await self.registration.unregister()
      } catch (e) {
        // ignore
      }
      // Reload every controlled tab so they drop this SW and re-fetch a
      // fresh, network-served index.html + chunks.
      try {
        const clients = await self.clients.matchAll({ type: 'window' })
        clients.forEach((client) => client.navigate(client.url))
      } catch (e) {
        // ignore
      }
    })()
  )
})
