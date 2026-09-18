"""KLASSIO backend — espace du Directeur des disciplines (et adjoint) :
« Aujourd'hui », pointage des retards au portail, signalements des
professeurs, cycle de vie des incidents (convocation → décision → clôture),
corrections de points, seuils, import du règlement, registres imprimables.

Klassio enregistre et alerte ; il ne sanctionne jamais. Chaque décision est
prise par un humain identifié, et le parent ne reçoit que le communicable.
"""
import io
import json
import re
import time
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, g

import db
import security
import events as events_module
import notifications as notif_module
import school
import discipline as disc
from security import require_auth, new_id, audit, has_permission
from validation import json_object, ValidationError, required_text

bp = Blueprint("discipline", __name__)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _denied(action, message="Vous n'avez pas l'autorisation d'effectuer cette action."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, status="denied")
    return jsonify({"error": message}), 403


def _not_found(action, message="Introuvable ou accès non autorisé."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, status="denied")
    return jsonify({"error": message}), 404


def _is_dd():
    return g.ctx["role"] in ("directeur", "discipline")


# ===========================================================================
# AUJOURD'HUI
# ===========================================================================

@bp.get("/api/discipline/today")
@require_auth
def today():
    if not _is_dd():
        return _denied("discipline.today")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    day = school.today_iso()
    class_ids = school.visible_class_ids(conn, g.ctx)
    if class_ids is not None and not class_ids:
        conn.close()
        return jsonify({"date": day, "classes_pending_roll": [], "late_today": [], "absent_today": [], "reports": [], "justifications": [], "open_incidents": [], "convocations": [], "alerts": []})
    cfilter, cparams = ("", []) if class_ids is None else (f" AND c.id IN ({','.join('?' for _ in class_ids)})", list(class_ids))
    pending_roll = [dict(r) for r in conn.execute(
        f"""SELECT c.id, c.name, c.cycle, (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id AND s.status='active') AS student_count,
                   (SELECT u.name FROM class_teachers ct JOIN users u ON u.id=ct.user_id WHERE ct.class_id=c.id AND ct.is_titulaire=1 LIMIT 1) AS titulaire
            FROM classes c WHERE c.tenant_id=?{cfilter} AND NOT EXISTS (SELECT 1 FROM attendance a WHERE a.class_id=c.id AND a.date=?)
            ORDER BY c.name""", [tenant_id] + cparams + [day])]
    sfilter, sparams = ("", []) if class_ids is None else (f" AND s.class_id IN ({','.join('?' for _ in class_ids)})", list(class_ids))
    late = [dict(r) for r in conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, s.code, c.name AS class_name, a.arrival_time, a.note, a.source FROM attendance a JOIN students s ON s.id=a.student_id LEFT JOIN classes c ON c.id=s.class_id
            WHERE a.tenant_id=? AND a.date=? AND a.status='late'{sfilter} ORDER BY a.arrival_time, s.last_name""", [tenant_id, day] + sparams)]
    absent = [dict(r) for r in conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, s.code, c.name AS class_name, a.note,
                   (SELECT COUNT(*) FROM attendance a2 WHERE a2.student_id=s.id AND a2.status='absent' AND a2.date>=?) AS absences_30d
            FROM attendance a JOIN students s ON s.id=a.student_id LEFT JOIN classes c ON c.id=s.class_id
            WHERE a.tenant_id=? AND a.date=? AND a.status='absent'{sfilter} ORDER BY absences_30d DESC, s.last_name""", [(date.today() - timedelta(days=30)).isoformat(), tenant_id, day] + sparams)]
    reports = [dict(r) for r in conn.execute(
        f"""SELECT r.id, r.description, r.occurred_at, r.created_at, s.id AS student_id, s.first_name, s.last_name, c.name AS class_name, u.name AS reporter
            FROM incident_reports r JOIN students s ON s.id=r.student_id LEFT JOIN classes c ON c.id=r.class_id JOIN users u ON u.id=r.reported_by
            WHERE r.tenant_id=? AND r.status='pending'{sfilter} ORDER BY r.created_at DESC LIMIT 30""", [tenant_id] + sparams)]
    justifs = [dict(r) for r in conn.execute(
        f"""SELECT j.id, j.date, j.reason, j.created_at, s.id AS student_id, s.first_name, s.last_name, c.name AS class_name
            FROM attendance_justifications j JOIN students s ON s.id=j.student_id LEFT JOIN classes c ON c.id=s.class_id
            WHERE j.tenant_id=? AND j.status='pending'{sfilter} ORDER BY j.created_at DESC LIMIT 30""", [tenant_id] + sparams)]
    open_inc = [dict(r) for r in conn.execute(
        f"""SELECT i.id, i.title, i.severity, i.status, i.occurred_at, i.points, s.id AS student_id, s.first_name, s.last_name, c.name AS class_name
            FROM incidents i JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=i.class_id
            WHERE i.tenant_id=? AND i.status IN ('open','convocation'){sfilter} ORDER BY i.occurred_at DESC LIMIT 30""", [tenant_id] + sparams)]
    convs = [dict(r) for r in conn.execute(
        f"""SELECT cv.*, s.first_name, s.last_name, c.name AS class_name FROM convocations cv JOIN students s ON s.id=cv.student_id LEFT JOIN classes c ON c.id=s.class_id
            WHERE cv.tenant_id=? AND cv.status='planned' AND cv.scheduled_on<=?{sfilter} ORDER BY cv.scheduled_on, cv.scheduled_time""", [tenant_id, day] + sparams)]
    settings = school.get_settings(conn, tenant_id)
    capital = int(settings.get("discipline_capital") or 100)
    ths = school.thresholds(conn, tenant_id)
    top = ths[0]["remaining_points"] if ths else 70
    alerts = [dict(r) for r in conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, s.code, c.name AS class_name, ? + COALESCE(SUM(i.points),0) AS remaining
            FROM students s JOIN incidents i ON i.student_id=s.id LEFT JOIN classes c ON c.id=s.class_id
            WHERE s.tenant_id=? AND s.status='active'{sfilter}
            -- GROUP BY : PostgreSQL n'accepte une colonne nue que si elle appartient à la
            -- table dont la clé primaire est groupée — c.name vient de `classes`.
            -- HAVING : PostgreSQL n'y reconnaît pas l'alias `remaining` d'une colonne de
            -- sortie (contrairement à ORDER BY, et contrairement à SQLite) ; l'expression
            -- est donc répétée, d'où le `capital` en double dans les paramètres.
            GROUP BY s.id, s.first_name, s.last_name, s.code, c.name
            HAVING ? + COALESCE(SUM(i.points),0) <= ? ORDER BY remaining ASC LIMIT 20""",
        [capital, tenant_id] + sparams + [capital, top])]
    for a in alerts:
        a["capital"] = capital
        a["step"] = next((t["label"] for t in ths if a["remaining"] <= t["remaining_points"]), None)
    conn.close()
    return jsonify({"date": day, "classes_pending_roll": pending_roll, "late_today": late, "absent_today": absent, "reports": reports,
                    "justifications": justifs, "open_incidents": open_inc, "convocations": convs, "alerts": alerts, "capital": capital, "thresholds": ths})


@bp.post("/api/discipline/remind-roll")
@require_auth
def remind_roll():
    """Relance en un clic le titulaire d'une classe dont l'appel n'est pas fait."""
    if not _is_dd():
        return _denied("discipline.remind")
    class_id = (json_object(request.get_json(force=True))).get("class_id")
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls:
        conn.close()
        return _not_found("discipline.remind")
    staff = notif_module.class_staff(conn, g.ctx["tenant_id"], class_id)
    if not staff:
        conn.close()
        return jsonify({"error": "Aucun enseignant rattaché à cette classe — rattachez un titulaire depuis Classes."}), 409
    notif_module.send(conn, g.ctx["tenant_id"], staff, f"Appel non fait — {cls['name']}", "Merci de faire l'appel de la classe dès que possible.",
                      link=f"classe.html?id={class_id}&tab=presence", kind="attendance", priority="HIGH")
    conn.close()
    return jsonify({"ok": True, "notified": len(staff)})


# ===========================================================================
# POINTAGE AU PORTAIL (retards)
# ===========================================================================

@bp.get("/api/attendance/search")
@require_auth
def search_for_gate():
    if not _is_dd():
        return _denied("attendance.search")
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    like = f"%{q}%"
    rows = conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, s.code, c.name AS class_name, a.status AS today_status, a.arrival_time
            FROM students s LEFT JOIN classes c ON c.id=s.class_id LEFT JOIN attendance a ON a.student_id=s.id AND a.date=?
            WHERE {where} AND s.status='active' AND (LOWER(s.first_name||' '||s.last_name) LIKE ? OR LOWER(s.last_name||' '||s.first_name) LIKE ? OR LOWER(s.code) LIKE ?)
            ORDER BY s.last_name LIMIT 12""", (school.today_iso(), *params, like, like, like)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/attendance/gate")
@require_auth
def gate_late():
    """Retard pointé au portail : heure d'arrivée enregistrée. Prime sur un
    « présent » saisi ensuite en classe (le portail a vu l'heure)."""
    if not _is_dd():
        return _denied("attendance.gate")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, data.get("student_id"))
    if not student:
        conn.close()
        return _not_found("attendance.gate", "Élève introuvable ou hors de votre périmètre.")
    arrival = (data.get("arrival_time") or time.strftime("%H:%M")).strip()
    if not re.match(r"^\d{2}:\d{2}$", arrival):
        raise ValidationError("arrival_time doit être au format HH:MM.")
    day = school.today_iso()
    now = str(time.time())
    previous = conn.execute("SELECT status FROM attendance WHERE tenant_id=? AND student_id=? AND date=?", (tenant_id, student["id"], day)).fetchone()
    note = (data.get("note") or "").strip()[:200] or f"Arrivé(e) à {arrival} (portail)"
    conn.execute(
        """INSERT INTO attendance (id, tenant_id, student_id, class_id, date, status, note, recorded_by, created_at, updated_at, arrival_time, source)
           VALUES (?,?,?,?,?,'late',?,?,?,?,?,'gate')
           ON CONFLICT(tenant_id, student_id, date) DO UPDATE SET status='late', note=excluded.note, recorded_by=excluded.recorded_by,
             updated_at=excluded.updated_at, arrival_time=excluded.arrival_time, source='gate'""",
        (new_id(), tenant_id, student["id"], student["class_id"], day, note, g.ctx["user_id"], now, now, arrival))
    conn.commit()
    settings = school.get_settings(conn, tenant_id)
    event = events_module.emit(conn, tenant_id, "attendance.gate_late", "student", student["id"], g.ctx["user_id"], payload={"arrival_time": arrival})
    if not previous or previous["status"] != "late":
        notif_module.on_attendance_recorded(conn, tenant_id, student, student["class_id"], "late", g.ctx["user_id"], settings, event_id=event["id"])
    late_30 = conn.execute("SELECT COUNT(*) n FROM attendance WHERE tenant_id=? AND student_id=? AND status='late' AND date>=?",
                           (tenant_id, student["id"], (date.today() - timedelta(days=30)).isoformat())).fetchone()["n"]
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "attendance.gate_late", "student", student["id"], "success", after={"arrival_time": arrival})
    return jsonify({"ok": True, "arrival_time": arrival, "late_count_30d": late_30, "student": {"id": student["id"], "first_name": student["first_name"], "last_name": student["last_name"], "class_name": student["class_name"]}})


