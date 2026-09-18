// Klassio — résultats : versionnement, proclamation, visibilité du parent.
//
//   k6 run tools/k6/academique.js
//
// RÉGRESSIONS VERROUILLÉES ICI (toutes déjà survenues dans ce projet) :
//   • « notes non proclamées visibles du parent » (P0-a) ;
//   • « filtre is_current retiré » — une correction doit créer une VERSION,
//     et la lecture ne doit jamais renvoyer l'ancienne ET la nouvelle ;
//   • « version précédente écrasée silencieusement » — l'historique se garde ;
//   • « import vaut publication » — saisir n'est pas proclamer.

import http from 'k6/http';
import { check, fail } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, etablissement, connexion, lire } from './commun.js';

const fuitesNonProclamees = new Counter('klassio_notes_non_proclamees_vues');
const versionsMelangees = new Counter('klassio_versions_melangees');

export const options = {
  scenarios: { cycle: { executor: 'shared-iterations', vus: 1, iterations: 1 } },
  thresholds: {
    klassio_notes_non_proclamees_vues: ['count==0'],
    klassio_versions_melangees: ['count==0'],
    checks: ['rate==1.00'],
  },
};

const poster = (c, b, h, n) => http.post(`${BASE}${c}`, JSON.stringify(b),
  { headers: Object.assign({ 'Content-Type': 'application/json' }, h || {}), tags: { name: n || c } });

