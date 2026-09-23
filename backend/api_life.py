"""KLASSIO backend — vie de l'établissement autour du dossier élève :
calendrier & communiqués, ressources (livres, leçons, devoirs), documents
officiels, cahier de communication, justifications d'absence, droit de
réponse, contacts, préférences.

Chaque route : session serveur → permission du rôle → périmètre school.py.
"""
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
from security import require_auth, new_id, audit, has_permission
from validation import json_object, ValidationError, required_text, file_data_uri

bp = Blueprint("life", __name__)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVENT_KINDS = ("evenement", "communique", "reunion", "fete", "deuil", "conge", "examens", "echeance")
RESOURCE_KINDS = ("livre", "lecon", "fiche", "devoir", "autre")
MAX_RESOURCE_BYTES = 3_500_000
MAX_DOCUMENT_BYTES = 4_500_000


def _denied(action, message="Vous n'avez pas l'autorisation d'effectuer cette action."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, status="denied")
    return jsonify({"error": message}), 403


def _not_found(action, message="Introuvable ou accès non autorisé."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, status="denied")
    return jsonify({"error": message}), 404


def _staff():
    return g.ctx["role"] in ("directeur", "discipline", "professeur")


def _check_file(data_url, allowed_prefixes, max_bytes, label):
    """Valide une pièce jointe transmise en data URI.

    `allowed_prefixes` n'est plus consulté : un simple `startswith` laissait
    passer une chaîne contenant un guillemet, qui s'échappait ensuite de
    l'attribut `src` d'un `<iframe>` ou d'un `<img>` du frontend. Le même
    défaut a été trouvé et exploité sur photo_data pendant l'audit de
    production. On impose donc la forme complète (validation.DATA_URI_FICHIER).
    Le paramètre reste dans la signature pour ne pas toucher aux appelants ;
    tous passent la même liste (PDF ou image).
    """
    return file_data_uri(data_url, label, max_length=max_bytes)


def _class_ids_for_ctx(conn):
    """Classes visibles : None = toutes (Direction)."""
    return school.visible_class_ids(conn, g.ctx)


def _event_recipients(conn, tenant_id, ev):
    """Destinataires autorisés d'un événement selon sa cible et son audience."""
    if ev["target_scope"] == "class":
        class_ids = [ev["target_value"]]
    elif ev["target_scope"] == "cycle":
        class_ids = [r["id"] for r in conn.execute("SELECT id FROM classes WHERE tenant_id=? AND cycle=?", (tenant_id, ev["target_value"]))]
    else:
        class_ids = None
    recipients = []
    if ev["audience"] in ("all", "parents"):
        recipients += notif_module.all_parents(conn, tenant_id) if class_ids is None else notif_module.parents_of_classes(conn, tenant_id, class_ids)
    if ev["audience"] in ("all", "staff"):
        if class_ids is None:
            recipients += notif_module.staff_users(conn, tenant_id)
        else:
            for cid in class_ids:
                recipients += notif_module.class_staff(conn, tenant_id, cid)
            recipients += notif_module.discipline_officers(conn, tenant_id) + notif_module.directors(conn, tenant_id)
    return list(dict.fromkeys(recipients))


# ===========================================================================
# CALENDRIER & COMMUNIQUÉS
# ===========================================================================

@bp.get("/api/calendar/events")
@require_auth
def list_events():
    """Événements visibles par l'utilisateur (cible + audience)."""
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    role = g.ctx["role"]
    rows = conn.execute("SELECT e.*, u.name AS author FROM calendar_events e LEFT JOIN users u ON u.id = e.created_by WHERE e.tenant_id=? ORDER BY COALESCE(e.starts_on, '9999') , e.created_at DESC", (tenant_id,)).fetchall()
    my_classes = _class_ids_for_ctx(conn)
    my_cycles = None
    if my_classes is not None:
        my_cycles = {r["cycle"] for r in conn.execute(f"SELECT cycle FROM classes WHERE id IN ({','.join('?' for _ in my_classes)})", my_classes)} if my_classes else set()
    result = []
    for e in rows:
        d = dict(e)
        if role == "parent" and d["audience"] == "staff":
            continue
        if role != "parent" and d["audience"] == "parents" and role != "directeur":
            continue
        if my_classes is not None:
            if d["target_scope"] == "class" and d["target_value"] not in my_classes:
                continue
            if d["target_scope"] == "cycle" and d["target_value"] not in my_cycles:
                continue
        if d["target_scope"] == "class":
            c = conn.execute("SELECT name FROM classes WHERE id=?", (d["target_value"],)).fetchone()
            d["target_label"] = c["name"] if c else "—"
        elif d["target_scope"] == "cycle":
            d["target_label"] = d["target_value"].capitalize()
        else:
            d["target_label"] = "Toute l'école"
        d["can_delete"] = role == "directeur" or d["created_by"] == g.ctx["user_id"]
        result.append(d)
    conn.close()
    return jsonify(result)