# ===========================================================================
# SIGNALEMENTS (professeur → DD)
# ===========================================================================

@bp.post("/api/incident-reports")
@require_auth
def create_report():
    if g.ctx["role"] not in ("professeur", "directeur", "discipline"):
        return _denied("report.create")
    data = json_object(request.get_json(force=True))
    description = required_text(data.get("description"), "description", 1500)
    occurred = (data.get("occurred_at") or school.today_iso()).strip()
    if not ISO_DATE.match(occurred) or occurred > school.today_iso():
        raise ValidationError("occurred_at invalide.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, data.get("student_id"))
    if not student:
        conn.close()
        return _not_found("report.create", "Élève introuvable ou hors de votre périmètre.")
    rid = new_id()
    now = str(time.time())
    conn.execute("INSERT INTO incident_reports (id, tenant_id, student_id, class_id, reported_by, description, occurred_at, status, created_at) VALUES (?,?,?,?,?,?,?,'pending',?)",
                 (rid, tenant_id, student["id"], student["class_id"], g.ctx["user_id"], description, occurred, now))
    conn.commit()
    event = events_module.emit(conn, tenant_id, "discipline.report.created", "incident_report", rid, g.ctx["user_id"], payload={"student_id": student["id"]})
    notif_module.on_report_created(conn, tenant_id, student, {"description": description}, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "discipline.report_created", "incident_report", rid, "success")
    return jsonify({"id": rid}), 201


@bp.get("/api/incident-reports")
@require_auth
def list_reports():
    if g.ctx["role"] not in ("professeur", "directeur", "discipline"):
        return _denied("report.list")
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    extra = ""
    if g.ctx["role"] == "professeur":
        extra += " AND r.reported_by=?"; params = params + (g.ctx["user_id"],)
    status = request.args.get("status")
    if status in ("pending", "qualified", "dismissed"):
        extra += " AND r.status=?"; params = params + (status,)
    rows = conn.execute(
        f"""SELECT r.*, s.first_name, s.last_name, s.code, c.name AS class_name, u.name AS reporter, h.name AS handler
            FROM incident_reports r JOIN students s ON s.id=r.student_id LEFT JOIN classes c ON c.id=r.class_id JOIN users u ON u.id=r.reported_by LEFT JOIN users h ON h.id=r.handled_by
            WHERE {where}{extra} ORDER BY (r.status<>'pending'), r.created_at DESC LIMIT 200""", params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/incident-reports/<report_id>/qualify")
@require_auth
def qualify_report(report_id):
    if not _is_dd():
        return _denied("report.qualify")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    report = conn.execute("SELECT * FROM incident_reports WHERE id=? AND tenant_id=?", (report_id, tenant_id)).fetchone()
    if not report:
        conn.close()
        return _not_found("report.qualify")
    student = school.resolve_student_access(conn, g.ctx, report["student_id"])
    if not student:
        conn.close()
        return _not_found("report.qualify")
    if report["status"] != "pending":
        conn.close()
        return jsonify({"error": "Ce signalement a déjà été traité."}), 409
    payload = dict(data)
    payload.setdefault("title", (data.get("title") or report["description"][:80]))
    payload.setdefault("description", report["description"])
    payload.setdefault("occurred_at", report["occurred_at"])
    incident, info = disc.create_incident(conn, g.ctx, student, payload, report_id=report_id)
    now = str(time.time())
    conn.execute("UPDATE incident_reports SET status='qualified', incident_id=?, handled_by=?, handled_at=?, handling_note=? WHERE id=?",
                 (incident["id"], g.ctx["user_id"], now, (data.get("handling_note") or "").strip()[:300] or None, report_id))
    conn.commit()
    r = dict(conn.execute("SELECT * FROM incident_reports WHERE id=?", (report_id,)).fetchone())
    notif_module.on_report_handled(conn, tenant_id, student, r)
    conn.close()
    return jsonify({"ok": True, "incident_id": incident["id"], "balance": info["balance"], "crossed": info["crossed"]}), 201


@bp.post("/api/incident-reports/<report_id>/dismiss")
@require_auth
def dismiss_report(report_id):
    if not _is_dd():
        return _denied("report.dismiss")
    note = ((json_object(request.get_json(force=True))).get("note") or "").strip()[:300] or None
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    report = conn.execute("SELECT * FROM incident_reports WHERE id=? AND tenant_id=?", (report_id, tenant_id)).fetchone()
    if not report or not school.resolve_student_access(conn, g.ctx, report["student_id"]):
        conn.close()
        return _not_found("report.dismiss")
    if report["status"] != "pending":
        conn.close()
        return jsonify({"error": "Ce signalement a déjà été traité."}), 409
    conn.execute("UPDATE incident_reports SET status='dismissed', handled_by=?, handled_at=?, handling_note=? WHERE id=?", (g.ctx["user_id"], str(time.time()), note, report_id))
    conn.commit()
    student = conn.execute("SELECT * FROM students WHERE id=?", (report["student_id"],)).fetchone()
    notif_module.on_report_handled(conn, tenant_id, student, dict(conn.execute("SELECT * FROM incident_reports WHERE id=?", (report_id,)).fetchone()))
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "discipline.report_dismissed", "incident_report", report_id, "success")
    return jsonify({"ok": True})


# ===========================================================================
# CYCLE DE VIE DES INCIDENTS, CORRECTIONS, CONVOCATIONS
# ===========================================================================

@bp.get("/api/incidents/<incident_id>")
@require_auth
def incident_detail(incident_id):
    conn = db.get_connection()
    inc = conn.execute("SELECT i.*, u.name AS recorded_by_name, r.label AS rule_label FROM incidents i LEFT JOIN users u ON u.id=i.recorded_by LEFT JOIN discipline_rules r ON r.id=i.rule_id WHERE i.id=? AND i.tenant_id=?",
                       (incident_id, g.ctx["tenant_id"])).fetchone()
    if not inc or not school.resolve_student_access(conn, g.ctx, inc["student_id"]) or (g.ctx["role"] == "parent" and not inc["notify_parent"]):
        conn.close()
        return _not_found("incident.detail")
    d = dict(inc)
    if g.ctx["role"] not in ("directeur", "discipline"):
        d.pop("internal_note", None)
    d["replies"] = [dict(r) for r in conn.execute("SELECT r.id, r.body, r.created_at, u.name AS author, m.role AS author_role FROM incident_replies r JOIN users u ON u.id=r.user_id LEFT JOIN memberships m ON m.user_id=r.user_id AND m.tenant_id=r.tenant_id WHERE r.incident_id=? ORDER BY r.created_at", (incident_id,))]
    d["convocations"] = [dict(r) for r in conn.execute("SELECT * FROM convocations WHERE incident_id=? ORDER BY scheduled_on", (incident_id,))] if g.ctx["role"] != "professeur" else []
    conn.close()
    return jsonify(d)


@bp.post("/api/incidents/<incident_id>/status")
@require_auth
def incident_status(incident_id):
    if not _is_dd():
        return _denied("incident.status")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    inc = conn.execute("SELECT * FROM incidents WHERE id=? AND tenant_id=?", (incident_id, g.ctx["tenant_id"])).fetchone()
    if not inc or not school.resolve_student_access(conn, g.ctx, inc["student_id"]):
        conn.close()
        return _not_found("incident.status")
    disc.set_incident_status(conn, g.ctx, dict(inc), data.get("status"), data.get("action_taken"))
    if data.get("status") == "decided" and inc["notify_parent"]:
        student = conn.execute("SELECT * FROM students WHERE id=?", (inc["student_id"],)).fetchone()
        settings = school.get_settings(conn, g.ctx["tenant_id"])
        if settings.get("parent_notify_incidents"):
            notif_module.send(conn, g.ctx["tenant_id"], notif_module.guardian_users(conn, g.ctx["tenant_id"], inc["student_id"]),
                              f"Décision concernant {student['first_name']}", f"« {inc['title']} » — mesure : {(data.get('action_taken') or inc['action_taken'] or '—')}.",
                              link=f"eleve-dossier.html?id={inc['student_id']}&tab=discipline", kind="discipline", dedupe=False)
    conn.close()
    return jsonify({"ok": True})


@bp.post("/api/students/<student_id>/points-adjust")
@require_auth
def adjust_points(student_id):
    """« Vous lui avez retiré X points ; voulez-vous modifier ? » — toute
    correction est une nouvelle ligne tracée, jamais un effacement."""
    if not _is_dd():
        return _denied("points.adjust")
    data = json_object(request.get_json(force=True))
    reason = required_text(data.get("reason"), "reason", 300)
    try:
        points = int(data.get("points"))
    except (TypeError, ValueError):
        raise ValidationError("points doit être un entier (positif pour rendre des points, négatif pour en retirer).")
    if points == 0:
        raise ValidationError("points ne peut pas être nul.")
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("points.adjust")
    incident, info = disc.create_incident(conn, g.ctx, student, {
        "title": ("Correction : " if points > 0 else "Retrait : ") + reason, "category": "correction" if points > 0 else "autre",
        "points": points, "severity": "low", "description": reason, "notify_parent": bool(data.get("notify_parent", True)), "status": "closed",
    })
    conn.close()
    return jsonify({"ok": True, "incident_id": incident["id"], "balance": info["balance"], "crossed": info["crossed"]}), 201


@bp.post("/api/convocations")
@require_auth
def create_convocation():
    if not _is_dd():
        return _denied("convocation.create")
    data = json_object(request.get_json(force=True))
    motif = required_text(data.get("motif"), "motif", 300)
    day = (data.get("scheduled_on") or "").strip()
    if not ISO_DATE.match(day):
        raise ValidationError("scheduled_on doit être au format AAAA-MM-JJ.")
    t = (data.get("scheduled_time") or "").strip()[:5] or None
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, data.get("student_id"))
    if not student:
        conn.close()
        return _not_found("convocation.create")
    incident_id = data.get("incident_id") or None
    if incident_id and not conn.execute("SELECT 1 FROM incidents WHERE id=? AND tenant_id=? AND student_id=?", (incident_id, tenant_id, student["id"])).fetchone():
        conn.close()
        return jsonify({"error": "Incident introuvable pour cet élève."}), 404
    cid = new_id()
    now = str(time.time())
    conn.execute("INSERT INTO convocations (id, tenant_id, student_id, incident_id, scheduled_on, scheduled_time, motif, status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'planned',?,?,?)",
                 (cid, tenant_id, student["id"], incident_id, day, t, motif, g.ctx["user_id"], now, now))
    if incident_id:
        conn.execute("UPDATE incidents SET status='convocation' WHERE id=? AND status='open'", (incident_id,))
    conn.commit()
    conv = {"scheduled_on": day, "scheduled_time": t, "motif": motif}
    event = events_module.emit(conn, tenant_id, "discipline.convocation.created", "convocation", cid, g.ctx["user_id"], payload={"student_id": student["id"], "date": day})
    notif_module.on_convocation(conn, tenant_id, student, conv, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "discipline.convocation_created", "convocation", cid, "success", after={"date": day})
    return jsonify({"id": cid}), 201


