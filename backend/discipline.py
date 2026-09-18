"""KLASSIO backend — Discipline Core : création d'incident, capital de points,
seuils, corrections. Utilisé par les routes (api_school, api_discipline) —
jamais par l'assistant IA, qui n'y a structurellement pas accès.

Règle absolue : Klassio enregistre, calcule et alerte ; il ne sanctionne
jamais. Chaque ligne d'incident est écrite par un humain identifié.
"""
import time

import events as events_module
import notifications as notif_module
import school
from security import new_id, audit
from validation import ValidationError, required_text

SEVERITIES = ("low", "medium", "high")
CATEGORIES = ("retard", "absence", "comportement", "bonus", "correction", "autre")


def create_incident(conn, ctx, student, data, report_id=None):
    """Enregistre un incident (ou une correction) pour un élève déjà résolu
    dans le périmètre de l'acteur. Retourne (incident, threshold_info)."""
    tenant_id = ctx["tenant_id"]
    title = required_text(data.get("title"), "title", 160)
    severity = data.get("severity") or "medium"
    if severity not in SEVERITIES:
        raise ValidationError("severity doit être low, medium ou high.")
    occurred_at = (data.get("occurred_at") or school.today_iso()).strip()
    if len(occurred_at) != 10:
        raise ValidationError("occurred_at doit être au format AAAA-MM-JJ.")
    rule = None
    if data.get("rule_id"):
        rule = conn.execute("SELECT * FROM discipline_rules WHERE id=? AND tenant_id=?", (data["rule_id"], tenant_id)).fetchone()
        if not rule:
            raise ValidationError("Règle disciplinaire introuvable.")
    category = data.get("category") or (rule["category"] if rule else "comportement")
    if category not in CATEGORIES:
        raise ValidationError("category invalide.")
    if data.get("points") not in (None, ""):
        try:
            points = int(data["points"])
        except (TypeError, ValueError):
            raise ValidationError("points doit être un entier.")
    else:
        points = int(rule["points"]) if rule else 0
    if abs(points) > 100:
        raise ValidationError("points doit rester entre -100 et 100.")

    settings = school.get_settings(conn, tenant_id)
    before = school.discipline_balance(conn, tenant_id, student["id"], settings)

    iid = new_id()
    now = str(time.time())
    incident = {
        "id": iid, "student_id": student["id"], "class_id": student["class_id"], "rule_id": rule["id"] if rule else None,
        "category": category, "title": title, "description": (data.get("description") or "").strip()[:2000] or None,
        "severity": severity, "points": points, "action_taken": (data.get("action_taken") or "").strip()[:500] or None,
        "internal_note": (data.get("internal_note") or "").strip()[:2000] or None,
        "notify_parent": 1 if data.get("notify_parent") else 0, "occurred_at": occurred_at,
        "status": data.get("status") if data.get("status") in ("open", "convocation", "decided", "closed") else ("closed" if category in ("bonus", "correction") else "open"),
    }
    conn.execute(
        """INSERT INTO incidents (id, tenant_id, student_id, class_id, rule_id, category, title, description, severity, points,
             action_taken, internal_note, notify_parent, occurred_at, recorded_by, created_at, status, report_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (iid, tenant_id, incident["student_id"], incident["class_id"], incident["rule_id"], category, title, incident["description"],
         severity, points, incident["action_taken"], incident["internal_note"], incident["notify_parent"], occurred_at, ctx["user_id"], now,
         incident["status"], report_id),
    )
    conn.commit()

    event = events_module.emit(conn, tenant_id, "discipline.incident.created" if category != "correction" else "discipline.points.adjusted",
                               "incident", iid, ctx["user_id"], payload={"student_id": student["id"], "severity": severity, "points": points})
    notif_module.on_incident_created(conn, tenant_id, student, incident, ctx["user_id"], settings, event_id=event["id"])

    after = school.discipline_balance(conn, tenant_id, student["id"], settings)
    crossed = school.crossed_thresholds(conn, tenant_id, before["remaining"], after["remaining"]) if points < 0 else []
    if crossed:
        notif_module.on_thresholds_crossed(conn, tenant_id, student, crossed, after, event_id=event["id"])
    audit(tenant_id, ctx["user_id"], "discipline.incident_created", "incident", iid, "success",
          after={"student_id": student["id"], "points": points, "severity": severity, "category": category})
    return incident, {"balance": after, "crossed": crossed}


def set_incident_status(conn, ctx, incident, status, action_taken=None):
    if status not in ("open", "convocation", "decided", "closed"):
        raise ValidationError("status invalide.")
    now = str(time.time())
    fields, params = ["status=?"], [status]
    if action_taken is not None:
        fields.append("action_taken=?"); params.append((action_taken or "").strip()[:500] or None)
    if status == "decided":
        fields.append("decided_at=?"); params.append(now)
    if status == "closed":
        fields.append("closed_at=?"); params.append(now)
    params += [incident["id"]]
    conn.execute(f"UPDATE incidents SET {', '.join(fields)} WHERE id=?", params)
    conn.commit()
    audit(ctx["tenant_id"], ctx["user_id"], "discipline.incident_status", "incident", incident["id"], "success", after={"status": status})
