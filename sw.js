// Option Panda service worker — v3 (2026-05-22)
// Handles three responsibilities:
//
//   1. iOS 16.4+ Web Push notifications. iOS only fires alerts that come
//      through a registered service worker — the browser-level
//      `new Notification()` API is unsupported on Safari mobile. The
//      page calls `registration.showNotification()` for local alerts,
//      and the `push` listener below handles real server-side push
//      events from OneSignal / FCM / a custom Cloudflare worker.
//
//   2. Offline shell — cache static assets (icons, splash) so the PWA
//      icon launches instantly even on poor connectivity. index.html is
//      served network-first (bypasses Safari HTTP cache — can't set
//      response headers on GitHub Pages); cached only as an offline
//      fallback, never served stale while online.
//
//   3. Notification click routing — focus an existing tab if open,
//      otherwise launch a new one.

var CACHE_NAME = 'option-panda-v4';   // v3 (2026-05-22): network-first navigation — purges v3 cache on activate
var STATIC_ASSETS = [
  './assets/icon-192.png',
  './assets/icon-512.png',
  './assets/apple-touch-icon.png',
  './assets/pandas2.webp',
  './assets/panda-transparent.webp',
  './assets/rrjcar-icon.webp',
  './manifest.json'
];

self.addEventListener('install', function(e){
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache){
      return cache.addAll(STATIC_ASSETS).catch(function(){
        // Best-effort: don't fail install if a single asset is missing
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e){
  e.waitUntil(
    Promise.all([
      // Drop old cache versions
      caches.keys().then(function(keys){
        return Promise.all(keys.map(function(k){
          if (k !== CACHE_NAME) return caches.delete(k);
        }));
      }),
      self.clients.claim()
    ])
  );
});

// Network-first for navigation; cache-first for static assets.
// Navigation is intercepted here to bypass Safari's HTTP cache (GitHub Pages
// can't set Cache-Control headers, so the meta tag approach is unreliable).
self.addEventListener('fetch', function(e){
  var url = e.request.url;
  // Skip non-GET (POST to broker etc.)
  if (e.request.method !== 'GET') return;
  // Network-first for navigation (index.html / document requests).
  // 3s timeout → fall back to cached copy; if no cache → inline offline page.
  if (e.request.mode === 'navigate' || e.request.destination === 'document' ||
      url.indexOf('.html') >= 0) {
    e.respondWith(
      Promise.race([
        fetch(e.request).then(function(resp){
          var clone = resp.clone();
          caches.open(CACHE_NAME).then(function(c){ c.put(e.request, clone); });
          return resp;
        }),
        new Promise(function(_, rej){
          setTimeout(function(){ rej(new Error('sw-timeout')); }, 3000);
        })
      ]).catch(function(){
        return caches.match(e.request).then(function(cached){
          return cached || new Response(
            '<!doctype html><html><body style="font-family:sans-serif;padding:2em">' +
            '<h2>Option Panda is offline</h2>' +
            '<p>Reconnect and reload to continue.</p></body></html>',
            { headers: { 'Content-Type': 'text/html' } }
          );
        });
      })
    );
    return;
  }
  // Skip API requests (Tradier, FMP, etc.) — never cache
  if (url.indexOf('/v1/') >= 0 || url.indexOf('/api/') >= 0 ||
      url.indexOf('tradier.com') >= 0 || url.indexOf('financialmodelingprep') >= 0 ||
      url.indexOf('workers.dev') >= 0) return;
  // Cache-first for static assets we pre-cached
  if (STATIC_ASSETS.some(function(a){ return url.indexOf(a.replace('./','')) >= 0; })){
    e.respondWith(
      caches.match(e.request).then(function(cached){
        return cached || fetch(e.request);
      })
    );
  }
});

// ── PUSH EVENT — fired when a server-side push notification arrives.
// Payload format: { title: '…', body: '…', tag: '…', url: '…', data: {…} }
// OneSignal, FCM, and any custom backend hit this same handler.
self.addEventListener('push', function(e){
  var data = {};
  try { data = e.data ? e.data.json() : {}; } catch(_){
    try { data = { body: e.data ? e.data.text() : '' }; } catch(__){}
  }
  // OneSignal wraps payloads in {custom:{a:{...}}} — flatten if present
  if (data.custom && data.custom.a) data = Object.assign({}, data, data.custom.a);
  var title = data.title || data.heading || 'Option Panda';
  var body  = data.body  || data.alert    || '';
  var opts = {
    body: body,
    tag: data.tag || ('opt-panda-push-'+Date.now()),
    icon: data.icon || './assets/icon-192.png',
    badge: data.badge || './assets/icon-192.png',
    data: { url: data.url || './index.html' },
    requireInteraction: !!data.requireInteraction,
    silent: !!data.silent,
    vibrate: data.silent ? undefined : [120, 60, 120]
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

// ── NOTIFICATION CLICK — focus existing tab or open the URL from payload.
self.addEventListener('notificationclick', function(e){
  e.notification.close();
  var targetUrl = (e.notification.data && e.notification.data.url) || './index.html';
  e.waitUntil(
    self.clients.matchAll({type:'window', includeUncontrolled:true}).then(function(clients){
      for (var i=0; i<clients.length; i++){
        var c = clients[i];
        if (c.url.indexOf('alexreed122287.github.io/scanner') >= 0 && 'focus' in c){
          if (c.navigate && targetUrl !== './index.html') {
            try { c.navigate(targetUrl); } catch(_){}
          }
          return c.focus();
        }
      }
      if (self.clients.openWindow){
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});

// ── MESSAGE — page can post {action:'skipWaiting'} to force activation
self.addEventListener('message', function(e){
  if (e.data && e.data.action === 'skipWaiting') self.skipWaiting();
});
