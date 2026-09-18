// KLASSIO — Catalogue du modèle multi-tenant (référence, voir docs/MULTI_TENANT.md §10, §19)
//
// Comme les catalogues précédents (permissions.js, financial-model.js, import-model.js,
// event-model.js) : aucune logique exécutable. Documente le vocabulaire de l'isolation
// multi-tenant pour le futur backend — rien ici ne résout un tenant, ne filtre une
// requête ni n'applique une politique RLS réelle. Tant qu'il n'y a pas de backend,
// aucun de ces objets n'a d'existence réelle — voir docs/MULTI_TENANT.md §0.
(function (global) {
  "use strict";

  // Hiérarchie tenant (docs/MULTI_TENANT.md §3) — Campus n'est PAS une frontière de
  // sécurité, contrairement à Tenant. Organization ne donne jamais d'accès implicite.
  var TENANT_HIERARCHY = ["Organization", "Tenant", "Campus", "AcademicYear", "Level", "Class", "Student"];

  // Mode de déploiement d'un tenant dans le Tenant Registry (docs/MULTI_TENANT.md §6, §19)
  var DEPLOYMENT_MODES = ["shared", "dedicated"];

  // Types de compte structurellement distincts (docs/MULTI_TENANT.md §16) — un
  // Platform Administrator ne peut jamais être confondu avec un utilisateur d'école.
  var ACCOUNT_TYPES = ["school_user", "platform_administrator", "support"];

  // Statut d'un tenant
  var TENANT_STATUSES = ["active", "suspended", "pending_deletion", "deleted"];

  // Portée d'une contrainte d'unicité (docs/MULTI_TENANT.md §10.5)
  var UNIQUENESS_SCOPES = ["global", "tenant_scoped"];

  // Exemples classés selon cette portée — à titre de référence, pas exhaustif.
  var UNIQUENESS_EXAMPLES = {
    global: ["user_id", "event_id", "payment_provider_transaction_id"],
    tenant_scoped: ["student_number", "class_code", "invoice_number"]
  };

  // Formes d'entités clés (docs/MULTI_TENANT.md §10, §19, §16.1)
  var ENTITY_SHAPES = {
    TenantRegistry: [
      "tenant_id", "tenant_name", "status", "deployment_mode",
      "database_cluster", "database_identifier", "region", "plan", "created_at"
    ],
    TenantSettings: [
      "tenant_id", "currency", "timezone", "academic_calendar", "grading_system",
      "fee_structure", "payment_providers", "notification_preferences", "branding"
    ],
    Membership: ["user_id", "tenant_id", "role", "status", "granted_at"],
    Organization: ["id", "name", "tenant_ids"],
    FeatureFlag: ["tenant_id", "feature_key", "enabled"],
    SupportAccessGrant: [
      "id", "support_user_id", "tenant_id", "justification",
      "approved_by", "granted_at", "expires_at", "revoked_at"
    ]
  };

  global.KlassioTenantModel = {
    TENANT_HIERARCHY: TENANT_HIERARCHY,
    DEPLOYMENT_MODES: DEPLOYMENT_MODES,
    ACCOUNT_TYPES: ACCOUNT_TYPES,
    TENANT_STATUSES: TENANT_STATUSES,
    UNIQUENESS_SCOPES: UNIQUENESS_SCOPES,
    UNIQUENESS_EXAMPLES: UNIQUENESS_EXAMPLES,
    ENTITY_SHAPES: ENTITY_SHAPES
  };
})(window);
