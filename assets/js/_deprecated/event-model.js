// KLASSIO — Catalogue du modèle d'événements, règles et notifications
// (référence, voir docs/EVENEMENTS.md §22)
//
// Comme permissions.js, financial-model.js et import-model.js : aucune logique
// exécutable. Ce fichier documente le vocabulaire du futur Event/Rule/Notification
// Engine — rien ici n'émet, ne traite ni ne persiste un événement réel. Tant qu'il
// n'y a pas de backend/bus d'événements, aucun de ces objets n'a d'existence réelle
// — voir docs/EVENEMENTS.md §0.
(function (global) {
  "use strict";

  // Taxonomie d'événements par domaine (docs/EVENEMENTS.md §6.2) — extrait
  // représentatif, extensible sans casser les consommateurs existants (versioning,
  // docs/EVENEMENTS.md §14).
  var EVENT_TAXONOMY = {
    student: ["created", "updated", "enrolled", "transferred", "class_changed", "archived", "reactivated"],
    guardian: ["added", "updated", "removed", "contact_verified"],
    class_: ["created", "updated"],
    import: ["started", "analyzed", "mapping_completed", "validation_completed", "completed", "failed", "rolled_back", "requires_review"],
    obligation: ["created", "updated", "due", "overdue", "partially_paid", "fully_paid", "cancelled"],
    installment: ["created", "upcoming", "due", "overdue", "extended", "cancelled"],
    payment: ["created", "pending", "processing", "confirmed", "failed", "cancelled", "expired", "unknown",
              "duplicate_detected", "reconciled", "unidentified", "refunded", "reversed", "corrected"],
    refund: ["requested", "approved", "processing", "completed", "failed"],
    treasury: ["transaction_created", "transaction_reconciled", "transaction_unreconciled",
               "transfer_created", "transfer_completed", "balance_threshold_reached"],
    cash_session: ["opened", "closed"],
    cash_variance: ["detected"],
    bank_transaction: ["imported", "matched", "unmatched"],
    bank_reconciliation: ["completed"],
    mobile_money: ["payment_initiated", "payment_pending", "payment_confirmed", "payment_failed",
                   "settlement_received", "settlement_completed", "reconciliation_failed"],
    expense: ["created", "submitted", "approved", "rejected", "paid", "cancelled"],
    supplier: ["created", "invoice_received", "invoice_due", "paid"],
    payroll: ["created", "approved", "processed", "paid", "failed"],
    inventory: ["item_created", "stock_low", "stock_out", "stock_received", "stock_adjusted", "sale_completed"],
    document: ["generated", "ready", "failed", "expired"],
    security: ["login_success", "login_failed", "account_locked", "permission_denied",
               "suspicious_activity", "critical_setting_changed", "payment_configuration_changed",
               "settlement_destination_changed"],
    ai: ["insight_generated", "anomaly_detected", "recommendation_created", "action_requested", "action_approved", "action_rejected"]
  };

  // Sévérité d'un événement (docs/EVENEMENTS.md §6.1, §17.4)
  var EVENT_SEVERITIES = ["low", "normal", "high", "critical"];

  // Statut de traitement d'un événement pour un consommateur donné (docs/EVENEMENTS.md §6.3)
  var PROCESSING_STATUSES = ["pending", "processing", "processed", "failed", "dead_letter"];

  // Priorité de notification (docs/EVENEMENTS.md §17.4)
  var NOTIFICATION_PRIORITIES = ["LOW", "NORMAL", "HIGH", "CRITICAL"];

  // Statut de livraison d'une notification
  var DELIVERY_STATUSES = ["pending", "sent", "delivered", "failed", "read"];

  // Canaux de notification, indépendants du fournisseur (docs/EVENEMENTS.md §17.1)
  var NOTIFICATION_CHANNELS = ["in_app", "push", "email", "sms", "whatsapp"];

  // Formes d'entités (docs/EVENEMENTS.md §22) — documentation, pas des classes.
  var ENTITY_SHAPES = {
    Event: [
      "event_id", "event_type", "version", "occurred_at", "recorded_at",
      "tenant_id", "academic_year_id", "actor", "entity", "correlation_id", "causation_id",
      "source", "severity", "processing_status", "retry_count", "metadata", "payload"
    ],
    EventType: ["key", "producer", "consumers", "security_classification", "ai_relevance", "retention"],
    EventProcessing: ["event_id", "consumer_id", "status", "attempts", "last_error", "processed_at"],
    Rule: ["id", "tenant_id", "name", "event_type", "conditions", "actions", "priority", "enabled", "version"],
    Notification: ["id", "tenant_id", "event_id", "rule_id", "recipient_id", "priority", "status", "created_at"],
    NotificationTemplate: ["key", "channel", "locale", "version", "body"],
    NotificationDelivery: ["notification_id", "channel", "status", "attempted_at", "delivered_at", "error"],
    NotificationPreference: ["user_id", "event_category", "channel", "enabled", "quiet_hours"],
    Digest: ["id", "tenant_id", "recipient_id", "period", "summary", "generated_at"],
    Workflow: ["id", "tenant_id", "name", "trigger_event_type", "steps"],
    WorkflowExecution: ["id", "workflow_id", "entity_id", "current_step", "status", "history"]
  };

  global.KlassioEventModel = {
    EVENT_TAXONOMY: EVENT_TAXONOMY,
    EVENT_SEVERITIES: EVENT_SEVERITIES,
    PROCESSING_STATUSES: PROCESSING_STATUSES,
    NOTIFICATION_PRIORITIES: NOTIFICATION_PRIORITIES,
    DELIVERY_STATUSES: DELIVERY_STATUSES,
    NOTIFICATION_CHANNELS: NOTIFICATION_CHANNELS,
    ENTITY_SHAPES: ENTITY_SHAPES
  };
})(window);
