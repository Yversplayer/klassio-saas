// Klassio — audit de performance et de scalabilité.
//
// Un seul script pour les trois scénarios : ce qui change est le NOMBRE
// D'ÉTABLISSEMENTS actifs et le nombre d'utilisateurs simulés. Même code, mêmes
// parcours, mêmes seuils — c'est ce qui rend la comparaison 3 → 4 → 5 écoles
// honnête.
//
//   k6 run -e ECOLES=3 -e VUS=20 -e DUREE=60s tools/k6/audit.js
//   k6 run -e ECOLES=5 -e VUS=80 -e DUREE=60s tools/k6/audit.js
//   k6 run -e ECOLES=5 -e VUS=40 -e ECRITURES=1 tools/k6/audit.js
//
// Principes :
// - Un VU joue un RÔLE et n'effectue que des opérations de ce rôle.
// - Chaque contrôle regarde le contenu, jamais seulement le code HTTP.
// - Des sondes inter-établissements tournent en continu : la performance ne
//   doit jamais être obtenue au prix de l'isolation.

import http from 'k6/http';
import { check, sleep, group, fail } from 'k6';
import { Counter, Trend, Rate } from 'k6/metrics';

// Un refus d'accès attendu n'est pas une panne. Sans cette déclaration, les
// sondes d'isolation — qui DOIVENT être refusées — feraient croire à un taux
// d'erreur de 30 %, et le vrai signal serait noyé.
http.setResponseCallback(http.expectedStatuses(200, 201, 204, 401, 403, 404, 409));

const env = JSON.parse(open('./env-echelle.json'));
const BASE = env.base_url;
const ECOLES = parseInt(__ENV.ECOLES || '5', 10);
const VUS = parseInt(__ENV.VUS || '20', 10);
const DUREE = __ENV.DUREE || '60s';
const ECRITURES = __ENV.ECRITURES === '1';
const PALIER = __ENV.PALIER || 'libre';
// PROFIL=complet inclut /api/classes et /api/classes/:id/students.
// Ces deux routes balayent toute la table `attendance` (index privé de sa
// colonne de tête, voir le rapport d'audit) : à 80 jours d'appel elles
// coûtent 13 s et 29 s à un SEUL utilisateur. Les inclure dans une montée en
// charge ne mesurerait qu'elles. PROFIL=sain les écarte pour caractériser le
// reste de l'architecture ; le défaut est mesuré séparément, à 1 VU.
const PROFIL = __ENV.PROFIL || 'sain';
const PATHOLOGIQUES = PROFIL !== 'complet';

const etabs = env.etablissements.slice(0, ECOLES);
if (etabs.length < ECOLES) fail(`env-echelle.json ne contient que ${env.etablissements.length} établissements`);

// ---- métriques par domaine, pour classer les endpoints ----
const fuites = new Counter('klassio_fuites');
const erreursApplicatives = new Counter('klassio_erreurs_applicatives');
const contenuInvalide = new Rate('klassio_contenu_invalide');
const dureeParRole = {
  directeur: new Trend('klassio_role_directeur', true),
  discipline: new Trend('klassio_role_discipline', true),
  professeur: new Trend('klassio_role_professeur', true),
  parent: new Trend('klassio_role_parent', true),
};

// k6 n'expose une sous-métrique `http_req_duration{name:...}` dans le résumé
// QUE si un seuil la référence. Sans ces entrées, le classement des endpoints
// — l'un des livrables de l'audit — reste vide alors que les requêtes partent
// bien. Le seuil est volontairement inatteignable : il sert à matérialiser la
// mesure, pas à faire échouer le run.
const ENDPOINTS = [
  'GET /dashboard', 'GET /students', 'GET /students/:id', 'GET /reports/summary',
  'GET /receipts', 'GET /students?q=', 'GET /classes', 'GET /classes/:id/students',
  'GET /classes/:id/attendance', 'GET /classes/:id/grades', 'GET /students (prof)',
  'GET /students (parent)', 'GET /students/:id/bulletin', 'GET /financial-summary',
  'GET /notifications', 'GET /notifications/summary', 'GET /discipline/overview',
  'GET /discipline/today', 'GET /incidents', 'POST /auth/login',
  'POST /classes/:id/attendance', 'isolation (doit refuser)',
];
function seuilsParEndpoint() {
  const t = {};
  for (const e of ENDPOINTS) t[`http_req_duration{name:${e}}`] = ['max>=0'];
  return t;
}

