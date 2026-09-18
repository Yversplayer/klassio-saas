// Klassio — matrice de permissions, vérifiée PAR APPEL DIRECT.
//
//   k6 run tools/k6/rbac.js
//
// Un bouton caché ne protège rien. Ce scénario ignore complètement l'interface
// et appelle les routes sensibles avec chaque rôle, exactement comme le ferait
// quelqu'un qui connaît l'URL. La seule réponse acceptable pour un rôle non
// autorisé est un refus franc — 401, 403 ou 404 — jamais un 200.
//
// Un 500 est également un échec : une route sensible qui plante sous un rôle
// inattendu est une route qui n'a pas été pensée pour lui.

import { check } from 'k6';
import http from 'k6/http';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

const acces = new Counter('klassio_acces_non_autorises');
const plantages = new Counter('klassio_500_sur_route_sensible');

export const options = {
  scenarios: { matrice: { executor: 'shared-iterations', vus: 1, iterations: 1 } },
  thresholds: {
    klassio_acces_non_autorises: ['count==0'],
    klassio_500_sur_route_sensible: ['count==0'],
    checks: ['rate==1.00'],
  },
};

// [chemin, méthode, rôles AUTORISÉS]. Tout rôle absent doit être refusé.
const MATRICE = [
  ['/api/reports/summary',        'GET',  ['directeur']],
  ['/api/receipts',               'GET',  ['directeur', 'parent']],
  ['/api/catalog-items',          'GET',  ['directeur', 'parent']],
  ['/api/invitations',            'GET',  ['directeur']],
  ['/api/invitations',            'POST', ['directeur']],
  ['/api/team',                   'GET',  ['directeur', 'discipline']],
  ['/api/discipline/overview',    'GET',  ['directeur', 'discipline']],
  ['/api/discipline/today',       'GET',  ['directeur', 'discipline']],
  ['/api/subscription',           'GET',  ['directeur']],
  // GET /api/settings est VOLONTAIREMENT ouvert à tous : chaque rôle a besoin de
  // la devise et du nom de l'école pour s'afficher. Ce qui compte n'est donc pas
  // le code HTTP mais le CONTENU — vérifié séparément plus bas.
  ['/api/settings',               'PUT',  ['directeur']],
  ['/api/platform/contact-requests', 'GET', []],   // administration Klassio seulement
];

export default function () {
  const alpha = etablissement('alpha');
  const jetons = {};
  for (const role of ['directeur', 'professeur', 'discipline', 'parent']) {
    jetons[role] = connexion(alpha.comptes[role]);
  }

  for (const [chemin, methode, autorises] of MATRICE) {
    for (const role of ['directeur', 'professeur', 'discipline', 'parent']) {
      const attendu = autorises.indexOf(role) !== -1;
      const entetes = Object.assign({ 'Content-Type': 'application/json' }, jetons[role]);
      const r = methode === 'GET' ? lire(chemin, jetons[role], chemin)
        : methode === 'PUT' ? http.put(`${BASE}${chemin}`, JSON.stringify({ currency: 'USD' }), { headers: entetes, tags: { name: chemin } })
        : http.post(`${BASE}${chemin}`, JSON.stringify({ role: 'professeur' }), { headers: entetes, tags: { name: chemin } });

      if (r.status >= 500) plantages.add(1);
      if (!attendu && r.status >= 200 && r.status < 300) acces.add(1);

      check(r, {
        [`${methode} ${chemin} — ${role} : ${attendu ? 'autorisé' : 'refusé'}`]: (x) =>
          attendu ? (x.status >= 200 && x.status < 300)
                  : (x.status === 401 || x.status === 403 || x.status === 404),
      });
    }
  }

  // Le contenu de /api/settings : un rôle non-Direction ne doit recevoir QUE ce
  // qui conditionne son affichage. Les réglages de l'établissement — politique
  // de diffusion des résultats, seuils de discipline, préfixe des identifiants,
  // coordonnées — ne sont pas de son ressort.
  const SECRETS_DIRECTION = ['results_policy', 'discipline_capital', 'code_prefix',
                             'branding', 'school_phone', 'school_email', 'school_address'];
  for (const role of ['professeur', 'discipline', 'parent']) {
    const r = lire('/api/settings', jetons[role], 'settings-contenu');
    let fuite = null;
    try {
      const corps = r.json();
      fuite = SECRETS_DIRECTION.filter((k) => corps[k] !== undefined)[0] || null;
    } catch (e) { fuite = 'illisible'; }
    if (fuite) acces.add(1);
    check(r, {
      [`GET /api/settings — ${role} : aucun réglage de Direction exposé`]: () => fuite === null,
    });
  }

  // Sans jeton du tout : aucune route privée ne doit s'ouvrir.
  for (const [chemin] of MATRICE) {
    const r = lire(chemin, {}, 'sans-jeton');
    if (r.status >= 200 && r.status < 300) acces.add(1);
    check(r, { [`${chemin} — sans authentification : refusé`]: (x) => x.status === 401 });
  }

  // Jeton fabriqué de toutes pièces.
  const faux = { Authorization: 'Bearer ' + 'f'.repeat(48) };
  const r = lire('/api/students', faux, 'jeton-invalide');
  if (r.status < 300) acces.add(1);
  check(r, { 'jeton inventé : refusé': (x) => x.status === 401 });
}