@bp.get("/api/convocations")
@require_auth
def list_convocations():
    if not _is_dd():
        return _denied("convocation.list")
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    status = request.args.get("status")
    extra = " AND cv.status=?" if status in ("planned", "held", "missed", "cancelled") else ""
    rows = conn.execute(
        f"""SELECT cv.*, s.first_name, s.last_name, s.code, c.name AS class_name, i.title AS incident_title, u.name AS created_by_name
            FROM convocations cv JOIN students s ON s.id=cv.student_id LEFT JOIN classes c ON c.id=s.class_id LEFT JOIN incidents i ON i.id=cv.incident_id LEFT JOIN users u ON u.id=cv.created_by
            WHERE {where}{extra} ORDER BY (cv.status<>'planned'), cv.scheduled_on DESC LIMIT 200""", params + ((status,) if extra else ())).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/convocations/<conv_id>/status")
@require_auth
def convocation_status(conv_id):
    if not _is_dd():
        return _denied("convocation.status")
    data = json_object(request.get_json(force=True))
    status = data.get("status")
    if status not in ("planned", "held", "missed", "cancelled"):
        raise ValidationError("status invalide.")
    conn = db.get_connection()
    conv = conn.execute("SELECT * FROM convocations WHERE id=? AND tenant_id=?", (conv_id, g.ctx["tenant_id"])).fetchone()
    if not conv or not school.resolve_student_access(conn, g.ctx, conv["student_id"]):
        conn.close()
        return _not_found("convocation.status")
    conn.execute("UPDATE convocations SET status=?, parent_attended=?, notes=?, updated_at=? WHERE id=?",
                 (status, 1 if data.get("parent_attended") else (0 if status in ("held", "missed") else None), (data.get("notes") or "").strip()[:600] or None, str(time.time()), conv_id))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "discipline.convocation_status", "convocation", conv_id, "success", after={"status": status})
    return jsonify({"ok": True})


