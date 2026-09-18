// KLASSIO — Catalogue du modèle de recherche/commande (référence, voir docs/DASHBOARDS_RECHERCHE.md)
//
// Comme les cinq catalogues précédents : aucune logique exécutable. Documente le
// vocabulaire du futur Intent Engine / Command Bar réel. Le prototype actuel
// (assets/js/app.js, DASH_CONTENT) affiche une réponse pré-écrite quel que soit le
// texte saisi — ce fichier ne change pas ce comportement, il catalogue ce que la
// vraie implémentation devra respecter. Voir docs/DASHBOARDS_RECHERCHE.md §0.
(function (global) {
  "use strict";

  // Taxonomie d'intentions (docs/DASHBOARDS_RECHERCHE.md §37 du brief / §6)
  var INTENT_TYPES = [
    "SEARCH", "VIEW", "FILTER", "COMPARE", "CREATE", "UPDATE",
    "EXPORT", "ANALYZE", "EXPLAIN", "NAVIGATE", "APPROVE", "REVIEW"
  ];

  // Niveau de recherche — jamais les deux confondus (docs/DASHBOARDS_RECHERCHE.md §8)
  var SEARCH_LEVELS = ["deterministic", "natural_language"];

  // Composantes de la priorité d'une information affichée (docs/DASHBOARDS_RECHERCHE.md §12.1)
  // — un triplet, jamais un niveau global seul.
  var INFORMATION_PRIORITY_LEVELS = ["low", "normal", "high", "critical"];

  // Statut d'une commande déclenchée depuis la Command Bar (docs/DASHBOARDS_RECHERCHE.md §10.2)
  var COMMAND_STATUSES = [
    "draft", "preview", "awaiting_confirmation", "awaiting_approval",
    "confirmed", "executed", "cancelled", "denied"
  ];

  // Formes d'entités clés (docs/DASHBOARDS_RECHERCHE.md §6.2, §12.1)
  var ENTITY_SHAPES = {
    StructuredIntent: ["intent", "tenant_id", "user_id", "filters", "raw_query", "confidence"],
    SearchResult: ["entity_type", "entity_id", "label", "summary_fields", "actions_available"],
    CommandPreview: ["command_id", "intent", "summary", "risk_level", "requires_approval"],
    DashboardBlock: ["key", "audience_role", "priority", "importance", "context", "visible"],
    ContextSnapshot: [
      "user_id", "role", "tenant_id", "academic_year_id", "current_page",
      "current_entity", "active_filters", "permissions", "recent_events"
    ]
  };

  global.KlassioSearchModel = {
    INTENT_TYPES: INTENT_TYPES,
    SEARCH_LEVELS: SEARCH_LEVELS,
    INFORMATION_PRIORITY_LEVELS: INFORMATION_PRIORITY_LEVELS,
    COMMAND_STATUSES: COMMAND_STATUSES,
    ENTITY_SHAPES: ENTITY_SHAPES
  };
})(window);
