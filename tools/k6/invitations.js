// Klassio — cycle de vie complet d'une invitation, révocation comprise.
//
//   k6 run tools/k6/invitations.js
//
// Couvre le cycle réel : création → pending → activation → accepted → revoked,
// et les altérations qu'un client malveillant peut tenter à chaque étape.
//
// RÉGRESSIONS VERROUILLÉES ICI :
//   • « invitation parent reste pending après activation » — l'état backend
//     doit passer à `accepted`, pas seulement l'écran.
//   • « révoquer une invitation acceptée ne coupe rien » — avant le 17/09, la
//     route réécrivait un statut et la personne gardait son accès.
//   • « escalade de rôle » — envoyer role=directeur à l'acceptation.
//   • « évasion de tenant » — envoyer un tenant_id étranger.

import http from 'k6/http';
import { check, fail } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

const escalades = new Counter('klassio_escalades_reussies');
const accesApresRevocation = new Counter('klassio_acces_apres_revocation');

export const options = {
  scenarios: { cycle: { executor: 'shared-iterations', vus: 1, iterations: 1 } },
  thresholds: {
    klassio_escalades_reussies: ['count==0'],
    klassio_acces_apres_revocation: ['count==0'],
    checks: ['rate==1.00'],
  },
};

function poster(chemin, corps, entetes, nom) {
  return http.post(`${BASE}${chemin}`, JSON.stringify(corps), {
    headers: Object.assign({ 'Content-Type': 'application/json' }, entetes || {}),
    tags: { name: nom || chemin },
  });
}