export const options = {
  scenarios: {
    ecole: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DUREE,
      gracefulStop: '20s',
    },
  },
  thresholds: Object.assign({
    // Seuils volontairement larges : l'objectif est de MESURER la frontière,
    // pas de faire échouer le run. Seule l'isolation est non négociable.
    klassio_fuites: ['count==0'],
    klassio_contenu_invalide: ['rate<0.01'],
  }, seuilsParEndpoint()),
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false,
  noConnectionReuse: false,
};

// ---- répartition des rôles : une école réelle n'est pas 100 % direction ----
// 10 % direction, 10 % discipline, 30 % professeurs, 50 % parents.
function roleDuVU(n) {
  const r = n % 10;
  if (r === 0) return 'directeur';
  if (r === 1) return 'discipline';
  if (r <= 4) return 'professeur';
  return 'parent';
}

export function setup() {
  // Une connexion par rôle et par école, faite une seule fois. Se reconnecter
  // à chaque itération mesurerait surtout PBKDF2 (200 000 itérations, voulu)
  // et déclencherait la limitation anti-force-brute — à juste titre.
  const sessions = [];
  for (const e of etabs) {
    const parEcole = { etiquette: e.etiquette, tenant_id: e.tenant_id, exemples: e.exemples,
                       eleves_count: e.eleves_count, classes_count: e.classes_count, jetons: {} };
    for (const [role, courriel] of Object.entries(e.comptes)) {
      const r = http.post(`${BASE}/api/auth/login`,
        JSON.stringify({ email: courriel, password: env.mot_de_passe }),
        { headers: { 'Content-Type': 'application/json' }, tags: { name: 'POST /auth/login' } });
      if (r.status !== 200) fail(`connexion ${courriel} : ${r.status} ${r.body}`);
      parEcole.jetons[role] = { Authorization: `Bearer ${r.json('token')}` };
    }
    // Chaque rôle travaille sur un élève de SON périmètre. Le Directeur des
    // disciplines ne voit que le secondaire : lui présenter un élève de
    // primaire produirait un 404 parfaitement correct, qu'on prendrait à tort
    // pour une panne.
    for (const role of ['discipline', 'professeur', 'parent']) {
      const v = http.get(`${BASE}/api/students`, { headers: parEcole.jetons[role],
                                                   tags: { name: 'setup' } });
      parEcole.exemples[`eleve_${role}`] = (v.status === 200 && v.json().length)
        ? v.json()[0].id : e.exemples.eleve_id;
      parEcole[`portee_${role}`] = v.status === 200 ? v.json().length : 0;
    }
    // Pour le scénario d'écriture : une classe et ses élèves, résolus une fois.
    //
    // On passe par /api/students (rapide, correctement indexée) puis on filtre
    // par classe, plutôt que par /api/classes/:id/students — cette dernière
    // met 22 s et son coût noierait la mesure de l'écriture. Le parcours réel
    // d'un professeur y passe bien ; c'est mesuré à part, en PROFIL=complet.
    const clw = http.get(`${BASE}/api/classes`, { headers: parEcole.jetons.professeur,
                                                  tags: { name: 'setup' } });
    const tousEleves = http.get(`${BASE}/api/students`, { headers: parEcole.jetons.professeur,
                                                          tags: { name: 'setup' } });
    if (clw.status === 200 && tousEleves.status === 200) {
      const classes = clw.json(); const eleves = tousEleves.json();
      if (Array.isArray(classes) && classes.length && Array.isArray(eleves)) {
        parEcole.classe_ecriture = classes[0].id;
        parEcole.eleves_ecriture = eleves
          .filter((e) => e.class_id === classes[0].id)
          .map((e) => e.id);
      }
    }
    sessions.push(parEcole);
  }
  console.log(`Audit : ${ECOLES} école(s), ${VUS} VU, ${DUREE}, profil=${PROFIL}, écritures=${ECRITURES}, palier=${PALIER}`);
  return { sessions };
}

