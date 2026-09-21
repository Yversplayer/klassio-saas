"""KLASSIO backend — résultats : périodes officielles et proclamation,
appréciations (maternelle), cote de conduite, décisions de fin d'année,
vue de classe pour le conseil, années scolaires.

Les notes existent en interne dès la saisie ; les parents ne les voient
qu'après proclamation de la période par la Direction.
"""
import json
import re
import time
from datetime import date

from flask import Blueprint, request, jsonify, g, current_app

import db
import events as events_module
import notifications as notif_module
import ingestion
import results_import
import school
import deliberations as delib
from security import require_auth, new_id, audit
from validation import json_object, ValidationError, required_text

bp = Blueprint("academics", __name__)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MATERNELLE_DOMAINS = ["Langage", "Motricité", "Socialisation", "Autonomie", "Éveil et découverte", "Graphisme"]
LEVELS = {1: "En construction", 2: "En cours d'acquisition", 3: "Acquis", 4: "Dépassé"}


def _denied(action, message="Vous n'avez pas l'autorisation d'effectuer cette action."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, status="denied")
    return jsonify({"error": message}), 403


def _not_found(action, message="Introuvable ou accès non autorisé."):
    audit(g.ctx["tenant_id"], g.ctx["user_id"], action, status="denied")
    return jsonify({"error": message}), 404


def _active_year(conn, tenant_id):
    row = conn.execute("SELECT * FROM academic_years WHERE tenant_id=? ORDER BY is_active DESC, created_at DESC LIMIT 1", (tenant_id,)).fetchone()
    return row


CHAMPS_DATE = ("starts_on", "ends_on", "result_entry_deadline", "validation_deadline", "proclamation_at")


def _valider_dates(data, existant=None):
    """Valide le format des dates ET leur cohérence entre elles.

    Un calendrier incohérent — période qui finit avant de commencer, échéance
    de saisie antérieure à la fin de la période, proclamation avant la
    validation — produirait des états impossibles que `period_state` devrait
    ensuite démêler. On refuse à l'écriture plutôt que d'interpréter à la
    lecture.

    `existant` est la période DÉJÀ EN BASE, sur une modification. Sans elle, la
    cohérence n'était vérifiée qu'entre les champs présents dans la requête :
    envoyer la seule `ends_on`, antérieure au `starts_on` déjà enregistré,
    passait — le début, absent du corps, était lu comme None et comparé à rien.
    Le calendrier devenait incohérent en base sans qu'aucune règle n'ait été
    violée « visiblement ».
    """
    out = {}
    for f in CHAMPS_DATE:
        if f not in data and existant is not None:
            # Champ non modifié : on valide contre ce qui est déjà enregistré.
            out[f] = existant[f] if f in existant.keys() else None
            continue
        v = data.get(f)
        if v in (None, ""):
            out[f] = None
            continue
        if not isinstance(v, str) or not ISO_DATE.match(v):
            raise ValidationError(f"{f} doit être au format AAAA-MM-JJ.")
        out[f] = v

    def avant(a, b, message):
        if out.get(a) and out.get(b) and out[a] > out[b]:
            raise ValidationError(message)

    avant("starts_on", "ends_on", "Une période ne peut pas se terminer avant d'avoir commencé.")
    avant("ends_on", "result_entry_deadline",
          "L'échéance de saisie des résultats ne peut pas précéder la fin de la période.")
    avant("result_entry_deadline", "validation_deadline",
          "L'échéance de validation ne peut pas précéder celle de saisie.")
    avant("validation_deadline", "proclamation_at",
          "La proclamation ne peut pas précéder l'échéance de validation.")
    return out


def _valider_division(valeur):
    if valeur in (None, ""):
        return None   # période commune à toutes les divisions
    if valeur not in school.DIVISIONS:
        raise ValidationError(f"division doit valoir {', '.join(school.DIVISIONS)} — ou être absente.")
    return valeur


# ===========================================================================
# ANNÉES SCOLAIRES
# ===========================================================================

@bp.post("/api/academic-years/<year_id>/activate")
@require_auth
def activate_year(year_id):
    if g.ctx["role"] != "directeur":
        return _denied("year.activate")
    conn = db.get_connection()
    if not conn.execute("SELECT 1 FROM academic_years WHERE id=? AND tenant_id=?", (year_id, g.ctx["tenant_id"])).fetchone():
        conn.close()
        return _not_found("year.activate")
    conn.execute("UPDATE academic_years SET is_active=0 WHERE tenant_id=?", (g.ctx["tenant_id"],))
    conn.execute("UPDATE academic_years SET is_active=1 WHERE id=?", (year_id,))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "year.activated", "academic_year", year_id, "success")
    return jsonify({"ok": True})


# ===========================================================================
# PÉRIODES OFFICIELLES & PROCLAMATION
# ===========================================================================

@bp.get("/api/periods")
@require_auth
def list_periods():
    conn = db.get_connection()
    year = _active_year(conn, g.ctx["tenant_id"])
    rows = school.periods_for_year(conn, g.ctx["tenant_id"], year["id"]) if year else []
    conn.close()
    if g.ctx["role"] == "parent":
        rows = [{k: v for k, v in r.items() if k not in ("published_by", "locked_by")} for r in rows]
    return jsonify({"academic_year": dict(year) if year else None, "periods": rows})


@bp.get("/api/academic-calendar")
@require_auth
def academic_calendar():
    """Le calendrier tel que l'établissement l'a configuré, division par division.

    Rien n'est supposé ici : ni le nombre de périodes, ni leur nom, ni qu'une
    division en ait autant qu'une autre. On renvoie ce qui est déclaré, et la
    période en cours DÉDUITE DES DATES — c'est le backend qui sait quel jour on
    est, jamais l'horloge du navigateur.
    """
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    year_id = request.args.get("academic_year_id")
    if year_id:
        year = conn.execute("SELECT * FROM academic_years WHERE id=? AND tenant_id=?",
                            (year_id, tenant_id)).fetchone()
        if not year:
            conn.close()
            return _not_found("calendar.read")
    else:
        year = _active_year(conn, tenant_id)
    if not year:
        conn.close()
        return jsonify({"academic_year": None, "divisions": [], "current_period": None})

    # Divisions réellement utilisées par l'établissement, plus celles qui
    # portent déjà des périodes. Une école qui n'a que du secondaire ne se voit
    # pas proposer trois onglets vides.
    utilisees = {r["cycle"] for r in conn.execute(
        "SELECT DISTINCT cycle FROM classes WHERE tenant_id=? AND academic_year_id=? AND cycle IS NOT NULL",
        (tenant_id, year["id"]))}
    utilisees |= {r["division"] for r in conn.execute(
        "SELECT DISTINCT division FROM academic_periods WHERE tenant_id=? AND academic_year_id=? AND division IS NOT NULL",
        (tenant_id, year["id"]))}
    divisions = [d for d in school.DIVISIONS if d in utilisees] or list(school.DIVISIONS)

    toutes = school.periods_for_year(conn, tenant_id, year["id"])
    communes = [p for p in toutes if not p["division"]]
    sortie = []
    for d in divisions:
        propres = [p for p in toutes if p["division"] == d]
        # Une période propre à la division REMPLACE la période commune de même
        # libellé : c'est ainsi qu'une école donne au primaire six périodes là
        # où le secondaire en a quatre, sans dupliquer les autres.
        labels = {p["label"] for p in propres}
        effectives = sorted(propres + [p for p in communes if p["label"] not in labels],
                            key=lambda p: (p["sort"], p["label"]))
        sortie.append({
            "division": d,
            "period_count": len(effectives),
            "periods": effectives,
            "current_period": school.current_period(conn, tenant_id, year["id"], d),
        })
    courante = school.current_period(conn, tenant_id, year["id"])
    conn.close()
    return jsonify({
        "academic_year": dict(year),
        "today": school.today_iso(),
        "divisions": sortie,
        "current_period": courante,
    })


