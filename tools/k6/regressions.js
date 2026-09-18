// Klassio — les défauts DÉJÀ CORRIGÉS, rejoués un par un.
//
//   k6 run tools/k6/regressions.js
//
// Ce scénario ne cherche pas de nouveaux bugs : il vérifie que les anciens ne
// sont pas revenus. Chaque bloc porte le nom du défaut tel qu'il est consigné
// dans REPRISE.md, pour qu'un échec ici renvoie directement à son histoire.
//
// Ne sont repris ICI que les défauts qu'aucun autre scénario ne couvre déjà :
//   - P0-a (notes non proclamées vues du parent) et le filtre `is_current`
//     sont dans academique.js ;
//   - la double consommation d'une invitation est dans invitations.js ;
//   - les reçus manquants sous concurrence sont dans recus.js ;
//   - l'idempotence des paiements est dans finance.js.
// Dupliquer une couverture n'ajoute pas de preuve, seulement du temps.

import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

// Un 500 n'est jamais une réponse acceptable : c'est un défaut, pas un refus.
const cinqCents = new Counter('klassio_erreurs_500');

export const options = {
  scenarios: { regressions: { executor: 'shared-iterations', vus: 1, iterations: 1 } },
  thresholds: {
    klassio_erreurs_500: ['count==0'],
    checks: ['rate==1.00'],
  },
};

const poster = (chemin, corps, h, nom) => {
  const r = http.post(`${BASE}${chemin}`, typeof corps === 'string' ? corps : JSON.stringify(corps),
    { headers: Object.assign({ 'Content-Type': 'application/json' }, h), tags: { name: nom || chemin } });
  if (r.status >= 500) cinqCents.add(1);
  return r;
};