export default function () {
  const alpha = etablissement('alpha');
  const beta = etablissement('beta');
  const hA = connexion(alpha.comptes.directeur);
  const hB = connexion(beta.comptes.directeur);
  const marque = `${__VU}-${Date.now()}`;

  // ---- 1. Création et état initial ------------------------------------
  const eleve = lire('/api/students', hA, 'students').json()[0].id;
  const creation = poster('/api/invitations',
    { role: 'parent', label: `k6 ${marque}`, student_ids: [eleve] }, hA, 'invitation-create');
  check(creation, {
    'création : 201': (r) => r.status === 201,
    'création : un jeton est renvoyé': (r) => !!r.json('token'),
  });
  const invitation = creation.json('id');
  const jeton = creation.json('token');

  const liste = () => lire('/api/invitations', hA, 'invitations').json()
    .filter((i) => i.id === invitation)[0];
  check(null, { 'état initial : pending': () => liste().status === 'pending' });

  // ---- 2. Altérations refusées à l'acceptation ------------------------
  // Escalade de rôle : le rôle vient de l'INVITATION, jamais du corps.
  const escalade = poster('/api/invitations/accept', {
    token: jeton, name: 'Escalade', email: `esc-${marque}@k6.test`,
    password: 'ChargeKlassio2026!', role: 'directeur', tenant_id: beta.tenant_id,
  }, {}, 'accept-escalade');
  // Un 429 ici ne devrait plus arriver : depuis le 18/09, seul un échec sur le
  // jeton consomme le budget anti-énumération, et une acceptation réussie
  // efface l'ardoise de l'adresse. S'il arrive quand même, c'est qu'un scénario
  // présente des jetons INVALIDES en rafale — on le dit plutôt que de laisser
  // un échec incompréhensible.
  if (escalade.status === 429) {
    fail("limitation anti-abus atteinte sur /api/invitations/accept. Depuis le correctif "
       + "du 18/09 cela signale des jetons INVALIDES en rafale, pas des inscriptions réussies.");
  }
  const roleObtenu = escalade.status === 201 ? escalade.json('role') : null;
  const tenantObtenu = escalade.status === 201 ? escalade.json('tenant_id') : null;
  if (roleObtenu === 'directeur' || tenantObtenu === beta.tenant_id) escalades.add(1);
  check(escalade, {
    'escalade de rôle ignorée : reste parent': () => roleObtenu === 'parent',
    "évasion de tenant ignorée : reste l'établissement de l'invitation": () => tenantObtenu === alpha.tenant_id,
  });

  // ---- 3. RÉGRESSION : l'état passe bien à accepted --------------------
  check(null, {
    "activation : l'invitation passe à accepted côté serveur": () => liste().status === 'accepted',
    "activation : le serveur retient QUI a accepté": () => !!liste().accepted_name,
  });

  // ---- 4. Jeton à usage unique ----------------------------------------
  const rejeu = poster('/api/invitations/accept', {
    token: jeton, name: 'Second', email: `second-${marque}@k6.test`, password: 'ChargeKlassio2026!',
  }, {}, 'accept-rejeu');
  check(rejeu, { 'jeton déjà utilisé : refusé': (r) => r.status !== 201 });

  // ---- 5. L'accès obtenu fonctionne AVANT révocation -------------------
  const hParent = { Authorization: `Bearer ${escalade.json('token')}` };
  check(lire('/api/me', hParent, 'me'), { 'accès accordé avant révocation': (r) => r.status === 200 });

  // ---- 6. Une autre école ne peut pas révoquer -------------------------
  check(poster(`/api/invitations/${invitation}/revoke`, {}, hB, 'revoke-etranger'), {
    "révocation par un autre établissement : introuvable": (r) => r.status === 404,
  });

  // ---- 7. RÉGRESSION : révoquer une invitation ACCEPTÉE coupe l'accès ---
  const revoc = poster(`/api/invitations/${invitation}/revoke`,
    { reason: 'k6 — vérification de coupure réelle' }, hA, 'revoke');
  check(revoc, {
    'révocation : 200': (r) => r.status === 200,
    "révocation : le serveur confirme avoir coupé l'accès": (r) => r.json('access_revoked') === true,
  });

  const apres = lire('/api/me', hParent, 'me-apres');
  if (apres.status === 200) accesApresRevocation.add(1);
  check(apres, { 'session ouverte invalidée immédiatement': (r) => r.status === 401 });

  const reconnexion = poster('/api/auth/login',
    { email: `esc-${marque}@k6.test`, password: 'ChargeKlassio2026!' }, {}, 'relogin');
  if (reconnexion.status === 200) accesApresRevocation.add(1);
  check(reconnexion, { 'reconnexion impossible après révocation': (r) => r.status !== 200 });

  // ---- 8. L'historique est conservé, l'élève intact --------------------
  const ligne = liste();
  check(null, {
    "invitation révoquée : conservée dans l'historique": () => !!ligne && ligne.status === 'revoked',
    'invitation révoquée : datée': () => !!ligne.revoked_at,
    'invitation révoquée : motif conservé': () => !!ligne.revoked_reason,
  });
  check(lire(`/api/students/${eleve}`, hA, 'eleve-apres'), {
    "révocation : l'élève et son dossier sont intacts": (r) => r.status === 200,
  });

  // ---- 9. Un jeton révoqué ne crée plus rien ---------------------------
  const invPending = poster('/api/invitations', { role: 'professeur' }, hA, 'invitation-prof');
  poster(`/api/invitations/${invPending.json('id')}/revoke`, {}, hA, 'revoke-pending');
  check(poster('/api/invitations/accept', {
    token: invPending.json('token'), name: 'Jamais', email: `jamais-${marque}@k6.test`,
    password: 'ChargeKlassio2026!',
  }, {}, 'accept-revoque'), {
    'jeton révoqué : ne crée aucun compte': (r) => r.status !== 201,
  });

  // ---- 10. Jetons invalides -------------------------------------------
  for (const [nom, t] of [['inventé', 'x'.repeat(40)], ['vide', ''], ['nul', null]]) {
    check(poster('/api/invitations/accept', {
      token: t, name: 'N', email: `n-${marque}@k6.test`, password: 'ChargeKlassio2026!',
    }, {}, 'accept-invalide'), {
      [`jeton ${nom} : refusé`]: (r) => r.status !== 201,
    });
  }
}
