// KLASSIO — Catalogue du modèle de données financier (référence, voir docs/FINANCE.md §22)
//
// Ce fichier ne contient AUCUNE logique exécutable. Il documente les formes de
// données du futur Financial Core (backend + base de données), pour que
// l'implémentation réelle parte d'un vocabulaire commun. Rien ici ne calcule un
// solde, ne stocke une transaction, ni ne remplace les valeurs d'affichage déjà
// présentes dans le prototype (assets/js/app.js). Tant qu'il n'y a pas de backend,
// aucun de ces objets n'a d'existence réelle — voir docs/FINANCE.md §0.
(function (global) {
  "use strict";

  // Types de comptes financiers (docs/FINANCE.md §4)
  var ACCOUNT_TYPES = [
    "ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE",
    "RECEIVABLE", "PAYABLE",
    "CASH", "BANK", "MOBILE_MONEY",
    "INVENTORY", "FIXED_ASSET"
  ];

  // Statuts d'une obligation/créance élève (docs/FINANCE.md §6.2) — dérivés par le
  // backend à partir des paiements réels, jamais déclarés par le frontend.
  var OBLIGATION_STATUSES = [
    "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED", "WAIVED", "REFUNDED"
  ];

  // États d'une transaction de paiement (docs/FINANCE.md §7.3). UNKNOWN n'est
  // jamais automatiquement réduit à FAILED.
  var TRANSACTION_STATUSES = [
    "CREATED", "PENDING", "PROCESSING", "CONFIRMED",
    "FAILED", "CANCELLED", "EXPIRED", "UNKNOWN",
    "REFUNDED", "REVERSED"
  ];

  var RECONCILIATION_STATUSES = ["MATCHED", "UNMATCHED", "PARTIAL_MATCH", "NEEDS_REVIEW"];

  var PAYROLL_STATUSES = ["DRAFT", "CALCULATED", "APPROVED", "PROCESSING", "PAID", "FAILED", "CANCELLED"];

  var ASSET_LIFECYCLE = [
    "PURCHASED", "ACTIVE", "MAINTENANCE", "TRANSFERRED", "DAMAGED", "LOST", "SOLD", "DISPOSED"
  ];

  var APPROVAL_WORKFLOW = ["DRAFT", "SUBMITTED", "REVIEW", "APPROVED", "EXECUTED"];

  var RECEIVABLE_AGING_BUCKETS = ["CURRENT", "1-30_DAYS", "31-60_DAYS", "61-90_DAYS", "90_PLUS_DAYS"];

  // Formes d'entités (docs/FINANCE.md §22) — documentation, pas des classes.
  var ENTITY_SHAPES = {
    FinancialAccount: [
      "id", "tenant_id", "name", "type", "currency",
      "balance", // dérivé du ledger — jamais une valeur stockée comme vérité primaire
      "status", "created_at", "external_reference"
    ],
    LedgerEntry: [
      "transaction_id", "tenant_id", "date", "currency", "amount",
      "source_account", "destination_account", "type", "reference",
      "description", "status", "created_by", "approved_by", "created_at"
    ],
    Receivable: [
      "student_id", "tenant_id", "academic_year", "category", "amount", "currency",
      "due_date", "status", "payments", "remaining_balance"
    ],
    Payment: [
      "id", "tenant_id", "obligation_id", "amount", "currency", "channel",
      "status", "idempotency_key", "provider_reference", "created_at"
    ],
    PaymentAllocation: ["payment_id", "obligation_id", "amount"],
    Refund: [
      "id", "original_transaction_id", "amount", "reason",
      "requested_by", "approved_by", "method", "date", "reference"
    ],
    Expense: ["id", "tenant_id", "category", "amount", "currency", "status", "approved_by"],
    Supplier: ["id", "tenant_id", "name", "contacts", "invoices", "total_due", "payments", "contracts", "documents"],
    Employee: ["id", "tenant_id", "profile", "function", "contract", "salary", "currency", "frequency", "status"],
    Payroll: ["id", "tenant_id", "period", "employee_id", "base_salary", "adjustments", "net_amount", "status"],
    BankAccount: ["id", "tenant_id", "institution", "reference", "currency", "status", "balance"],
    CashRegister: ["id", "tenant_id", "opening_balance", "cash_in", "cash_out", "expected_balance", "actual_balance", "status"],
    Transfer: ["id", "tenant_id", "source_account", "destination_account", "amount", "currency", "created_at"],
    Budget: ["id", "tenant_id", "category", "annual_amount", "period"],
    Asset: [
      "asset_id", "tenant_id", "name", "category", "purchase_date", "purchase_value",
      "current_value", "location", "responsible", "status", "supplier", "document"
    ],
    FinancialAdjustment: ["id", "tenant_id", "target_type", "target_id", "before", "after", "reason", "created_by", "created_at"],
    Reconciliation: ["id", "tenant_id", "account_id", "period", "status", "discrepancies"]
  };

  global.KlassioFinancialModel = {
    ACCOUNT_TYPES: ACCOUNT_TYPES,
    OBLIGATION_STATUSES: OBLIGATION_STATUSES,
    TRANSACTION_STATUSES: TRANSACTION_STATUSES,
    RECONCILIATION_STATUSES: RECONCILIATION_STATUSES,
    PAYROLL_STATUSES: PAYROLL_STATUSES,
    ASSET_LIFECYCLE: ASSET_LIFECYCLE,
    APPROVAL_WORKFLOW: APPROVAL_WORKFLOW,
    RECEIVABLE_AGING_BUCKETS: RECEIVABLE_AGING_BUCKETS,
    ENTITY_SHAPES: ENTITY_SHAPES
  };
})(window);