# ===========================================================================
# SEUILS, CAPITAL, RÈGLEMENT
# ===========================================================================

@bp.get("/api/discipline/thresholds")
@require_auth
def get_thresholds():
    if g.ctx["role"] == "parent":
        return _denied("thresholds.read")
    conn = db.get_connection()
    settings = school.get_settings(conn, g.ctx["tenant_id"])
    ths = school.thresholds(conn, g.ctx["tenant_id"])
    conn.close()
    return jsonify({"capital": int(settings.get("discipline_capital") or 100), "thresholds": ths, "conduct_scale": school.conduct_scale(settings)})


@bp.put("/api/discipline/thresholds")
@require_auth
def put_thresholds():
    if g.ctx["role"] != "directeur":
        return _denied("thresholds.update")
    data = json_object(request.get_json(force=True))
    items = data.get("thresholds")
    if not isinstance(items, list) or not items:
        raise ValidationError("thresholds doit être une liste non vide.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    clean = []
    for it in items:
        try:
            pts = int(it.get("remaining_points"))
        except (TypeError, ValueError, AttributeError):
            raise ValidationError("remaining_points doit être un entier.")
        clean.append((pts, required_text(it.get("label"), "label", 80), (it.get("action") or "").strip()[:200] or None))
    conn.execute("DELETE FROM discipline_thresholds WHERE tenant_id=?", (tenant_id,))
    for i, (pts, label, action) in enumerate(sorted(clean, key=lambda x: -x[0])):
        conn.execute("INSERT INTO discipline_thresholds (id, tenant_id, remaining_points, label, action, sort) VALUES (?,?,?,?,?,?)", (new_id(), tenant_id, pts, label, action, i))
    if "capital" in data:
        try:
            cap = int(data["capital"])
        except (TypeError, ValueError):
            raise ValidationError("capital doit être un entier.")
        if not 10 <= cap <= 1000:
            raise ValidationError("capital doit être compris entre 10 et 1000.")
        school.save_settings(conn, tenant_id, {"discipline_capital": cap})
    if "conduct_scale" in data:
        scale = data["conduct_scale"]
        if not isinstance(scale, list) or not all(isinstance(x, list) and len(x) == 2 for x in scale):
            raise ValidationError("conduct_scale doit être une liste de [pourcentage, libellé].")
        school.save_settings(conn, tenant_id, {"conduct_scale": json.dumps([[int(a), str(b)[:40]] for a, b in scale])})
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "discipline.thresholds_updated", "tenant", tenant_id, "success")
    return jsonify({"ok": True})


