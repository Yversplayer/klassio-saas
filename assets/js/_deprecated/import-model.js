// KLASSIO — Catalogue du modèle de données d'import (référence, voir docs/IMPORT.md §23)
//
// Comme permissions.js et financial-model.js : aucune logique exécutable. Ce fichier
// documente les formes de données du futur moteur d'ingestion (parseur, mapping IA,
// validation, import), pour partir d'un vocabulaire commun une fois le backend
// construit. Rien ici ne lit de fichier, ne parse rien, ne crée rien. Tant qu'il n'y
// a pas de backend, aucun de ces objets n'a d'existence réelle — voir docs/IMPORT.md §0.
(function (global) {
  "use strict";

  // Cycle de vie d'un import (docs/IMPORT.md §15.1)
  var IMPORT_JOB_STATUSES = [
    "UPLOADED", "ANALYZING", "MAPPING", "VALIDATING", "READY",
    "IMPORTING", "COMPLETED", "PARTIAL", "FAILED", "ROLLED_BACK"
  ];

  // Sévérité des anomalies détectées (docs/IMPORT.md §11)
  var ANOMALY_SEVERITIES = ["INFO", "WARNING", "ERROR", "CRITICAL"];

  // Types de correspondance de doublons (docs/IMPORT.md §9)
  var DUPLICATE_MATCH_TYPES = ["EXACT_DUPLICATE", "STRONG_DUPLICATE", "POSSIBLE_DUPLICATE"];

  // Décision d'upsert lors d'un import de mise à jour (docs/IMPORT.md §17)
  var UPSERT_DECISIONS = ["CREATE", "UPDATE", "SKIP", "REVIEW"];

  // Seuils de confiance par défaut — configurables par établissement (docs/IMPORT.md §14)
  var CONFIDENCE_THRESHOLDS = {
    AUTOMATIC: 0.95,          // >= 95% : appliqué automatiquement
    QUICK_VALIDATION: 0.85,   // 85-94% : proposition + validation rapide
    MANDATORY_REVIEW: 0.60    // 60-84% : validation obligatoire ; < 60% : pas d'interprétation auto
  };

  // Formes d'entités (docs/IMPORT.md §23) — documentation, pas des classes.
  var ENTITY_SHAPES = {
    ImportJob: [
      "id", "tenant_id", "user_id", "source", "status",
      "started_at", "completed_at",
      "records_detected", "records_created", "records_updated", "records_skipped", "records_failed",
      "errors", "warnings"
    ],
    ImportFile: ["id", "import_job_id", "filename", "mime_type", "size", "storage_ref", "uploaded_at"],
    ImportSheet: ["id", "import_file_id", "name", "row_count", "column_count"],
    ImportColumn: ["id", "import_sheet_id", "raw_header", "detected_type", "sample_values"],
    ImportMapping: ["id", "import_sheet_id", "column_id", "target_field", "confidence", "explanation", "confirmed_by"],
    ImportRecord: ["id", "import_job_id", "source_sheet", "source_row", "raw_data", "normalized_data", "resolved_entity_id"],
    ImportError: ["id", "import_job_id", "record_id", "severity", "message", "field"],
    ImportWarning: ["id", "import_job_id", "record_id", "message", "field"],
    ImportConflict: ["id", "import_job_id", "existing_entity_id", "incoming_value", "existing_value", "field", "resolution"],
    ImportPreview: ["import_job_id", "summary_counts", "issues_summary", "entities_to_create"],
    ImportResult: ["import_job_id", "status", "created", "updated", "skipped", "failed", "report"],
    ImportRollback: ["id", "import_job_id", "requested_by", "affected_entities", "status", "created_at"],
    DataProvenance: ["entity_type", "entity_id", "import_job_id", "source_file", "source_sheet", "source_row"]
  };

  global.KlassioImportModel = {
    IMPORT_JOB_STATUSES: IMPORT_JOB_STATUSES,
    ANOMALY_SEVERITIES: ANOMALY_SEVERITIES,
    DUPLICATE_MATCH_TYPES: DUPLICATE_MATCH_TYPES,
    UPSERT_DECISIONS: UPSERT_DECISIONS,
    CONFIDENCE_THRESHOLDS: CONFIDENCE_THRESHOLDS,
    ENTITY_SHAPES: ENTITY_SHAPES
  };
})(window);
