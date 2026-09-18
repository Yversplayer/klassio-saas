"""KLASSIO backend — Event Engine (version MVP réelle, pas un bus distribué).

Reflète docs/EVENEMENTS.md à l'échelle d'un MVP mono-processus : pas de queue
externe, pas de retry/DLQ (inutile tant qu'il n'y a qu'un seul consommateur
synchrone — la Notification Engine). L'important, déjà vrai ici : un événement
décrit un fait DÉJÀ VALIDÉ (jamais créé avant que le Financial Core n'ait confirmé
l'opération), il est persisté avant tout traitement, et il porte tenant_id +
correlation.
"""
import time
import json
from security import new_id


def emit(conn, tenant_id, event_type, entity_type, entity_id, actor_id, payload=None, correlation_id=None):
    event_id = new_id()
    conn.execute(
        """INSERT INTO events (id, tenant_id, event_type, entity_type, entity_id, actor_id, correlation_id, payload, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (event_id, tenant_id, event_type, entity_type, entity_id, actor_id,
         correlation_id or event_id, json.dumps(payload or {}), str(time.time())),
    )
    conn.commit()
    return {"id": event_id, "event_type": event_type, "tenant_id": tenant_id, "payload": payload or {}}


def list_events(conn, tenant_id, limit=50):
    rows = conn.execute(
        "SELECT * FROM events WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
        (tenant_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