RULE_KEYWORDS = [
    (r"retard", "retard", -2, "low"), (r"absence|absent", "absence", -5, "medium"),
    (r"bagarre|violence|coup|agress|arme", "comportement", -15, "high"), (r"vol|fraude|trich", "comportement", -10, "high"),
    (r"insolen|irrespect|injure|insult|impoli", "comportement", -5, "medium"), (r"t[ée]l[ée]phone|portable|smartphone", "comportement", -3, "low"),
    (r"tenue|uniforme|coiffure|chaussure", "comportement", -2, "low"), (r"exclu|renvoi|renvoy", "comportement", -20, "high"),
    (r"drogue|alcool|cigarette|tabac", "comportement", -15, "high"), (r"devoir|cahier|mat[ée]riel", "autre", -1, "low"),
    (r"m[ée]rite|f[ée]licit|bonne conduite|r[ée]compense", "bonus", 2, "low"),
]


def _extract_text(file_storage):
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if filename.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((p.extract_text() or "") for p in reader.pages), raw
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError:
        return raw.decode("latin-1"), raw


@bp.post("/api/discipline/reglement/analyze")
@require_auth
def analyze_reglement():
    """Lecture structurée du règlement (PDF ou texte) : propose des règles à
    valider — jamais appliquées sans confirmation de la Direction. Pas de
    modèle de langage : détection par articles numérotés et mots-clés."""
    if g.ctx["role"] != "directeur":
        return _denied("reglement.analyze")
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier reçu (PDF ou texte)."}), 400
    text, raw = _extract_text(request.files["file"])
    text = re.sub(r"[ \t]+", " ", text or "")
    if len(text.strip()) < 40:
        return jsonify({"error": "Aucun texte lisible dans ce fichier — s'il s'agit d'un scan, il faut un PDF avec texte (ou saisir les règles à la main)."}), 400
    # Découpage : articles numérotés (« Article 12 », « Art. 3 », « 4. », « 4) », « - ») sinon phrases.
    chunks = re.split(r"\n(?=\s*(?:article\s*\d+|art\.?\s*\d+|\d{1,2}[.)\-]\s|[•\-–]\s))", text, flags=re.I)
    if len(chunks) < 3:
        chunks = re.split(r"(?<=[.;])\s+", text)
    proposals, seen = [], set()
    for c in chunks:
        line = " ".join(c.split()).strip(" -•–")
        if len(line) < 12 or len(line) > 400:
            continue
        low = line.lower()
        match = next(((cat, pts, sev) for pat, cat, pts, sev in RULE_KEYWORDS if re.search(pat, low)), None)
        if not match:
            continue
        cat, pts, sev = match
        if re.search(r"interdit|sanction|pass?ible|entra[iî]ne|expos|puni|avertissement|exclu", low) and pts < 0 and pts > -10:
            pts -= 2
        label = line[:110].rstrip(",.;:") + ("…" if len(line) > 110 else "")
        key = label.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        proposals.append({"label": label, "category": cat, "points": pts, "severity": sev, "source": line[:400]})
    conn = db.get_connection()
    existing = {r["label"].lower() for r in conn.execute("SELECT label FROM discipline_rules WHERE tenant_id=? AND active=1", (g.ctx["tenant_id"],))}
    conn.close()
    for p in proposals:
        p["already_exists"] = p["label"].lower() in existing
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "discipline.reglement_analyzed", "tenant", g.ctx["tenant_id"], "success", after={"proposals": len(proposals), "chars": len(text)})
    return jsonify({"proposals": proposals[:60], "text_length": len(text), "chunks": len(chunks), "excerpt": text[:600]})


