"""KLASSIO backend — routes du dossier central de l'élève et des domaines
rattachés (équipe, classes, présences, discipline, résultats, horaires,
examens, boutique, reçus, notifications, réglages).

Chaque route :
  1. résout le contexte depuis la session serveur (require_auth → g.ctx) ;
  2. vérifie la permission du rôle (security.ROLE_PERMISSIONS) ;
  3. réduit le périmètre aux données réellement autorisées (school.py) ;
  4. journalise les refus (audit).
Aucune de ces trois étapes ne dépend d'un champ envoyé par le client.
"""
import json
import re
import time
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, g

import db
import security
import financial
import events as events_module
import notifications as notif_module
import school
import discipline as disc
from security import require_auth, new_id, audit, has_permission
from validation import (json_object, ValidationError, required_text, positive_amount, valid_phone, valid_hex_color,
                        valid_password, valid_email, image_data_uri, DATA_URI_IMAGE)

bp = Blueprint("school", __name__)

ATTENDANCE_STATUSES = ("present", "late", "absent", "excused")
INCIDENT_SEVERITIES = ("low", "medium", "high")
ORDER_STATUSES = ("pending", "paid", "delivered", "cancelled")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _denied(action, resource_type=None, resource_id=None, message="Vous n'avez pas l'autorisation d'effectuer cette action."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, resource_type, resource_id, "denied")
    return jsonify({"error": message}), 403


def _not_found(action, resource_type=None, resource_id=None, message="Introuvable ou accès non autorisé."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, resource_type, resource_id, "denied")
    return jsonify({"error": message}), 404


def _est_image_valide(valeur, limite):
    """Forme stricte d'une image en data URI (voir validation.DATA_URI_IMAGE)."""
    return isinstance(valeur, str) and len(valeur) <= limite and bool(DATA_URI_IMAGE.match(valeur))


def _has(perm):
    return has_permission(g.ctx["role"], perm)


def _iso_date(value, field="date"):
    value = (value or school.today_iso()).strip()
    if not ISO_DATE.match(value):
        raise ValidationError(f"{field} doit être au format AAAA-MM-JJ.")
    return value


# ===========================================================================
# DOSSIER CENTRAL DE L'ÉLÈVE
# ===========================================================================

@bp.get("/api/students/<student_id>")
@require_auth
def get_student_dossier(student_id):
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("student.dossier", "student", student_id, "Élève introuvable ou accès non autorisé.")
    dossier = school.build_dossier(conn, g.ctx, student, financial)
    conn.close()
    return jsonify(dossier)


@bp.put("/api/students/<student_id>")
@require_auth
def update_student(student_id):
    if not _has("students.manage"):
        return _denied("student.update", "student", student_id)
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    student = conn.execute("SELECT * FROM students WHERE id=? AND tenant_id=?", (student_id, g.ctx["tenant_id"])).fetchone()
    if not student:
        conn.close()
        return _not_found("student.update", "student", student_id)
    fields, params = [], []
    if "first_name" in data:
        fields.append("first_name=?"); params.append(required_text(data["first_name"], "first_name", 100))
    if "last_name" in data:
        fields.append("last_name=?"); params.append(required_text(data["last_name"], "last_name", 100))
    if "gender" in data:
        if data["gender"] not in (None, "", "F", "M"):
            raise ValidationError("gender doit être F ou M.")
        fields.append("gender=?"); params.append(data["gender"] or None)
    if "birth_date" in data:
        bd = data["birth_date"] or None
        if bd and not ISO_DATE.match(bd):
            raise ValidationError("birth_date doit être au format AAAA-MM-JJ.")
        fields.append("birth_date=?"); params.append(bd)
    if "status" in data:
        if data["status"] not in ("active", "archived", "transferred"):
            raise ValidationError("status invalide.")
        fields.append("status=?"); params.append(data["status"])
    if "class_id" in data:
        cid = data["class_id"] or None
        if cid and not conn.execute("SELECT 1 FROM classes WHERE id=? AND tenant_id=?", (cid, g.ctx["tenant_id"])).fetchone():
            conn.close()
            return jsonify({"error": "Classe introuvable pour cet établissement."}), 404
        fields.append("class_id=?"); params.append(cid)
    if "photo_data" in data:
        # Forme stricte imposée (voir validation.image_data_uri) : un simple
        # `startswith("data:image/")` laissait passer une chaîne contenant un
        # guillemet, qui s'échappait ensuite de l'attribut `src` du frontend.
        photo = image_data_uri(data["photo_data"], "La photo", max_length=400_000)
        fields.append("photo_data=?"); params.append(photo)
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification fournie."}), 400
    params += [student_id, g.ctx["tenant_id"]]
    conn.execute(f"UPDATE students SET {', '.join(fields)} WHERE id=? AND tenant_id=?", params)
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "student.updated", "student", student_id, "success",
          after={k: ("<photo>" if k == "photo_data" else v) for k, v in data.items()})
    return jsonify({"ok": True})


@bp.get("/api/students/<student_id>/bulletin")
@require_auth
def student_bulletin(student_id):
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("student.bulletin", "student", student_id)
    # only_published : cette route l'omettait, alors que la composition du
    # dossier élève (school.py) le passait correctement. Un parent obtenait
    # donc par /bulletin des résultats que /students lui refusait — y compris
    # des résultats jamais proclamés, ou proclamés pour d'autres classes que
    # celle de son enfant.
    result = school.bulletin(conn, g.ctx["tenant_id"], student,
                             period=request.args.get("period"),
                             only_published=(g.ctx["role"] == "parent"))
    result["student"] = {"id": student["id"], "code": student["code"], "first_name": student["first_name"],
                         "last_name": student["last_name"], "class_name": student["class_name"]}
    tenant = conn.execute("SELECT name FROM tenants WHERE id=?", (g.ctx["tenant_id"],)).fetchone()
    result["school_name"] = tenant["name"] if tenant else ""
    conn.close()
    return jsonify(result)


# ===========================================================================
# ÉQUIPE & CLASSES
# ===========================================================================

@bp.get("/api/team")
@require_auth
def list_team():
    if g.ctx["role"] not in ("directeur", "discipline"):
        return _denied("team.read")
    conn = db.get_connection()
    rows = conn.execute(
        """SELECT u.id, u.name, u.email, u.phone, m.role, m.created_at, m.title, m.scope_cycles FROM memberships m JOIN users u ON u.id = m.user_id
           WHERE m.tenant_id=? AND m.status='active' ORDER BY m.role, u.name""",
        (g.ctx["tenant_id"],),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["email"] = school.display_email(d.get("email"))
        if g.ctx["role"] != "directeur":
            d.pop("email", None)
        if r["role"] == "professeur":
            d["classes"] = [dict(c) for c in conn.execute(
                """SELECT c.id, c.name, ct.subject, ct.is_titulaire FROM class_teachers ct JOIN classes c ON c.id = ct.class_id
                   WHERE ct.tenant_id=? AND ct.user_id=? ORDER BY c.name""", (g.ctx["tenant_id"], r["id"]))]
        result.append(d)
    conn.close()
    return jsonify(result)


def _class_detail(conn, ctx, cls):
    tenant_id = ctx["tenant_id"]
    d = dict(cls)
    d["student_count"] = conn.execute("SELECT COUNT(*) n FROM students WHERE tenant_id=? AND class_id=? AND status='active'",
                                      (tenant_id, cls["id"])).fetchone()["n"]
    d["teachers"] = [dict(t) for t in conn.execute(
        """SELECT u.id AS user_id, u.name, ct.subject, ct.is_titulaire FROM class_teachers ct JOIN users u ON u.id = ct.user_id
           WHERE ct.tenant_id=? AND ct.class_id=? ORDER BY ct.is_titulaire DESC, u.name""", (tenant_id, cls["id"]))]
    d["titulaire"] = next((t for t in d["teachers"] if t["is_titulaire"]), None)
    today = school.today_iso()
    att = conn.execute(
        """SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) p, SUM(CASE WHEN status='late' THEN 1 ELSE 0 END) l, SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) a, SUM(CASE WHEN status='excused' THEN 1 ELSE 0 END) e, COUNT(*) n
           FROM attendance WHERE tenant_id=? AND class_id=? AND date=?""", (tenant_id, cls["id"], today)).fetchone()
    d["attendance_today"] = {"present": att["p"] or 0, "late": att["l"] or 0, "absent": att["a"] or 0,
                             "excused": att["e"] or 0, "recorded": att["n"] or 0, "date": today}
    if ctx["role"] == "professeur":
        d["is_titulaire"] = school.is_titulaire_of(conn, ctx, cls["id"])
    return d


@bp.put("/api/team/<user_id>")
@require_auth
def update_member(user_id):
    """Direction : titre (ex. « Adjoint ») et périmètre d'un DD (cycles)."""
    if not _has("team.manage"):
        return _denied("team.update", "user", user_id)
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    m = conn.execute("SELECT * FROM memberships WHERE tenant_id=? AND user_id=? AND status='active'", (g.ctx["tenant_id"], user_id)).fetchone()
    if not m or m["role"] == "directeur":
        conn.close()
        return _not_found("team.update", "user", user_id)
    fields, params = [], []
    if "title" in data:
        fields.append("title=?"); params.append((data["title"] or "").strip()[:60] or None)
    if "scope_cycles" in data:
        cycles = [c for c in (data["scope_cycles"] or []) if c in ("maternelle", "primaire", "secondaire")]
        if m["role"] != "discipline":
            conn.close()
            return jsonify({"error": "Le périmètre par cycle ne s'applique qu'au Directeur des disciplines."}), 400
        if not cycles:
            raise ValidationError("Choisissez au moins un cycle.")
        import json as _json
        fields.append("scope_cycles=?"); params.append(_json.dumps(cycles))
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification fournie."}), 400
    conn.execute(f"UPDATE memberships SET {', '.join(fields)} WHERE id=?", params + [m["id"]])
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "team.member_updated", "user", user_id, "success", after=data)
    return jsonify({"ok": True})


