// Klassio — la campagne fonctionnelle COMPLÈTE, en une commande et un verdict.
//
//   k6 run tools/k6/complet.js
//
// Rien de neuf ici : ce fichier n'écrit AUCUN test. Il importe les scénarios
// existants et les enchaîne dans un ordre qui a un sens, pour qu'une seule
// sortie réponde à « le produit tient-il debout ? ». Chaque scénario reste
// exécutable seul, avec ses propres seuils — c'est même la façon normale de
// travailler quand on corrige un point précis.
//
// L'ordre n'est pas décoratif :
//   1. smoke        — les parcours de base répondent ; inutile d'aller plus loin sinon
//   2. rbac         — chaque rôle voit ce qu'il doit voir, et rien d'autre
//   3. isolation    — aucun établissement ne déborde sur un autre
//   4. invitations  — cycle de vie complet d'un accès, révocation comprise
//   5. academique   — saisie, versions, proclamation
//   6. regressions  — les défauts déjà corrigés ne sont pas revenus
//   7. concurrence  — ce qui se passe quand deux personnes agissent ensemble
//   8. ia           — l'assistant lit, n'écrit jamais
//
// `regressions` crée un frais de 1 000 avant `concurrence`, qui a besoin d'une
// dette ouverte : les intervertir ferait échouer le second sans qu'il y ait de
// défaut. C'est la seule dépendance entre étapes, et elle est volontaire.
//
// LA LIMITATION ANTI-ABUS NE GÊNE PLUS LA CAMPAGNE. L'acceptation d'une
// invitation reste plafonnée par adresse IP — un jeton d'invitation est un
// secret — mais depuis le 18/09 seul un ÉCHEC sur le secret consomme le budget,
// et une acceptation réussie efface l'ardoise. Deux campagnes enchaînées
// passent donc sans attendre. Un 429 ici signifie qu'un scénario présente des
// jetons INVALIDES en rafale : c'est le scénario qu'il faut regarder.
//
// NE SONT PAS ICI les scénarios de CHARGE (charge.js, pic.js, finance.js,
// recus.js, echelle.js) : ils répondent à une autre question — « jusqu'où ça
// tient » — et ils consomment les dettes dont les scénarios ci-dessus ont
// besoin. Voir README.md pour la campagne de montée en charge.

import smoke from './smoke.js';
import rbac from './rbac.js';
import invitations from './invitations.js';
import academique from './academique.js';
import regressions from './regressions.js';
import concurrence from './concurrence.js';
import ia from './ia.js';
import { setup as isolationSetup, cotéAlpha, cotéBeta } from './isolation.js';

// Chaque étape dure 1 à 3 s. Les créneaux de 20 s laissent une marge large :
// deux étapes qui se chevaucheraient pourraient se voler leurs données et
// produire un échec qui ne correspond à aucun défaut.
const etape = (nom, debut) => ({
  executor: 'shared-iterations', vus: 1, iterations: 1,
  exec: nom, startTime: `${debut}s`, maxDuration: '20s',
});

export const options = {
  scenarios: {
    smoke: etape('etapeSmoke', 0),
    rbac: etape('etapeRbac', 20),
    isolation: etape('etapeIsolation', 40),
    invitations: etape('etapeInvitations', 60),
    academique: etape('etapeAcademique', 80),
    regressions: etape('etapeRegressions', 100),
    concurrence: etape('etapeConcurrence', 120),
    ia: etape('etapeIa', 140),
  },
  // Les seuils des scénarios importés ne sont PAS repris par k6 : on les
  // redéclare ici, agrégés. Un seul compteur non nul fait rougir la campagne.
  thresholds: {
    checks: ['rate==1.00'],
    klassio_fuites_inter_etablissements: ['count==0'],
    klassio_erreurs_500: ['count==0'],
    klassio_surpaiements: ['count==0'],
    klassio_doublons_crees: ['count==0'],
    klassio_ia_ecritures: ['count==0'],
    klassio_ia_refus_manques: ['count==0'],
    klassio_ia_fuites: ['count==0'],
    klassio_acces_non_autorises: ['count==0'],
    klassio_500_sur_route_sensible: ['count==0'],
    klassio_escalades_reussies: ['count==0'],
    klassio_acces_apres_revocation: ['count==0'],
    klassio_notes_non_proclamees_vues: ['count==0'],
    klassio_versions_melangees: ['count==0'],
  },
};

export function setup() {
  // Seul `isolation` a besoin d'un décor préparé : les autres ouvrent leurs
  // sessions eux-mêmes. k6 n'appelle qu'UN setup par script, d'où ce relais.
  return { isolation: isolationSetup() };
}

export function etapeSmoke() { smoke(); }
export function etapeRbac() { rbac(); }
export function etapeIsolation(data) { cotéAlpha(data.isolation); cotéBeta(data.isolation); }
export function etapeInvitations() { invitations(); }
export function etapeAcademique() { academique(); }
export function etapeRegressions() { regressions(); }
export function etapeConcurrence() { concurrence(); }
export function etapeIa() { ia(); }
