// Klassio — ce qui se passe quand deux personnes agissent EN MÊME TEMPS.
//
//   k6 run tools/k6/concurrence.js
//
// Les défauts de concurrence ne se voient jamais en cliquant : ils demandent
// deux requêtes qui se croisent entre le SELECT et le COMMIT. Chaque épreuve
// ici part donc de requêtes SIMULTANÉES (http.batch, un seul aller-retour
// réseau pour N appels), puis relit l'état pour juger — jamais le seul statut.
//
// Quatre courses, choisies parce qu'elles coûtent cher :
//   1. deux acceptations du même lien d'invitation → un seul compte ;
//   2. deux clics sur « Payer » → un seul paiement (clé d'idempotence) ;
//   3. deux guichets encaissant le même frais → jamais plus que la dette ;
//   4. deux confirmations du même paiement → un seul reçu, un seul numéro.

import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

const surpaiements = new Counter('klassio_surpaiements');
const doublons = new Counter('klassio_doublons_crees');
const cinqCents = new Counter('klassio_erreurs_500');

export const options = {
  scenarios: { concurrence: { executor: 'shared-iterations', vus: 1, iterations: 1 } },
  thresholds: {
    klassio_surpaiements: ['count==0'],
    klassio_doublons_crees: ['count==0'],
    klassio_erreurs_500: ['count==0'],
    checks: ['rate==1.00'],
  },
};

const jsonH = (h) => Object.assign({ 'Content-Type': 'application/json' }, h);
const poster = (chemin, corps, h, nom) => {
  const r = http.post(`${BASE}${chemin}`, JSON.stringify(corps), { headers: jsonH(h), tags: { name: nom } });
  if (r.status >= 500) cinqCents.add(1);
  return r;
};
// N requêtes identiques lancées ensemble. C'est le cœur du scénario : lancées
// l'une après l'autre, aucune de ces courses ne se produit.
const enMemeTemps = (n, chemin, corps, h, nom) => {
  const lot = [];
  for (let i = 0; i < n; i += 1) {
    lot.push(['POST', `${BASE}${chemin}`, JSON.stringify(corps), { headers: jsonH(h), tags: { name: nom } }]);
  }
  const reponses = http.batch(lot);
  for (const r of reponses) if (r.status >= 500) cinqCents.add(1);
  return reponses;
};