@bp.get("/api/classes/<class_id>")
@require_auth
def get_class(class_id):
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls:
        conn.close()
        return _not_found("class.read", "class", class_id, "Classe introuvable ou accès non autorisé.")
    d = _class_detail(conn, g.ctx, cls)
    d["schedule"] = school.schedule_for_class(conn, g.ctx["tenant_id"], class_id)
    d["exams"] = school.exams_for_class(conn, g.ctx["tenant_id"], class_id)
    d["finance_visible"] = school.finance_visible(conn, g.ctx) and g.ctx["role"] != "parent"
    conn.close()
    return jsonify(d)


@bp.put("/api/classes/<class_id>")
@require_auth
def update_class(class_id):
    if not _has("classes.manage"):
        return _denied("class.update", "class", class_id)
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    cls = conn.execute("SELECT * FROM classes WHERE id=? AND tenant_id=?", (class_id, g.ctx["tenant_id"])).fetchone()
    if not cls:
        conn.close()
        return _not_found("class.update", "class", class_id)
    fields, params = [], []
    if "name" in data:
        fields.append("name=?"); params.append(required_text(data["name"], "name", 100))
    if "level" in data:
        fields.append("level=?"); params.append((data["level"] or "").strip() or None)
    if "cycle" in data:
        if data["cycle"] not in ("maternelle", "primaire", "secondaire"):
            raise ValidationError("cycle doit être maternelle, primaire ou secondaire.")
        fields.append("cycle=?"); params.append(data["cycle"])
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification fournie."}), 400
    params += [class_id, g.ctx["tenant_id"]]
    conn.execute(f"UPDATE classes SET {', '.join(fields)} WHERE id=? AND tenant_id=?", params)
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "class.updated", "class", class_id, "success", after=data)
    return jsonify({"ok": True})


@bp.post("/api/classes/<class_id>/teachers")
@require_auth
def assign_teacher(class_id):
    if not _has("team.manage"):
        return _denied("class.assign_teacher", "class", class_id)
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    cls = conn.execute("SELECT id FROM classes WHERE id=? AND tenant_id=?", (class_id, tenant_id)).fetchone()
    member = conn.execute("SELECT 1 FROM memberships WHERE user_id=? AND tenant_id=? AND role='professeur' AND status='active'",
                          (data.get("user_id"), tenant_id)).fetchone()
    if not cls or not member:
        conn.close()
        return jsonify({"error": "Classe ou professeur introuvable pour cet établissement."}), 404
    is_tit = 1 if data.get("is_titulaire") else 0
    if is_tit:
        # Un seul titulaire par classe : le nouveau remplace explicitement l'ancien.
        conn.execute("UPDATE class_teachers SET is_titulaire=0 WHERE tenant_id=? AND class_id=?", (tenant_id, class_id))
    conn.execute(
        """INSERT INTO class_teachers (id, tenant_id, class_id, user_id, subject, is_titulaire, created_at) VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(class_id, user_id) DO UPDATE SET subject=excluded.subject, is_titulaire=excluded.is_titulaire""",
        (new_id(), tenant_id, class_id, data["user_id"], (data.get("subject") or "").strip() or None, is_tit, str(time.time())),
    )
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "class.teacher_assigned", "class", class_id, "success",
          after={"user_id": data["user_id"], "is_titulaire": is_tit})
    return jsonify({"ok": True}), 201


@bp.delete("/api/classes/<class_id>/teachers/<user_id>")
@require_auth
def unassign_teacher(class_id, user_id):
    if not _has("team.manage"):
        return _denied("class.unassign_teacher", "class", class_id)
    conn = db.get_connection()
    # rowcount vérifié : voir delete_rule plus bas (faux succès). Ici le
    # journal d'audit était en plus alimenté d'un « success » pour un
    # détachement qui n'avait jamais eu lieu.
    curseur = conn.execute("DELETE FROM class_teachers WHERE tenant_id=? AND class_id=? AND user_id=?", (g.ctx["tenant_id"], class_id, user_id))
    conn.commit()
    conn.close()
    if not (curseur.rowcount or 0):
        return _not_found("class.unassign_teacher", "class", class_id,
                          "Ce professeur n'est pas rattaché à cette classe dans votre établissement.")
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "class.teacher_unassigned", "class", class_id, "success", after={"user_id": user_id})
    return jsonify({"ok": True})


@bp.get("/api/classes/<class_id>/students")
@require_auth
def class_students(class_id):
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls:
        conn.close()
        return _not_found("class.students", "class", class_id, "Classe introuvable ou accès non autorisé.")
    tenant_id = g.ctx["tenant_id"]
    day = _iso_date(request.args.get("date"))
    show_finance = school.finance_visible(conn, g.ctx) and g.ctx["role"] != "parent"
    rows = conn.execute(
        """SELECT s.id, s.code, s.first_name, s.last_name, s.gender, s.status, s.photo_data IS NOT NULL AS has_photo,
                  a.status AS attendance_status, a.note AS attendance_note,
                  COALESCE(ob.total_due,0) AS total_due, COALESCE(pay.total_paid,0) AS total_paid,
                  COALESCE(pts.points,0) AS discipline_points,
                  -- x.tenant_id = s.tenant_id : ce n'est pas une redondance, c'est
                  -- la colonne de TÊTE des index (tenant_id, student_id). Sans
                  -- elle, chaque sous-requête balaie toute la table attendance,
                  -- qui grossit d'environ 10 000 lignes par jour de classe.
                  -- Mesuré sur 80 jours : 29 875 ms → 12,4 ms (2 418×).
                  (SELECT COUNT(*) FROM attendance x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.status='absent') AS absences_unjustified,
                  (SELECT COUNT(*) FROM attendance x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.status='excused') AS absences_justified,
                  (SELECT COUNT(*) FROM attendance x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.status='late') AS lates,
                  (SELECT COUNT(*) FROM incidents x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.points < 0) AS faults
           FROM students s
           LEFT JOIN attendance a ON a.student_id = s.id AND a.tenant_id = s.tenant_id AND a.date = ?
           LEFT JOIN (SELECT student_id, SUM(amount) total_due FROM obligations WHERE tenant_id=? GROUP BY student_id) ob ON ob.student_id = s.id
           LEFT JOIN (SELECT o.student_id, SUM(p.amount) total_paid FROM payments p JOIN obligations o ON o.id=p.obligation_id
                      WHERE p.tenant_id=? AND p.status='CONFIRMED' GROUP BY o.student_id) pay ON pay.student_id = s.id
           LEFT JOIN (SELECT student_id, SUM(points) points FROM incidents WHERE tenant_id=? GROUP BY student_id) pts ON pts.student_id = s.id
           WHERE s.tenant_id=? AND s.class_id=? AND s.status='active' ORDER BY s.last_name, s.first_name""",
        (day, tenant_id, tenant_id, tenant_id, tenant_id, class_id),
    ).fetchall()
    settings = school.get_settings(conn, tenant_id)
    capital = int(settings.get("discipline_capital") or 100)
    result = []
    for r in rows:
        d = dict(r)
        if show_finance:
            d["balance"] = round((d["total_due"] or 0) - (d["total_paid"] or 0), 2)
        else:
            d.pop("total_due", None); d.pop("total_paid", None)
        d["points_remaining"] = max(0, min(capital, capital + (d["discipline_points"] or 0)))
        d["capital"] = capital
        if g.ctx["role"] == "parent":
            d.pop("discipline_points", None); d.pop("points_remaining", None); d.pop("faults", None)
        result.append(d)
    class_info = _class_detail(conn, g.ctx, cls)
    conn.close()
    return jsonify({"class": class_info, "date": day, "finance_visible": show_finance, "students": result})


# ===========================================================================
# PRÉSENCES — une donnée centrale, lue par tous les espaces autorisés
# ===========================================================================

@bp.get("/api/classes/<class_id>/attendance")
@require_auth
def get_class_attendance(class_id):
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls or g.ctx["role"] == "parent":
        conn.close()
        return _not_found("attendance.read", "class", class_id, "Classe introuvable ou accès non autorisé.")
    day = _iso_date(request.args.get("date"))
    rows = conn.execute(
        """SELECT a.student_id, a.status, a.note, a.updated_at, u.name AS recorded_by_name FROM attendance a
           LEFT JOIN users u ON u.id = a.recorded_by WHERE a.tenant_id=? AND a.class_id=? AND a.date=?""",
        (g.ctx["tenant_id"], class_id, day),
    ).fetchall()
    conn.close()
    return jsonify({"date": day, "records": [dict(r) for r in rows]})


