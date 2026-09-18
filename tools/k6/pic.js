// Klassio — test de pic (spike).
//
// Cas réel : 8 h 00, le personnel de plusieurs écoles ouvre son espace en même
// temps. On passe de 5 à 150 utilisateurs en cinq secondes, on tient, puis on
// redescend. Ce qu'on mesure n'est pas le débit mais la RÉCUPÉRATION : le
// système encaisse-t-il le choc, et revient-il à son état normal ensuite ?
//
//   k6 run tools/k6/pic.js
import http from 'k6/http';
import { check, sleep, fail } from 'k6';
import { Trend } from 'k6/metrics';

const env = JSON.parse(open('./env-echelle.json'));
const BASE = env.base_url;
const DEBUT = Date.now();

const avant = new Trend('pic_avant', true);
const pendant = new Trend('pic_pendant', true);
const apres = new Trend('pic_apres', true);

export const options = {
  scenarios: {
    pic: {
      executor: 'ramping-vus',
      startVUs: 5,
      stages: [
        { duration: '20s', target: 5 },
        { duration: '5s', target: 150 },
        { duration: '30s', target: 150 },
        { duration: '5s', target: 5 },
        { duration: '30s', target: 5 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: { http_req_failed: ['rate<0.05'] },
  summaryTrendStats: ['med', 'p(95)', 'p(99)', 'max'],
};

export function setup() {
  const e = env.etablissements[0];
  const r = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ email: e.comptes.directeur, password: env.mot_de_passe }),
    { headers: { 'Content-Type': 'application/json' } });
  if (r.status !== 200) fail(`connexion : ${r.status}`);
  return { h: { Authorization: `Bearer ${r.json('token')}` }, debut: Date.now() };
}

export default function (d) {
  const t = (Date.now() - d.debut) / 1000;
  const r = http.get(`${BASE}/api/dashboard`, { headers: d.h, tags: { name: 'dashboard' } });
  check(r, { 'tableau de bord servi': (x) => x.status === 200 });
  // Découpage temporel : 0-20 s avant, 25-55 s pendant, 60 s+ après.
  if (t < 20) avant.add(r.timings.duration);
  else if (t >= 25 && t < 55) pendant.add(r.timings.duration);
  else if (t >= 62) apres.add(r.timings.duration);
  sleep(1);
}