function lire(chemin, entetes, nom) {
  const r = http.get(`${BASE}${chemin}`, { headers: entetes, tags: { name: nom } });
  if (r.status >= 500) erreursApplicatives.add(1);
  return r;
}

// Vérifie le CONTENU, pas seulement le statut.
function valide(r, nom, predicat) {
  let ok = false;
  try { ok = r.status === 200 && predicat(r); } catch (e) { ok = false; }
  contenuInvalide.add(!ok);
  check(r, { [`${nom} : contenu attendu`]: () => ok });
  return ok;
}

const listeNonVide = (r) => Array.isArray(r.json()) && r.json().length > 0;

// ---- parcours par rôle ----

function parcoursDirection(s) {
  const h = s.jetons.directeur;
  const t0 = Date.now();
  valide(lire('/api/dashboard', h, 'GET /dashboard'), 'tableau de bord',
         (r) => r.json('role') === 'directeur');
  if (!PATHOLOGIQUES) lire('/api/classes', h, 'GET /classes');
  valide(lire('/api/students', h, 'GET /students'), 'liste élèves',
         (r) => r.json().length === s.eleves_count);
  valide(lire(`/api/students/${s.exemples.eleve_id}`, h, 'GET /students/:id'), 'dossier élève',
         (r) => !!r.json('student.code'));
  valide(lire('/api/reports/summary', h, 'GET /reports/summary'), 'rapports',
         (r) => r.json('financial') !== undefined);
  lire('/api/receipts', h, 'GET /receipts');
  lire(`/api/students?q=${s.exemples.eleve_nom}`, h, 'GET /students?q=');
  dureeParRole.directeur.add(Date.now() - t0);
}

function parcoursDiscipline(s) {
  const h = s.jetons.discipline;
  const t0 = Date.now();
  valide(lire('/api/discipline/overview', h, 'GET /discipline/overview'), 'aperçu discipline',
         (r) => r.json('incidents_week') !== undefined);
  lire('/api/discipline/today', h, 'GET /discipline/today');
  lire('/api/incidents', h, 'GET /incidents');
  valide(lire(`/api/students/${s.exemples.eleve_discipline}`, h, 'GET /students/:id'), 'dossier élève (DD)',
         (r) => !!r.json('student.code'));
  dureeParRole.discipline.add(Date.now() - t0);
}

function parcoursProfesseur(s) {
  const h = s.jetons.professeur;
  const t0 = Date.now();
  const classe = s.exemples.class_id;
  if (!PATHOLOGIQUES) {
    const cl = lire('/api/classes', h, 'GET /classes');
    valide(cl, 'classes du professeur', (r) => listeNonVide(r) && r.json().length < s.classes_count);
    valide(lire(`/api/classes/${classe}/students`, h, 'GET /classes/:id/students'), 'élèves de la classe',
           (r) => Array.isArray(r.json()));
  }
  lire(`/api/classes/${classe}/attendance`, h, 'GET /classes/:id/attendance');
  lire(`/api/classes/${classe}/grades`, h, 'GET /classes/:id/grades');
  valide(lire('/api/students', h, 'GET /students (prof)'), 'élèves du professeur',
         (r) => Array.isArray(r.json()));
  dureeParRole.professeur.add(Date.now() - t0);
}

function parcoursParent(s) {
  const h = s.jetons.parent;
  const t0 = Date.now();
  const enfants = lire('/api/students', h, 'GET /students (parent)');
  valide(enfants, 'enfants du parent', (r) => listeNonVide(r) && r.json().length <= 5);
  if (enfants.status === 200 && enfants.json().length) {
    const enfant = enfants.json()[0].id;
    valide(lire(`/api/students/${enfant}`, h, 'GET /students/:id'), 'dossier enfant',
           (r) => !!r.json('student.code'));
    lire(`/api/students/${enfant}/bulletin`, h, 'GET /students/:id/bulletin');
    lire(`/api/students/${enfant}/financial-summary`, h, 'GET /financial-summary');
  }
  lire('/api/notifications/summary', h, 'GET /notifications/summary');
  lire('/api/notifications', h, 'GET /notifications');
  dureeParRole.parent.add(Date.now() - t0);
}