@bp.post("/api/calendar/events")
@require_auth
def create_event():
    if g.ctx["role"] not in ("directeur", "discipline"):
        return _denied("calendar.create")
    data = json_object(request.get_json(force=True))
    kind = data.get("kind") or "evenement"
    if kind not in EVENT_KINDS:
        raise ValidationError("kind invalide.")
    title = required_text(data.get("title"), "title", 160)
    starts_on = (data.get("starts_on") or "").strip() or None
    ends_on = (data.get("ends_on") or "").strip() or None
    for v in (starts_on, ends_on):
        if v and not ISO_DATE.match(v):
            raise ValidationError("Les dates doivent être au format AAAA-MM-JJ.")
    if kind != "communique" and not starts_on:
        raise ValidationError("Un événement doit avoir une date (un communiqué peut ne pas en avoir).")
    scope = data.get("target_scope") or "all"
    value = data.get("target_value") or None
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    if scope == "class":
        if not value or not school.can_access_class(conn, g.ctx, value):
            conn.close()
            return jsonify({"error": "Classe introuvable ou hors de votre périmètre."}), 404
    elif scope == "cycle":
        if value not in ("maternelle", "primaire", "secondaire"):
            conn.close()
            raise ValidationError("target_value doit être maternelle, primaire ou secondaire.")
        if g.ctx["role"] == "discipline" and value not in school.discipline_scope_cycles(conn, g.ctx):
            conn.close()
            return _denied("calendar.create", "Ce cycle est hors de votre périmètre.")
    elif scope == "all":
        if g.ctx["role"] == "discipline":
            # Le DD publie pour son périmètre ; « toute l'école » reste à la Direction.
            scope, value = "cycle", school.discipline_scope_cycles(conn, g.ctx)[0]
    else:
        conn.close()
        raise ValidationError("target_scope doit être all, cycle ou class.")
    audience = data.get("audience") or "all"
    if audience not in ("all", "parents", "staff"):
        raise ValidationError("audience invalide.")
    now = str(time.time())
    eid = new_id()
    ev = {"id": eid, "kind": kind, "title": title, "body": (data.get("body") or "").strip()[:2000] or None, "starts_on": starts_on, "ends_on": ends_on,
          "starts_time": (data.get("starts_time") or "").strip()[:5] or None, "target_scope": scope, "target_value": value, "audience": audience}
    conn.execute(
        """INSERT INTO calendar_events (id, tenant_id, kind, title, body, starts_on, ends_on, starts_time, target_scope, target_value, audience, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, tenant_id, kind, title, ev["body"], starts_on, ends_on, ev["starts_time"], scope, value, audience, g.ctx["user_id"], now, now),
    )
    conn.commit()
    recipients = [u for u in _event_recipients(conn, tenant_id, ev) if u != g.ctx["user_id"]]
    event = events_module.emit(conn, tenant_id, "calendar.event.published", "calendar_event", eid, g.ctx["user_id"], payload={"kind": kind, "recipients": len(recipients)})
    notif_module.on_event_published(conn, tenant_id, ev, recipients, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "calendar.event_created", "calendar_event", eid, "success", after={"kind": kind, "scope": scope})
    return jsonify({"id": eid, "notified": len(recipients)}), 201


@bp.delete("/api/calendar/events/<event_id>")
@require_auth
def delete_event(event_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM calendar_events WHERE id=? AND tenant_id=?", (event_id, g.ctx["tenant_id"])).fetchone()
    if not row or (g.ctx["role"] != "directeur" and row["created_by"] != g.ctx["user_id"]):
        conn.close()
        return _not_found("calendar.delete")
    conn.execute("DELETE FROM calendar_events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "calendar.event_deleted", "calendar_event", event_id, "success")
    return jsonify({"ok": True})


@bp.get("/api/calendar")
@require_auth
def calendar_feed():
    """Tout ce qui a une date pour cet utilisateur, sur un mois : événements,
    examens, devoirs, convocations, échéances, présence des enfants."""
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise ValidationError("month doit être au format AAAA-MM.")
    start = month + "-01"
    y, m = int(month[:4]), int(month[5:7])
    end = (date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)).isoformat()
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    role = g.ctx["role"]
    items = []
    class_ids = _class_ids_for_ctx(conn)

    # Événements ciblés (même filtre de visibilité que la liste)
    rows = conn.execute(
        """SELECT * FROM calendar_events WHERE tenant_id=? AND ((starts_on BETWEEN ? AND ?) OR (ends_on BETWEEN ? AND ?) OR (starts_on <= ? AND ends_on >= ?))""",
        (tenant_id, start, end, start, end, start, end)).fetchall()
    my_cycles = None
    if class_ids is not None:
        my_cycles = {r["cycle"] for r in conn.execute(f"SELECT cycle FROM classes WHERE id IN ({','.join('?' for _ in class_ids)})", class_ids)} if class_ids else set()
    for e in rows:
        if role == "parent" and e["audience"] == "staff":
            continue
        if role in ("professeur", "discipline") and e["audience"] == "parents":
            continue
        if class_ids is not None:
            if e["target_scope"] == "class" and e["target_value"] not in class_ids:
                continue
            if e["target_scope"] == "cycle" and e["target_value"] not in my_cycles:
                continue
        items.append({"date": e["starts_on"], "end": e["ends_on"], "time": e["starts_time"], "kind": e["kind"], "title": e["title"], "body": e["body"], "link": "calendrier.html"})

    # Examens et devoirs des classes visibles
    if class_ids is None or class_ids:
        if class_ids is None:
            cfilter, cparams = "", []
        else:
            cfilter, cparams = f" AND class_id IN ({','.join('?' for _ in class_ids)})", list(class_ids)
        for x in conn.execute(f"SELECT x.*, c.name AS class_name FROM exams x JOIN classes c ON c.id=x.class_id WHERE x.tenant_id=? AND x.date BETWEEN ? AND ?{cfilter.replace('class_id', 'x.class_id')}",
                              [tenant_id, start, end] + cparams):
            items.append({"date": x["date"], "time": x["start_time"], "kind": "examen", "title": f"{x['exam_type']} — {x['subject']}",
                          "body": x["class_name"] + (f" · {x['room']}" if x["room"] else ""), "link": f"classe.html?id={x['class_id']}&tab=horaire"})
        for r in conn.execute(f"SELECT r.id, r.title, r.due_date, r.class_id, c.name AS class_name FROM resources r JOIN classes c ON c.id=r.class_id WHERE r.tenant_id=? AND r.kind='devoir' AND r.due_date BETWEEN ? AND ?{cfilter.replace('class_id', 'r.class_id')}",
                              [tenant_id, start, end] + cparams):
            items.append({"date": r["due_date"], "kind": "devoir", "title": f"Devoir à rendre — {r['title']}", "body": r["class_name"], "link": f"ressources.html?class={r['class_id']}"})

    # Parent : présence, échéances, convocations de ses enfants
    if role == "parent":
        for sid in school.own_children_ids(conn, g.ctx):
            s = conn.execute("SELECT first_name FROM students WHERE id=?", (sid,)).fetchone()
            for a in conn.execute("SELECT date, status FROM attendance WHERE tenant_id=? AND student_id=? AND date BETWEEN ? AND ?", (tenant_id, sid, start, end)):
                items.append({"date": a["date"], "kind": "presence_" + a["status"], "title": f"{s['first_name']} — " + {"present": "présent", "late": "retard", "absent": "absent", "excused": "excusé"}[a["status"]], "link": f"eleve-dossier.html?id={sid}&tab=presence"})
            for o in conn.execute("SELECT o.due_date, o.amount, o.currency, COALESCE(o.label, c.name) AS label FROM obligations o JOIN catalog_items c ON c.id=o.catalog_item_id WHERE o.tenant_id=? AND o.student_id=? AND o.due_date BETWEEN ? AND ?", (tenant_id, sid, start, end)):
                items.append({"date": o["due_date"], "kind": "echeance", "title": f"Échéance — {o['label']}", "body": f"{s['first_name']} · {o['amount']:.0f} {o['currency']}", "link": f"eleve-dossier.html?id={sid}&tab=finance"})
            for cv in conn.execute("SELECT * FROM convocations WHERE tenant_id=? AND student_id=? AND scheduled_on BETWEEN ? AND ? AND status<>'cancelled'", (tenant_id, sid, start, end)):
                items.append({"date": cv["scheduled_on"], "time": cv["scheduled_time"], "kind": "convocation", "title": f"Convocation — {s['first_name']}", "body": cv["motif"], "link": f"eleve-dossier.html?id={sid}&tab=discipline"})
    elif role in ("discipline", "directeur"):
        if class_ids is None:
            sfilter, sparams = "", []
        else:
            sfilter, sparams = f" AND cv.student_id IN (SELECT id FROM students WHERE tenant_id=cv.tenant_id AND class_id IN ({','.join('?' for _ in class_ids)}))", list(class_ids)
        for cv in conn.execute(f"SELECT cv.*, s.first_name, s.last_name FROM convocations cv JOIN students s ON s.id=cv.student_id WHERE cv.tenant_id=? AND cv.scheduled_on BETWEEN ? AND ? AND cv.status<>'cancelled'{sfilter}",
                               [tenant_id, start, end] + sparams):
            items.append({"date": cv["scheduled_on"], "time": cv["scheduled_time"], "kind": "convocation", "title": f"Convocation — {cv['first_name']} {cv['last_name']}", "body": cv["motif"], "link": f"eleve-dossier.html?id={cv['student_id']}&tab=discipline"})

    settings = school.get_settings(conn, tenant_id)
    conn.close()
    items.sort(key=lambda i: (i["date"] or "", i.get("time") or ""))
    return jsonify({"month": month, "items": items, "exam_period": {"starts": settings.get("exam_period_starts"), "ends": settings.get("exam_period_ends")}})


# ===========================================================================
# RESSOURCES : livres, leçons, fiches, devoirs (par classe)
# ===========================================================================

@bp.get("/api/resources")
@require_auth
def list_resources():
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    class_ids = _class_ids_for_ctx(conn)
    wanted = request.args.get("class_id")
    if class_ids is not None and not class_ids:
        conn.close()
        return jsonify([])
    if wanted and class_ids is not None and wanted not in class_ids:
        conn.close()
        return _not_found("resources.list")
    where, params = "r.tenant_id=?", [tenant_id]
    if wanted:
        where += " AND r.class_id=?"; params.append(wanted)
    elif class_ids is not None:
        where += f" AND r.class_id IN ({','.join('?' for _ in class_ids)})"; params += class_ids
    rows = conn.execute(
        f"""SELECT r.id, r.class_id, r.kind, r.title, r.subject, r.description, r.file_name, r.file_size, r.due_date, r.created_at,
                   c.name AS class_name, u.name AS author FROM resources r JOIN classes c ON c.id=r.class_id LEFT JOIN users u ON u.id=r.published_by
            WHERE {where} ORDER BY r.created_at DESC LIMIT 400""", params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/resources")
@require_auth
def create_resource():
    if g.ctx["role"] not in ("directeur", "professeur"):
        return _denied("resources.create")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    cls = school.can_access_class(conn, g.ctx, data.get("class_id"))
    if not cls:
        conn.close()
        return _not_found("resources.create", "Classe introuvable ou hors de votre périmètre.")
    kind = data.get("kind") or "lecon"
    if kind not in RESOURCE_KINDS:
        raise ValidationError("kind invalide.")
    title = required_text(data.get("title"), "title", 160)
    due = (data.get("due_date") or "").strip() or None
    if kind == "devoir" and not due:
        raise ValidationError("Un devoir doit avoir une date de remise.")
    if due and not ISO_DATE.match(due):
        raise ValidationError("due_date doit être au format AAAA-MM-JJ.")
    file_data = _check_file(data.get("file_data"), ("data:application/pdf", "data:image/"), MAX_RESOURCE_BYTES, "Le fichier")
    rid = new_id()
    now = str(time.time())
    resource = {"id": rid, "class_id": cls["id"], "kind": kind, "title": title, "subject": (data.get("subject") or "").strip()[:80] or None,
                "description": (data.get("description") or "").strip()[:2000] or None, "due_date": due}
    conn.execute(
        """INSERT INTO resources (id, tenant_id, class_id, kind, title, subject, description, file_name, file_data, file_size, due_date, published_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid, tenant_id, cls["id"], kind, title, resource["subject"], resource["description"], (data.get("file_name") or "").strip()[:160] or None,
         file_data, len(file_data) if file_data else None, due, g.ctx["user_id"], now),
    )
    conn.commit()
    event = events_module.emit(conn, tenant_id, "resource.published", "resource", rid, g.ctx["user_id"], payload={"kind": kind, "class_id": cls["id"]})
    notif_module.on_resource_published(conn, tenant_id, resource, cls["name"], event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "resource.published", "resource", rid, "success", after={"kind": kind, "class_id": cls["id"]})
    return jsonify({"id": rid}), 201


