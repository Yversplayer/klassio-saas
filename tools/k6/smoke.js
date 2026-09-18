// Klassio — scénario de fumée. UN utilisateur, tous les parcours critiques,
// une fois. À lancer avant toute montée en charge : inutile de charger un
// système dont un parcours est déjà cassé.
//
//   k6 run tools/k6/smoke.js
//
// Il échoue si un parcours répond « bien » mais sans les données attendues.

import { sleep, group, check } from 'k6';
import { BASE, etablissement, connexion, lire, verifierListe, verifierObjet } from './commun.js';

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    checks: ['rate==1.00'],            // aucun parcours cassé, sans exception
    // Retiré : ce scénario vérifie DÉLIBÉRÉMENT des refus (un parent qui tente
    // les rapports d'établissement doit recevoir 403). Compter ces refus comme
    // des erreurs HTTP faisait échouer un scénario dont les 32 assertions
    // métier passaient toutes — le seuil mesurait le contraire de ce qu'on veut.
    http_req_duration: ['p(95)<1500'],
  },
};

export default function () {
  const alpha = etablissement('alpha');

  group('Direction', () => {
    const h = connexion(alpha.comptes.directeur);
    verifierObjet(lire('/api/me', h, 'me'), 'me', ['user_id', 'tenant_id', 'role']);
    verifierObjet(lire('/api/dashboard', h, 'dashboard'), 'tableau de bord', ['role']);
    verifierListe(lire('/api/students', h, 'students'), 'élèves', 'code');
    verifierListe(lire('/api/classes', h, 'classes'), 'classes', 'name');
    verifierObjet(lire('/api/reports/summary', h, 'reports'), 'rapports', ['financial', 'monthly_collections']);
    verifierObjet(lire('/api/settings', h, 'settings'), 'réglages', ['currency']);

    const dossier = lire(`/api/students/${alpha.exemples.eleve_id}`, h, 'dossier');
    check(dossier, {
      'dossier élève : 200': (r) => r.status === 200,
      'dossier élève : identité présente': (r) => !!r.json('student.code'),
      'dossier élève : finance recalculée': (r) => r.json('finance.total_due') !== undefined,
    });

    const finance = lire(`/api/students/${alpha.exemples.eleve_id}/financial-summary`, h, 'finance-eleve');
    check(finance, {
      'finance élève : solde cohérent': (r) =>
        r.status === 200 &&
        Math.abs(r.json('balance') - (r.json('total_due') - r.json('total_paid'))) < 0.01,
    });
  });

  group('Professeur', () => {
    const h = connexion(alpha.comptes.professeur);
    const classes = lire('/api/classes', h, 'classes-prof');
    check(classes, {
      'professeur : ne voit que ses classes': (r) =>
        r.status === 200 && r.json().length > 0 && r.json().length < alpha.classes_count,
    });
    verifierListe(lire('/api/students', h, 'students-prof'), 'élèves du professeur', 'code');
  });

  group('Parent', () => {
    const h = connexion(alpha.comptes.parent);
    const enfants = lire('/api/students', h, 'students-parent');
    check(enfants, {
      'parent : périmètre réduit à ses enfants': (r) =>
        r.status === 200 && r.json().length > 0 && r.json().length <= 3,
    });
    check(lire('/api/reports/summary', h, 'reports-parent'), {
      'parent : rapports d’établissement refusés': (r) => r.status === 403,
    });
  });

  group('Discipline', () => {
    const h = connexion(alpha.comptes.discipline);
    verifierObjet(lire('/api/discipline/overview', h, 'discipline'), 'discipline',
                  ['incidents_week', 'incidents_month']);
  });

  sleep(1);
}
