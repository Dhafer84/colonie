// Service worker de la Colonie spatiale.
//
// Stratégie « réseau d'abord » pour l'interface : en ligne on a toujours la
// dernière version, hors ligne on affiche la copie en cache. L'API n'est jamais
// mise en cache (le serveur fait foi). Changer VERSION force le renouvellement.

const VERSION = "colonie-v1";
const COQUILLE = [
  "/",
  "/style.css",
  "/app.js",
  "/manifest.webmanifest",
  "/icones/icone.svg",
  "/icones/icone-192.png",
];

self.addEventListener("install", (evenement) => {
  evenement.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(COQUILLE)));
  self.skipWaiting();
});

self.addEventListener("activate", (evenement) => {
  evenement.waitUntil(
    caches.keys()
      .then((cles) => Promise.all(cles.filter((cle) => cle !== VERSION).map((cle) => caches.delete(cle))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (evenement) => {
  const requete = evenement.request;
  const url = new URL(requete.url);
  if (requete.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    return;
  }
  evenement.respondWith(
    fetch(requete)
      .then((reponse) => {
        if (reponse.ok) {
          const copie = reponse.clone();
          caches.open(VERSION).then((cache) => cache.put(requete, copie));
        }
        return reponse;
      })
      .catch(() => caches.match(requete, { ignoreSearch: true })
        .then((enCache) => enCache || caches.match("/"))),
  );
});