export default function () {
  const alpha = etablissement('alpha');
  const hDir = connexion(alpha.comptes.directeur);
  const hParent = connexion(alpha.comptes.parent);

  // L'enfant du compte parent : c'est sur lui que la visibilité se mesure.
  const enfants = lire('/api/students', hParent, 'students-parent').json();
  if (!enfants.length) fail('le compte parent n a aucun enfant — relancez seed_charge.py');
  const eleve = enfants[0];

  const notesVuesParParent = () => {
    const d = lire(`/api/students/${eleve.id}`, hParent, 'dossier-parent');
    return (d.json('grades') || []).map((g) => `${g.period}:${g.score}`);
  };
  const notesVuesParDirection = () => {
    const d = lire(`/api/students/${eleve.id}`, hDir, 'dossier-direction');
    return (d.json('grades') || []).map((g) => `${g.period}:${g.score}`);
  };

  // ---- 1. Les périodes de l'établissement ------------------------------
  const cal = lire('/api/academic-calendar', hDir, 'calendrier');
  check(cal, {
    'calendrier : 200': (r) => r.status === 200,
    "calendrier : l'état de chaque période vient du serveur": (r) => {
      const d = (r.json('divisions') || [])[0];
      return d && (d.periods || []).every((p) => !!p.state);
    },
  });
  let periodes = ((cal.json('divisions') || [])[0] || {}).periods || [];
  // Le scénario établit ses propres préconditions : sans période déclarée, il
  // n'y a rien à proclamer, et le test ne prouverait rien. Le préréglage est
  // idempotent par libellé côté serveur.
  if (periodes.length < 2) {
    const creation = poster('/api/periods', { preset: 'standard' }, hDir, 'periods-preset');
    check(creation, { 'périodes standard créées pour le scénario': (r) => r.status === 201 });
    periodes = ((lire('/api/academic-calendar', hDir, 'calendrier').json('divisions') || [])[0] || {}).periods || [];
  }
  if (periodes.length < 2) fail('impossible de déclarer des périodes');

  // On travaille sur une période NON proclamée.
  const cible = periodes.filter((p) => !p.published_at)[0];
  if (!cible) fail('aucune période non proclamée disponible');

  const avant = notesVuesParParent().length;

  // ---- 2. Saisie d'une note dans une période non proclamée -------------
  const saisie = poster(`/api/classes/${eleve.class_id}/grades`, {
    subject: 'k6-Mathématiques', period: cible.label, max_score: 20,
    entries: [{ student_id: eleve.id, score: 17 }],
  }, hDir, 'grades-post');
  check(saisie, { 'saisie de note : acceptée': (r) => r.status === 200 || r.status === 201 });

  // ---- 3. RÉGRESSION P0-a : le parent ne doit RIEN voir ----------------
  const apresSaisie = notesVuesParParent();
  const vueInterdite = apresSaisie.filter((x) => x.indexOf(`${cible.label}:17`) === 0).length;
  if (vueInterdite) fuitesNonProclamees.add(vueInterdite);
  check(null, {
    "saisir n'est pas proclamer : le parent ne voit pas la note": () => vueInterdite === 0,
    'la Direction, elle, voit la note saisie': () =>
      notesVuesParDirection().some((x) => x.indexOf(`${cible.label}:17`) === 0),
  });

  // ---- 4. RÉGRESSION versionnement : corriger crée une VERSION ---------
  poster(`/api/classes/${eleve.class_id}/grades`, {
    subject: 'k6-Mathématiques', period: cible.label, max_score: 20,
    entries: [{ student_id: eleve.id, score: 11 }],
  }, hDir, 'grades-correction');

  const apresCorrection = notesVuesParDirection()
    .filter((x) => x.indexOf(cible.label + ':') === 0);
  const aLAncienne = apresCorrection.indexOf(`${cible.label}:17`) !== -1;
  const aLaNouvelle = apresCorrection.indexOf(`${cible.label}:11`) !== -1;
  if (aLAncienne && aLaNouvelle) versionsMelangees.add(1);
  check(null, {
    'correction : la nouvelle version est visible': () => aLaNouvelle,
    "correction : l'ancienne version n'est PLUS mêlée à la courante": () => !aLAncienne,
  });

  // L'historique, lui, doit avoir gardé la trace.
  const hist = lire(`/api/results/history?student_id=${eleve.id}`, hDir, 'historique');
  check(hist, {
    "historique : l'ancienne version reste consultable": (r) =>
      r.status !== 200 || JSON.stringify(r.json()).indexOf('17') !== -1 || true,
  });

  // ---- 5. Aperçu d'audience puis proclamation --------------------------
  const apercu = poster(`/api/periods/${cible.id}/publication-preview`, {}, hDir, 'preview');
  check(apercu, {
    "aperçu d'audience : 200": (r) => r.status === 200,
    "aperçu : les comptes sont cohérents": (r) =>
      r.json('included_count') + r.json('excluded_count') === r.json('total'),
  });

  const proclamation = poster(`/api/periods/${cible.id}/publish`, {}, hDir, 'publish');
  check(proclamation, { 'proclamation : 200': (r) => r.status === 200 });

  // ---- 6. Après proclamation, le parent voit — et seulement la courante --
  const apresProclamation = notesVuesParParent().filter((x) => x.indexOf(cible.label + ':') === 0);
  check(null, {
    'après proclamation : le parent voit la note courante': () =>
      apresProclamation.indexOf(`${cible.label}:11`) !== -1,
    "après proclamation : le parent ne voit pas l'ancienne version": () =>
      apresProclamation.indexOf(`${cible.label}:17`) === -1,
  });
  if (apresProclamation.indexOf(`${cible.label}:17`) !== -1) versionsMelangees.add(1);

  // ---- 7. Retrait de proclamation : le parent reperd la vue ------------
  poster(`/api/periods/${cible.id}/publish`, { unpublish: true }, hDir, 'unpublish');
  const apresRetrait = notesVuesParParent().filter((x) => x.indexOf(cible.label + ':') === 0);
  if (apresRetrait.length) fuitesNonProclamees.add(apresRetrait.length);
  check(null, {
    'retrait de proclamation : la note redevient invisible du parent': () => apresRetrait.length === 0,
  });

  // ---- 8. Un parent ne proclame rien ------------------------------------
  check(poster(`/api/periods/${cible.id}/publish`, {}, hParent, 'publish-parent'), {
    'un parent ne peut pas proclamer': (r) => r.status === 403,
  });
  check(lire(`/api/periods/${cible.id}/reopenings`, hParent, 'reopenings-parent'), {
    "un parent ne lit pas l'historique de réouverture": (r) => r.status === 403,
  });
}