@bp.post("/api/classes/<class_id>/attendance")
@require_auth
def record_class_attendance(class_id):
    """Appel de la classe : un enregistrement réel par élève. `Présence
    enregistrée` n'est renvoyé qu'après l'écriture effective en base."""
    conn = db.get_connection()
    if not school.can_manage_class_attendance(conn, g.ctx, class_id):
        conn.close()
        return _denied("attendance.record", "class", class_id, "Vous n'êtes pas rattaché(e) à cette classe.")
    data = json_object(request.get_json(force=True))
    day = _iso_date(data.get("date"))
    records = data.get("records") or []
    if not isinstance(records, list) or not records:
        conn.close()
        return jsonify({"error": "Aucun statut de présence fourni."}), 400
    if day > school.today_iso():
        conn.close()
        return jsonify({"error": "Impossible d'enregistrer une présence dans le futur."}), 400

    tenant_id = g.ctx["tenant_id"]
    settings = school.get_settings(conn, tenant_id)
    class_student_ids = {r["id"] for r in conn.execute("SELECT id FROM students WHERE tenant_id=? AND class_id=?", (tenant_id, class_id))}
    now = str(time.time())
    saved, changed, kept_gate = 0, [], 0
    for rec in records:
        sid, status = rec.get("student_id"), rec.get("status")
        if sid not in class_student_ids:
            conn.close()
            return jsonify({"error": "Un élève fourni n'appartient pas à cette classe."}), 400
        if status not in ATTENDANCE_STATUSES:
            conn.close()
            return jsonify({"error": f"Statut de présence inconnu : {status}"}), 400
        note = (rec.get("note") or "").strip()[:200] or None
        previous = conn.execute("SELECT status, source FROM attendance WHERE tenant_id=? AND student_id=? AND date=?", (tenant_id, sid, day)).fetchone()
        # Le retard pointé au portail (heure d'arrivée constatée) prime sur un
        # « présent » saisi ensuite en classe ; il n'est écrasé que par un statut explicite.
        if previous and previous["source"] == "gate" and previous["status"] == "late" and status == "present":
            kept_gate += 1
            saved += 1
            continue
        conn.execute(
            """INSERT INTO attendance (id, tenant_id, student_id, class_id, date, status, note, recorded_by, created_at, updated_at, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,'class')
               ON CONFLICT(tenant_id, student_id, date) DO UPDATE SET status=excluded.status, note=COALESCE(excluded.note, attendance.note),
                 recorded_by=excluded.recorded_by, updated_at=excluded.updated_at, class_id=excluded.class_id, source='class'""",
            (new_id(), tenant_id, sid, class_id, day, status, note, g.ctx["user_id"], now, now),
        )
        saved += 1
        if (previous is None or previous["status"] != status) and status in ("absent", "late"):
            changed.append((sid, status))
    conn.commit()

    event = events_module.emit(conn, tenant_id, "attendance.recorded", "class", class_id, g.ctx["user_id"],
                               payload={"date": day, "count": saved, "absent_or_late": len(changed), "finalized": bool(data.get("finalize"))})
    for sid, status in changed:
        student = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
        notif_module.on_attendance_recorded(conn, tenant_id, student, class_id, status, g.ctx["user_id"], settings, event_id=event["id"])
    # Finalisation : « votre enfant est à l'école » — une fois par enfant et par jour (aujourd'hui seulement).
    present_sent = 0
    if data.get("finalize") and day == school.today_iso():
        for r in conn.execute("SELECT s.* FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.tenant_id=? AND a.class_id=? AND a.date=? AND a.status IN ('present','late')",
                              (tenant_id, class_id, day)).fetchall():
            present_sent += notif_module.on_attendance_present(conn, tenant_id, r, day, settings, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "attendance.recorded", "class", class_id, "success", after={"date": day, "count": saved, "finalized": bool(data.get("finalize"))})
    return jsonify({"ok": True, "saved": saved, "date": day, "notified": len(changed), "present_notified": present_sent, "kept_gate": kept_gate})


@bp.get("/api/attendance/overview")
@require_auth
def attendance_overview():
    """Vue Direction/DD : pour chaque classe visible, l'appel du jour a-t-il
    été fait, et avec quels totaux."""
    if g.ctx["role"] not in ("directeur", "discipline"):
        return _denied("attendance.overview")
    conn = db.get_connection()
    day = _iso_date(request.args.get("date"))
    allowed = school.visible_class_ids(conn, g.ctx)
    where, params = "c.tenant_id=?", [g.ctx["tenant_id"]]
    if allowed is not None:
        if not allowed:
            conn.close()
            return jsonify({"date": day, "classes": []})
        where += f" AND c.id IN ({','.join('?' for _ in allowed)})"
        params += allowed
    rows = conn.execute(
        f"""SELECT c.id, c.name, c.cycle,
                   (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id AND s.status='active') AS student_count,
                   SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) present, SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) late, SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) absent,
                   SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) excused, COUNT(a.id) recorded
            FROM classes c LEFT JOIN attendance a ON a.class_id=c.id AND a.date=? AND a.tenant_id=c.tenant_id
            WHERE {where} GROUP BY c.id ORDER BY c.name""",
        [day] + params,
    ).fetchall()
    conn.close()
    return jsonify({"date": day, "classes": [dict(r) for r in rows]})


# ===========================================================================
# DISCIPLINE — règles configurées par la Direction, incidents par un humain
# ===========================================================================

@bp.get("/api/discipline/rules")
@require_auth
def list_rules():
    if not (_has("discipline.rules.manage") or _has("discipline.rules.read")):
        return _denied("discipline.rules.read")
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM discipline_rules WHERE tenant_id=? ORDER BY category, label", (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/discipline/rules")
@require_auth
def create_rule():
    if not _has("discipline.rules.manage"):
        return _denied("discipline.rules.create")
    data = json_object(request.get_json(force=True))
    label = required_text(data.get("label"), "label", 120)
    category = data.get("category") or "autre"
    if category not in ("retard", "absence", "comportement", "bonus", "autre"):
        raise ValidationError("category invalide.")
    try:
        points = int(data.get("points", 0))
    except (TypeError, ValueError):
        raise ValidationError("points doit être un entier.")
    if abs(points) > 100:
        raise ValidationError("points doit rester entre -100 et 100.")
    conn = db.get_connection()
    rid = new_id()
    conn.execute("INSERT INTO discipline_rules (id, tenant_id, label, category, points, active, created_at) VALUES (?,?,?,?,?,1,?)",
                 (rid, g.ctx["tenant_id"], label, category, points, str(time.time())))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "discipline.rule_created", "discipline_rule", rid, "success", after={"label": label, "points": points})
    return jsonify({"id": rid}), 201


@bp.delete("/api/discipline/rules/<rule_id>")
@require_auth
def delete_rule(rule_id):
    if not _has("discipline.rules.manage"):
        return _denied("discipline.rules.delete")
    conn = db.get_connection()
    # Désactivation, jamais suppression : les incidents passés y font référence.
    # Le rowcount est vérifié : le filtre tenant_id protégeait bien les données
    # d'un autre établissement, mais la route répondait « ok » sans avoir rien
    # modifié. Un succès annoncé pour une opération qui n'a rien fait est un
    # faux succès — l'interface l'affichait comme une désactivation réussie.
    curseur = conn.execute("UPDATE discipline_rules SET active=0 WHERE id=? AND tenant_id=?", (rule_id, g.ctx["tenant_id"]))
    conn.commit()
    conn.close()
    if not (curseur.rowcount or 0):
        return _not_found("discipline.rules.delete", "discipline_rule", rule_id, "Règle introuvable pour cet établissement.")
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "discipline.rule_disabled", "discipline_rule", rule_id, "success")
    return jsonify({"ok": True})


@bp.post("/api/incidents")
@require_auth
def create_incident():
    if not _has("discipline.manage"):
        return _denied("incident.create")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, data.get("student_id"))
    if not student:
        conn.close()
        return _not_found("incident.create", "student", data.get("student_id"), "Élève introuvable ou hors de votre périmètre.")
    incident, info = disc.create_incident(conn, g.ctx, student, data)
    conn.close()
    return jsonify({"id": incident["id"], "points_total": info["balance"]["delta"], "balance": info["balance"],
                    "threshold_reached": bool(info["crossed"]), "crossed": info["crossed"]}), 201


