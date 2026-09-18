// Klassio — intégrité des reçus sous concurrence.
//
//   k6 run tools/k6/recus.js
//
// RÉGRESSION VERROUILLÉE ICI (campagne du 17/09).
//
// `next_receipt_number` calcule « max + 1 ». Entre le SELECT et le COMMIT, un
// autre encaissement peut viser le même numéro. Avec cinq essais seulement, sur
// 1 067 paiements concurrents, UN a épuisé son budget : le paiement était déjà
// CONFIRMÉ et inscrit au grand livre — l'argent était juste — mais la requête
// finissait en **500**. Le guichetier lisait « échec » sur un encaissement
// réussi, et recommençait.
//
// Deux invariants, tous deux non négociables :
//   1. AUCUN 5xx sur /api/payments, quelle que soit la concurrence ;
//   2. AUCUN paiement confirmé sans son reçu.
//
// Le second se vérifie à la fin, en relisant les reçus par le serveur : c'est
// l'état réel qui compte, pas ce que la réponse HTTP a raconté.

import http from 'k6/http';
import { check, fail } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

const erreursServeur = new Counter('klassio_erreurs_500');
const confirmesSansRecu = new Counter('klassio_confirmes_sans_recu');
const confirmes = new Counter('klassio_paiements_confirmes');

export const options = {
  scenarios: {
    // Volontairement agressif : c'est la contention qui révèle le défaut.
    guichets: { executor: 'constant-vus', vus: 12, duration: '30s' },
  },
  thresholds: {
    klassio_erreurs_500: ['count==0'],
    klassio_confirmes_sans_recu: ['count==0'],
    checks: ['rate>0.99'],
  },
};

export function setup() {
  const beta = etablissement('beta');
  const h = connexion(beta.comptes.directeur);
  const eleves = lire('/api/students', h, 'students').json()
    .filter((e) => (e.balance || 0) > 60).slice(0, 60).map((e) => e.id);
  if (!eleves.length) fail('aucun élève avec solde — relancez seed_charge.py');

  const obligations = [];
  for (const id of eleves) {
    const f = lire(`/api/students/${id}/financial-summary`, h, 'finance-eleve');
    if (f.status !== 200) continue;
    for (const o of f.json('obligations') || []) {
      if (o.remaining > 60) obligations.push(o.obligation_id);
    }
  }
  if (!obligations.length) fail('aucune obligation avec reste suffisant');
  return { h, obligations };
}

export default function (d) {
  const ob = d.obligations[Math.floor(Math.random() * d.obligations.length)];
  const r = http.post(`${BASE}/api/payments`, JSON.stringify({
    obligation_id: ob, amount: 1, method: 'cash',
    idempotency_key: `recu-${__VU}-${__ITER}-${Date.now()}`,
  }), {
    headers: Object.assign({ 'Content-Type': 'application/json' }, d.h),
    tags: { name: 'payment' },
  });

  if (r.status >= 500) erreursServeur.add(1);

  check(r, {
    'aucune erreur serveur sur un encaissement': (x) => x.status < 500,
    // Un 400 « dette soldée » reste correct ; un 500 ne l'est jamais.
    'réponse exploitable': (x) => [201, 200, 409, 400].indexOf(x.status) !== -1,
  });

  if (r.status === 201 && r.json('status') === 'CONFIRMED') {
    confirmes.add(1);
    // Le reçu doit accompagner le paiement, pas arriver plus tard.
    check(r, {
      'un paiement confirmé porte son numéro de reçu': (x) => !!x.json('receipt_number'),
    });
    if (!r.json('receipt_number')) confirmesSansRecu.add(1);
  }
}

export function teardown(d) {
  // Contrôle final sur l'ÉTAT RÉEL, relu par le serveur : la réponse HTTP a pu
  // mentir, la base non.
  const recus = lire('/api/receipts?q=', d.h, 'receipts');
  console.log(`Reçus lisibles par l'établissement : ${(recus.json() || []).length}`);
}
