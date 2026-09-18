// Klassio — montée en charge sur les parcours de lecture.
//
//   k6 run tools/k6/charge.js
//   k6 run -e PALIER=60 tools/k6/charge.js     (60 utilisateurs simultanés)
//
// Le profil imite une matinée d'école : tout le monde ouvre son espace en même
// temps, consulte, cherche, puis reste. Les seuils ci-dessous ne sont pas des
// vœux — ce sont les chiffres mesurés en local, majorés de la marge réseau.
// Un seuil dépassé doit être compris, pas relevé.

import { sleep, group } from 'k6';
import { Trend } from 'k6/metrics';
import { etablissement, connexion, lire, verifierListe, verifierObjet } from './commun.js';

const PALIER = parseInt(__ENV.PALIER || '30', 10);
// Durée du plateau, en secondes. Par défaut 120 — le profil d'origine, celui
// dont les seuils ci-dessous sont tirés. Raccourci uniquement pour BALAYER
// plusieurs paliers d'affilée (voir paliers.sh) : une mesure sur un plateau
// court reste une vraie mesure, mais elle voit moins bien les dérives lentes.
const PLATEAU = parseInt(__ENV.DUREE || '120', 10);
const MONTEE = Math.max(10, Math.round(PLATEAU / 4));

const dureeListeEleves = new Trend('klassio_liste_eleves', true);
const dureeTableauDeBord = new Trend('klassio_tableau_de_bord', true);
const dureeDossier = new Trend('klassio_dossier_eleve', true);
const dureeRapports = new Trend('klassio_rapports', true);

export const options = {
  scenarios: {
    matinee: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: `${MONTEE}s`, target: PALIER },    // arrivée du personnel
        { duration: `${PLATEAU}s`, target: PALIER },   // plateau de travail
        { duration: `${MONTEE}s`, target: 0 },         // décrue
      ],
      gracefulRampDown: '20s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    // Une page composée de plusieurs appels reste sous ~2 s tant que chaque
    // appel tient ces seuils.
    'klassio_tableau_de_bord': ['p(95)<800'],
    'klassio_liste_eleves': ['p(95)<1500'],   // ~126 Ko compressés
    'klassio_dossier_eleve': ['p(95)<500'],
    'klassio_rapports': ['p(95)<1200'],
    // Le login est lourd à dessein (PBKDF2, 200 000 itérations) : c'est une
    // protection, pas un défaut. On le surveille sans le contraindre autant.
    'http_req_duration{name:login}': ['p(95)<3000'],
  },
};

export function setup() {
  // Une seule connexion par rôle au démarrage : les VU réutilisent le jeton,
  // comme un navigateur réel. Sinon on mesurerait surtout PBKDF2.
  const alpha = etablissement('alpha');
  return {
    alpha,
    directeur: connexion(alpha.comptes.directeur),
    professeur: connexion(alpha.comptes.professeur),
    parent: connexion(alpha.comptes.parent),
  };
}

export default function (donnees) {
  const { alpha } = donnees;

  group('Direction — ouverture de l’espace', () => {
    const t = lire('/api/dashboard', donnees.directeur, 'dashboard');
    dureeTableauDeBord.add(t.timings.duration);
    verifierObjet(t, 'tableau de bord', ['role']);

    const e = lire('/api/students', donnees.directeur, 'students');
    dureeListeEleves.add(e.timings.duration);
    verifierListe(e, 'élèves', 'code');

    const d = lire(`/api/students/${alpha.exemples.eleve_id}`, donnees.directeur, 'dossier');
    dureeDossier.add(d.timings.duration);
    verifierObjet(d, 'dossier', ['student', 'finance']);
  });

  sleep(Math.random() * 2 + 1);

  group('Direction — rapports', () => {
    const r = lire('/api/reports/summary', donnees.directeur, 'reports');
    dureeRapports.add(r.timings.duration);
    verifierObjet(r, 'rapports', ['financial', 'monthly_collections']);
  });

  group('Professeur — sa classe', () => {
    verifierListe(lire('/api/classes', donnees.professeur, 'classes'), 'classes', 'name');
    lire(`/api/classes/${alpha.exemples.class_id}/students`, donnees.professeur, 'classe-eleves');
  });

  group('Parent — ses enfants', () => {
    verifierListe(lire('/api/students', donnees.parent, 'students-parent'), 'enfants', 'code');
    lire('/api/notifications/summary', donnees.parent, 'notifs');
  });

  sleep(Math.random() * 3 + 2);
}