export default function () {
  const alpha = etablissement('alpha');
  const hDir = connexion(alpha.comptes.directeur);
  const marque = Date.now();

  // === C1 — deux acceptations simultanées du même lien ====================
  // Défaut P0-b du 14/09 : l'invitation n'était marquée « acceptée » qu'en fin
  // de route. Deux acceptations lisaient toutes deux `pending` → DEUX comptes
  // parent rattachés au même enfant. Un lien transféré par WhatsApp suffisait.
  const inv = poster('/api/invitations', {
    role: 'parent', student_ids: [alpha.exemples.eleve_id],
  }, hDir, 'invitation-creer');
  check(inv, { 'C1 invitation créée pour l’épreuve': (r) => r.status === 201 });
  if (inv.status === 201) {
    const jeton = inv.json('token');
    const corps = {
      token: jeton, name: 'Parent Course', email: `course-${marque}@concurrence.test`,
      password: 'Concurrence2026!',
    };
    const reponses = enMemeTemps(4, '/api/invitations/accept', corps, {}, 'accept-simultane');
    const gagnants = reponses.filter((r) => r.status === 200 || r.status === 201).length;
    const etrangles = reponses.filter((r) => r.status === 429).length;
    if (gagnants > 1) doublons.add(gagnants - 1);

    // UN 429 INVALIDE L'ÉPREUVE, IL NE LA FAIT PAS PASSER.
    //
    // La limitation anti-force-brute (5 tentatives / 5 min par adresse IP)
    // protège légitimement l'acceptation d'une invitation : un jeton est un
    // secret, et sans plafond on l'énumère. Mais si elle écarte trois des
    // quatre requêtes, « une seule réussit » devient vrai SANS que la prise
    // atomique ait été éprouvée — un vert qui ne prouve rien.
    //
    // On exige donc que les perdants aient perdu POUR UNE RAISON MÉTIER
    // (404/409 : le lien était déjà consommé), pas parce qu'on les a comptés.
    const perdantsMetier = reponses.filter((r) => r.status === 404 || r.status === 409 || r.status === 400).length;
    check(null, {
      'C1 l’épreuve n’est pas faussée par la limitation anti-abus (aucun 429)':
        () => etrangles === 0,
      'C1 quatre acceptations simultanées : une seule réussit': () => gagnants === 1,
      'C1 les trois perdants sont refusés pour une raison métier, pas étranglés':
        () => perdantsMetier === reponses.length - gagnants,
      'C1 les perdants repartent sans 500': () =>
        reponses.every((r) => r.status < 500),
    });
    // La preuve par l'état, pas par le statut : le lien est consommé.
    const rejeu = poster('/api/invitations/accept', {
      token: jeton, name: 'Parent Tardif', email: `tardif-${marque}@concurrence.test`,
      password: 'Concurrence2026!',
    }, {}, 'accept-apres-coup');
    check(rejeu, { 'C1 le lien reste consommé après la course': (r) => r.status >= 400 });
  }

  // === C2 — deux clics sur « Payer » =====================================
  // Même clé d'idempotence : UNIQUE(tenant_id, idempotency_key) doit faire
  // qu'un seul paiement existe, et que les deux réponses désignent le MÊME.
  const situation = lire(`/api/students/${alpha.exemples.eleve_id}/financial-summary`, hDir, 'finance');
  check(situation, {
    'C2 situation financière lisible (sans quoi rien n’est mesuré)':
      (r) => r.status === 200 && typeof r.json('total_paid') === 'number',
  });
  const lignes = (situation.status === 200 && situation.json('obligations')) || [];
  const ouverte = lignes.find((l) => l.remaining > 0);
  check(null, { 'C2 un frais non soldé est disponible': () => !!ouverte });

  if (ouverte) {
    const cle = `concurrence-double-clic-${marque}`;
    const payeAvant = situation.json('total_paid');
    const reponses = enMemeTemps(5, '/api/payments', {
      obligation_id: ouverte.obligation_id, amount: 1, method: 'cash', idempotency_key: cle,
    }, hDir, 'paiement-double-clic');

    const ids = [];
    for (const r of reponses) {
      if (r.status === 200 || r.status === 201) {
        try { ids.push(r.json('id') || r.json('payment_id')); } catch (e) { /* ignoré */ }
      }
    }
    const uniques = ids.filter((v, i) => v !== undefined && ids.indexOf(v) === i);
    const apres = lire(`/api/students/${alpha.exemples.eleve_id}/financial-summary`, hDir, 'finance-apres');
    const payeApres = apres.json('total_paid');
    const delta = Math.round((payeApres - payeAvant) * 100);
    if (delta > 100) surpaiements.add(1);

    check(null, {
      'C2 cinq clics, un seul paiement identifié': () => uniques.length === 1,
      'C2 cinq clics, un seul dollar encaissé': () => delta === 100,
    });

    // === C3 — deux guichets encaissent le même frais ====================
    // Clés DIFFÉRENTES : l'idempotence ne protège plus. Seule la validation
    // du montant côté serveur empêche d'encaisser plus que la dette — c'est
    // le défaut trouvé le 17/09 (reçu de 999 999 $) vu sous l'angle course.
    const apres2 = lire(`/api/students/${alpha.exemples.eleve_id}/financial-summary`, hDir, 'finance-c3');
    const ligne2 = (apres2.json('obligations') || []).find((l) => l.obligation_id === ouverte.obligation_id);
    const reste = ligne2 ? ligne2.remaining : 0;
    check(null, { 'C3 il reste quelque chose à devoir': () => reste > 0 });
    if (reste > 0) {
      const payeAvant3 = apres2.json('total_paid');
      // Six guichets tentent chacun de solder la TOTALITÉ du reste, ensemble.
      const lot = [];
      for (let i = 0; i < 6; i += 1) {
        lot.push(['POST', `${BASE}/api/payments`, JSON.stringify({
          obligation_id: ouverte.obligation_id, amount: reste, method: 'cash',
          idempotency_key: `concurrence-guichet-${marque}-${i}`,
        }), { headers: jsonH(hDir), tags: { name: 'paiement-guichets' } }]);
      }
      const r6 = http.batch(lot);
      for (const r of r6) if (r.status >= 500) cinqCents.add(1);

      const fin = lire(`/api/students/${alpha.exemples.eleve_id}/financial-summary`, hDir, 'finance-fin');
      const ligneFin = (fin.json('obligations') || []).find((l) => l.obligation_id === ouverte.obligation_id);
      const encaisse = Math.round((fin.json('total_paid') - payeAvant3) * 100);
      const attendu = Math.round(reste * 100);
      if (encaisse > attendu) surpaiements.add(1);

      check(null, {
        'C3 six guichets simultanés : jamais plus que la dette':
          () => encaisse <= attendu,
        'C3 le frais est soldé, pas dépassé':
          () => ligneFin && ligneFin.remaining >= 0 && ligneFin.paid <= ligneFin.amount,
        'C3 aucun guichet ne reçoit de 500': () => r6.every((r) => r.status < 500),
      });
    }
  }

  // === C4 — deux confirmations du même paiement ==========================
  // UNIQUE(payment_id) sur les reçus : la double confirmation doit rendre le
  // MÊME numéro, jamais en créer un second.
  const situation4 = lire(`/api/students/${alpha.exemples.eleve_id}/financial-summary`, hDir, 'finance-c4');
  const ligne4 = (situation4.json('obligations') || []).find((l) => l.remaining > 0)
    || (situation4.json('obligations') || [])[0];
  if (ligne4) {
    const p = poster('/api/payments', {
      obligation_id: ligne4.obligation_id, amount: 1, method: 'mobile_money',
      idempotency_key: `concurrence-confirm-${marque}`,
    }, hDir, 'paiement-mm');
    if (p.status === 200 || p.status === 201) {
      const pid = p.json('id') || p.json('payment_id');
      const reponses = enMemeTemps(4, `/api/payments/${pid}/confirm`, { provider_reference: 'MM-COURSE' }, hDir, 'confirm-simultane');
      const numeros = [];
      for (const r of reponses) {
        if (r.status === 200) { try { numeros.push(r.json('receipt_number')); } catch (e) { /* ignoré */ } }
      }
      const distincts = numeros.filter((v, i) => v && numeros.indexOf(v) === i);
      if (distincts.length > 1) doublons.add(distincts.length - 1);
      check(null, {
        'C4 quatre confirmations simultanées : au moins une aboutit': () => numeros.length >= 1,
        'C4 un seul numéro de reçu, jamais deux': () => distincts.length === 1,
        'C4 aucune confirmation ne finit en 500': () => reponses.every((r) => r.status < 500),
      });
    }
  }
}