@bp.get("/api/incidents")
@require_auth
def list_incidents():
    """Liste filtrée au périmètre : DD/Direction (leurs classes), professeur
    (ses classes, champs communicables), parent (ses enfants, notify_parent=1)."""
    if not any(_has(p) for p in ("discipline.read", "discipline.read.assigned", "discipline.read.own")):
        return _denied("incident.list")
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    extra = ""
    if request.args.get("student_id"):
        extra += " AND i.student_id = ?"; params = params + (request.args["student_id"],)
    if request.args.get("class_id"):
        extra += " AND i.class_id = ?"; params = params + (request.args["class_id"],)
    if g.ctx["role"] == "parent":
        extra += " AND i.notify_parent = 1"
    limit = min(int(request.args.get("limit", 100)), 500)
    rows = conn.execute(
        f"""SELECT i.*, s.first_name, s.last_name, s.code, c.name AS class_name, u.name AS recorded_by_name, r.label AS rule_label
            FROM incidents i JOIN students s ON s.id = i.student_id LEFT JOIN classes c ON c.id = i.class_id
            LEFT JOIN users u ON u.id = i.recorded_by LEFT JOIN discipline_rules r ON r.id = i.rule_id
            WHERE {where}{extra} ORDER BY i.occurred_at DESC, i.created_at DESC LIMIT ?""",
        params + (limit,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if g.ctx["role"] not in ("directeur", "discipline"):
            d.pop("internal_note", None)
        result.append(d)
    return jsonify(result)


@bp.get("/api/discipline/overview")
@require_auth
def discipline_overview():
    if not _has("discipline.read"):
        return _denied("discipline.overview")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify({"incidents_week": 0, "incidents_month": 0, "students_below_threshold": [], "by_category": [], "threshold": 0})
    settings = school.get_settings(conn, tenant_id)
    capital = int(settings.get("discipline_capital") or 100)
    ths = school.thresholds(conn, tenant_id)
    threshold = (ths[0]["remaining_points"] - capital) if ths else -30  # exprimé en delta de points
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    month_ago = (date.today() - timedelta(days=30)).isoformat()
    week = conn.execute(f"SELECT COUNT(*) n FROM incidents i JOIN students s ON s.id=i.student_id WHERE {where} AND i.occurred_at >= ?", params + (week_ago,)).fetchone()["n"]
    month = conn.execute(f"SELECT COUNT(*) n FROM incidents i JOIN students s ON s.id=i.student_id WHERE {where} AND i.occurred_at >= ?", params + (month_ago,)).fetchone()["n"]
    below = conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, s.code, c.name AS class_name, SUM(i.points) AS points
            FROM incidents i JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=s.class_id
            -- GROUP BY : PostgreSQL n'accepte une colonne nue que si elle appartient à la
            -- table dont la clé primaire est groupée. c.name vient de `classes`, pas de
            -- `students` : elle doit être listée explicitement (SQLite, lui, l'acceptait).
            WHERE {where} GROUP BY s.id, s.first_name, s.last_name, s.code, c.name
            HAVING SUM(i.points) <= ? ORDER BY points ASC LIMIT 20""",
        params + (threshold,),
    ).fetchall()
    by_cat = conn.execute(
        f"""SELECT i.category, COUNT(*) n FROM incidents i JOIN students s ON s.id=i.student_id
            WHERE {where} AND i.occurred_at >= ? GROUP BY i.category ORDER BY n DESC""", params + (month_ago,)).fetchall()
    absences_today = conn.execute(
        f"""SELECT COUNT(*) n FROM attendance a JOIN students s ON s.id=a.student_id WHERE {where} AND a.date=? AND a.status='absent'""",
        params + (school.today_iso(),)).fetchone()["n"]
    conn.close()
    result_below = []
    for r in below:
        d = dict(r)
        d["remaining"] = max(0, capital + int(d["points"] or 0)); d["capital"] = capital
        d["step"] = next((t["label"] for t in ths if d["remaining"] <= t["remaining_points"]), None)
        result_below.append(d)
    return jsonify({"incidents_week": week, "incidents_month": month, "threshold": ths[0]["remaining_points"] if ths else None, "capital": capital,
                    "thresholds": ths, "students_below_threshold": result_below, "by_category": [dict(r) for r in by_cat],
                    "absences_today": absences_today})


# ===========================================================================
# RÉSULTATS — saisie par la Direction ou un professeur rattaché à la classe
# ===========================================================================

@bp.post("/api/classes/<class_id>/grades")
@require_auth
def record_grades(class_id):
    if not (_has("grades.manage") or _has("grades.manage.assigned")):
        return _denied("grades.record", "class", class_id)
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls or g.ctx["role"] not in ("directeur", "professeur"):
        conn.close()
        return _denied("grades.record", "class", class_id, "Vous n'êtes pas rattaché(e) à cette classe.")
    data = json_object(request.get_json(force=True))
    subject = required_text(data.get("subject"), "subject", 80)
    period = required_text(data.get("period"), "period", 40)
    try:
        max_score = float(data.get("max_score", 20))
    except (TypeError, ValueError):
        raise ValidationError("max_score doit être un nombre.")
    if not (0 < max_score <= 1000):
        raise ValidationError("max_score doit être compris entre 1 et 1000.")
    entries = data.get("entries") or []
    if not entries:
        conn.close()
        return jsonify({"error": "Aucune note fournie."}), 400
    tenant_id = g.ctx["tenant_id"]
    # Rattachement à la période déclarée, et refus si elle est verrouillée.
    # Le verrou est vérifié ICI, côté serveur : une période fermée ne se rouvre
    # pas en modifiant la requête.
    periode = school.resolve_period(conn, tenant_id, cls["academic_year_id"], period, cls["cycle"])
    ouverte, motif = school.period_accepts_results(periode)
    if not ouverte:
        conn.close()
        return _denied("grades.record", "class", class_id, motif)
    period_id = periode["id"] if periode else None
    class_student_ids = {r["id"] for r in conn.execute("SELECT id FROM students WHERE tenant_id=? AND class_id=?", (tenant_id, class_id))}
    settings = school.get_settings(conn, tenant_id)
    now = str(time.time())
    saved = 0
    notified_students = []
    for e in entries:
        sid = e.get("student_id")
        if sid not in class_student_ids:
            conn.close()
            return jsonify({"error": "Un élève fourni n'appartient pas à cette classe."}), 400
        if e.get("score") in (None, ""):
            continue  # absent à l'évaluation : pas de note fabriquée
        try:
            score = float(e["score"])
        except (TypeError, ValueError):
            raise ValidationError("Chaque score doit être un nombre.")
        if score < 0 or score > max_score:
            raise ValidationError(f"Un score doit être compris entre 0 et {max_score:g}.")
        # VERSIONNEMENT — corriger une note crée une VERSION, elle ne s'ajoute pas.
        #
        # Trouvé par la campagne k6 du 17/09 : ce chemin faisait un INSERT sec.
        # Un enseignant qui corrigeait une note laissait DEUX lignes
        # `is_current=1` pour le même élève, la même matière et la même période.
        # Bulletins, moyennes et rangs comptaient alors les deux — un 17 corrigé
        # en 11 produisait une moyenne de 14 sur une note qui n'existe pas.
        #
        # Le chemin d'IMPORT versionnait déjà correctement
        # (`api_academics.confirmer_import`) ; la saisie manuelle, elle, avait
        # été oubliée. C'est pourtant le chemin le plus emprunté.
        #
        # La portée est (élève, matière, période) : une saisie remplace une
        # note, pas les résultats de toute la période — c'est ce que fait
        # l'import, qui remplace un lot entier.
        conn.execute(
            """UPDATE grades SET is_current=0, superseded_at=?
               WHERE tenant_id=? AND student_id=? AND subject=? AND is_current=1
                 AND ((period_id IS NOT NULL AND period_id=?) OR (period_id IS NULL AND period=?))""",
            (now, tenant_id, sid, subject, period_id, period),
        )
        # academic_year_id : une note appartient à un millésime. Sans lui, la
        # proclamation se décidait sur le seul libellé de période et exposait
        # aux parents les notes d'une autre année (voir school.published_period_keys).
        conn.execute(
            """INSERT INTO grades (id, tenant_id, student_id, class_id, academic_year_id, period_id, subject, period,
                                   score, max_score, comment, recorded_by, created_at, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'saisie')""",
            (new_id(), tenant_id, sid, class_id, cls["academic_year_id"], period_id, subject, period, score, max_score,
             (e.get("comment") or "").strip()[:300] or None, g.ctx["user_id"], now),
        )
        saved += 1
        notified_students.append(sid)
    conn.commit()
    if saved:
        event = events_module.emit(conn, tenant_id, "grades.published", "class", class_id, g.ctx["user_id"],
                                   payload={"subject": subject, "period": period, "count": saved})
        for sid in notified_students:
            student = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
            notif_module.on_grades_published(conn, tenant_id, student, subject, period, settings, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "grades.recorded", "class", class_id, "success", after={"subject": subject, "period": period, "count": saved})
    return jsonify({"ok": True, "saved": saved})


@bp.get("/api/classes/<class_id>/grades")
@require_auth
def list_class_grades(class_id):
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls or g.ctx["role"] == "parent":
        conn.close()
        return _not_found("grades.list", "class", class_id, "Classe introuvable ou accès non autorisé.")
    # `is_current=1` : sans ce filtre, une note corrigée revenait DEUX FOIS
    # dans l'écran de classe — l'ancienne version à côté de la nouvelle, sans
    # rien pour les distinguer. L'historique reste consultable, mais par la
    # route d'historique dédiée (api_academics), pas en se mélangeant ici.
    rows = conn.execute(
        """SELECT g.*, s.first_name, s.last_name FROM grades g JOIN students s ON s.id = g.student_id
           WHERE g.tenant_id=? AND g.class_id=? AND g.is_current=1
           ORDER BY g.period, g.subject, s.last_name""",
        (g.ctx["tenant_id"], class_id),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ===========================================================================
# HORAIRES & EXAMENS — rattachés à la classe
# ===========================================================================

def _time_ok(v):
    return isinstance(v, str) and re.match(r"^\d{2}:\d{2}$", v)


@bp.post("/api/classes/<class_id>/schedule")
@require_auth
def add_schedule_slot(class_id):
    if not _has("schedule.manage"):
        return _denied("schedule.add", "class", class_id)
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    if not conn.execute("SELECT 1 FROM classes WHERE id=? AND tenant_id=?", (class_id, tenant_id)).fetchone():
        conn.close()
        return _not_found("schedule.add", "class", class_id)
    try:
        weekday = int(data.get("weekday"))
    except (TypeError, ValueError):
        raise ValidationError("weekday doit être un entier de 1 (lundi) à 7.")
    if not 1 <= weekday <= 7:
        raise ValidationError("weekday doit être compris entre 1 et 7.")
    if not (_time_ok(data.get("start_time")) and _time_ok(data.get("end_time"))) or data["start_time"] >= data["end_time"]:
        raise ValidationError("start_time/end_time doivent être au format HH:MM, début avant fin.")
    subject = required_text(data.get("subject"), "subject", 80)
    teacher_id = data.get("teacher_user_id") or None
    # `status='active'` : un professeur dont l'accès a été révoqué ne doit plus
    # pouvoir être affecté à un cours. Sans ce filtre, on lui assignait encore
    # des heures alors qu'il ne pouvait plus se connecter pour les assurer.
    if teacher_id and not conn.execute("SELECT 1 FROM memberships WHERE user_id=? AND tenant_id=? AND role='professeur' AND status='active'", (teacher_id, tenant_id)).fetchone():
        conn.close()
        return jsonify({"error": "Professeur introuvable pour cet établissement."}), 404
    sid = new_id()
    conn.execute(
        "INSERT INTO schedule_slots (id, tenant_id, class_id, weekday, start_time, end_time, subject, teacher_user_id, room, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, tenant_id, class_id, weekday, data["start_time"], data["end_time"], subject, teacher_id, (data.get("room") or "").strip()[:40] or None, str(time.time())),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": sid}), 201


@bp.delete("/api/schedule/<slot_id>")
@require_auth
def delete_schedule_slot(slot_id):
    if not _has("schedule.manage"):
        return _denied("schedule.delete")
    conn = db.get_connection()
    # rowcount vérifié : voir delete_rule ci-dessus (faux succès).
    curseur = conn.execute("DELETE FROM schedule_slots WHERE id=? AND tenant_id=?", (slot_id, g.ctx["tenant_id"]))
    conn.commit()
    conn.close()
    if not (curseur.rowcount or 0):
        return _not_found("schedule.delete", "schedule_slot", slot_id, "Créneau introuvable pour cet établissement.")
    return jsonify({"ok": True})


@bp.post("/api/classes/<class_id>/exams")
@require_auth
def add_exam(class_id):
    if not _has("schedule.manage"):
        return _denied("exam.add", "class", class_id)
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    if not conn.execute("SELECT 1 FROM classes WHERE id=? AND tenant_id=?", (class_id, tenant_id)).fetchone():
        conn.close()
        return _not_found("exam.add", "class", class_id)
    subject = required_text(data.get("subject"), "subject", 80)
    day = _iso_date(data.get("date"))
    start = data.get("start_time") or None
    if start and not _time_ok(start):
        raise ValidationError("start_time doit être au format HH:MM.")
    eid = new_id()
    conn.execute(
        "INSERT INTO exams (id, tenant_id, class_id, subject, date, start_time, room, exam_type, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (eid, tenant_id, class_id, subject, day, start, (data.get("room") or "").strip()[:40] or None,
         (data.get("exam_type") or "Évaluation").strip()[:60], (data.get("notes") or "").strip()[:300] or None, str(time.time())),
    )
    conn.commit()
    conn.close()
    return jsonify({"id": eid}), 201


@bp.delete("/api/exams/<exam_id>")
@require_auth
def delete_exam(exam_id):
    if not _has("schedule.manage"):
        return _denied("exam.delete")
    conn = db.get_connection()
    # rowcount vérifié : voir delete_rule ci-dessus (faux succès).
    curseur = conn.execute("DELETE FROM exams WHERE id=? AND tenant_id=?", (exam_id, g.ctx["tenant_id"]))
    conn.commit()
    conn.close()
    if not (curseur.rowcount or 0):
        return _not_found("exam.delete", "exam", exam_id, "Évaluation introuvable pour cet établissement.")
    return jsonify({"ok": True})


# ===========================================================================
# BOUTIQUE — produits (Direction), commandes (Parent), reliées au Financial Core
# ===========================================================================

@bp.get("/api/store/products")
@require_auth
def list_products():
    if not _has("store.read"):
        return _denied("store.read")
    conn = db.get_connection()
    where = "tenant_id=?" + ("" if g.ctx["role"] == "directeur" else " AND active=1")
    rows = conn.execute(f"SELECT * FROM store_products WHERE {where} ORDER BY category, name", (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/store/products")
@require_auth
def create_product():
    if not _has("store.manage"):
        return _denied("store.product_create")
    data = json_object(request.get_json(force=True))
    name = required_text(data.get("name"), "name", 120)
    price = positive_amount(data.get("price"), "price")
    try:
        stock = int(data.get("stock", 0))
    except (TypeError, ValueError):
        raise ValidationError("stock doit être un entier.")
    if stock < 0:
        raise ValidationError("stock ne peut pas être négatif.")
    conn = db.get_connection()
    settings = school.get_settings(conn, g.ctx["tenant_id"])
    pid = new_id()
    options = _clean_options(data.get("options"))
    conn.execute(
        "INSERT INTO store_products (id, tenant_id, name, category, price, currency, stock, active, created_at, options) VALUES (?,?,?,?,?,?,?,1,?,?)",
        (pid, g.ctx["tenant_id"], name, (data.get("category") or "fournitures").strip()[:60], price,
         data.get("currency") or settings["currency"], stock, str(time.time()), options),
    )
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "store.product_created", "store_product", pid, "success", after={"name": name, "price": price})
    return jsonify({"id": pid}), 201


@bp.put("/api/store/products/<product_id>")
@require_auth
def update_product(product_id):
    if not _has("store.manage"):
        return _denied("store.product_update")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM store_products WHERE id=? AND tenant_id=?", (product_id, g.ctx["tenant_id"])).fetchone()
    if not row:
        conn.close()
        return _not_found("store.product_update", "store_product", product_id)
    fields, params = [], []
    if "name" in data:
        fields.append("name=?"); params.append(required_text(data["name"], "name", 120))
    if "price" in data:
        fields.append("price=?"); params.append(positive_amount(data["price"], "price"))
    if "stock" in data:
        try:
            stock = int(data["stock"])
        except (TypeError, ValueError):
            raise ValidationError("stock doit être un entier.")
        if stock < 0:
            raise ValidationError("stock ne peut pas être négatif.")
        fields.append("stock=?"); params.append(stock)
    if "active" in data:
        fields.append("active=?"); params.append(1 if data["active"] else 0)
    if "category" in data:
        fields.append("category=?"); params.append((data["category"] or "fournitures").strip()[:60])
    if "options" in data:
        fields.append("options=?"); params.append(_clean_options(data["options"]))
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification fournie."}), 400
    params += [product_id, g.ctx["tenant_id"]]
    conn.execute(f"UPDATE store_products SET {', '.join(fields)} WHERE id=? AND tenant_id=?", params)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


def _clean_options(raw):
    """Variantes d'un produit (tailles, couleurs…) : liste de libellés courts, en JSON."""
    import json as _json
    if raw in (None, "", []):
        return None
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",")]
    if not isinstance(raw, list):
        raise ValidationError("options doit être une liste de libellés.")
    clean = [str(x).strip()[:30] for x in raw if str(x).strip()]
    return _json.dumps(clean[:20]) if clean else None


def _pickup_date(settings):
    """Commande avant l'heure limite → retrait le jour ouvré suivant ; après → deux jours."""
    from datetime import date as _date, datetime as _dt, timedelta as _td
    cutoff = settings.get("store_cutoff_time") or "20:00"
    now = _dt.now()
    day = now.date() + _td(days=1 if now.strftime("%H:%M") < cutoff else 2)
    while day.weekday() >= 5:
        day += _td(days=1)
    return day.isoformat()


def _store_catalog_item(conn, tenant_id, currency):
    row = conn.execute("SELECT id FROM catalog_items WHERE tenant_id=? AND category='boutique' LIMIT 1", (tenant_id,)).fetchone()
    if row:
        return row["id"]
    cid = new_id()
    conn.execute("INSERT INTO catalog_items (id, tenant_id, name, category, amount, currency, created_at) VALUES (?,?,?,?,?,?,?)",
                 (cid, tenant_id, "Boutique scolaire", "boutique", 1.0, currency, str(time.time())))
    return cid


def _next_order_number(conn, tenant_id):
    n = conn.execute("SELECT COUNT(*) n FROM orders WHERE tenant_id=?", (tenant_id,)).fetchone()["n"]
    return f"ORD-{n + 1:04d}"


@bp.post("/api/store/orders")
@require_auth
def create_order():
    """Le parent commande pour UN de ses enfants. La commande crée une
    obligation dans le Financial Core (même moteur que les frais scolaires) —
    le paiement, la confirmation et le reçu suivent le circuit existant."""
    if not _has("orders.create.own"):
        return _denied("order.create")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, data.get("student_id"))
    if not student:
        conn.close()
        return _not_found("order.create", "student", data.get("student_id"), "Élève introuvable ou non rattaché à votre compte.")
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        conn.close()
        return jsonify({"error": "Le panier est vide."}), 400
    lines, total, currency = [], 0.0, None
    for it in items:
        product = conn.execute("SELECT * FROM store_products WHERE id=? AND tenant_id=? AND active=1", (it.get("product_id"), tenant_id)).fetchone()
        if not product:
            conn.close()
            return jsonify({"error": "Un produit du panier n'est plus disponible."}), 404
        try:
            qty = int(it.get("quantity", 1))
        except (TypeError, ValueError):
            raise ValidationError("quantity doit être un entier.")
        if qty < 1 or qty > 50:
            raise ValidationError("La quantité doit être comprise entre 1 et 50.")
        if product["stock"] < qty:
            conn.close()
            return jsonify({"error": f"Stock insuffisant pour « {product['name']} » ({product['stock']} disponible(s))."}), 409
        if currency and product["currency"] != currency:
            conn.close()
            return jsonify({"error": "Une commande ne peut pas mélanger plusieurs devises."}), 400
        currency = product["currency"]
        variant = (it.get("variant") or "").strip()[:30] or None
        if product["options"]:
            import json as _json
            allowed = _json.loads(product["options"])
            if variant not in allowed:
                conn.close()
                return jsonify({"error": f"Choisissez une option pour « {product['name']} » ({', '.join(allowed)})."}), 400
        lines.append((product, qty, variant))
        total += product["price"] * qty
    total = round(total, 2)

    year = conn.execute("SELECT id FROM academic_years WHERE tenant_id=? ORDER BY created_at DESC LIMIT 1", (tenant_id,)).fetchone()
    if not year:
        conn.close()
        return jsonify({"error": "Aucune année scolaire configurée — contactez l'établissement."}), 409
    now = str(time.time())
    oid, number = new_id(), _next_order_number(conn, tenant_id)
    summary = ", ".join(f"{qty} × {p['name']}" + (f" ({v})" if v else "") for p, qty, v in lines)
    pickup_code = "".join(__import__("secrets").choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))
    catalog_item_id = _store_catalog_item(conn, tenant_id, currency)
    ob_id = new_id()
    conn.execute(
        """INSERT INTO obligations (id, tenant_id, student_id, academic_year_id, catalog_item_id, amount, currency, due_date, status, label, created_at)
           VALUES (?,?,?,?,?,?,?,?, 'ISSUED', ?, ?)""",
        (ob_id, tenant_id, student["id"], year["id"], catalog_item_id, total, currency, None, f"Commande {number} — {summary}"[:200], now),
    )
    conn.execute(
        "INSERT INTO orders (id, tenant_id, number, student_id, parent_user_id, status, total, currency, obligation_id, created_at, updated_at, pickup_code) VALUES (?,?,?,?,?,'pending',?,?,?,?,?,?)",
        (oid, tenant_id, number, student["id"], g.ctx["user_id"], total, currency, ob_id, now, now, pickup_code),
    )
    for product, qty, variant in lines:
        conn.execute("INSERT INTO order_items (id, tenant_id, order_id, product_id, name, quantity, unit_price, variant) VALUES (?,?,?,?,?,?,?,?)",
                     (new_id(), tenant_id, oid, product["id"], product["name"], qty, product["price"], variant))
        conn.execute("UPDATE store_products SET stock = stock - ? WHERE id=?", (qty, product["id"]))
    conn.commit()
    order = dict(conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
    event = events_module.emit(conn, tenant_id, "order.created", "order", oid, g.ctx["user_id"],
                               payload={"student_id": student["id"], "total": total, "currency": currency})
    notif_module.on_order_created(conn, tenant_id, order, student, event_id=event["id"])
    settings = school.get_settings(conn, tenant_id)
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "order.created", "order", oid, "success", after={"number": number, "total": total})
    return jsonify({"id": oid, "number": number, "total": total, "currency": currency, "obligation_id": ob_id, "status": "pending",
                    "pickup_code": pickup_code, "pickup_date": _pickup_date(settings)}), 201