// ---- écriture : seulement si ECRITURES=1 ----
function parcoursEcriture(s) {
  const h = s.jetons.professeur;
  const jour = new Date(Date.now() - 86400000 * (1 + (__ITER % 5))).toISOString().slice(0, 10);
  // La liste des élèves est récupérée UNE FOIS dans setup(). Première version :
  // chaque itération appelait /api/classes/:id/students — la route à 22 s — et
  // le débit d'écriture mesuré n'était que son reflet (1 req/s à 40 VU).
  // Le parcours réel d'un professeur passe bien par là ; c'est mesuré à part,
  // en PROFIL=complet. Ici on veut le coût propre de l'ÉCRITURE.
  const classe = s.classe_ecriture;
  const eleves = s.eleves_ecriture || [];
  if (!classe || !eleves.length) return;
  const records = eleves.slice(0, 30).map((id) => ({ student_id: id, status: 'present' }));
  const r = http.post(`${BASE}/api/classes/${classe}/attendance`,
    JSON.stringify({ date: jour, records }),
    { headers: Object.assign({ 'Content-Type': 'application/json' }, h),
      tags: { name: 'POST /classes/:id/attendance' } });
  if (r.status >= 500) erreursApplicatives.add(1);
  check(r, { 'appel enregistré': (x) => x.status === 200 });
}

// ---- sonde d'isolation : tourne à chaque itération ----
function sondeIsolation(data, indice) {
  if (data.sessions.length < 2) return;
  // L'indice est passé explicitement. Première version : `indexOf(s)` sur les
  // données de setup — que k6 recopie par VU — ne retrouvait pas la session,
  // renvoyait -1, et la sonde interrogeait alors SA PROPRE école. Le 200
  // parfaitement légitime était compté comme une fuite : 33 fausses alertes.
  // Un détecteur qui crie au loup ne sert à rien.
  const s = data.sessions[indice];
  const autre = data.sessions[(indice + 1) % data.sessions.length];
  if (autre.tenant_id === s.tenant_id) return;
  const h = s.jetons.directeur;
  const cibles = [
    [`/api/students/${autre.exemples.eleve_id}`, 'dossier'],
    [`/api/classes/${autre.exemples.class_id}/attendance`, 'classe'],
  ];
  for (const [chemin, quoi] of cibles) {
    const r = http.get(`${BASE}${chemin}`, { headers: h, tags: { name: 'isolation (doit refuser)' } });
    const fuite = r.status === 200;
    if (fuite) fuites.add(1);
    check(r, { [`isolation ${quoi} : refusée`]: () => !fuite });
  }
  // La recherche, chemin le plus facile à oublier de filtrer.
  //
  // On vérifie l'IDENTIFIANT, pas le nom. Première version : elle cherchait le
  // patronyme d'un élève de l'autre école et criait à la fuite dès qu'un
  // homonyme apparaissait — or le générateur puise dans le même jeu de noms
  // pour toutes les écoles, et « Mbala0 » existe dans plusieurs. 28 fausses
  // alertes. Un identifiant, lui, est unique : il ne ment pas.
  const rq = http.get(`${BASE}/api/students?q=${encodeURIComponent(autre.exemples.eleve_nom)}`,
                      { headers: h, tags: { name: 'isolation (doit refuser)' } });
  if (rq.status === 200) {
    const trouve = rq.json().some((e) => e.id === autre.exemples.eleve_id);
    if (trouve) fuites.add(1);
    check(rq, { 'isolation recherche : ne traverse pas': () => !trouve });
  }
}

export default function (data) {
  const indice = __VU % data.sessions.length;
  const s = data.sessions[indice];
  // En mode référence (1 VU), on parcourt les quatre rôles tour à tour :
  // sinon un seul rôle serait mesuré, et la référence ne vaudrait rien.
  const role = VUS === 1
    ? ['directeur', 'discipline', 'professeur', 'parent'][__ITER % 4]
    : roleDuVU(__VU);

  group(role, () => {
    if (ECRITURES && role === 'professeur') parcoursEcriture(s);
    else if (role === 'directeur') parcoursDirection(s);
    else if (role === 'discipline') parcoursDiscipline(s);
    else if (role === 'professeur') parcoursProfesseur(s);
    else parcoursParent(s);
  });

  sondeIsolation(data, indice);
  sleep(Math.random() * 2 + 0.5);   // temps de lecture humain
}