@bp.post("/api/discipline/reglement/confirm")
@require_auth
def confirm_reglement():
    if g.ctx["role"] != "directeur":
        return _denied("reglement.confirm")
    data = json_object(request.get_json(force=True))
    rules = data.get("rules") or []
    if not isinstance(rules, list) or not rules:
        raise ValidationError("Aucune règle à enregistrer.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    created = 0
    now = str(time.time())
    for r in rules:
        label = required_text(r.get("label"), "label", 120)
        cat = r.get("category") if r.get("category") in ("retard", "absence", "comportement", "bonus", "autre") else "autre"
        try:
            pts = int(r.get("points", 0))
        except (TypeError, ValueError):
            raise ValidationError(f"points invalide pour « {label} ».")
        if abs(pts) > 100:
            raise ValidationError("points doit rester entre -100 et 100.")
        conn.execute("INSERT INTO discipline_rules (id, tenant_id, label, category, points, active, created_at) VALUES (?,?,?,?,?,1,?)", (new_id(), tenant_id, label, cat, pts, now))
        created += 1
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "discipline.reglement_confirmed", "tenant", tenant_id, "success", after={"rules": created})
    return jsonify({"ok": True, "created": created}), 201


# ===========================================================================
# REGISTRES IMPRIMABLES (présence, discipline)
# ===========================================================================