@bp.get("/api/store/orders")
@require_auth
def list_orders():
    if not (_has("orders.read") or _has("orders.read.own")):
        return _denied("orders.list")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    if g.ctx["role"] == "directeur":
        where, params = "o.tenant_id=?", (tenant_id,)
    else:
        where, params = "o.tenant_id=? AND o.parent_user_id=?", (tenant_id, g.ctx["user_id"])
    rows = conn.execute(
        f"""SELECT o.*, s.first_name, s.last_name, s.code, u.name AS parent_name FROM orders o
            JOIN students s ON s.id=o.student_id JOIN users u ON u.id=o.parent_user_id WHERE {where} ORDER BY o.created_at DESC LIMIT 200""",
        params,
    ).fetchall()
    settings = school.get_settings(conn, tenant_id)
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(i) for i in conn.execute("SELECT name, quantity, unit_price, variant FROM order_items WHERE order_id=?", (r["id"],))]
        d["pickup_date"] = _pickup_date(settings) if r["status"] in ("pending", "paid") else None
        summary = financial.financial_summary(conn, tenant_id, r["student_id"])
        line = next((l for l in summary["obligations"] if l["obligation_id"] == r["obligation_id"]), None)
        d["paid"] = line["paid"] if line else 0
        d["remaining"] = line["remaining"] if line else d["total"]
        result.append(d)
    conn.close()
    return jsonify(result)


