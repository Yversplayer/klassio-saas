// Klassio — le Worker Cloudflare : les pages ici, l'API relayée vers Render.
//
// POURQUOI UN RELAIS ET PAS DEUX DOMAINES. Depuis le 29/09, Klassio vit sur
// une ORIGINE UNIQUE : pages et API sous le même nom. En production, `ui.js` et
// `contact.js` appellent `/api` sur le domaine de la page, et la CSP de chaque
// page dit `connect-src 'self'`. Servir les pages ici et l'API sur
// `*.onrender.com` aurait rouvert les trois murs que l'origine unique a fait
// tomber : CORS, CSP de 36 pages, adresse d'API à maintenir. Le Worker garde
// l'origine unique : le navigateur ne voit qu'un domaine.
//
// Ce que fait le Worker, et rien d'autre :
//   - /api/*        → relayé tel quel vers KLASSIO_API_ORIGIN (Render) ;
//   - /             → index.html ;
//   - tout le reste → les fichiers de `dist/` (liste blanche, construire.sh).
// Les en-têtes de cache et de sécurité reprennent ceux que Flask posait quand
// il servait les pages lui-même (backend/app.py), pour que rien ne change
// en passant de l'un à l'autre.

const ENTETES_SECURITE = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
};

// En-têtes qu'un navigateur ne doit jamais pouvoir poser lui-même : ils
// portent l'adresse du visiteur et la preuve que la requête vient du relais.
const ENTETES_DU_RELAIS = ["x-klassio-client-ip", "x-klassio-relais"];

async function relayerApi(requete, env, url) {
  if (!env.KLASSIO_API_ORIGIN) {
    return Response.json({ error: "Le serveur Klassio n'est pas encore configuré." }, { status: 503 });
  }
  const cible = new URL(url.pathname + url.search, env.KLASSIO_API_ORIGIN);
  const entetes = new Headers(requete.headers);
  for (const nom of ENTETES_DU_RELAIS) entetes.delete(nom);
  // Derrière un relais, le serveur voit l'adresse du relais, pas celle du
  // visiteur. On la transmet, avec un secret partagé : sans le secret, le
  // backend ne doit pas croire cet en-tête (n'importe qui pourrait l'écrire
  // en appelant Render directement).
  const ip = requete.headers.get("CF-Connecting-IP");
  if (ip && env.KLASSIO_RELAIS_SECRET) {
    entetes.set("X-Klassio-Client-IP", ip);
    entetes.set("X-Klassio-Relais", env.KLASSIO_RELAIS_SECRET);
  }
  return fetch(cible, {
    method: requete.method,
    headers: entetes,
    body: requete.method === "GET" || requete.method === "HEAD" ? undefined : requete.body,
    redirect: "manual",
  });
}

async function servirFichier(requete, env, url) {
  let demande = requete;
  if (url.pathname === "/") {
    demande = new Request(new URL("/index.html", url), requete);
  }
  const reponse = await env.ASSETS.fetch(demande);
  const finale = new Response(reponse.body, reponse);
  for (const [nom, valeur] of Object.entries(ENTETES_SECURITE)) finale.headers.set(nom, valeur);
  // Même règle que `mettre_en_cache_les_ressources` (backend/app.py) : une
  // ressource versionnée (`?v=`) ne change jamais — un an ; une ressource sans
  // version garde un jour ; les pages HTML ne sont jamais figées.
  if (reponse.status === 200 && url.pathname.startsWith("/assets/")) {
    finale.headers.set("Cache-Control", url.searchParams.get("v")
      ? "public, max-age=31536000, immutable"
      : "public, max-age=86400");
  }
  return finale;
}

// HTTPS OBLIGATOIRE. Constaté le 06/10/2026 : http://klassio….workers.dev
// répondait 200, page de connexion comprise — un mot de passe pouvait partir
// en clair jusqu'à Cloudflare. Une page demandée en HTTP est renvoyée vers
// HTTPS ; une écriture (POST, PUT…) n'est PAS redirigée mais refusée : la
// rediriger apprendrait au navigateur à renvoyer ses données, et celles-ci
// ont déjà voyagé en clair une fois.
function exigerHttps(requete, url) {
  if (url.protocol !== "http:") return null;
  if (requete.method === "GET" || requete.method === "HEAD") {
    url.protocol = "https:";
    return Response.redirect(url.toString(), 301);
  }
  return Response.json({ error: "Klassio n'accepte que HTTPS." }, { status: 403 });
}

export default {
  async fetch(requete, env) {
    const url = new URL(requete.url);
    const refus = exigerHttps(requete, url);
    if (refus) return refus;
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      return relayerApi(requete, env, url);
    }
    return servirFichier(requete, env, url);
  },
};