@bp.get("/api/resources/<resource_id>/file")
@require_auth
def resource_file(resource_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM resources WHERE id=? AND tenant_id=?", (resource_id, g.ctx["tenant_id"])).fetchone()
    if not row or not school.can_access_class(conn, g.ctx, row["class_id"]):
        conn.close()
        return _not_found("resources.file")
    conn.close()
    return jsonify({"file_name": row["file_name"], "file_data": row["file_data"], "title": row["title"]})


@bp.delete("/api/resources/<resource_id>")
@require_auth
def delete_resource(resource_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM resources WHERE id=? AND tenant_id=?", (resource_id, g.ctx["tenant_id"])).fetchone()
    if not row or (g.ctx["role"] != "directeur" and row["published_by"] != g.ctx["user_id"]):
        conn.close()
        return _not_found("resources.delete")
    conn.execute("DELETE FROM resources WHERE id=?", (resource_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ===========================================================================
# DOCUMENTS OFFICIELS & ATTESTATIONS
# ===========================================================================

@bp.get("/api/documents")
@require_auth
def list_documents():
    conn = db.get_connection()
    where = "tenant_id=?" + ("" if _staff() else " AND visible_to='all'")
    rows = conn.execute(f"SELECT id, kind, title, file_name, file_size, visible_to, created_at FROM school_documents WHERE {where} ORDER BY created_at DESC", (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/documents")
@require_auth
def create_document():
    if g.ctx["role"] != "directeur":
        return _denied("documents.create")
    data = json_object(request.get_json(force=True))
    title = required_text(data.get("title"), "title", 160)
    kind = data.get("kind") if data.get("kind") in ("reglement", "calendrier", "autre") else "autre"
    file_data = _check_file(data.get("file_data"), ("data:application/pdf", "data:image/"), MAX_DOCUMENT_BYTES, "Le document")
    if not file_data:
        raise ValidationError("Un fichier PDF ou image est requis.")
    visible_to = data.get("visible_to") if data.get("visible_to") in ("all", "staff") else "all"
    conn = db.get_connection()
    did = new_id()
    conn.execute("INSERT INTO school_documents (id, tenant_id, kind, title, file_name, file_data, file_size, visible_to, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (did, g.ctx["tenant_id"], kind, title, (data.get("file_name") or "").strip()[:160] or None, file_data, len(file_data), visible_to, g.ctx["user_id"], str(time.time())))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "document.uploaded", "school_document", did, "success", after={"kind": kind})
    return jsonify({"id": did}), 201


@bp.get("/api/documents/<doc_id>/file")
@require_auth
def document_file(doc_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM school_documents WHERE id=? AND tenant_id=?", (doc_id, g.ctx["tenant_id"])).fetchone()
    conn.close()
    if not row or (row["visible_to"] == "staff" and not _staff()):
        return _not_found("documents.file")
    return jsonify({"file_name": row["file_name"], "file_data": row["file_data"], "title": row["title"]})


@bp.delete("/api/documents/<doc_id>")
@require_auth
def delete_document(doc_id):
    if g.ctx["role"] != "directeur":
        return _denied("documents.delete")
    conn = db.get_connection()
    # rowcount vérifié : le filtre tenant_id protégeait bien le document d'un
    # autre établissement, mais la route répondait « ok » sans rien supprimer.
    # L'interface affichait alors une suppression qui n'avait pas eu lieu.
    curseur = conn.execute("DELETE FROM school_documents WHERE id=? AND tenant_id=?", (doc_id, g.ctx["tenant_id"]))
    conn.commit()
    conn.close()
    if not (curseur.rowcount or 0):
        return _not_found("documents.delete", "Document introuvable pour cet établissement.")
    return jsonify({"ok": True})


@bp.get("/api/students/<student_id>/attestation")
@require_auth
def attestation(student_id):
    """Données réelles d'une attestation de fréquentation — imprimée par le navigateur."""
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("attestation")
    tenant = conn.execute("SELECT * FROM tenants WHERE id=?", (g.ctx["tenant_id"],)).fetchone()
    settings = school.get_settings(conn, g.ctx["tenant_id"])
    year = conn.execute("SELECT label FROM academic_years WHERE id=?", (student["academic_year_id"],)).fetchone()
    director = conn.execute("SELECT u.name FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? AND m.role='directeur' ORDER BY m.created_at LIMIT 1", (g.ctx["tenant_id"],)).fetchone()
    att = school.attendance_summary(conn, g.ctx["tenant_id"], student_id)
    conn.close()
    return jsonify({
        "school": {"name": tenant["name"], "phone": settings["school_phone"], "address": settings["school_address"], "email": settings["school_email"], "logo_data": tenant["logo_data"]},
        "student": {"code": student["code"], "first_name": student["first_name"], "last_name": student["last_name"], "birth_date": student["birth_date"], "gender": student["gender"], "class_name": student["class_name"]},
        "academic_year": year["label"] if year else "", "director": director["name"] if director else "", "attendance": att, "issued_on": date.today().isoformat(),
    })


# ===========================================================================
# CAHIER DE COMMUNICATION (fil par élève)
# ===========================================================================

def _thread_participants(conn, tenant_id, student):
    """Parents + titulaire/enseignants de la classe + DD du périmètre + Direction."""
    users = notif_module.guardian_users(conn, tenant_id, student["id"]) + notif_module.class_staff(conn, tenant_id, student["class_id"]) + notif_module.directors(conn, tenant_id)
    for dd in conn.execute("SELECT user_id, scope_cycles FROM memberships WHERE tenant_id=? AND role='discipline' AND status='active'", (tenant_id,)):
        cycles = ["secondaire"]
        if dd["scope_cycles"]:
            try:
                cycles = json.loads(dd["scope_cycles"]) or cycles
            except ValueError:
                pass
        if student["class_cycle"] in cycles:
            users.append(dd["user_id"])
    return list(dict.fromkeys(users))


@bp.get("/api/messages/threads")
@require_auth
def message_threads():
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    rows = conn.execute(
        f"""SELECT s.id, s.first_name, s.last_name, s.code, c.name AS class_name,
                   (SELECT body FROM messages m WHERE m.student_id=s.id ORDER BY m.created_at DESC LIMIT 1) AS last_body,
                   (SELECT created_at FROM messages m WHERE m.student_id=s.id ORDER BY m.created_at DESC LIMIT 1) AS last_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.student_id=s.id AND m.sender_id<>? AND NOT EXISTS (SELECT 1 FROM message_reads r WHERE r.message_id=m.id AND r.user_id=?)) AS unread
            FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE {where} AND s.status='active'
            -- ORDER BY : PostgreSQL accepte un alias de sortie seul, jamais
            -- à l'intérieur d'une expression — `(last_at IS NULL)` faisait
            -- échouer toute la route. `NULLS LAST` dit la même chose et passe
            -- sur les deux moteurs (SQLite le comprend depuis 3.30).
            ORDER BY last_at DESC NULLS LAST, s.last_name LIMIT 500""",
        (g.ctx["user_id"], g.ctx["user_id"], *params)).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    if g.ctx["role"] != "parent":
        # Le personnel voit d'abord les fils actifs ; les élèves sans message restent accessibles via la recherche.
        result = [r for r in result if r["last_at"]] + [r for r in result if not r["last_at"]][:60]
    return jsonify(result)


@bp.get("/api/messages/unread-count")
@require_auth
def messages_unread():
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify({"unread": 0})
    n = conn.execute(
        f"""SELECT COUNT(*) n FROM messages m JOIN students s ON s.id=m.student_id WHERE {where} AND m.sender_id<>?
            AND NOT EXISTS (SELECT 1 FROM message_reads r WHERE r.message_id=m.id AND r.user_id=?)""", (*params, g.ctx["user_id"], g.ctx["user_id"])).fetchone()["n"]
    conn.close()
    return jsonify({"unread": n})


@bp.get("/api/messages/<student_id>")
@require_auth
def message_thread(student_id):
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("messages.read")
    rows = conn.execute(
        """SELECT m.id, m.sender_id, m.sender_role, m.body, m.created_at, u.name AS sender_name FROM messages m JOIN users u ON u.id=m.sender_id
           WHERE m.tenant_id=? AND m.student_id=? ORDER BY m.created_at""", (g.ctx["tenant_id"], student_id)).fetchall()
    now = str(time.time())
    for r in rows:
        if r["sender_id"] != g.ctx["user_id"]:
            conn.execute("INSERT INTO message_reads (message_id, user_id, read_at) VALUES (?,?,?) ON CONFLICT DO NOTHING", (r["id"], g.ctx["user_id"], now))
    conn.commit()
    conn.close()
    return jsonify({"student": {"id": student["id"], "first_name": student["first_name"], "last_name": student["last_name"], "class_name": student["class_name"], "code": student["code"]},
                    "messages": [dict(r) for r in rows]})


@bp.post("/api/messages/<student_id>")
@require_auth
def post_message(student_id):
    data = json_object(request.get_json(force=True))
    body = required_text(data.get("body"), "body", 2000)
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("messages.post")
    mid = new_id()
    now = str(time.time())
    conn.execute("INSERT INTO messages (id, tenant_id, student_id, sender_id, sender_role, body, created_at) VALUES (?,?,?,?,?,?,?)",
                 (mid, tenant_id, student_id, g.ctx["user_id"], g.ctx["role"], body, now))
    conn.execute("INSERT INTO message_reads (message_id, user_id, read_at) VALUES (?,?,?) ON CONFLICT DO NOTHING", (mid, g.ctx["user_id"], now))
    conn.commit()
    participants = _thread_participants(conn, tenant_id, student)
    if g.ctx["role"] == "parent":
        recipients = [u for u in participants if u not in notif_module.guardian_users(conn, tenant_id, student_id)]
    else:
        recipients = notif_module.guardian_users(conn, tenant_id, student_id)
    event = events_module.emit(conn, tenant_id, "message.sent", "student", student_id, g.ctx["user_id"], payload={"recipients": len(recipients)})
    notif_module.on_message(conn, tenant_id, student, g.ctx["user_id"], g.ctx["role"], body, recipients, event_id=event["id"])
    conn.close()
    return jsonify({"id": mid, "created_at": now}), 201


# ===========================================================================
# JUSTIFICATIONS D'ABSENCE (parent → décision humaine)
# ===========================================================================

@bp.post("/api/students/<student_id>/justifications")
@require_auth
def request_justification(student_id):
    if g.ctx["role"] != "parent":
        return _denied("justification.request", "Seul le parent justifie une absence ; le personnel excuse directement depuis l'appel.")
    data = json_object(request.get_json(force=True))
    day = (data.get("date") or "").strip()
    if not ISO_DATE.match(day) or day > school.today_iso():
        raise ValidationError("date invalide.")
    reason = required_text(data.get("reason"), "reason", 600)
    attachment = _check_file(data.get("attachment_data"), ("data:application/pdf", "data:image/"), 1_500_000, "La pièce jointe")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("justification.request")
    if conn.execute("SELECT 1 FROM attendance_justifications WHERE tenant_id=? AND student_id=? AND date=? AND status='pending'", (tenant_id, student_id, day)).fetchone():
        conn.close()
        return jsonify({"error": "Une justification est déjà en attente pour cette date."}), 409
    jid = new_id()
    now = str(time.time())
    conn.execute(
        """INSERT INTO attendance_justifications (id, tenant_id, student_id, date, reason, attachment_name, attachment_data, status, requested_by, created_at)
           VALUES (?,?,?,?,?,?,?,'pending',?,?)""",
        (jid, tenant_id, student_id, day, reason, (data.get("attachment_name") or "").strip()[:160] or None, attachment, g.ctx["user_id"], now))
    conn.commit()
    event = events_module.emit(conn, tenant_id, "attendance.justification.requested", "student", student_id, g.ctx["user_id"], payload={"date": day})
    notif_module.on_justification_requested(conn, tenant_id, student, {"date": day, "reason": reason}, event_id=event["id"])
    conn.close()
    return jsonify({"id": jid}), 201


@bp.get("/api/justifications")
@require_auth
def list_justifications():
    if g.ctx["role"] not in ("directeur", "discipline", "professeur"):
        return _denied("justifications.list")
    conn = db.get_connection()
    where, params = school.students_where_clause(conn, g.ctx)
    if where is None:
        conn.close()
        return jsonify([])
    status = request.args.get("status")
    extra = " AND j.status=?" if status in ("pending", "accepted", "refused") else ""
    rows = conn.execute(
        f"""SELECT j.id, j.student_id, j.date, j.reason, j.status, j.decision_note, j.created_at, j.decided_at, j.attachment_name, j.attachment_data IS NOT NULL AS has_attachment,
                   s.first_name, s.last_name, s.code, c.name AS class_name, a.status AS attendance_status
            FROM attendance_justifications j JOIN students s ON s.id=j.student_id LEFT JOIN classes c ON c.id=s.class_id
            LEFT JOIN attendance a ON a.student_id=j.student_id AND a.date=j.date
            WHERE {where}{extra} ORDER BY (j.status<>'pending'), j.created_at DESC LIMIT 300""", params + ((status,) if extra else ())).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/api/justifications/<jid>/attachment")
@require_auth
def justification_attachment(jid):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM attendance_justifications WHERE id=? AND tenant_id=?", (jid, g.ctx["tenant_id"])).fetchone()
    if not row or not school.resolve_student_access(conn, g.ctx, row["student_id"]):
        conn.close()
        return _not_found("justification.attachment")
    conn.close()
    return jsonify({"file_name": row["attachment_name"], "file_data": row["attachment_data"]})


@bp.post("/api/justifications/<jid>/decide")
@require_auth
def decide_justification(jid):
    if g.ctx["role"] not in ("directeur", "discipline", "professeur"):
        return _denied("justification.decide")
    data = json_object(request.get_json(force=True))
    status = data.get("status")
    if status not in ("accepted", "refused"):
        raise ValidationError("status doit être accepted ou refused.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM attendance_justifications WHERE id=? AND tenant_id=?", (jid, tenant_id)).fetchone()
    if not row:
        conn.close()
        return _not_found("justification.decide")
    student = school.resolve_student_access(conn, g.ctx, row["student_id"])
    if not student:
        conn.close()
        return _not_found("justification.decide")
    if g.ctx["role"] == "professeur" and not school.is_titulaire_of(conn, g.ctx, student["class_id"]):
        conn.close()
        return _denied("justification.decide", "Seul le titulaire de la classe (ou le DD / la Direction) décide d'une justification.")
    if row["status"] != "pending":
        conn.close()
        return jsonify({"error": "Cette justification a déjà été traitée."}), 409
    now = str(time.time())
    note = (data.get("note") or "").strip()[:300] or None
    conn.execute("UPDATE attendance_justifications SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?", (status, g.ctx["user_id"], now, note, jid))
    if status == "accepted":
        conn.execute(
            """INSERT INTO attendance (id, tenant_id, student_id, class_id, date, status, note, recorded_by, created_at, updated_at, source)
               VALUES (?,?,?,?,?,'excused',?,?,?,?,'justification')
               ON CONFLICT(tenant_id, student_id, date) DO UPDATE SET status='excused', note=excluded.note, recorded_by=excluded.recorded_by, updated_at=excluded.updated_at""",
            (new_id(), tenant_id, student["id"], student["class_id"], row["date"], ("Justifiée : " + row["reason"])[:200], g.ctx["user_id"], now, now))
    conn.commit()
    j = dict(conn.execute("SELECT * FROM attendance_justifications WHERE id=?", (jid,)).fetchone())
    event = events_module.emit(conn, tenant_id, "attendance.justification.decided", "student", student["id"], g.ctx["user_id"], payload={"status": status, "date": row["date"]})
    notif_module.on_justification_decided(conn, tenant_id, student, j, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "attendance.justification_decided", "attendance_justification", jid, "success", after={"status": status})
    return jsonify({"ok": True, "status": status})


# ===========================================================================
# DROIT DE RÉPONSE (incident communiqué)
# ===========================================================================

@bp.get("/api/incidents/<incident_id>/replies")
@require_auth
def incident_replies(incident_id):
    conn = db.get_connection()
    inc = conn.execute("SELECT * FROM incidents WHERE id=? AND tenant_id=?", (incident_id, g.ctx["tenant_id"])).fetchone()
    if not inc or not school.resolve_student_access(conn, g.ctx, inc["student_id"]) or (g.ctx["role"] == "parent" and not inc["notify_parent"]):
        conn.close()
        return _not_found("incident.replies")
    rows = conn.execute("SELECT r.id, r.body, r.created_at, u.name AS author, m.role AS author_role FROM incident_replies r JOIN users u ON u.id=r.user_id LEFT JOIN memberships m ON m.user_id=r.user_id AND m.tenant_id=r.tenant_id WHERE r.incident_id=? ORDER BY r.created_at", (incident_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/api/incidents/<incident_id>/replies")
@require_auth
def reply_incident(incident_id):
    body = required_text((json_object(request.get_json(force=True))).get("body"), "body", 1500)
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    inc = conn.execute("SELECT * FROM incidents WHERE id=? AND tenant_id=?", (incident_id, tenant_id)).fetchone()
    if not inc:
        conn.close()
        return _not_found("incident.reply")
    student = school.resolve_student_access(conn, g.ctx, inc["student_id"])
    if not student or (g.ctx["role"] == "parent" and not inc["notify_parent"]) or g.ctx["role"] == "professeur":
        conn.close()
        return _not_found("incident.reply")
    rid = new_id()
    conn.execute("INSERT INTO incident_replies (id, tenant_id, incident_id, user_id, body, created_at) VALUES (?,?,?,?,?,?)", (rid, tenant_id, incident_id, g.ctx["user_id"], body, str(time.time())))
    conn.commit()
    event = events_module.emit(conn, tenant_id, "discipline.incident.replied", "incident", incident_id, g.ctx["user_id"], payload={"role": g.ctx["role"]})
    notif_module.on_incident_reply(conn, tenant_id, student, dict(inc), g.ctx["role"], event_id=event["id"])
    conn.close()
    return jsonify({"id": rid}), 201


# ===========================================================================
# CONTACTS & PRÉFÉRENCES
# ===========================================================================

@bp.get("/api/students/<student_id>/contacts")
@require_auth
def student_contacts(student_id):
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("contacts")
    settings = school.get_settings(conn, tenant_id)
    teachers = []
    for t in conn.execute(
        """SELECT u.id, u.name, u.email, u.phone, ct.subject, ct.is_titulaire, p.share_phone FROM class_teachers ct JOIN users u ON u.id=ct.user_id
           LEFT JOIN user_preferences p ON p.user_id=u.id WHERE ct.tenant_id=? AND ct.class_id=? ORDER BY ct.is_titulaire DESC, u.name""", (tenant_id, student["class_id"])):
        visible = g.ctx["role"] != "parent" or bool(settings.get("teacher_contact_visible")) or bool(t["share_phone"])
        teachers.append({"id": t["id"], "name": t["name"], "subject": t["subject"], "is_titulaire": bool(t["is_titulaire"]),
                         "phone": t["phone"] if visible else None, "email": school.display_email(t["email"]) if visible else None, "contact_visible": visible})
    dds = [{"name": r["name"], "title": r["title"]} for r in conn.execute(
        "SELECT u.name, m.title FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? AND m.role='discipline' AND m.status='active'", (tenant_id,))]
    conn.close()
    return jsonify({"teachers": teachers, "discipline": dds,
                    "school": {"phone": settings["school_phone"], "email": settings["school_email"], "address": settings["school_address"]},
                    "message_link": f"messages.html?student={student_id}"})


@bp.get("/api/me/preferences")
@require_auth
def get_preferences():
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM user_preferences WHERE user_id=?", (g.ctx["user_id"],)).fetchone()
    conn.close()
    return jsonify({"notify_present_daily": bool(row["notify_present_daily"]) if row else True, "share_phone": bool(row["share_phone"]) if row else False})


@bp.put("/api/me/preferences")
@require_auth
def put_preferences():
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    cur = conn.execute("SELECT * FROM user_preferences WHERE user_id=?", (g.ctx["user_id"],)).fetchone()
    npd = int(bool(data.get("notify_present_daily", cur["notify_present_daily"] if cur else 1)))
    sp = int(bool(data.get("share_phone", cur["share_phone"] if cur else 0)))
    conn.execute("INSERT INTO user_preferences (user_id, notify_present_daily, share_phone, updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET notify_present_daily=excluded.notify_present_daily, share_phone=excluded.share_phone, updated_at=excluded.updated_at",
                 (g.ctx["user_id"], npd, sp, str(time.time())))
    conn.commit()
    conn.close()
    return jsonify({"notify_present_daily": bool(npd), "share_phone": bool(sp)})