@bp.post("/api/store/orders/<order_id>/status")
@require_auth
def update_order_status(order_id):
    if not _has("orders.manage"):
        return _denied("order.status", "order", order_id)
    data = json_object(request.get_json(force=True))
    status = data.get("status")
    if status not in ("ready", "delivered", "cancelled"):
        return jsonify({"error": "Statut modifiable manuellement : ready, delivered ou cancelled (le passage à 'paid' vient du paiement réel)."}), 400
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    order = conn.execute("SELECT * FROM orders WHERE id=? AND tenant_id=?", (order_id, tenant_id)).fetchone()
    if not order:
        conn.close()
        return _not_found("order.status", "order", order_id)
    if order["status"] == "cancelled":
        conn.close()
        return jsonify({"error": "Cette commande est déjà annulée."}), 409
    if status == "cancelled":
        summary = financial.financial_summary(conn, tenant_id, order["student_id"])
        line = next((l for l in summary["obligations"] if l["obligation_id"] == order["obligation_id"]), None)
        if line and line["paid"] > 0:
            conn.close()
            return jsonify({"error": "Impossible d'annuler une commande déjà (partiellement) payée — un remboursement doit être traité par la Direction."}), 409
        # Ordre imposé par les clés étrangères : détacher la commande, retirer
        # les intentions de paiement non confirmées (aucune preuve, aucun
        # crédit), puis supprimer l'obligation. Un paiement CONFIRMÉ a été
        # exclu juste au-dessus — il n'est jamais effacé.
        conn.execute("UPDATE orders SET obligation_id=NULL WHERE id=?", (order_id,))
        conn.execute("DELETE FROM payments WHERE tenant_id=? AND obligation_id=? AND status IN ('CREATED','PENDING','PROCESSING')",
                     (tenant_id, order["obligation_id"]))
        conn.execute("DELETE FROM obligations WHERE id=? AND tenant_id=?", (order["obligation_id"], tenant_id))
        for it in conn.execute("SELECT product_id, quantity FROM order_items WHERE order_id=?", (order_id,)).fetchall():
            conn.execute("UPDATE store_products SET stock = stock + ? WHERE id=?", (it["quantity"], it["product_id"]))
    if status == "ready" and order["status"] != "paid":
        conn.close()
        return jsonify({"error": "Une commande ne peut être préparée qu'une fois payée."}), 409
    if status == "delivered" and order["status"] not in ("paid", "ready"):
        conn.close()
        return jsonify({"error": "Une commande ne peut être remise qu'une fois payée."}), 409
    if status == "delivered" and data.get("pickup_code") and (data.get("pickup_code") or "").strip().upper() != (order["pickup_code"] or ""):
        conn.close()
        return jsonify({"error": "Code de retrait incorrect."}), 400
    now = str(time.time())
    extra = ", ready_at=?, prepared_by=?" if status == "ready" else (", delivered_at=?, prepared_by=?" if status == "delivered" else "")
    params = [status, now] + ([now, g.ctx["user_id"]] if extra else []) + [order_id]
    conn.execute(f"UPDATE orders SET status=?, updated_at=?{extra} WHERE id=?", params)
    conn.commit()
    order = dict(conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    student = conn.execute("SELECT * FROM students WHERE id=?", (order["student_id"],)).fetchone()
    event = events_module.emit(conn, tenant_id, "order.status_changed", "order", order_id, g.ctx["user_id"], payload={"status": status})
    if status == "ready":
        notif_module.on_order_ready(conn, tenant_id, order, student, event_id=event["id"])
    else:
        notif_module.on_order_status(conn, tenant_id, order, student, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "order.status_changed", "order", order_id, "success", after={"status": status})
    return jsonify({"ok": True, "status": status})


# ===========================================================================
# REÇUS
# ===========================================================================

@bp.get("/api/receipts")
@require_auth
def list_receipts():
    if not (_has("receipts.read") or _has("receipts.read.own")):
        return _denied("receipts.list")
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    extra = ""
    if request.args.get("q"):
        # LOWER() des deux côtés : SQLite ignore la casse sur l'ASCII,
        # PostgreSQL non — sans cela la recherche de reçus ne trouve plus rien
        # dès que l'utilisateur ne respecte pas la casse exacte.
        extra = (" AND (LOWER(r.number) LIKE ? OR LOWER(s.first_name) LIKE ?"
                 " OR LOWER(s.last_name) LIKE ? OR LOWER(s.code) LIKE ?)")
        q = "%" + request.args["q"].strip().lower() + "%"
        params = params + (q, q, q, q)
    rows = conn.execute(
        f"""SELECT r.*, s.first_name, s.last_name, s.code, c.name AS class_name FROM receipts r
            JOIN students s ON s.id = r.student_id LEFT JOIN classes c ON c.id = s.class_id
            WHERE {where}{extra} ORDER BY r.created_at DESC LIMIT 300""",
        params,
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/api/receipts/<receipt_id>")
@require_auth
def get_receipt(receipt_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM receipts WHERE id=? AND tenant_id=?", (receipt_id, g.ctx["tenant_id"])).fetchone()
    if not row or not school.resolve_student_access(conn, g.ctx, row["student_id"]) or not (_has("receipts.read") or _has("receipts.read.own")):
        conn.close()
        return _not_found("receipt.read", "receipt", receipt_id, "Reçu introuvable ou accès non autorisé.")
    student = conn.execute("SELECT s.*, c.name AS class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?", (row["student_id"],)).fetchone()
    tenant = conn.execute("SELECT name FROM tenants WHERE id=?", (g.ctx["tenant_id"],)).fetchone()
    payment = conn.execute("SELECT p.*, u.name AS created_by_name FROM payments p LEFT JOIN users u ON u.id=p.created_by WHERE p.id=?", (row["payment_id"],)).fetchone()
    settings = school.get_settings(conn, g.ctx["tenant_id"])
    conn.close()
    return jsonify({
        "receipt": dict(row),
        "student": {"id": student["id"], "code": student["code"], "first_name": student["first_name"], "last_name": student["last_name"], "class_name": student["class_name"]},
        "payment": {"id": payment["id"], "method": payment["method"], "confirmed_at": payment["confirmed_at"], "provider_reference": payment["provider_reference"],
                    "recorded_by": payment["created_by_name"]},
        "school": {"name": tenant["name"] if tenant else "", "phone": settings["school_phone"], "address": settings["school_address"], "email": settings["school_email"]},
    })


# ===========================================================================
# NOTIFICATIONS & RÉGLAGES
# ===========================================================================

@bp.get("/api/notifications/summary")
@require_auth
def notifications_summary():
    conn = db.get_connection()
    result = notif_module.summary_for_user(conn, g.ctx["tenant_id"], g.ctx["user_id"])
    conn.close()
    return jsonify(result)


@bp.post("/api/notifications/read-all")
@require_auth
def notifications_read_all():
    conn = db.get_connection()
    notif_module.mark_all_read(conn, g.ctx["tenant_id"], g.ctx["user_id"])
    conn.close()
    return jsonify({"ok": True})


@bp.get("/api/settings")
@require_auth
def get_settings_route():
    conn = db.get_connection()
    settings = school.get_settings(conn, g.ctx["tenant_id"])
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (g.ctx["tenant_id"],)).fetchone()
    conn.close()
    if g.ctx["role"] != "directeur":
        # Les autres rôles ne reçoivent que ce qui conditionne leur affichage.
        settings = {"currency": settings["currency"], "teacher_sees_finance": settings["teacher_sees_finance"]}
    settings["school_name"] = tenant["name"] if tenant else ""
    if g.ctx["role"] == "directeur" and tenant:
        settings["branding"] = school.branding(tenant)
        settings["code_prefix"] = tenant["code_prefix"] or "STU"
        settings["code_mode"] = tenant["code_mode"] or "random"
    return jsonify(settings)


@bp.put("/api/settings")
@require_auth
def update_settings_route():
    if not _has("settings.manage"):
        return _denied("settings.update")
    data = json_object(request.get_json(force=True))
    patch = {}
    if "currency" in data:
        cur = (data["currency"] or "").strip().upper()
        if cur not in ("USD", "CDF", "EUR"):
            raise ValidationError("currency doit être USD, CDF ou EUR.")
        patch["currency"] = cur
    for flag in ("teacher_sees_finance", "parent_notify_attendance", "parent_notify_incidents", "parent_notify_grades",
                 "parent_notify_present", "teacher_contact_visible"):
        if flag in data:
            patch[flag] = 1 if data[flag] else 0
    if "store_cutoff_time" in data:
        t = (data["store_cutoff_time"] or "").strip()
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t):
            raise ValidationError("L'heure limite doit être au format HH:MM.")
        patch["store_cutoff_time"] = t
    if "pass_threshold" in data:
        try:
            v = float(data["pass_threshold"])
        except (TypeError, ValueError):
            raise ValidationError("Le seuil de réussite doit être un nombre.")
        if not 0 <= v <= 100:
            raise ValidationError("Le seuil de réussite doit être compris entre 0 et 100 %.")
        patch["pass_threshold"] = v
    for d8 in ("exam_period_starts", "exam_period_ends"):
        if d8 in data:
            v = (data[d8] or "").strip() or None
            if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                raise ValidationError(f"{d8} doit être au format AAAA-MM-JJ.")
            patch[d8] = v
    if "discipline_alert_threshold" in data:
        try:
            t = int(data["discipline_alert_threshold"])
        except (TypeError, ValueError):
            raise ValidationError("discipline_alert_threshold doit être un entier.")
        if not -1000 <= t <= 0:
            raise ValidationError("Le seuil d'alerte doit être un entier négatif ou nul.")
        patch["discipline_alert_threshold"] = t
    for txt in ("school_phone", "school_address", "school_email"):
        if txt in data:
            patch[txt] = (data[txt] or "").strip()[:200] or None
    if "results_policy" in data:
        # Politique de diffusion des résultats. Elle est VALIDÉE ici plutôt
        # qu'interprétée à la lecture : une politique illisible retomberait
        # silencieusement sur « toujours diffuser », et l'établissement croirait
        # avoir posé une condition qui ne s'applique pas.
        p = data["results_policy"]
        if p in (None, "", {}):
            patch["results_policy"] = None
        else:
            if not isinstance(p, dict):
                raise ValidationError("results_policy doit être un objet.")
            mode = p.get("mode")
            if mode not in ("always", "balance"):
                raise ValidationError("results_policy.mode doit valoir 'always' ou 'balance'.")
            plafond = p.get("max_balance", 0)
            if isinstance(plafond, bool) or not isinstance(plafond, (int, float)):
                raise ValidationError("results_policy.max_balance doit être un nombre.")
            if plafond < 0:
                raise ValidationError("results_policy.max_balance ne peut pas être négatif.")
            exempts = p.get("exempt_class_ids") or []
            if not isinstance(exempts, list) or not all(isinstance(x, str) for x in exempts):
                raise ValidationError("results_policy.exempt_class_ids doit être une liste d'identifiants.")
            patch["results_policy"] = json.dumps({
                "mode": mode, "max_balance": float(plafond), "exempt_class_ids": exempts[:500]})
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    tenant_fields, tenant_params = [], []
    if "school_name" in data:
        tenant_fields.append("name=?"); tenant_params.append(required_text(data["school_name"], "school_name", 160))
    if "slug" in data:
        wanted = school.slugify(data["slug"] or "")
        if len(wanted) < 3:
            raise ValidationError("L'adresse du portail doit contenir au moins 3 caractères (lettres, chiffres, tirets).")
        taken = conn.execute("SELECT id FROM tenants WHERE slug=? AND id<>?", (wanted, tenant_id)).fetchone()
        if taken:
            conn.close()
            return jsonify({"error": "Cette adresse de portail est déjà utilisée par un autre établissement."}), 409
        tenant_fields.append("slug=?"); tenant_params.append(wanted)
    if "tagline" in data:
        tenant_fields.append("tagline=?"); tenant_params.append((data["tagline"] or "").strip()[:160] or None)
    for img in ("logo_data", "cover_data"):
        if img in data:
            v = data[img] or None
            limit = 400_000 if img == "logo_data" else 1_200_000
            if v and not _est_image_valide(v, limit):
                raise ValidationError(f"{'Le logo' if img == 'logo_data' else 'La photo de couverture'} doit être une image JPEG/PNG de moins de {limit // 1000 // 1000 or 300} {'Mo' if limit > 500_000 else 'Ko'}.")
            tenant_fields.append(f"{img}=?"); tenant_params.append(v)
    if "accent_color" in data:
        tenant_fields.append("accent_color=?"); tenant_params.append(valid_hex_color(data["accent_color"]))
    if "show_flag" in data:
        tenant_fields.append("show_flag=?"); tenant_params.append(1 if data["show_flag"] else 0)
    if "code_prefix" in data:
        prefix = re.sub(r"[^A-Za-z0-9]", "", str(data["code_prefix"] or "")).upper()[:8]
        if len(prefix) < 2:
            raise ValidationError("Le préfixe d'identifiant doit contenir 2 à 8 lettres ou chiffres.")
        tenant_fields.append("code_prefix=?"); tenant_params.append(prefix)
    if "code_mode" in data:
        if data["code_mode"] not in ("random", "sequential"):
            raise ValidationError("code_mode doit être random ou sequential.")
        tenant_fields.append("code_mode=?"); tenant_params.append(data["code_mode"])
    if tenant_fields:
        conn.execute(f"UPDATE tenants SET {', '.join(tenant_fields)} WHERE id=?", tenant_params + [tenant_id])
        conn.commit()
    result = school.save_settings(conn, tenant_id, patch)
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    conn.close()
    result["school_name"] = tenant["name"]
    result["branding"] = school.branding(tenant)
    result["code_prefix"] = tenant["code_prefix"] or "STU"
    result["code_mode"] = tenant["code_mode"] or "random"
    audit(tenant_id, g.ctx["user_id"], "settings.updated", "tenant", tenant_id, "success",
          after={k: ("<image>" if k in ("logo_data", "cover_data") else v) for k, v in data.items()})
    return jsonify(result)


# ===========================================================================
# PORTAIL PAR ÉTABLISSEMENT (public) · PROFIL · RÉINITIALISATION DE MOT DE PASSE
# ===========================================================================

@bp.get("/api/portal/<slug>")
def public_portal(slug):
    """Habillage public d'un établissement (nom, logo, photo, couleur) pour
    la page d'atterrissage aux couleurs de l'école. Aucune donnée métier."""
    allowed, retry_after = security.check_rate_limit("portal", request.remote_addr, 120, 300)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429
    security.record_attempt("portal", request.remote_addr)
    conn = db.get_connection()
    tenant = conn.execute("SELECT * FROM tenants WHERE slug=? AND status='active'", (school.slugify(slug),)).fetchone()
    conn.close()
    if not tenant:
        return jsonify({"error": "Aucun établissement à cette adresse."}), 404
    return jsonify(school.branding(tenant))


@bp.get("/api/me/onboarding")
@require_auth
def get_onboarding():
    """État de l'accueil pour l'utilisateur courant.

    Le tableau de bord s'en sert pour savoir s'il doit jouer la séquence
    d'accueil. La source de vérité est le membership, côté serveur : le
    stockage local du navigateur ne survit ni au changement d'appareil ni à
    un vidage de cache, et l'accueil se rejouerait indéfiniment.
    """
    conn = db.get_connection()
    row = conn.execute(
        "SELECT onboarding_completed_at, staff_code, title FROM memberships WHERE user_id=? AND tenant_id=?",
        (g.ctx["user_id"], g.ctx["tenant_id"])).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Aucun rattachement à cet établissement."}), 404
    return jsonify({
        "completed": bool(row["onboarding_completed_at"]),
        "completed_at": row["onboarding_completed_at"],
        "staff_code": row["staff_code"],
        "title": row["title"],
        "role": g.ctx["role"],
    })


@bp.post("/api/me/onboarding")
@require_auth
def set_onboarding():
    """Clôt l'accueil (ou le rouvre depuis les paramètres : « Revoir l'introduction »).

    Idempotent : la date de première complétion ne bouge plus une fois posée.
    Un double clic, un rejeu réseau ou un rafraîchissement ne produisent donc
    ni doublon ni état incohérent.
    """
    rejouer = bool((json_object(request.get_json(silent=True))).get("replay"))
    conn = db.get_connection()
    row = conn.execute("SELECT onboarding_completed_at FROM memberships WHERE user_id=? AND tenant_id=?",
                       (g.ctx["user_id"], g.ctx["tenant_id"])).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Aucun rattachement à cet établissement."}), 404
    if rejouer:
        conn.execute("UPDATE memberships SET onboarding_completed_at=NULL WHERE user_id=? AND tenant_id=?",
                     (g.ctx["user_id"], g.ctx["tenant_id"]))
        conn.commit()
        conn.close()
        return jsonify({"completed": False, "completed_at": None})
    deja = row["onboarding_completed_at"]
    if not deja:
        deja = str(time.time())
        # Condition sur NULL : deux requêtes simultanées ne réécrivent pas la date.
        conn.execute(
            "UPDATE memberships SET onboarding_completed_at=? WHERE user_id=? AND tenant_id=? AND onboarding_completed_at IS NULL",
            (deja, g.ctx["user_id"], g.ctx["tenant_id"]))
        conn.commit()
        relu = conn.execute("SELECT onboarding_completed_at FROM memberships WHERE user_id=? AND tenant_id=?",
                            (g.ctx["user_id"], g.ctx["tenant_id"])).fetchone()
        deja = relu["onboarding_completed_at"]
    conn.close()
    return jsonify({"completed": True, "completed_at": deja})


@bp.put("/api/me")
@require_auth
def update_me():
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    fields, params = [], []
    if "name" in data:
        fields.append("name=?"); params.append(required_text(data["name"], "name", 120))
    if "phone" in data:
        phone = valid_phone(data["phone"])
        if phone and conn.execute("SELECT id FROM users WHERE phone=? AND id<>?", (phone, g.ctx["user_id"])).fetchone():
            conn.close()
            return jsonify({"error": "Ce numéro est déjà utilisé par un autre compte."}), 409
        fields.append("phone=?"); params.append(phone)
    if "email" in data:
        email = valid_email(data["email"]) if data["email"] else None
        if email and conn.execute("SELECT id FROM users WHERE email=? AND id<>?", (email, g.ctx["user_id"])).fetchone():
            conn.close()
            return jsonify({"error": "Cet email est déjà utilisé par un autre compte."}), 409
        if email:
            fields.append("email=?"); params.append(email)
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification fournie."}), 400
    conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", params + [g.ctx["user_id"]])
    conn.commit()
    user = conn.execute("SELECT name, email, phone FROM users WHERE id=?", (g.ctx["user_id"],)).fetchone()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "user.profile_updated", "user", g.ctx["user_id"], "success", after={k: v for k, v in data.items()})
    return jsonify({"name": user["name"], "email": school.display_email(user["email"]), "phone": user["phone"]})


