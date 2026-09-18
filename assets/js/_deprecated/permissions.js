// KLASSIO — Catalogue de permissions (référence, voir docs/SECURITE.md §6-8)
//
// Ceci N'EST PAS une frontière de sécurité : ce fichier tourne dans le navigateur,
// donc n'importe qui peut le lire ou le modifier localement. Il documente la source
// de vérité que le futur backend devra appliquer (RBAC + permissions granulaires),
// et sert aujourd'hui uniquement à générer l'affichage adapté au rôle dans le
// prototype (ex. quels menus/actions montrer) — jamais à décider ce qu'un
// utilisateur a réellement le droit de faire. Cette décision n'appartiendra
// qu'au serveur, une fois qu'il existera.
(function (global) {
  "use strict";

  var PERMISSIONS = [
    "students.read", "students.create", "students.update", "students.delete",
    "payments.read", "payments.create", "payments.cancel", "payments.refund",
    "finance.read", "finance.manage",
    "expenses.read", "expenses.create", "expenses.approve",
    "treasury.read", "treasury.transfer",
    "bank_accounts.read", "bank_accounts.manage",
    "mobile_money.read", "mobile_money.manage",
    "users.read", "users.create", "users.update", "users.delete",
    "roles.read", "roles.manage",
    "reports.read", "reports.export",
    "audit.read",
    "settings.read", "settings.manage",
    "ai.use"
  ];

  // Permissions par défaut par rôle — reflète la matrice de docs/SECURITE.md §8.
  // "*" signifie "toutes les permissions listées ci-dessus".
  // Une entrée avec { scope: "..." } documente une restriction de portée
  // (ex. seulement ses propres classes) que seul le backend peut réellement imposer.
  var ROLE_DEFAULT_PERMISSIONS = {
    super_admin: ["*"], // toujours audité, jamais un court-circuit du Permission Layer

    directeur: [
      "students.read", "students.create", "students.update",
      "payments.read", "payments.create", "payments.cancel",
      { key: "payments.refund", note: "approbation si > seuil établissement" },
      "finance.read", "finance.manage",
      "expenses.read", "expenses.create", "expenses.approve",
      "treasury.read", "treasury.transfer",
      { key: "bank_accounts.manage", note: "step-up + double validation" },
      { key: "mobile_money.manage", note: "step-up + double validation" },
      "users.read", "users.create", "users.update",
      { key: "roles.manage", note: "step-up requis" },
      "reports.read", { key: "reports.export", note: "limité et audité" },
      { key: "audit.read", scope: "son établissement" },
      "ai.use", "settings.read", "settings.manage"
    ],

    responsable_financier: [
      "students.read",
      "payments.read", "payments.create", "payments.cancel",
      { key: "payments.refund", note: "approbation si > seuil" },
      "finance.read",
      "expenses.read", "expenses.approve",
      "treasury.read",
      { key: "reports.export", note: "données financières uniquement" },
      "ai.use"
    ],

    caissier: [
      { key: "payments.read", scope: "ceux qu'il enregistre" },
      { key: "payments.create", note: "jusqu'au seuil autorisé" },
      { key: "ai.use", scope: "lecture limitée" }
    ],

    professeur: [
      { key: "students.read", scope: "ses classes" },
      { key: "ai.use", scope: "lecture limitée" }
    ],

    parent: [
      { key: "students.read", scope: "ses enfants" },
      { key: "payments.read", scope: "ses enfants" },
      { key: "ai.use", scope: "ses enfants" }
    ],

    eleve: [
      { key: "students.read", scope: "lui-même" },
      { key: "payments.read", scope: "lui-même" },
      { key: "ai.use", scope: "lui-même" }
    ]
  };

  global.KlassioPermissions = {
    ALL: PERMISSIONS,
    ROLE_DEFAULT_PERMISSIONS: ROLE_DEFAULT_PERMISSIONS
  };
})(window);
