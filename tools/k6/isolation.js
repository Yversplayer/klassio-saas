// Klassio — isolation entre établissements SOUS CHARGE.
//
//   k6 run tools/k6/isolation.js
//
// Les tests unitaires vérifient l'isolation au repos. Ce scénario la vérifie
// pendant que deux établissements travaillent simultanément : c'est là que les
// fuites apparaissent — état partagé entre threads, connexion réutilisée avec
// le mauvais contexte, cache global. Une seule fuite fait échouer le run.

import { group, check, fail } from 'k6';
import { Counter } from 'k6/metrics';
import { etablissement, connexion, lire } from './commun.js';

const fuites = new Counter('klassio_fuites_inter_etablissements');

export const options = {
  scenarios: {
    alpha_travaille: { executor: 'constant-vus', vus: 10, duration: '1m', exec: 'cotéAlpha' },
    beta_travaille: { executor: 'constant-vus', vus: 10, duration: '1m', exec: 'cotéBeta' },
  },
  thresholds: {
    klassio_fuites_inter_etablissements: ['count==0'],  // non négociable
    checks: ['rate==1.00'],
    http_req_failed: ['rate<0.01'],
  },
};

export function setup() {
  const a = etablissement('alpha');
  const b = etablissement('beta');
  return {
    a, b,
    hA: connexion(a.comptes.directeur),
    hB: connexion(b.comptes.directeur),
    hParentB: connexion(b.comptes.parent),
  };
}

function verifierAucuneFuite(d, entetes, cible, qui) {
  // L'identifiant d'un élève de l'AUTRE établissement, présenté ici.
  const r = lire(`/api/students/${cible.exemples.eleve_id}`, entetes, 'dossier-croise');
  const fuite = r.status === 200;
  if (fuite) fuites.add(1);
  check(r, { [`${qui} : dossier d’un autre établissement refusé`]: () => !fuite });

  const r2 = lire(`/api/classes/${cible.exemples.class_id}/students`, entetes, 'classe-croisee');
  const fuite2 = r2.status === 200;
  if (fuite2) fuites.add(1);
  check(r2, { [`${qui} : classe d’un autre établissement refusée`]: () => !fuite2 });

  // Et la recherche, qui est le chemin le plus facile à oublier de filtrer.
  const r3 = lire(`/api/students?q=${encodeURIComponent(cible.exemples.eleve_nom)}`,
                  entetes, 'recherche-croisee');
  if (r3.status === 200) {
    const noms = r3.json().map((s) => s.last_name);
    const fuite3 = noms.indexOf(cible.exemples.eleve_nom) !== -1;
    if (fuite3) fuites.add(1);
    check(r3, { [`${qui} : recherche ne traverse pas les établissements`]: () => !fuite3 });
  }
}

export function cotéAlpha(d) {
  group('Alpha travaille, et ne voit jamais Beta', () => {
    const mien = lire('/api/students', d.hA, 'students');
    check(mien, { 'alpha : voit ses propres élèves': (r) => r.status === 200 && r.json().length > 0 });
    verifierAucuneFuite(d, d.hA, d.b, 'directeur alpha');
  });
}

export function cotéBeta(d) {
  group('Beta travaille, et ne voit jamais Alpha', () => {
    const mien = lire('/api/students', d.hB, 'students');
    check(mien, { 'beta : voit ses propres élèves': (r) => r.status === 200 && r.json().length > 0 });
    verifierAucuneFuite(d, d.hB, d.a, 'directeur beta');
    // Le rôle le plus étroit : un parent de Beta face aux données d'Alpha.
    verifierAucuneFuite(d, d.hParentB, d.a, 'parent beta');
  });
}