RESET_TTL_SECONDS = 60 * 60 * 24


@bp.post("/api/team/<user_id>/reset-link")
@require_auth
def create_reset_link(user_id):
    """La Direction génère un lien de réinitialisation pour un membre de SON
    établissement (parent, professeur, DD). Aucun canal email/SMS n'existe
    encore : le lien est partagé sur WhatsApp comme l'invitation. Usage
    unique, 24 h, jamais pour un compte hors de l'établissement."""
    if not _has("team.manage"):
        return _denied("password_reset.create", "user", user_id)
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    member = conn.execute(
        """SELECT u.id, u.name FROM memberships m JOIN users u ON u.id = m.user_id
           WHERE m.tenant_id=? AND m.user_id=? AND m.status='active' AND m.role <> 'directeur'""", (tenant_id, user_id)).fetchone()
    if not member:
        conn.close()
        return _not_found("password_reset.create", "user", user_id, "Membre introuvable dans votre établissement (la Direction change son propre mot de passe depuis Paramètres).")
    token = security.generate_invitation_token()
    now = time.time()
    conn.execute("UPDATE password_resets SET used_at=? WHERE tenant_id=? AND user_id=? AND used_at IS NULL", (str(now), tenant_id, user_id))
    conn.execute(
        "INSERT INTO password_resets (id, tenant_id, user_id, token_hash, created_by, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        (new_id(), tenant_id, user_id, security.hash_invitation_token(token), g.ctx["user_id"], str(now), str(now + RESET_TTL_SECONDS)),
    )
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "password_reset.link_created", "user", user_id, "success")
    return jsonify({"token": token, "expires_at": now + RESET_TTL_SECONDS, "name": member["name"]}), 201


