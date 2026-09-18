// Klassio — briques communes aux scénarios de charge.
//
// Règle appliquée partout ici : un statut 200 ne prouve rien. Chaque check
// regarde le CONTENU de la réponse. Un serveur qui renvoie 200 avec une liste
// vide, ou avec les élèves d'un autre établissement, doit faire échouer le
// scénario — pas le faire passer.

import http from 'k6/http';
import { check, fail } from 'k6';

export const env = JSON.parse(open('./env.json'));
export const BASE = env.base_url;

export function etablissement(etiquette) {
  const e = env.etablissements.find((x) => x.etiquette === etiquette);
  if (!e) fail(`établissement « ${etiquette} » absent de env.json — relancez seed_charge.py`);
  return e;
}

// Ouvre une session réelle. Un jeton codé en dur ne testerait pas la connexion,
// qui est justement l'endroit où la limitation anti-force-brute peut mordre.
export function connexion(courriel) {
  const r = http.post(
    `${BASE}/api/auth/login`,
    JSON.stringify({ email: courriel, password: env.mot_de_passe }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } }
  );
  if (r.status !== 200) fail(`connexion refusée pour ${courriel} : ${r.status} ${r.body}`);
  return { Authorization: `Bearer ${r.json('token')}` };
}

export function lire(chemin, entetes, nom) {
  return http.get(`${BASE}${chemin}`, {
    headers: entetes,
    tags: { name: nom || chemin },
  });
}

// Vérifie qu'une réponse est bien une liste NON VIDE de la forme attendue.
// C'est la différence entre « le serveur répond » et « le serveur travaille ».
export function verifierListe(r, nom, champRequis) {
  return check(r, {
    [`${nom} : 200`]: (x) => x.status === 200,
    [`${nom} : liste non vide`]: (x) => {
      try { const c = x.json(); return Array.isArray(c) && c.length > 0; } catch (e) { return false; }
    },
    [`${nom} : champ « ${champRequis} » présent`]: (x) => {
      try { const c = x.json(); return Array.isArray(c) && c.length > 0 && c[0][champRequis] !== undefined; }
      catch (e) { return false; }
    },
  });
}

export function verifierObjet(r, nom, champsRequis) {
  return check(r, {
    [`${nom} : 200`]: (x) => x.status === 200,
    [`${nom} : champs attendus`]: (x) => {
      try { const c = x.json(); return champsRequis.every((k) => c[k] !== undefined); }
      catch (e) { return false; }
    },
  });
}