@bp.post("/api/periods")
@require_auth
def create_period():
    if g.ctx["role"] != "directeur":
        return _denied("period.create")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    year = _active_year(conn, tenant_id)
    if not year:
        conn.close()
        return jsonify({"error": "Aucune année scolaire."}), 409
    if data.get("preset") == "standard":
        existing = {r["label"] for r in school.periods_for_year(conn, tenant_id, year["id"])}
        created = 0
        for i, (label, is_exam, weight) in enumerate([("Période 1", 0, 1), ("Période 2", 0, 1), ("Examen 1er semestre", 1, 2), ("Période 3", 0, 1), ("Période 4", 0, 1), ("Examen 2e semestre", 1, 2)]):
            if label in existing:
                continue
            conn.execute("INSERT INTO academic_periods (id, tenant_id, academic_year_id, label, sort, weight, is_exam, created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (new_id(), tenant_id, year["id"], label, i, weight, is_exam, str(time.time())))
            created += 1
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "created": created}), 201
    label = required_text(data.get("label"), "label", 40)
    dates = _valider_dates(data)
    division = _valider_division(data.get("division"))
    try:
        weight = float(data.get("weight", 1))
        sort = int(data.get("sort", 0))
    except (TypeError, ValueError):
        raise ValidationError("weight/sort invalides.")
    etat = (data.get("admin_state") or "READY").upper()
    if etat not in ("DRAFT", "READY"):
        raise ValidationError("Une période se crée en DRAFT ou en READY.")
    pid = new_id()
    now = str(time.time())
    try:
        conn.execute(
            """INSERT INTO academic_periods (id, tenant_id, academic_year_id, division, label, sort, weight,
                                             starts_on, ends_on, is_exam, admin_state,
                                             result_entry_deadline, validation_deadline, proclamation_at,
                                             created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, tenant_id, year["id"], division, label, sort, weight,
             dates["starts_on"], dates["ends_on"], 1 if data.get("is_exam") else 0, etat,
             dates["result_entry_deadline"], dates["validation_deadline"], dates["proclamation_at"],
             now, now))
        conn.commit()
    except db.integrity_errors():
        # Restreint aux violations de contrainte : `except Exception` déguisait
        # n'importe quelle panne (colonne manquante, connexion perdue) en
        # « libellé déjà utilisé », et la vraie cause disparaissait.
        conn.close()
        return jsonify({"error": "Une période porte déjà ce libellé pour cette année."}), 409
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "period.created", "academic_period", pid, "success",
          after={"label": label, "division": division})
    return jsonify({"id": pid}), 201


@bp.put("/api/periods/<period_id>")
@require_auth
def update_period(period_id):
    """Dates, échéances et état d'une période.

    Une période VERROUILLÉE ne se modifie pas ici : il faut passer par la
    réouverture motivée. Sinon le verrou ne serait qu'un affichage.
    """
    if g.ctx["role"] != "directeur":
        return _denied("period.update")
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                       (period_id, tenant_id)).fetchone()
    if not row:
        conn.close()
        return _not_found("period.update")
    if school.period_state(dict(row)) == "LOCKED":
        conn.close()
        return _denied("period.update",
                       "Cette période est verrouillée. Rouvrez-la explicitement pour la modifier.")

    champs, params = [], []
    if "label" in data:
        champs.append("label=?"); params.append(required_text(data["label"], "label", 40))
    if "division" in data:
        champs.append("division=?"); params.append(_valider_division(data["division"]))
    if "sort" in data:
        try:
            champs.append("sort=?"); params.append(int(data["sort"]))
        except (TypeError, ValueError):
            raise ValidationError("sort invalide.")
    if "weight" in data:
        try:
            champs.append("weight=?"); params.append(float(data["weight"]))
        except (TypeError, ValueError):
            raise ValidationError("weight invalide.")
    if "is_exam" in data:
        champs.append("is_exam=?"); params.append(1 if data["is_exam"] else 0)
    if "admin_state" in data:
        etat = (data["admin_state"] or "").upper()
        if etat not in ("DRAFT", "READY", "ARCHIVED"):
            raise ValidationError("admin_state doit valoir DRAFT, READY ou ARCHIVED. "
                                  "Le verrouillage passe par /lock.")
        champs.append("admin_state=?"); params.append(etat)
    # La validation croise les champs envoyés AVEC ceux déjà enregistrés ; seuls
    # les champs effectivement fournis sont ensuite écrits.
    dates = _valider_dates(data, existant=row)
    for cle, valeur in dates.items():
        if cle in data:
            champs.append(f"{cle}=?"); params.append(valeur)
    if not champs:
        conn.close()
        return jsonify({"error": "Aucune modification fournie."}), 400
    champs.append("updated_at=?"); params.append(str(time.time()))
    try:
        conn.execute(f"UPDATE academic_periods SET {', '.join(champs)} WHERE id=? AND tenant_id=?",
                     params + [period_id, tenant_id])
        conn.commit()
    except db.integrity_errors():
        conn.close()
        return jsonify({"error": "Une période porte déjà ce libellé pour cette année."}), 409
    relu = dict(conn.execute("SELECT * FROM academic_periods WHERE id=?", (period_id,)).fetchone())
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "period.updated", "academic_period", period_id, "success",
          before={k: row[k] for k in ("starts_on", "ends_on", "admin_state")}, after=data)
    relu["state"] = school.period_state(relu)
    return jsonify(relu)


@bp.post("/api/periods/<period_id>/lock")
@require_auth
def lock_period(period_id):
    """Verrouille une période : ses résultats ne sont plus modifiables.

    C'est l'aboutissement normal du cycle — résultats validés, proclamés, puis
    fermés. Idempotent : verrouiller une période déjà verrouillée ne change pas
    la date de verrouillage initiale.
    """
    if g.ctx["role"] != "directeur":
        return _denied("period.lock")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                       (period_id, tenant_id)).fetchone()
    if not row:
        conn.close()
        return _not_found("period.lock")
    now = str(time.time())
    # Condition sur locked_at : deux clics simultanés ne réécrivent pas la date.
    conn.execute(
        """UPDATE academic_periods SET admin_state='LOCKED', locked_at=?, locked_by=?, updated_at=?
           WHERE id=? AND tenant_id=? AND locked_at IS NULL""",
        (now, g.ctx["user_id"], now, period_id, tenant_id))
    # Une réouverture en cours se referme avec le verrou.
    conn.execute(
        """UPDATE period_reopenings SET relocked_at=?, relocked_by=?
           WHERE tenant_id=? AND period_id=? AND relocked_at IS NULL""",
        (now, g.ctx["user_id"], tenant_id, period_id))
    conn.commit()
    relu = dict(conn.execute("SELECT * FROM academic_periods WHERE id=?", (period_id,)).fetchone())
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "period.locked", "academic_period", period_id, "success",
          after={"label": row["label"]})
    relu["state"] = school.period_state(relu)
    return jsonify(relu)


@bp.post("/api/periods/<period_id>/reopen")
@require_auth
def reopen_period(period_id):
    """Réouverture EXCEPTIONNELLE d'une période verrouillée.

    Exige une raison écrite, et l'enregistre avec son auteur et son horodatage.
    Une réouverture sans motif n'est pas une réouverture : c'est un contournement
    du verrou, et le §6 l'interdit explicitement.

    La période retourne en READY ; la Direction la referme ensuite par /lock,
    ce qui clôt aussi la ligne de réouverture.
    """
    if g.ctx["role"] != "directeur":
        return _denied("period.reopen")
    data = json_object(request.get_json(force=True))
    raison = required_text(data.get("reason"), "reason", 400)
    if len(raison) < 10:
        raise ValidationError("Indiquez une raison explicite (10 caractères minimum) : "
                              "elle est conservée au journal d'audit.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                       (period_id, tenant_id)).fetchone()
    if not row:
        conn.close()
        return _not_found("period.reopen")
    if not row["locked_at"]:
        conn.close()
        return jsonify({"error": "Cette période n'est pas verrouillée."}), 409
    now = str(time.time())
    conn.execute(
        """INSERT INTO period_reopenings (id, tenant_id, period_id, reason, reopened_by, reopened_at)
           VALUES (?,?,?,?,?,?)""",
        (new_id(), tenant_id, period_id, raison, g.ctx["user_id"], now))
    conn.execute(
        """UPDATE academic_periods SET admin_state='READY', locked_at=NULL, locked_by=NULL, updated_at=?
           WHERE id=? AND tenant_id=?""",
        (now, period_id, tenant_id))
    conn.commit()
    relu = dict(conn.execute("SELECT * FROM academic_periods WHERE id=?", (period_id,)).fetchone())
    conn.close()
    # Journalisé comme une action sensible : qui, quand, et POURQUOI.
    audit(tenant_id, g.ctx["user_id"], "period.reopened", "academic_period", period_id, "success",
          before={"locked_at": row["locked_at"]}, after={"reason": raison})
    relu["state"] = school.period_state(relu)
    return jsonify(relu)


@bp.get("/api/periods/<period_id>/reopenings")
@require_auth
def list_reopenings(period_id):
    """Historique des réouvertures — consultable, jamais effaçable par l'API."""
    if g.ctx["role"] != "directeur":
        return _denied("period.reopenings.read")
    conn = db.get_connection()
    # L'existence de la période est vérifiée AVANT de lister : sans cela, la
    # route répondait « 200 [] » à une direction d'un autre établissement, ce
    # qui affirme « cette période existe et n'a jamais été rouverte ». Toutes
    # les autres routes répondent 404 dans ce cas — la passe d'isolation du
    # release gate l'a relevé.
    if not conn.execute("SELECT 1 FROM academic_periods WHERE id=? AND tenant_id=?",
                        (period_id, g.ctx["tenant_id"])).fetchone():
        conn.close()
        return _not_found("period.reopenings.read")
    rows = [dict(r) for r in conn.execute(
        """SELECT r.*, u.name AS reopened_by_name FROM period_reopenings r
           LEFT JOIN users u ON u.id = r.reopened_by
           WHERE r.tenant_id=? AND r.period_id=? ORDER BY r.reopened_at DESC""",
        (g.ctx["tenant_id"], period_id))]
    conn.close()
    return jsonify(rows)


@bp.delete("/api/periods/<period_id>")
@require_auth
def delete_period(period_id):
    if g.ctx["role"] != "directeur":
        return _denied("period.delete")
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?", (period_id, g.ctx["tenant_id"])).fetchone()
    if not row:
        conn.close()
        return _not_found("period.delete")
    # Borné à l'année de la période : sans ce filtre, une "Période 1" vide de
    # l'année en cours restait indéboulonnable parce qu'une "Période 1" d'une
    # année précédente portait des notes.
    if conn.execute("SELECT 1 FROM grades WHERE tenant_id=? AND academic_year_id=? AND period=? LIMIT 1",
                    (g.ctx["tenant_id"], row["academic_year_id"], row["label"])).fetchone():
        conn.close()
        return jsonify({"error": "Des notes existent pour cette période — elle ne peut pas être supprimée."}), 409
    conn.execute("DELETE FROM academic_periods WHERE id=?", (period_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


def _filtre_audience(data):
    """Filtre d'audience envoyé par la Direction. Ce sont des CRITÈRES, jamais
    une liste de destinataires : le serveur recalcule qui ils désignent."""
    f = {}
    for cle in ("class_ids", "levels", "student_ids"):
        v = data.get(cle)
        if v:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValidationError(f"{cle} doit être une liste de chaînes.")
            f[cle] = v[:2000]
    if data.get("division"):
        f["division"] = _valider_division(data["division"])
    return f


@bp.post("/api/periods/<period_id>/publication-preview")
@require_auth
def publication_preview(period_id):
    """Aperçu de l'audience AVANT publication : inclus, exclus, total.

    Calculé par la même fonction que la publication elle-même
    (`school.compute_publication_audience`). L'aperçu ne peut donc pas montrer
    autre chose que ce qui sera réellement publié — c'est la raison d'être de
    cette route plutôt qu'un comptage côté navigateur.
    """
    if g.ctx["role"] != "directeur":
        return _denied("period.publish.preview")
    data = json_object(request.get_json(silent=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                       (period_id, tenant_id)).fetchone()
    if not row:
        conn.close()
        return _not_found("period.publish.preview")
    audience = school.compute_publication_audience(conn, tenant_id, dict(row), _filtre_audience(data))
    conn.close()
    # Les listes complètes servent à l'écran de confirmation ; on les borne pour
    # ne pas renvoyer 10 000 lignes à un navigateur qui en affiche vingt.
    return jsonify({
        "period": {"id": row["id"], "label": row["label"], "division": row["division"]},
        "included_count": audience["included_count"],
        "excluded_count": audience["excluded_count"],
        "total": audience["total"],
        "policy": audience["policy"],
        "included_sample": audience["included"][:50],
        "excluded_sample": audience["excluded"][:50],
    })


@bp.post("/api/periods/<period_id>/publish")
@require_auth
def publish_period(period_id):
    """Proclamation d'une période.

    Trois choses se passent ici, dans cet ordre, et aucune ne fait confiance au
    navigateur :

    1. l'audience est RECALCULÉE côté serveur à partir des critères envoyés ;
    2. elle est enregistrée telle quelle (`publication_students`) — c'est cette
       table, et non le libellé de la période, que lit ensuite le portail parent ;
    3. seuls les parents des élèves réellement inclus sont notifiés.

    Réversible : `unpublish` retire la proclamation sans effacer les résultats.
    """
    if g.ctx["role"] != "directeur":
        return _denied("period.publish")
    data = json_object(request.get_json(silent=True))
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    row = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                       (period_id, tenant_id)).fetchone()
    if not row:
        conn.close()
        return _not_found("period.publish")
    unpublish = bool(data.get("unpublish"))
    now = str(time.time())

    if unpublish:
        conn.execute("UPDATE academic_periods SET published_at=NULL, published_by=NULL, updated_at=? WHERE id=? AND tenant_id=?",
                     (now, period_id, tenant_id))
        conn.execute("""UPDATE period_publications SET unpublished_at=?, unpublished_by=?
                        WHERE tenant_id=? AND period_id=? AND unpublished_at IS NULL""",
                     (now, g.ctx["user_id"], tenant_id, period_id))
        conn.commit()
        conn.close()
        audit(tenant_id, g.ctx["user_id"], "results.period_unpublished", "academic_period", period_id, "success")
        return jsonify({"ok": True, "published": False, "students": 0})

    if school.period_state(dict(row)) == "DRAFT":
        conn.close()
        return jsonify({"error": "Cette période est encore en brouillon : terminez sa configuration avant de proclamer."}), 409

    audience = school.compute_publication_audience(conn, tenant_id, dict(row), _filtre_audience(data))
    inclus_ids = [e["id"] for e in audience["included"]]

    # Prise atomique : deux proclamations simultanées de la même période ne
    # doivent pas créer deux audiences ni notifier les parents deux fois.
    prise = conn.execute(
        "UPDATE academic_periods SET published_at=?, published_by=?, updated_at=? WHERE id=? AND tenant_id=? AND published_at IS NULL",
        (now, g.ctx["user_id"], now, period_id, tenant_id))
    if not (prise.rowcount or 0):
        conn.rollback()
        conn.close()
        return jsonify({"error": "Cette période est déjà proclamée. Retirez la proclamation avant d'en émettre une nouvelle."}), 409

    pub_id = new_id()
    conn.execute(
        """INSERT INTO period_publications (id, tenant_id, period_id, audience_filter,
                                            included_count, excluded_count, published_by, published_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (pub_id, tenant_id, period_id, json.dumps(_filtre_audience(data)),
         audience["included_count"], audience["excluded_count"], g.ctx["user_id"], now))
    for sid in inclus_ids:
        conn.execute("INSERT INTO publication_students (publication_id, tenant_id, student_id) VALUES (?,?,?)",
                     (pub_id, tenant_id, sid))
    conn.commit()

    # Notification bornée à l'audience réelle, et aux élèves qui ont
    # effectivement un résultat dans cette période : prévenir le parent d'un
    # élève sans note serait une fausse annonce.
    avec_resultats = {r["student_id"] for r in conn.execute(
        "SELECT DISTINCT student_id FROM grades WHERE tenant_id=? AND period_id=? AND is_current=1",
        (tenant_id, period_id))}
    avec_resultats |= {r["student_id"] for r in conn.execute(
        "SELECT DISTINCT student_id FROM appreciations WHERE tenant_id=? AND period_id=?",
        (tenant_id, period_id))}
    a_notifier = [s for s in inclus_ids if s in avec_resultats]
    event = events_module.emit(conn, tenant_id, "results.period.published", "academic_period", period_id,
                               g.ctx["user_id"],
                               payload={"label": row["label"], "division": row["division"],
                                        "included": audience["included_count"],
                                        "excluded": audience["excluded_count"],
                                        "notified": len(a_notifier)})
    notif_module.on_period_published(conn, tenant_id, dict(row), a_notifier, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "results.period_published", "academic_period", period_id, "success",
          after={"included": audience["included_count"], "excluded": audience["excluded_count"]})
    return jsonify({"ok": True, "published": True, "publication_id": pub_id,
                    "included": audience["included_count"], "excluded": audience["excluded_count"],
                    "students": len(a_notifier)})


# ===========================================================================
# APPRÉCIATIONS (maternelle)
# ===========================================================================

@bp.get("/api/appreciations/domains")
@require_auth
def domains():
    return jsonify({"domains": MATERNELLE_DOMAINS, "levels": LEVELS})


@bp.post("/api/classes/<class_id>/appreciations")
@require_auth
def record_appreciations(class_id):
    if g.ctx["role"] not in ("directeur", "professeur"):
        return _denied("appreciations.record")
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls:
        conn.close()
        return _denied("appreciations.record", "Vous n'êtes pas rattaché(e) à cette classe.")
    data = json_object(request.get_json(force=True))
    period = required_text(data.get("period"), "period", 40)
    domain = required_text(data.get("domain"), "domain", 60)
    entries = data.get("entries") or []
    if not entries:
        conn.close()
        return jsonify({"error": "Aucune appréciation fournie."}), 400
    tenant_id = g.ctx["tenant_id"]
    # Même règle que pour les notes : rattachement par clé, et refus si la
    # période est verrouillée.
    periode = school.resolve_period(conn, tenant_id, cls["academic_year_id"], period, cls["cycle"])
    ouverte, motif = school.period_accepts_results(periode)
    if not ouverte:
        conn.close()
        return _denied("appreciations.record", motif)
    period_id = periode["id"] if periode else None
    ids = {r["id"] for r in conn.execute("SELECT id FROM students WHERE tenant_id=? AND class_id=?", (tenant_id, class_id))}
    now = str(time.time())
    saved = 0
    for e in entries:
        if e.get("student_id") not in ids:
            conn.close()
            return jsonify({"error": "Un élève fourni n'appartient pas à cette classe."}), 400
        if e.get("level") in (None, ""):
            continue
        try:
            level = int(e["level"])
        except (TypeError, ValueError):
            raise ValidationError("level doit être un entier de 1 à 4.")
        if level not in LEVELS:
            raise ValidationError("level doit être compris entre 1 et 4.")
        # Le remplacement est borné à l'ANNÉE en cours. Sans ce filtre, saisir
        # l'appréciation "Période 1 / Langage" de 2026-2027 effaçait celle de
        # 2025-2026 : l'historique de l'élève disparaissait silencieusement.
        conn.execute("DELETE FROM appreciations WHERE tenant_id=? AND student_id=? AND academic_year_id=? AND period=? AND domain=?",
                     (tenant_id, e["student_id"], cls["academic_year_id"], period, domain))
        conn.execute("INSERT INTO appreciations (id, tenant_id, student_id, class_id, academic_year_id, period_id, period, domain, level, comment, recorded_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (new_id(), tenant_id, e["student_id"], class_id, cls["academic_year_id"], period_id, period, domain, level, (e.get("comment") or "").strip()[:300] or None, g.ctx["user_id"], now))
        saved += 1
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "appreciations.recorded", "class", class_id, "success", after={"period": period, "domain": domain, "count": saved})
    return jsonify({"ok": True, "saved": saved})


@bp.get("/api/classes/<class_id>/appreciations")
@require_auth
def list_appreciations(class_id):
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls or g.ctx["role"] == "parent":
        conn.close()
        return _not_found("appreciations.list")
    rows = conn.execute("SELECT a.*, s.first_name, s.last_name FROM appreciations a JOIN students s ON s.id=a.student_id WHERE a.tenant_id=? AND a.class_id=? ORDER BY a.period, a.domain, s.last_name", (g.ctx["tenant_id"], class_id)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ===========================================================================
# CONDUITE (conseil de classe) & DÉCISIONS DE FIN D'ANNÉE
# ===========================================================================

def _can_council(conn, student):
    if g.ctx["role"] == "directeur":
        return True
    return g.ctx["role"] == "professeur" and student["class_id"] and school.is_titulaire_of(conn, g.ctx, student["class_id"])


@bp.put("/api/students/<student_id>/conduct")
@require_auth
def set_conduct(student_id):
    data = json_object(request.get_json(force=True))
    period = required_text(data.get("period"), "period", 40)
    conn = db.get_connection()
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student or not _can_council(conn, student):
        conn.close()
        return _denied("conduct.set", "Seuls la Direction et le titulaire (conseil de classe) fixent la cote de conduite.")
    if data.get("clear"):
        conn.execute("DELETE FROM conduct_overrides WHERE tenant_id=? AND student_id=? AND period=?", (g.ctx["tenant_id"], student_id, period))
    else:
        label = required_text(data.get("label"), "label", 40)
        conn.execute("INSERT INTO conduct_overrides (id, tenant_id, student_id, period, label, note, set_by, created_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id, student_id, period) DO UPDATE SET label=excluded.label, note=excluded.note, set_by=excluded.set_by, created_at=excluded.created_at",
                     (new_id(), g.ctx["tenant_id"], student_id, period, label, (data.get("note") or "").strip()[:300] or None, g.ctx["user_id"], str(time.time())))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "conduct.set", "student", student_id, "success", after={"period": period, "label": data.get("label")})
    return jsonify({"ok": True})


# ===========================================================================
# DÉLIBÉRATIONS
# ===========================================================================

def _delib_accessible(conn, ctx, deliberation):
    """Peut-on voir cette délibération ? Et à quel titre ?

    Retourne (autorise, peut_deposer_avis, peut_decider). Trois réponses
    distinctes parce que les rôles ne font pas la même chose :

      - la Direction pilote et DÉCIDE ;
      - le titulaire et le professeur affecté donnent un AVIS sur leur classe ;
      - le DD dépose des éléments disciplinaires, sans décider ;
      - le parent n'entre pas. La délibération est une discussion interne ;
        ce qui en sort et le concerne, c'est la décision, par le bulletin.
    """
    role = ctx["role"]
    if role == "parent":
        return (False, False, False)
    if role == "directeur":
        return (True, True, True)
    # Professeur, titulaire, DD : uniquement les classes de leur périmètre.
    autorisees = school.visible_class_ids(conn, ctx)
    if autorisees is not None and deliberation["class_id"] not in autorisees:
        return (False, False, False)
    # Le DD contribue (observations, éléments disciplinaires) mais ne se
    # prononce pas sur le passage : ce n'est pas son rôle institutionnel.
    return (True, role == "professeur", False)


@bp.get("/api/deliberations")
@require_auth
def list_deliberations():
    """Les séances visibles, par année. Le périmètre s'applique ici aussi :
    un professeur ne voit pas les délibérations des classes d'un collègue."""
    if g.ctx["role"] == "parent":
        return _denied("deliberations.read")
    conn = db.get_connection()
    try:
        tenant_id = g.ctx["tenant_id"]
        annee = request.args.get("academic_year_id")
        where, params = ["d.tenant_id=?"], [tenant_id]
        if annee:
            where.append("d.academic_year_id=?"); params.append(annee)
        autorisees = school.visible_class_ids(conn, g.ctx)
        if autorisees is not None:
            if not autorisees:
                return jsonify([])
            where.append(f"d.class_id IN ({','.join('?' for _ in autorisees)})")
            params.extend(autorisees)
        rows = conn.execute(
            f"""SELECT d.*, c.name AS class_name, a.label AS year_label,
                       p.label AS period_label,
                       (SELECT COUNT(*) FROM students s
                         WHERE s.class_id=d.class_id AND s.status='active') AS student_count,
                       (SELECT COUNT(*) FROM deliberation_entries e
                         WHERE e.deliberation_id=d.id AND e.kind='DECISION'
                           AND e.superseded_at IS NULL) AS decided_count
                FROM deliberations d
                JOIN classes c ON c.id = d.class_id
                JOIN academic_years a ON a.id = d.academic_year_id
                LEFT JOIN academic_periods p ON p.id = d.period_id
                WHERE {' AND '.join(where)}
                ORDER BY a.label DESC, p.sort, c.name""", tuple(params)).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@bp.post("/api/deliberations")
@require_auth
def create_deliberation():
    """Ouvre une séance. La Direction seule — c'est un acte d'organisation.

    Rien n'est calculé ni décidé à la création : on ouvre un cadre. Les
    éléments seront lus au moment où le conseil les regardera, donc toujours à
    jour, plutôt que figés dans une photographie prise trop tôt.
    """
    if g.ctx["role"] != "directeur":
        return _denied("deliberations.create")
    data = json_object(request.get_json(force=True))
    class_id = required_text(data.get("class_id"), "class_id")
    period_id = (data.get("period_id") or "").strip() or None
    kind = data.get("kind") or delib.PERIOD
    if kind not in (delib.PERIOD, delib.ANNUAL):
        raise ValidationError("kind doit être PERIOD ou ANNUAL.")
    if kind == delib.PERIOD and not period_id:
        raise ValidationError("Une délibération de période doit désigner une période.")
    if kind == delib.ANNUAL:
        period_id = None

    conn = db.get_connection()
    try:
        tenant_id = g.ctx["tenant_id"]
        classe = conn.execute("SELECT * FROM classes WHERE id=? AND tenant_id=?",
                              (class_id, tenant_id)).fetchone()
        if not classe:
            return _not_found("deliberations.create", "Classe introuvable.")
        if period_id:
            per = conn.execute(
                "SELECT id FROM academic_periods WHERE id=? AND tenant_id=? AND academic_year_id=?",
                (period_id, tenant_id, classe["academic_year_id"])).fetchone()
            if not per:
                return _not_found("deliberations.create", "Période introuvable pour cette année.")

        # `period_id IS ?` n'est pas du SQL valide en PostgreSQL : `IS` attend
        # NULL, pas un paramètre. On construit donc la clause — même précaution
        # que pour le filtre d'année des exports, et pour la même raison : ce
        # genre d'écart ne se voit qu'en production.
        clause = "period_id IS NULL" if period_id is None else "period_id=?"
        params = [tenant_id, classe["academic_year_id"], class_id, kind]
        if period_id is not None:
            params.append(period_id)
        existante = conn.execute(
            f"""SELECT id FROM deliberations WHERE tenant_id=? AND academic_year_id=?
                AND class_id=? AND kind=? AND {clause}""", tuple(params)).fetchone()
        if existante:
            return jsonify({"id": existante["id"], "already_exists": True}), 200

        did = new_id()
        conn.execute(
            """INSERT INTO deliberations (id, tenant_id, academic_year_id, period_id, class_id,
                                          kind, status, opened_by, opened_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (did, tenant_id, classe["academic_year_id"], period_id, class_id, kind,
             delib.IN_PROGRESS, g.ctx["user_id"], str(time.time()), str(time.time())))
        conn.commit()
        audit(tenant_id, g.ctx["user_id"], "deliberation.created", "deliberation", did, "success",
              after={"class_id": class_id, "kind": kind, "period_id": period_id})
        return jsonify({"id": did, "status": delib.IN_PROGRESS}), 201
    finally:
        conn.close()


@bp.get("/api/deliberations/<delib_id>")
@require_auth
def get_deliberation(delib_id):
    """Le tableau du conseil : une ligne par élève, tous les éléments réunis.

    Chaque chiffre vient d'une source existante — `school.bulletin()` pour les
    résultats et la conduite, `attendance_summary()` pour la présence,
    `incidents` pour la discipline. Rien n'est recalculé ici, rien n'est
    inventé : si une donnée n'existe pas, la case reste vide.
    """
    conn = db.get_connection()
    try:
        tenant_id = g.ctx["tenant_id"]
        d = conn.execute("SELECT * FROM deliberations WHERE id=? AND tenant_id=?",
                         (delib_id, tenant_id)).fetchone()
        if not d:
            return _not_found("deliberations.read")
        autorise, peut_avis, peut_decider = _delib_accessible(conn, g.ctx, d)
        if not autorise:
            return _denied("deliberations.read")

        classe = conn.execute("SELECT * FROM classes WHERE id=?", (d["class_id"],)).fetchone()
        periode = conn.execute("SELECT label FROM academic_periods WHERE id=?",
                               (d["period_id"],)).fetchone() if d["period_id"] else None
        libelle_periode = periode["label"] if periode else None
        reglages = school.get_settings(conn, tenant_id)

        eleves = conn.execute(
            """SELECT * FROM students WHERE tenant_id=? AND class_id=? AND status='active'
               ORDER BY last_name, first_name""", (tenant_id, d["class_id"])).fetchall()

        # Tous les dépôts de la séance, lus d'un coup : une requête par élève
        # ferait N+1 appels sur une classe de 60.
        tous = delib.entrees(conn, tenant_id, delib_id)
        par_eleve = {}
        for e in tous:
            par_eleve.setdefault(e["student_id"], []).append(e)

        lignes = []
        for row in eleves:
            eleve = dict(row)
            eleve["class_name"] = classe["name"]
            b = school.bulletin(conn, tenant_id, eleve, period=libelle_periode)
            presence = school.attendance_summary(conn, tenant_id, eleve["id"])
            incidents = conn.execute(
                "SELECT COUNT(*) n FROM incidents WHERE tenant_id=? AND student_id=?",
                (tenant_id, eleve["id"])).fetchone()["n"]
            discipline = {"incidents": incidents, "remaining": b["conduct"]["remaining"],
                          "capital": b["conduct"]["capital"]}
            depots = par_eleve.get(eleve["id"], [])
            decision = next((x for x in depots if x["kind"] == delib.DECISION), None)
            lignes.append({
                "student": {"id": eleve["id"], "code": eleve["code"],
                            "first_name": eleve["first_name"], "last_name": eleve["last_name"]},
                "results": {"average_20": b["general_average_20"], "percent": b["percent"],
                            "rank": b["rank"], "class_size": b["class_size"]},
                "attendance": presence,
                "conduct": b["conduct"],
                "signals": delib.indicateurs(b, presence, discipline, reglages),
                "avis_count": sum(1 for x in depots if x["kind"] == delib.AVIS),
                "observation_count": sum(1 for x in depots if x["kind"] == delib.OBSERVATION),
                # La décision OFFICIELLE, distincte des avis. `None` veut dire
                # que le conseil ne s'est pas prononcé — jamais que Klassio
                # aurait une préférence.
                "decision": {"value": decision["value"], "comment": decision["comment"],
                             "author": decision["author_name"], "at": decision["created_at"]}
                            if decision else None,
            })

        return jsonify({
            "id": d["id"], "kind": d["kind"], "status": d["status"],
            "class": {"id": classe["id"], "name": classe["name"]},
            "period": libelle_periode, "academic_year_id": d["academic_year_id"],
            "count": len(lignes),
            "can_give_opinion": peut_avis, "can_decide": peut_decider,
            "decisions_available": delib.DECISIONS,
            "rows": lignes,
        })
    finally:
        conn.close()


@bp.post("/api/deliberations/<delib_id>/entries")
@require_auth
def add_deliberation_entry(delib_id):
    """Déposer une observation, un avis, ou LA décision.

    LE POINT CENTRAL DE TOUT CE MODULE : un avis n'est pas une décision, et
    aucun mécanisme ne transforme l'un en l'autre. Un titulaire peut écrire
    « Avis : passage » dix fois ; tant que la Direction n'a pas déposé une
    entrée de type DECISION, l'élève n'a pas de décision. C'est vérifié ici, au
    serveur, et pas seulement en masquant un bouton.
    """
    data = json_object(request.get_json(force=True))
    kind = data.get("kind")
    if kind not in (delib.OBSERVATION, delib.AVIS, delib.DECISION):
        raise ValidationError("kind doit être OBSERVATION, AVIS ou DECISION.")
    student_id = required_text(data.get("student_id"), "student_id")
    value = (data.get("value") or "").strip() or None
    comment = (data.get("comment") or "").strip()[:2000] or None

    conn = db.get_connection()
    try:
        tenant_id = g.ctx["tenant_id"]
        d = conn.execute("SELECT * FROM deliberations WHERE id=? AND tenant_id=?",
                         (delib_id, tenant_id)).fetchone()
        if not d:
            return _not_found("deliberations.entry")
        autorise, peut_avis, peut_decider = _delib_accessible(conn, g.ctx, d)
        if not autorise:
            return _denied("deliberations.entry")
        if d["status"] == delib.CLOSED:
            return jsonify({"error": "Cette délibération est close. Rouvrez-la pour la modifier."}), 409

        if kind == delib.DECISION and not peut_decider:
            return _denied("deliberations.decide",
                           "La décision officielle appartient à la Direction. "
                           "Vous pouvez déposer un avis.")
        if kind == delib.AVIS and not peut_avis:
            return _denied("deliberations.opinion",
                           "Votre rôle ne dépose pas d'avis sur le passage. "
                           "Vous pouvez ajouter une observation.")

        # L'élève doit appartenir à la classe de CETTE délibération : sans ce
        # contrôle, un identifiant d'élève d'une autre classe — ou d'une autre
        # école — s'y glisserait.
        eleve = conn.execute(
            "SELECT * FROM students WHERE id=? AND tenant_id=? AND class_id=?",
            (student_id, tenant_id, d["class_id"])).fetchone()
        if not eleve:
            return _not_found("deliberations.entry",
                              "Cet élève n'appartient pas à la classe délibérée.")

        if kind in (delib.AVIS, delib.DECISION):
            if value not in delib.DECISIONS:
                raise ValidationError("value doit être l'une des décisions prévues.")
            if value in delib.DECISIONS_EXIGEANT_MOTIF and not comment:
                raise ValidationError(
                    f"« {delib.DECISIONS[value]} » demande un motif : sans lui, la trace "
                    "ne dira rien à qui la relira.")
        elif not comment:
            raise ValidationError("Une observation sans texte n'apporte rien.")

        entry_id = delib.deposer(conn, tenant_id, delib_id, student_id, kind, value,
                                 comment, g.ctx["user_id"], g.ctx["role"])

        # La décision officielle met à jour `bulletin_decisions`, que le
        # bulletin lit déjà. L'historique, lui, reste dans les entrées : on ne
        # crée pas une seconde vérité, on projette la plus récente.
        if kind == delib.DECISION:
            correspondance = delib.VERS_BULLETIN.get(value)
            if correspondance:
                conn.execute(
                    """INSERT INTO bulletin_decisions (id, tenant_id, student_id, academic_year_id,
                                                       decision, mention, note, set_by, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(tenant_id, student_id, academic_year_id) DO UPDATE SET
                         decision=excluded.decision, note=excluded.note,
                         set_by=excluded.set_by, created_at=excluded.created_at""",
                    (new_id(), tenant_id, student_id, d["academic_year_id"], correspondance,
                     None, comment, g.ctx["user_id"], str(time.time())))
                conn.commit()
            audit(tenant_id, g.ctx["user_id"], "deliberation.decision", "student", student_id,
                  "success", after={"decision": value, "deliberation_id": delib_id})
        else:
            audit(tenant_id, g.ctx["user_id"], f"deliberation.{kind.lower()}", "student",
                  student_id, "success", after={"deliberation_id": delib_id, "value": value})

        return jsonify({"id": entry_id, "kind": kind}), 201
    finally:
        conn.close()


@bp.get("/api/deliberations/<delib_id>/students/<student_id>")
@require_auth
def deliberation_student(delib_id, student_id):
    """Le dossier individuel : tout au même endroit, sans naviguer ailleurs.

    Résultats, présence, discipline, appréciations, et l'HISTORIQUE COMPLET des
    dépôts — y compris ceux qui ont été remplacés. Un conseil doit pouvoir voir
    qu'un avis a changé, et quand.
    """
    conn = db.get_connection()
    try:
        tenant_id = g.ctx["tenant_id"]
        d = conn.execute("SELECT * FROM deliberations WHERE id=? AND tenant_id=?",
                         (delib_id, tenant_id)).fetchone()
        if not d:
            return _not_found("deliberations.student")
        autorise, peut_avis, peut_decider = _delib_accessible(conn, g.ctx, d)
        if not autorise:
            return _denied("deliberations.student")

        eleve = conn.execute(
            "SELECT * FROM students WHERE id=? AND tenant_id=? AND class_id=?",
            (student_id, tenant_id, d["class_id"])).fetchone()
        if not eleve:
            return _not_found("deliberations.student")

        classe = conn.execute("SELECT * FROM classes WHERE id=?", (d["class_id"],)).fetchone()
        periode = conn.execute("SELECT label FROM academic_periods WHERE id=?",
                               (d["period_id"],)).fetchone() if d["period_id"] else None
        e = dict(eleve); e["class_name"] = classe["name"]
        b = school.bulletin(conn, tenant_id, e, period=periode["label"] if periode else None)
        presence = school.attendance_summary(conn, tenant_id, student_id)
        incidents = [dict(r) for r in conn.execute(
            """SELECT occurred_at, title, category, severity, points, action_taken
               FROM incidents WHERE tenant_id=? AND student_id=?
               ORDER BY occurred_at DESC LIMIT 50""", (tenant_id, student_id))]
        apprec = [dict(r) for r in conn.execute(
            """SELECT period, domain, level, comment, created_at FROM appreciations
               WHERE tenant_id=? AND student_id=? ORDER BY created_at DESC LIMIT 50""",
            (tenant_id, student_id))]

        return jsonify({
            "student": {"id": e["id"], "code": e["code"], "first_name": e["first_name"],
                        "last_name": e["last_name"], "class_name": classe["name"]},
            "bulletin": b,
            "attendance": presence,
            "incidents": incidents,
            "appreciations": apprec,
            # L'historique COMPLET, remplacés compris : c'est ce qui permet de
            # dire plus tard qui avait proposé quoi.
            "entries": delib.entrees(conn, tenant_id, delib_id, student_id=student_id,
                                     courantes=False),
            "can_give_opinion": peut_avis, "can_decide": peut_decider,
            "decisions_available": delib.DECISIONS,
        })
    finally:
        conn.close()


@bp.put("/api/students/<student_id>/decision")
@require_auth
def set_decision(student_id):
    if g.ctx["role"] != "directeur":
        return _denied("decision.set", "La décision de fin d'année est réservée à la Direction.")
    data = json_object(request.get_json(force=True))
    decision = data.get("decision")
    if decision not in ("admis", "ajourne", "doublant"):
        raise ValidationError("decision doit être admis, ajourne ou doublant.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    student = school.resolve_student_access(conn, g.ctx, student_id)
    if not student:
        conn.close()
        return _not_found("decision.set")
    d = {"decision": decision, "mention": (data.get("mention") or "").strip()[:40] or None, "note": (data.get("note") or "").strip()[:300] or None}
    conn.execute("INSERT INTO bulletin_decisions (id, tenant_id, student_id, academic_year_id, decision, mention, note, set_by, created_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id, student_id, academic_year_id) DO UPDATE SET decision=excluded.decision, mention=excluded.mention, note=excluded.note, set_by=excluded.set_by, created_at=excluded.created_at",
                 (new_id(), tenant_id, student_id, student["academic_year_id"], decision, d["mention"], d["note"], g.ctx["user_id"], str(time.time())))
    conn.commit()
    if data.get("notify", True):
        event = events_module.emit(conn, tenant_id, "results.decision.set", "student", student_id, g.ctx["user_id"], payload=d)
        notif_module.on_decision_set(conn, tenant_id, student, d, event_id=event["id"])
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "results.decision_set", "student", student_id, "success", after=d)
    return jsonify({"ok": True})


@bp.get("/api/classes/<class_id>/results")
@require_auth
def class_results(class_id):
    """Vue du conseil de classe : par élève, moyenne de la période, rang,
    conduite (calculée ou fixée), décision de fin d'année."""
    conn = db.get_connection()
    cls = school.can_access_class(conn, g.ctx, class_id)
    if not cls or g.ctx["role"] == "parent":
        conn.close()
        return _not_found("results.class")
    tenant_id = g.ctx["tenant_id"]
    period = request.args.get("period")
    students = conn.execute("SELECT * FROM students WHERE tenant_id=? AND class_id=? AND status='active' ORDER BY last_name, first_name", (tenant_id, class_id)).fetchall()
    settings = school.get_settings(conn, tenant_id)
    rows = []
    periods = sorted({r["period"] for r in conn.execute("SELECT DISTINCT period FROM grades WHERE tenant_id=? AND class_id=?", (tenant_id, class_id))})
    if period is None and periods:
        period = periods[-1]
    for s in students:
        b = school.bulletin(conn, tenant_id, dict(s) | {"class_name": cls["name"], "class_level": cls["level"], "class_cycle": cls["cycle"]}, period=period) if period else None
        bal = school.discipline_balance(conn, tenant_id, s["id"], settings)
        rows.append({"id": s["id"], "code": s["code"], "first_name": s["first_name"], "last_name": s["last_name"],
                     "average_20": b["general_average_20"] if b else None, "percent": b["percent"] if b else None, "rank": b["rank"] if b else None,
                     "conduct": b["conduct"] if b else {"label": bal["conduct"], "remaining": bal["remaining"], "capital": bal["capital"], "overridden": False},
                     "decision": b["decision"] if b else None, "subjects": b["subjects"] if b else []})
    can_council = g.ctx["role"] == "directeur" or school.is_titulaire_of(conn, g.ctx, class_id)
    conn.close()
    return jsonify({"class": {"id": cls["id"], "name": cls["name"], "cycle": cls["cycle"]}, "period": period, "periods": periods,
                    "pass_threshold": settings.get("pass_threshold"), "conduct_scale": school.conduct_scale(settings), "students": rows,
                    "can_council": can_council})


# ===========================================================================
# IMPORT DES RÉSULTATS OFFICIELS
#
# L'établissement calcule ses résultats avec ses propres outils. Klassio les
# reçoit, les rapproche de ses élèves, signale ce qui ne se rapproche pas, et
# n'écrit qu'après validation explicite de la Direction.
#
# L'IMPORT NE PUBLIE JAMAIS. La proclamation reste une décision distincte,
# prise plus tard, avec son audience — voir /api/periods/<id>/publish.
# ===========================================================================

IMPORT_RESULTATS_TTL = 60 * 60 * 6   # 6 h : le temps d'aller corriger un fichier


def _session_import(conn, tenant_id, import_id, user_id=None):
    sql = "SELECT * FROM result_imports WHERE id=? AND tenant_id=?"
    params = [import_id, tenant_id]
    if user_id:
        sql += " AND created_by=?"
        params.append(user_id)
    return conn.execute(sql, params).fetchone()


def _etat_import(session):
    """État courant d'une session d'import, expiration comprise.

    L'expiration est CALCULÉE, pas stockée : une session qui dort ne doit pas
    dépendre d'un travail de fond pour devenir invalide.
    """
    if session["status"] == "confirmed":
        return "COMPLETED"
    if session["status"] == "cancelled":
        return "CANCELLED"
    if time.time() - float(session["created_at"]) > IMPORT_RESULTATS_TTL:
        return "EXPIRED"
    return "READY_FOR_CONFIRMATION" if not session["rows_unmatched"] else "PREVIEW_READY"


def _resume_import(session, lignes=None):
    """Ce que la Direction doit voir avant de confirmer. Les compteurs sont
    ceux enregistrés au moment de l'analyse — jamais ceux du navigateur."""
    donnees = json.loads(session["records"])
    lignes = lignes if lignes is not None else donnees.get("rows", [])
    return {
        "import_id": session["id"],
        "state": _etat_import(session),
        "status": session["status"],
        "file_name": session["file_name"],
        "academic_year_id": session["academic_year_id"],
        "period_id": session["period_id"],
        "period_label": donnees.get("period_label"),
        "created_at": session["created_at"],
        "confirmed_at": session["confirmed_at"],
        "expires_at": float(session["created_at"]) + IMPORT_RESULTATS_TTL,
        "total_rows": session["rows_total"],
        "matched": session["rows_matched"],
        "warnings": session["rows_ambiguous"],
        "errors": session["rows_unmatched"],
        "mapping": donnees.get("mapping", []),
        "students_in_file": donnees.get("students_in_file"),
        "students_expected": donnees.get("students_expected"),
        "students_without_result": donnees.get("students_without_result", []),
        "next_version": donnees.get("next_version"),
        "blocking": bool(session["rows_unmatched"]),
    }


@bp.post("/api/results/imports")
@require_auth
def analyser_import_resultats():
    """Étape 1 — analyse. N'écrit AUCUN résultat.

    Le fichier est lu, rapproché des élèves réels, et le tout est PERSISTÉ dans
    `result_imports`. C'est cette copie serveur qui sera écrite à la
    confirmation : ce que la Direction voit à l'écran est exactement ce qui
    entrera en base, et un rafraîchissement de page ne perd rien.
    """
    if g.ctx["role"] != "directeur":
        return _denied("results.import.analyze")
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier reçu."}), 400

    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    period_id = request.form.get("period_id") or (request.args.get("period_id") or "")
    periode = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                           (period_id, tenant_id)).fetchone()
    if not periode:
        conn.close()
        return _not_found("results.import.analyze",
                          "Période introuvable. Choisissez la période à laquelle ces résultats se rapportent.")
    periode = dict(periode)
    ouverte, motif = school.period_accepts_results(periode)
    if not ouverte:
        conn.close()
        return _denied("results.import.analyze", motif)

    fichier = request.files["file"]
    try:
        # Même lecteur que l'import des élèves : un .xlsx abîmé ou un CSV
        # renommé produit ici un message clair, pas une erreur interne.
        table = ingestion.parse_uploaded_table(fichier)
        analyse = results_import.analyser_fichier(table, fichier.filename or "resultats")
    except ValidationError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        conn.close()
        audit(tenant_id, g.ctx["user_id"], "results.import.analyzed", "result_import", None, "denied",
              after={"file": fichier.filename, "reason": str(e)})
        return jsonify({"error": str(e)}), 400

    rapport = results_import.rapprocher(conn, tenant_id, periode["academic_year_id"],
                                        analyse["rows"], periode)

    # Version proposée : celle qui suivra la plus haute déjà écrite pour cette
    # période. Calculée ici pour l'aperçu, RECALCULÉE à la confirmation.
    haut = conn.execute(
        "SELECT MAX(version) v FROM grades WHERE tenant_id=? AND period_id=?",
        (tenant_id, periode["id"])).fetchone()
    prochaine = (haut["v"] or 0) + 1

    import_id = new_id()
    donnees = {
        "rows": rapport["rows"],
        "mapping": analyse["mapping"],
        "period_label": periode["label"],
        "students_in_file": rapport["students_in_file"],
        "students_expected": rapport["students_expected"],
        "students_without_result": rapport["students_without_result"],
        "next_version": prochaine,
    }
    conn.execute(
        """INSERT INTO result_imports (id, tenant_id, academic_year_id, period_id, created_by, file_name,
                                       rows_total, rows_matched, rows_ambiguous, rows_unmatched,
                                       records, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'analyzed', ?)""",
        (import_id, tenant_id, periode["academic_year_id"], periode["id"], g.ctx["user_id"],
         (fichier.filename or "")[:200], rapport["total_rows"], rapport["matched"],
         rapport["warnings"], rapport["errors"], json.dumps(donnees), str(time.time())))
    conn.commit()
    session = _session_import(conn, tenant_id, import_id)
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "results.import.analyzed", "result_import", import_id, "success",
          after={"file": fichier.filename, "rows": rapport["total_rows"],
                 "matched": rapport["matched"], "errors": rapport["errors"]})
    resume = _resume_import(session)
    # Un échantillon pour l'écran, et TOUTES les lignes en anomalie : ce sont
    # celles que la Direction doit corriger, elles ne doivent jamais être tronquées.
    resume["rows_sample"] = rapport["rows"][:50]
    resume["problems"] = [l for l in rapport["rows"] if l["severity"] != results_import.SEVERITE_OK]
    return jsonify(resume), 201


@bp.get("/api/results/imports/<import_id>")
@require_auth
def etat_import_resultats(import_id):
    """Étape 1bis — reprise d'état.

    Si la Direction actualise la page, ferme l'onglet ou change d'appareil,
    l'interface retrouve ICI l'état réel de l'import. Rien n'est gardé en
    mémoire de navigateur.
    """
    if g.ctx["role"] != "directeur":
        return _denied("results.import.read")
    conn = db.get_connection()
    session = _session_import(conn, g.ctx["tenant_id"], import_id)
    if not session:
        conn.close()
        return _not_found("results.import.read")
    donnees = json.loads(session["records"])
    conn.close()
    resume = _resume_import(session)
    resume["rows_sample"] = donnees.get("rows", [])[:50]
    resume["problems"] = [l for l in donnees.get("rows", [])
                          if l["severity"] != results_import.SEVERITE_OK]
    return jsonify(resume)


@bp.get("/api/results/imports")
@require_auth
def lister_imports_resultats():
    if g.ctx["role"] != "directeur":
        return _denied("results.import.list")
    conn = db.get_connection()
    rows = conn.execute(
        """SELECT r.*, p.label AS period_label, u.name AS created_by_name
           FROM result_imports r
           LEFT JOIN academic_periods p ON p.id = r.period_id AND p.tenant_id = r.tenant_id
           LEFT JOIN users u ON u.id = r.created_by
           WHERE r.tenant_id=? ORDER BY r.created_at DESC LIMIT 50""",
        (g.ctx["tenant_id"],)).fetchall()
    conn.close()
    return jsonify([{k: v for k, v in dict(r).items() if k != "records"} for r in rows])


@bp.post("/api/results/imports/<import_id>/cancel")
@require_auth
def annuler_import_resultats(import_id):
    if g.ctx["role"] != "directeur":
        return _denied("results.import.cancel")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    curseur = conn.execute(
        "UPDATE result_imports SET status='cancelled' WHERE id=? AND tenant_id=? AND status='analyzed'",
        (import_id, tenant_id))
    conn.commit()
    existe = _session_import(conn, tenant_id, import_id)
    conn.close()
    if not existe:
        return _not_found("results.import.cancel")
    if not (curseur.rowcount or 0):
        return jsonify({"error": "Cet import n'est plus annulable."}), 409
    audit(tenant_id, g.ctx["user_id"], "results.import.cancelled", "result_import", import_id, "success")
    return jsonify({"ok": True, "state": "CANCELLED"})


@bp.post("/api/results/imports/<import_id>/confirm")
@require_auth
def confirmer_import_resultats(import_id):
    """Étape 2 — écriture des résultats officiels.

    Tout ce qui compte est RELU côté serveur depuis la session d'import :
    les lignes, les élèves rapprochés, le nombre d'erreurs. Un navigateur qui
    annoncerait « 60 rapprochés, 0 erreur » sur un fichier qui en compte 58 et 2
    ne change rien — ces chiffres ne sont pas lus.

    Versionnage : les résultats existants de cette période ne sont PAS
    supprimés. Ils passent en `is_current = 0` et la nouvelle version prend leur
    place. L'historique reste intégralement consultable.

    Atomicité : un seul commit à la fin. Si quoi que ce soit échoue en route,
    rien n'est écrit et l'import redevient confirmable.
    """
    if g.ctx["role"] != "directeur":
        return _denied("results.import.confirm")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    session = _session_import(conn, tenant_id, import_id)
    if not session:
        conn.close()
        audit(tenant_id, g.ctx["user_id"], "results.import.confirmed", "result_import", import_id, "denied")
        return _not_found("results.import.confirm")

    etat = _etat_import(session)
    if etat == "COMPLETED":
        conn.close()
        return jsonify({"error": "Cet import a déjà été confirmé. Relancez une analyse pour importer à nouveau."}), 409
    if etat == "CANCELLED":
        conn.close()
        return jsonify({"error": "Cet import a été annulé."}), 409
    if etat == "EXPIRED":
        conn.close()
        return jsonify({"error": "Cette analyse a expiré. Relancez l'analyse du fichier."}), 410

    if session["rows_unmatched"]:
        conn.close()
        return jsonify({
            "error": f"{session['rows_unmatched']} ligne(s) en erreur. Corrigez le fichier et relancez "
                     "l'analyse : Klassio n'importe jamais un résultat ambigu.",
            "errors": session["rows_unmatched"]}), 409

    periode = conn.execute("SELECT * FROM academic_periods WHERE id=? AND tenant_id=?",
                           (session["period_id"], tenant_id)).fetchone()
    if not periode:
        conn.close()
        return _not_found("results.import.confirm", "La période de cet import n'existe plus.")
    ouverte, motif = school.period_accepts_results(dict(periode))
    if not ouverte:
        conn.close()
        return _denied("results.import.confirm", motif)

    # Prise de la session AVANT d'écrire : deux confirmations simultanées ne
    # peuvent pas produire deux versions du même import.
    maintenant = str(time.time())
    prise = conn.execute(
        "UPDATE result_imports SET status='confirmed', confirmed_at=? WHERE id=? AND tenant_id=? AND status='analyzed'",
        (maintenant, import_id, tenant_id))
    if not (prise.rowcount or 0):
        conn.rollback()
        conn.close()
        return jsonify({"error": "Cet import est déjà en cours de confirmation."}), 409

    try:
        donnees = json.loads(session["records"])
        lignes = [l for l in donnees.get("rows", [])
                  if l.get("student_id") and l["severity"] != results_import.SEVERITE_ERREUR]
        if not lignes:
            raise ValueError("Aucune ligne exploitable à importer.")

        haut = conn.execute("SELECT MAX(version) v FROM grades WHERE tenant_id=? AND period_id=?",
                            (tenant_id, periode["id"])).fetchone()
        version = (haut["v"] or 0) + 1

        # Les résultats déjà en place pour cette période cèdent la place sans
        # disparaître : ils restent lisibles, datés, et rattachés à leur import.
        conn.execute(
            """UPDATE grades SET is_current=0, superseded_at=?, superseded_by=?
               WHERE tenant_id=? AND period_id=? AND is_current=1""",
            (maintenant, import_id, tenant_id, periode["id"]))

        ecrites = 0
        for l in lignes:
            conn.execute(
                """INSERT INTO grades (id, tenant_id, student_id, class_id, academic_year_id, period_id,
                                       subject, period, score, max_score, recorded_by, created_at,
                                       version, is_current, result_import_id, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?, 'import')""",
                (new_id(), tenant_id, l["student_id"], l.get("class_id"), periode["academic_year_id"],
                 periode["id"], l["subject"], periode["label"], l["score"], l["max_score"],
                 g.ctx["user_id"], maintenant, version, import_id))
            ecrites += 1
        conn.commit()
    except Exception:
        # Rien de partiel ne survit : la session redevient confirmable après
        # correction, et aucune version incomplète ne reste en base.
        conn.rollback()
        conn.execute(
            "UPDATE result_imports SET status='analyzed', confirmed_at=NULL WHERE id=? AND tenant_id=?",
            (import_id, tenant_id))
        conn.commit()
        conn.close()
        current_app.logger.exception("Import de résultats interrompu (%s)", import_id)
        return jsonify({"error": "L'import n'a pas pu être finalisé. Aucun résultat n'a été écrit — "
                                 "vous pouvez réessayer."}), 500

    conn.close()
    audit(tenant_id, g.ctx["user_id"], "results.import.confirmed", "result_import", import_id, "success",
          after={"results": ecrites, "version": version, "period": periode["label"]})
    return jsonify({
        "ok": True, "state": "COMPLETED", "import_id": import_id,
        "results_written": ecrites, "version": version,
        "period_label": periode["label"],
        # Dit explicitement : ces résultats EXISTENT, ils ne sont pas proclamés.
        "published": False,
        "next_step": "La proclamation reste une étape distincte : "
                     f"publiez la période « {periode['label']} » quand vous êtes prêt.",
    })


@bp.get("/api/results/history")
@require_auth
def historique_resultats():
    """Toutes les versions d'un résultat, la courante comme les précédentes."""
    if g.ctx["role"] not in ("directeur", "professeur", "discipline"):
        return _denied("results.history")
    student_id = request.args.get("student_id")
    period_id = request.args.get("period_id")
    conn = db.get_connection()
    if student_id and not school.resolve_student_access(conn, g.ctx, student_id):
        conn.close()
        return _not_found("results.history")
    where, params = ["g.tenant_id=?"], [g.ctx["tenant_id"]]
    if student_id:
        where.append("g.student_id=?"); params.append(student_id)
    if period_id:
        where.append("g.period_id=?"); params.append(period_id)
    rows = [dict(r) for r in conn.execute(
        f"""SELECT g.id, g.student_id, g.subject, g.period, g.score, g.max_score, g.version,
                   g.is_current, g.created_at, g.superseded_at, g.result_import_id, g.source,
                   u.name AS recorded_by_name
            FROM grades g LEFT JOIN users u ON u.id = g.recorded_by
            WHERE {' AND '.join(where)}
            ORDER BY g.subject, g.version DESC""", params)]
    conn.close()
    return jsonify(rows)
