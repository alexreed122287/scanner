// OneSignal SDK service worker shim — required by OneSignal's Web Push SDK
// to be served from the scope root. We just re-import their hosted SDK
// rather than maintaining our own copy, so updates propagate automatically.
// Co-exists with sw.js (the Option Panda app SW). OneSignal registers ITS
// service worker against this file at /scanner/OneSignalSDKWorker.js;
// sw.js handles the rest of the app's offline + push routing.
importScripts('https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js');