@bp.get("/api/registers/attendance")
@require_auth
def register_attendance():
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, request.args.get("class_id"))
    if not cls or g.ctx["role"] == "parent":
        conn.close()
        return _not_found("register.attendance")
    start = request.args.get("from") or (date.today() - timedelta(days=30)).isoformat()
    end = request.args.get("to") or school.today_iso()
    if not (ISO_DATE.match(start) and ISO_DATE.match(end)):
        raise ValidationError("from/to doivent être au format AAAA-MM-JJ.")
    tenant_id = g.ctx["tenant_id"]
    students = [dict(r) for r in conn.execute("SELECT id, first_name, last_name, code FROM students WHERE tenant_id=? AND class_id=? AND status='active' ORDER BY last_name, first_name", (tenant_id, cls["id"]))]
    days = sorted({r["date"] for r in conn.execute("SELECT DISTINCT date FROM attendance WHERE tenant_id=? AND class_id=? AND date BETWEEN ? AND ?", (tenant_id, cls["id"], start, end))})
    marks = {}
    for r in conn.execute("SELECT student_id, date, status, arrival_time FROM attendance WHERE tenant_id=? AND class_id=? AND date BETWEEN ? AND ?", (tenant_id, cls["id"], start, end)):
        marks.setdefault(r["student_id"], {})[r["date"]] = {"present": "P", "late": "R", "absent": "A", "excused": "E"}[r["status"]]
    for s in students:
        s["marks"] = marks.get(s["id"], {})
        s["totals"] = {k: sum(1 for v in s["marks"].values() if v == k) for k in ("P", "R", "A", "E")}
    tenant = conn.execute("SELECT name FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    conn.close()
    return jsonify({"school": tenant["name"], "class": {"id": cls["id"], "name": cls["name"], "cycle": cls["cycle"]}, "from": start, "to": end, "days": days, "students": students})


@bp.get("/api/registers/discipline")
@require_auth
def register_discipline():
    if not _is_dd():
        return _denied("register.discipline")
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, request.args.get("class_id")) if request.args.get("class_id") else None
    if request.args.get("class_id") and not cls:
        conn.close()
        return _not_found("register.discipline")
    start = request.args.get("from") or (date.today() - timedelta(days=90)).isoformat()
    end = request.args.get("to") or school.today_iso()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify({"rows": []})
    extra = " AND i.class_id=?" if cls else ""
    rows = conn.execute(
        f"""SELECT i.occurred_at, i.title, i.category, i.severity, i.points, i.action_taken, i.status, s.first_name, s.last_name, s.code, c.name AS class_name, u.name AS recorded_by_name
            FROM incidents i JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=i.class_id LEFT JOIN users u ON u.id=i.recorded_by
            WHERE {where} AND i.occurred_at BETWEEN ? AND ?{extra} ORDER BY i.occurred_at, s.last_name""", params + (start, end) + ((cls["id"],) if cls else ())).fetchall()
    tenant = conn.execute("SELECT name FROM tenants WHERE id=?", (g.ctx["tenant_id"],)).fetchone()
    conn.close()
    return jsonify({"school": tenant["name"], "class": dict(cls) if cls else None, "from": start, "to": end, "rows": [dict(r) for r in rows]})
