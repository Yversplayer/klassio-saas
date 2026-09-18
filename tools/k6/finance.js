// Klassio — intégrité financière sous concurrence.
//
//   k6 run tools/k6/finance.js
//
// Le scénario qui compte vraiment : plusieurs guichets enregistrent des
// paiements en même temps, et certains rejouent la MÊME clé d'idempotence
// (double clic, réseau qui bégaie, agent qui recommence). À la fin, la somme
// encaissée doit correspondre exactement aux paiements distincts — ni un franc
// de plus, ni un de moins.
//
// C'est le seul scénario de charge qui écrit. Il vise l'établissement « beta »
// pour laisser « alpha » aux scénarios de lecture.

import http from 'k6/http';
import { check, fail } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

const paiementsAcceptes = new Counter('klassio_paiements_acceptes');
const rejeuxRefuses = new Counter('klassio_rejeux_refuses');
const doublesComptages = new Counter('klassio_doubles_comptages');
// Depuis l'audit du 17/09, le serveur REFUSE un montant supérieur au reste dû.
// Ce refus est le comportement voulu : il empêche un reçu officiel faux et une
// comptabilité fausse. Le scénario vide les obligations à force de payer, et
// les tentatives suivantes tombent donc en 400 — ce n'est pas une panne, c'est
// la garde qui fonctionne. On la compte séparément plutôt que de la confondre
// avec un échec, sinon le vrai signal (double comptage) serait noyé.
const refusMontant = new Counter('klassio_refus_montant_legitimes');

export const options = {
  scenarios: {
    guichets: { executor: 'constant-vus', vus: 8, duration: '45s' },
  },
  thresholds: {
    klassio_doubles_comptages: ['count==0'],   // non négociable
    // `http_req_failed` n'est pas un seuil utile ici : les 409 d'idempotence ET
    // les 400 « dette déjà soldée » sont des réponses CORRECTES. Un taux
    // d'erreur HTTP élevé ne dit donc rien sur la santé du système — seules les
    // assertions métier ci-dessous comptent.
    checks: ['rate>0.99'],
  },
};

export function setup() {
  const beta = etablissement('beta');
  const h = connexion(beta.comptes.directeur);

  // On travaille sur un lot d'élèves ayant encore un solde : payer une dette
  // déjà soldée ne prouverait rien.
  const eleves = lire('/api/students', h, 'students').json()
    .filter((e) => (e.balance || 0) > 20)
    .slice(0, 40)
    .map((e) => e.id);
  if (!eleves.length) fail('aucun élève avec solde restant — relancez seed_charge.py');

  const obligations = [];
  for (const id of eleves) {
    const f = lire(`/api/students/${id}/financial-summary`, h, 'finance-eleve');
    if (f.status !== 200) continue;
    for (const o of f.json('obligations') || []) {
      if (o.remaining > 20) obligations.push({ id: o.obligation_id, restant: o.remaining });
    }
  }
  if (!obligations.length) fail('aucune obligation avec reste à payer');

  const avant = lire('/api/reports/summary', h, 'reports').json('financial.total_paid');
  return { beta, h, obligations, avant };
}

export default function (d) {
  const o = d.obligations[Math.floor(Math.random() * d.obligations.length)];
  const montant = 10;
  // Clé stable par (VU, itération) : deux appels de la même itération rejouent
  // volontairement la même clé, comme un double clic.
  const cle = `k6-${__VU}-${__ITER}`;
  const corps = JSON.stringify({
    obligation_id: o.id, amount: montant, method: 'cash', idempotency_key: cle,
  });
  const parametres = {
    headers: Object.assign({ 'Content-Type': 'application/json' }, d.h),
    tags: { name: 'payment' },
  };

  const premier = http.post(`${BASE}/api/payments`, corps, parametres);
  // On lit le champ JSON DÉCODÉ, pas le corps brut : Flask échappe les
  // non-ASCII (« dépasse » arrive en « d\u00e9passe »), et un motif posé sur le
  // texte brut ne matchait jamais — le scénario comptait alors comme échecs des
  // refus parfaitement corrects.
  // Reconnaître un refus LÉGITIME de montant. On lit `r.json('error')` et non
  // `r.body` : Flask échappe les accents (« dépasse » devient « d\u00e9passe »
  // dans le corps brut), et la regex ne trouverait jamais rien.
  //
  // Deux familles de refus, et il faut les deux :
  //   - à la CRÉATION : « le montant dépasse ce qui reste dû », « cette
  //     obligation est déjà entièrement payée » ;
  //   - à la CONFIRMATION, depuis le 18/09 : « ce frais a été entièrement payé
  //     entre-temps » — un autre guichet a soldé pendant que celui-ci payait.
  // Le second manquait ici, et trois refus parfaitement corrects étaient
  // comptés comme des échecs. Reconnaître un refus à sa PROSE est fragile :
  // si un troisième message apparaît un jour, c'est ici qu'il faudra revenir.
  const refuseLegitimement = (r) => {
    if (r.status !== 400) return false;
    try { return /dépasse|entièrement pay/.test(r.json('error') || ''); }
    catch (e) { return false; }
  };
  check(premier, {
    'paiement accepté, rejoué, ou refusé pour une raison connue': (r) =>
      [201, 200, 409].indexOf(r.status) !== -1 || refuseLegitimement(r),
  });
  if (premier.status === 201) paiementsAcceptes.add(1);
  if (refuseLegitimement(premier)) refusMontant.add(1);

  // Dette soldée : il n'y a plus rien à rejouer, et insister ne prouverait rien.
  if (refuseLegitimement(premier)) return;

  // Le rejeu immédiat : il ne doit JAMAIS créer un second paiement.
  const rejeu = http.post(`${BASE}/api/payments`, corps, parametres);
  check(rejeu, {
    'rejeu : jamais une seconde écriture': (r) => {
      if (r.status === 409) { rejeuxRefuses.add(1); return true; }
      // Le premier paiement a soldé la dette : le rejeu est refusé pour cette
      // raison, pas pour un problème d'idempotence. C'est correct.
      if (refuseLegitimement(r)) { refusMontant.add(1); return true; }
      if (r.status === 200 || r.status === 201) {
        // Même paiement renvoyé = idempotence correcte. Un identifiant
        // différent = double comptage.
        const memeId = premier.status < 300 && r.json('id') === premier.json('id');
        if (!memeId) doublesComptages.add(1);
        return memeId;
      }
      return false;
    },
  });
}

export function teardown(d) {
  // Vérification finale, la seule qui compte : le total encaissé a-t-il
  // augmenté exactement du nombre de paiements distincts × leur montant ?
  const apres = lire('/api/reports/summary', d.h, 'reports').json('financial.total_paid');
  const ecart = apres - d.avant;
  console.log(`Encaissé avant : ${d.avant}`);
  console.log(`Encaissé après : ${apres}`);
  console.log(`Écart          : ${ecart} (doit valoir 10 × le nombre de paiements distincts)`);
}