def _resolve_reset(conn, token):
    if not token:
        return None
    row = conn.execute("SELECT * FROM password_resets WHERE token_hash=?", (security.hash_invitation_token(token),)).fetchone()
    if not row or row["used_at"] or float(row["expires_at"]) < time.time():
        return None
    return row


@bp.get("/api/password-reset/lookup")
def reset_lookup():
    allowed, retry_after = security.check_rate_limit("reset_lookup", request.remote_addr, 20, 300)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429
    conn = db.get_connection()
    row = _resolve_reset(conn, request.args.get("token", ""))
    if not row:
        # Seul l'échec consomme le budget anti-énumération (règle du 18/09) :
        # la clé est l'adresse IP, et toute une école peut partager la sienne.
        security.record_attempt("reset_lookup", request.remote_addr)
        conn.close()
        return jsonify({"error": "Lien invalide, expiré ou déjà utilisé — demandez-en un nouveau à votre établissement."}), 404
    security.clear_attempts("reset_lookup", request.remote_addr)
    user = conn.execute("SELECT name FROM users WHERE id=?", (row["user_id"],)).fetchone()
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (row["tenant_id"],)).fetchone()
    conn.close()
    return jsonify({"name": user["name"], "tenant_name": tenant["name"], "branding": school.branding(tenant)})


@bp.post("/api/password-reset")
def reset_apply():
    allowed, retry_after = security.check_rate_limit("reset_apply", request.remote_addr, 10, 300)
    if not allowed:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {retry_after} secondes."}), 429
    data = json_object(request.get_json(force=True))
    password = valid_password(data.get("password", ""))
    conn = db.get_connection()
    row = _resolve_reset(conn, data.get("token", ""))
    if not row:
        # Même règle : c'est le jeton faux qui coûte, pas la réinitialisation
        # réussie du parent assis à côté.
        security.record_attempt("reset_apply", request.remote_addr)
        conn.close()
        return jsonify({"error": "Lien invalide, expiré ou déjà utilisé — demandez-en un nouveau à votre établissement."}), 404
    now = str(time.time())
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (security.hash_password(password), row["user_id"]))
    conn.execute("UPDATE password_resets SET used_at=? WHERE id=?", (now, row["id"]))
    # Un mot de passe réinitialisé révoque toute session existante (même règle que le changement volontaire).
    conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
    conn.commit()
    token = security.create_session(conn, row["user_id"], row["tenant_id"])
    membership = conn.execute("SELECT role FROM memberships WHERE user_id=? AND tenant_id=?", (row["user_id"], row["tenant_id"])).fetchone()
    user = conn.execute("SELECT name FROM users WHERE id=?", (row["user_id"],)).fetchone()
    tenant = conn.execute("SELECT slug FROM tenants WHERE id=?", (row["tenant_id"],)).fetchone()
    conn.close()
    audit(row["tenant_id"], row["user_id"], "password_reset.applied", "user", row["user_id"], "success")
    security.clear_attempts("reset_apply", request.remote_addr)
    return jsonify({"token": token, "tenant_id": row["tenant_id"], "role": membership["role"] if membership else None,
                    "name": user["name"], "slug": tenant["slug"] if tenant else None})
