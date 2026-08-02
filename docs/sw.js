/* Cache minimal : l'app s'ouvre hors-ligne avec les dernières offres connues. */
const CACHE = 'veille-v1';
const COQUILLE = ['./', './index.html', './manifest.webmanifest', './icone.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(COQUILLE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  // Réseau d'abord pour les offres (fraîcheur), cache en secours si hors-ligne.
  e.respondWith(
    fetch(e.request)
      .then(r => {
        const copie = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, copie));
        return r;
      })
      .catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});