export default function () {
  const alpha = etablissement('alpha');
  const beta = etablissement('beta');
  const hDir = connexion(alpha.comptes.directeur);
  const hProf = connexion(alpha.comptes.professeur);
  const hDD = connexion(alpha.comptes.discipline);
  const hParent = connexion(alpha.comptes.parent);
  const hDirBeta = connexion(beta.comptes.directeur);

  // === R1 — « /reopenings répondait 200 [] à une autre école » ============
  // Corrigé le 17/09. Le piège : une liste vide RESSEMBLE à une absence de
  // fuite. Ce n'en est pas une — elle confirme que la période existe.
  const periodes = lire('/api/periods', hDir, 'periods').json();
  const listePeriodes = (periodes && periodes.periods) || [];
  if (listePeriodes.length > 0) {
    const cible = listePeriodes[0];
    const r = lire(`/api/periods/${cible.id}/reopenings`, hDirBeta, 'reopenings-croise');
    if (r.status >= 500) cinqCents.add(1);
    check(r, {
      'R1 période d’un autre établissement : 404, pas 200 []': () => r.status === 404,
    });
  }

  // === R2 — « POST /api/invitations renvoyait 500 sur un corps non-objet » =
  // `data.get` sur une chaîne. Le correctif (validation.json_object) couvre
  // 61 lectures de corps : on balaie donc plusieurs routes, pas une seule.
  const CORPS_TORDUS = ['"je suis une chaîne"', '[1,2,3]', '42', 'null', '"{}"'];
  const ROUTES_POST = [
    '/api/invitations', '/api/obligations', '/api/payments',
    '/api/catalog-items', '/api/obligations/schedule', '/api/students',
  ];
  let malformesOk = 0, malformesTotal = 0;
  for (const chemin of ROUTES_POST) {
    for (const corps of CORPS_TORDUS) {
      const r = poster(chemin, corps, hDir, 'corps-tordu');
      malformesTotal += 1;
      // 400 (corps invalide) ou 403/404 (refus métier) : tout sauf un 500.
      if (r.status < 500) malformesOk += 1;
    }
  }
  check(null, {
    [`R2 corps JSON non-objet : aucun 500 sur ${malformesTotal} tentatives`]:
      () => malformesOk === malformesTotal,
  });

  // === R3 — « /api/students/:id/bulletin ignorait only_published » ========
  // Le volet inter-établissements : la route la plus riche du produit ne doit
  // rien dire d'un élève qui n'est pas de chez vous.
  const bulletinCroise = lire(`/api/students/${beta.exemples.eleve_id}/bulletin`, hDir, 'bulletin-croise');
  if (bulletinCroise.status >= 500) cinqCents.add(1);
  check(bulletinCroise, {
    'R3 bulletin d’un élève d’une autre école : 404': (r) => r.status === 404,
    'R3 bulletin croisé : le nom de l’élève n’apparaît pas': (r) =>
      r.body.indexOf(beta.exemples.eleve_nom) === -1,
  });

  // === R4 — « la somme des tranches n'était vérifiée que côté client » ====
  // Trois tranches de 100 sur un frais de 1 000 : la dette devenait 300.
  // On vérifie DEUX choses : le refus, et qu'aucune tranche n'a été écrite.
  const article = poster('/api/catalog-items', {
    name: `Régression tranches ${Date.now()}`, amount: 1000, currency: 'USD',
  }, hDir, 'catalog-create');
  const anneeId = periodes && periodes.academic_year && periodes.academic_year.id;
  const eleveId = alpha.exemples.eleve_id;
  if (article.status === 201 && anneeId) {
    const articleId = article.json('id');
    // Garde-fou anti-faux-positif : si cette route ne répond pas, les
    // comparaisons « avant/après » vaudraient 0 === 0 et passeraient au vert
    // sans rien avoir mesuré. Une URL fautive doit faire ÉCHOUER le scénario.
    const sonde = lire(`/api/students/${eleveId}/financial-summary`, hDir, 'finance-sonde');
    check(sonde, {
      'R4/R6 la situation financière de l’élève est lisible (sans quoi rien n’est mesuré)':
        (r) => r.status === 200 && typeof r.json('total_due') === 'number',
    });
    const avant = lire(`/api/students/${eleveId}/financial-summary`, hDir, 'finance-avant');
    const detteAvant = (avant.status === 200 && avant.json('total_due')) || 0;

    const bancal = poster('/api/obligations/schedule', {
      student_id: eleveId, catalog_item_id: articleId, academic_year_id: anneeId,
      total: 1000,
      installments: [{ amount: 100 }, { amount: 100 }, { amount: 100 }],
    }, hDir, 'schedule-bancal');

    const apres = lire(`/api/students/${eleveId}/financial-summary`, hDir, 'finance-apres');
    const detteApres = (apres.status === 200 && apres.json('total_due')) || 0;

    check(bancal, {
      'R4 échéancier dont la somme ne tombe pas juste : refusé': (r) => r.status === 400,
      'R4 refus motivé (pas un 500 muet)': (r) => {
        try { return typeof r.json('error') === 'string' && r.json('error').length > 10; }
        catch (e) { return false; }
      },
    });
    check(null, {
      'R4 tout ou rien : aucune tranche écrite après le refus': () => detteApres === detteAvant,
    });

    // Le pendant positif : un échéancier juste passe, et la dette bouge de 1 000.
    const juste = poster('/api/obligations/schedule', {
      student_id: eleveId, catalog_item_id: articleId, academic_year_id: anneeId,
      total: 1000,
      installments: [{ amount: 400 }, { amount: 300 }, { amount: 300 }],
    }, hDir, 'schedule-juste');
    const apres2 = lire(`/api/students/${eleveId}/financial-summary`, hDir, 'finance-apres2');
    const detteApres2 = (apres2.status === 200 && apres2.json('total_due')) || 0;
    check(juste, { 'R4 échéancier juste : accepté': (r) => r.status === 201 || r.status === 200 });
    check(null, {
      'R4 échéancier juste : la dette augmente exactement de 1 000':
        () => Math.round((detteApres2 - detteApres) * 100) === 100000,
    });
  }

  // === R5 — « /api/catalog-items n'avait aucune vérification de permission » =
  // Le professeur et le DD y lisaient la grille tarifaire complète.
  const lectures = [
    ['directeur', hDir, true], ['parent', hParent, true],
    ['professeur', hProf, false], ['discipline', hDD, false],
  ];
  for (const [qui, h, autorise] of lectures) {
    const r = lire('/api/catalog-items', h, 'catalog-read');
    if (r.status >= 500) cinqCents.add(1);
    check(r, {
      [`R5 catalogue — ${qui} : ${autorise ? 'lit' : 'ne lit pas'}`]: () =>
        autorise ? r.status === 200 : r.status === 403,
    });
  }
  // Et personne d'autre que la Direction n'y écrit un prix.
  check(poster('/api/catalog-items', { name: 'Interdit', amount: 1 }, hProf, 'catalog-write-prof'), {
    'R5 catalogue — le professeur n’y crée pas d’article': (r) => r.status === 403,
  });

  // === R6 — « le montant du paiement venait du client » ===================
  // Trouvé le 17/09 : un parent qui gonflait le JSON obtenait un reçu de
  // 999 999 $. Le serveur borne désormais au reste dû.
  const situation = lire(`/api/students/${eleveId}/financial-summary`, hDir, 'finance-r6');
  const lignes = (situation.status === 200 && situation.json('obligations')) || [];
  const ouverte = lignes.find((l) => l.remaining > 0);
  check(null, {
    'R6 un frais non soldé existe pour éprouver le plafond de montant': () => !!ouverte,
  });
  if (ouverte) {
    const gonfle = poster('/api/payments', {
      obligation_id: ouverte.obligation_id, amount: 999999, method: 'cash',
      idempotency_key: `regression-gonfle-${Date.now()}`,
    }, hDir, 'paiement-gonfle');
    const apresGonflage = lire(`/api/students/${eleveId}/financial-summary`, hDir, 'finance-r6-apres');
    const payeApres = (apresGonflage.status === 200 && apresGonflage.json('total_paid')) || 0;
    const payeAvant = situation.json('total_paid') || 0;
    check(gonfle, {
      'R6 paiement supérieur au reste dû : refusé': (r) => r.status === 400,
    });
    check(null, {
      'R6 aucun encaissement fantôme : le total payé n’a pas bougé':
        () => Math.round(payeApres * 100) === Math.round(payeAvant * 100),
    });
  }
}
