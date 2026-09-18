"""KLASSIO backend — Notification Engine (MVP réel : in-app uniquement).

Architecture unique pour TOUS les domaines (docs/EVENEMENTS.md §17) :

    Événement → règle → destinataires AUTORISÉS → notification (in-app)

Il n'y a pas un système de notification par espace : présence, discipline,
notes, commandes et paiements passent tous par `send()`. Le contenu diffère
par destinataire (le titulaire ne reçoit pas le même texte que le parent), et
le regroupement évite le spam : une notification non lue de même titre et
même lien reçue dans la fenêtre glissante est INCRÉMENTÉE, pas dupliquée.

Canal temps réel : aucun WebSocket dans ce serveur Flask mono-processus —
l'interface interroge /api/notifications/summary toutes les 30 s (solution la
plus cohérente avec l'architecture actuelle, pas un remplacement).
"""
import time
from security import new_id

AGGREGATION_WINDOW_SECONDS = 900  # 15 minutes


def _create(conn, tenant_id, recipient_user_id, event_id, title, body, priority="NORMAL", link=None, kind=None):
    now = str(time.time())
    conn.execute(
        """INSERT INTO notifications
           (id, tenant_id, recipient_user_id, event_id, title, body, priority, count, amount_total, created_at, updated_at, link, kind)
           VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?)""",
        (new_id(), tenant_id, recipient_user_id, event_id, title, body, priority, None, now, now, link, kind),
    )


def send(conn, tenant_id, recipient_user_ids, title, body, link=None, kind=None, event_id=None, priority="NORMAL", dedupe=True):
    """Envoie une notification à chaque destinataire (déjà filtré par
    permission par l'appelant). Regroupe si une notification identique non
    lue existe dans la fenêtre glissante."""
    now = time.time()
    seen = set()
    for uid in recipient_user_ids:
        if not uid or uid in seen:
            continue
        seen.add(uid)
        if dedupe:
            row = conn.execute(
                """SELECT * FROM notifications WHERE tenant_id=? AND recipient_user_id=? AND title=? AND status='unread'
                   AND COALESCE(link,'') = COALESCE(?, '') AND CAST(updated_at AS REAL) > ? ORDER BY updated_at DESC LIMIT 1""",
                (tenant_id, uid, title, link, now - AGGREGATION_WINDOW_SECONDS),
            ).fetchone()
            if row:
                conn.execute("UPDATE notifications SET count = count + 1, body = ?, updated_at = ?, event_id = COALESCE(?, event_id) WHERE id = ?",
                             (body, str(now), event_id, row["id"]))
                continue
        _create(conn, tenant_id, uid, event_id, title, body, priority, link, kind)
    conn.commit()


# ---------------------------------------------------------------------------
# Résolution des destinataires — chaque fonction ne renvoie que des comptes
# réellement AUTORISÉS à connaître l'information.
# ---------------------------------------------------------------------------

def directors(conn, tenant_id):
    return [r["user_id"] for r in conn.execute(
        "SELECT user_id FROM memberships WHERE tenant_id=? AND role='directeur' AND status='active'", (tenant_id,))]


def discipline_officers(conn, tenant_id):
    return [r["user_id"] for r in conn.execute(
        "SELECT user_id FROM memberships WHERE tenant_id=? AND role='discipline' AND status='active'", (tenant_id,))]


def guardian_users(conn, tenant_id, student_id):
    return [r["user_id"] for r in conn.execute(
        """SELECT g.user_id FROM guardians g JOIN student_guardians sg ON sg.guardian_id = g.id
           WHERE sg.tenant_id=? AND sg.student_id=? AND g.user_id IS NOT NULL""", (tenant_id, student_id))]


def titulaire_user(conn, tenant_id, class_id):
    if not class_id:
        return None
    row = conn.execute("SELECT user_id FROM class_teachers WHERE tenant_id=? AND class_id=? AND is_titulaire=1 LIMIT 1",
                       (tenant_id, class_id)).fetchone()
    return row["user_id"] if row else None


def class_is_secondary(conn, class_id):
    if not class_id:
        return False
    row = conn.execute("SELECT cycle FROM classes WHERE id=?", (class_id,)).fetchone()
    return bool(row and row["cycle"] == "secondaire")


# ---------------------------------------------------------------------------
# Règles par événement
# ---------------------------------------------------------------------------

def _create_or_aggregate(conn, tenant_id, recipient_user_id, event_id, title, amount, currency):
    """Paiements de la Direction : regroupés sur une fenêtre glissante avec
    total cumulé (docs/RAPPORT_SIMULATION.md : 2530 notifications mesurées
    sans ce regroupement)."""
    now = time.time()
    row = conn.execute(
        """SELECT * FROM notifications
           WHERE tenant_id = ? AND recipient_user_id = ? AND title = ? AND status = 'unread'
             AND updated_at IS NOT NULL AND CAST(updated_at AS REAL) > ?
           ORDER BY updated_at DESC LIMIT 1""",
        (tenant_id, recipient_user_id, title, now - AGGREGATION_WINDOW_SECONDS),
    ).fetchone()
    if row:
        new_count = row["count"] + 1
        new_total = (row["amount_total"] or 0) + amount
        body = f"{new_count} paiements reçus — total {new_total:,.2f} {currency}".replace(",", " ")
        conn.execute(
            "UPDATE notifications SET count = ?, amount_total = ?, body = ?, updated_at = ?, event_id = ? WHERE id = ?",
            (new_count, new_total, body, str(now), event_id, row["id"]),
        )
    else:
        body = f"Nouveau paiement reçu — {amount:.2f} {currency}"
        conn.execute(
            """INSERT INTO notifications
               (id, tenant_id, recipient_user_id, event_id, title, body, priority, count, amount_total, created_at, updated_at, link, kind)
               VALUES (?,?,?,?,?,?, 'NORMAL', 1, ?, ?, ?, 'paiements.html', 'payment')""",
            (new_id(), tenant_id, recipient_user_id, event_id, title, body, amount, str(now), str(now)),
        )


def on_payment_confirmed(conn, tenant_id, student, payment, event, receipt=None):
    student_name = f"{student['first_name']} {student['last_name']}"
    link = f"eleve-dossier.html?id={student['id']}&tab=finance"
    receipt_txt = f" Reçu {receipt['number']}." if receipt else ""
    for uid in guardian_users(conn, tenant_id, student["id"]):
        _create(conn, tenant_id, uid, event["id"], "Paiement confirmé",
                f"Le paiement de {payment['amount']:.2f} {payment['currency']} pour {student_name} a été confirmé.{receipt_txt}",
                link=link, kind="payment")
    for d in directors(conn, tenant_id):
        _create_or_aggregate(conn, tenant_id, d, event["id"], "Nouveaux paiements reçus", payment["amount"], payment["currency"])
    conn.commit()


def on_attendance_recorded(conn, tenant_id, student, class_id, status, actor_id, settings, event_id=None):
    """Absence/retard : parent (si l'établissement l'autorise), titulaire de la
    classe (s'il n'est pas l'auteur), DD si classe secondaire."""
    if status not in ("absent", "late"):
        return
    name = f"{student['first_name']} {student['last_name']}"
    label = "Une absence" if status == "absent" else "Un retard"
    link = f"eleve-dossier.html?id={student['id']}&tab=presence"
    if settings.get("parent_notify_attendance"):
        send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]),
             f"{label} a été enregistré{'e' if status == 'absent' else ''} pour {student['first_name']}",
             f"{label} a été enregistré{'e' if status == 'absent' else ''} aujourd'hui pour {name}.", link=link, kind="attendance", event_id=event_id)
    staff = []
    tit = titulaire_user(conn, tenant_id, class_id)
    if tit and tit != actor_id:
        staff.append(tit)
    if class_is_secondary(conn, class_id):
        staff += [u for u in discipline_officers(conn, tenant_id) if u != actor_id]
    if staff:
        send(conn, tenant_id, staff, f"Suivi élève — {label.lower()} : {name}",
             f"{label} a été enregistré{'e' if status == 'absent' else ''} pour {name} dans sa classe.", link=link, kind="attendance", event_id=event_id)


def on_incident_created(conn, tenant_id, student, incident, actor_id, settings, event_id=None):
    """DD enregistre → titulaire informé, Direction informée (si elle n'est pas
    l'auteur), parent uniquement si l'établissement ET l'incident le prévoient."""
    name = f"{student['first_name']} {student['last_name']}"
    link = f"eleve-dossier.html?id={student['id']}&tab=discipline"
    staff = []
    tit = titulaire_user(conn, tenant_id, student["class_id"])
    if tit and tit != actor_id:
        staff.append(tit)
    staff += [d for d in directors(conn, tenant_id) if d != actor_id]
    if staff:
        send(conn, tenant_id, staff, f"Suivi élève — incident : {name}",
             f"Un événement disciplinaire concernant {name} a été enregistré ({incident['title']}). Consultez son dossier pour les informations auxquelles vous avez accès.",
             link=link, kind="discipline", event_id=event_id, dedupe=False)
    if incident.get("notify_parent") and settings.get("parent_notify_incidents"):
        send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]),
             f"Information de l'établissement concernant {student['first_name']}",
             f"L'établissement a enregistré un événement concernant {name} : {incident['title']}." +
             (f" Mesure : {incident['action_taken']}." if incident.get("action_taken") else ""),
             link=link, kind="discipline", event_id=event_id, dedupe=False)


def on_discipline_threshold(conn, tenant_id, student, points, threshold, event_id=None):
    name = f"{student['first_name']} {student['last_name']}"
    link = f"eleve-dossier.html?id={student['id']}&tab=discipline"
    send(conn, tenant_id, discipline_officers(conn, tenant_id) + directors(conn, tenant_id),
         f"Seuil disciplinaire atteint : {name}",
         f"{name} totalise {points} points (seuil configuré : {threshold}). Une décision humaine est attendue — Klassio ne sanctionne jamais automatiquement.",
         link=link, kind="discipline", event_id=event_id, priority="HIGH")


def on_grades_published(conn, tenant_id, student, subject, period, settings, event_id=None):
    if not settings.get("parent_notify_grades"):
        return
    send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]),
         f"Nouvelle note pour {student['first_name']}",
         f"Une note de {subject} ({period}) est disponible pour {student['first_name']} {student['last_name']}.",
         link=f"eleve-dossier.html?id={student['id']}&tab=scolarite", kind="grade", event_id=event_id)


def on_order_created(conn, tenant_id, order, student, event_id=None):
    send(conn, tenant_id, directors(conn, tenant_id), "Nouvelle commande boutique",
         f"Commande {order['number']} pour {student['first_name']} {student['last_name']} — {order['total']:.2f} {order['currency']}.",
         link="boutique.html", kind="order", event_id=event_id, dedupe=False)


def on_order_status(conn, tenant_id, order, student, event_id=None):
    labels = {"paid": "payée", "delivered": "livrée", "cancelled": "annulée", "pending": "en attente"}
    send(conn, tenant_id, [order["parent_user_id"]], f"Commande {order['number']} {labels.get(order['status'], order['status'])}",
         f"Votre commande {order['number']} pour {student['first_name']} est maintenant {labels.get(order['status'], order['status'])}.",
         link="boutique.html", kind="order", event_id=event_id, dedupe=False)


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def list_for_user(conn, tenant_id, user_id, limit=50):
    rows = conn.execute(
        """SELECT * FROM notifications WHERE tenant_id = ? AND recipient_user_id = ?
           ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?""",
        (tenant_id, user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def summary_for_user(conn, tenant_id, user_id):
    unread = conn.execute("SELECT COUNT(*) AS n FROM notifications WHERE tenant_id=? AND recipient_user_id=? AND status='unread'",
                          (tenant_id, user_id)).fetchone()["n"]
    return {"unread_count": unread, "latest": list_for_user(conn, tenant_id, user_id, limit=6)}


def mark_read(conn, tenant_id, user_id, notification_id):
    """Marque une notification comme lue. Retourne False si elle n'existe pas,
    n'appartient pas à cet établissement, ou ne s'adresse pas à cet utilisateur.

    Trouvé au balayage d'isolation : le filtre `tenant_id`/`recipient_user_id`
    était bien là — aucune donnée d'un autre établissement n'a jamais pu être
    modifiée — mais la route répondait `{"ok": true}` quoi qu'il arrive. Un
    succès annoncé pour une opération qui n'a rien fait est un mensonge de
    l'API : le résultat réel est maintenant remonté.
    """
    curseur = conn.execute(
        "UPDATE notifications SET status='read' WHERE id=? AND tenant_id=? AND recipient_user_id=?",
        (notification_id, tenant_id, user_id),
    )
    conn.commit()
    return (curseur.rowcount or 0) > 0


def mark_all_read(conn, tenant_id, user_id):
    conn.execute("UPDATE notifications SET status='read' WHERE tenant_id=? AND recipient_user_id=? AND status='unread'",
                 (tenant_id, user_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Lots 2–5 — mêmes règles : destinataires AUTORISÉS uniquement, texte
# communicable uniquement, regroupement anti-spam.
# ---------------------------------------------------------------------------

def class_staff(conn, tenant_id, class_id):
    """Enseignants rattachés à la classe (titulaire compris)."""
    if not class_id:
        return []
    return [r["user_id"] for r in conn.execute("SELECT user_id FROM class_teachers WHERE tenant_id=? AND class_id=?", (tenant_id, class_id))]


def parents_of_classes(conn, tenant_id, class_ids):
    if not class_ids:
        return []
    placeholders = ",".join("?" for _ in class_ids)
    return [r["user_id"] for r in conn.execute(
        f"""SELECT DISTINCT g.user_id FROM guardians g JOIN student_guardians sg ON sg.guardian_id = g.id
            JOIN students s ON s.id = sg.student_id
            WHERE sg.tenant_id=? AND g.user_id IS NOT NULL AND s.status='active' AND s.class_id IN ({placeholders})""",
        (tenant_id, *class_ids))]


def all_parents(conn, tenant_id):
    return [r["user_id"] for r in conn.execute(
        """SELECT DISTINCT g.user_id FROM guardians g JOIN student_guardians sg ON sg.guardian_id = g.id
           WHERE sg.tenant_id=? AND g.user_id IS NOT NULL""", (tenant_id,))]


def staff_users(conn, tenant_id, roles=("professeur", "discipline", "directeur")):
    placeholders = ",".join("?" for _ in roles)
    return [r["user_id"] for r in conn.execute(
        f"SELECT user_id FROM memberships WHERE tenant_id=? AND status='active' AND role IN ({placeholders})", (tenant_id, *roles))]


def on_attendance_present(conn, tenant_id, student, day, settings, event_id=None):
    """« Votre enfant est à l'école » — UNE fois par enfant et par jour, si
    l'établissement l'active et si le parent ne l'a pas désactivé."""
    if not settings.get("parent_notify_present"):
        return 0
    sent = 0
    link = f"eleve-dossier.html?id={student['id']}&tab=presence"
    for g in conn.execute(
        """SELECT g.user_id, g.notify_present_daily FROM guardians g JOIN student_guardians sg ON sg.guardian_id = g.id
           WHERE sg.tenant_id=? AND sg.student_id=? AND g.user_id IS NOT NULL""", (tenant_id, student["id"])):
        if not g["notify_present_daily"]:
            continue
        pref = conn.execute("SELECT notify_present_daily FROM user_preferences WHERE user_id=?", (g["user_id"],)).fetchone()
        if pref and not pref["notify_present_daily"]:
            continue
        already = conn.execute(
            """SELECT 1 FROM notifications WHERE tenant_id=? AND recipient_user_id=? AND kind='attendance_present'
               AND link=? AND body LIKE ?""", (tenant_id, g["user_id"], link, f"%{day}%")).fetchone()
        if already:
            continue
        _create(conn, tenant_id, g["user_id"], event_id, f"{student['first_name']} est à l'école",
                f"Présence confirmée pour {student['first_name']} {student['last_name']} le {day}.", link=link, kind="attendance_present")
        sent += 1
    conn.commit()
    return sent


def on_event_published(conn, tenant_id, event, recipient_ids, event_id=None):
    kind_label = {"communique": "Communiqué", "reunion": "Réunion", "fete": "Fête", "deuil": "Deuil", "conge": "Congé", "examens": "Examens", "echeance": "Échéance"}.get(event["kind"], "Événement")
    when = f" — {event['starts_on']}" if event.get("starts_on") else ""
    send(conn, tenant_id, recipient_ids, f"{kind_label} : {event['title']}", (event.get("body") or event["title"])[:240] + when,
         link="calendrier.html" + (f"?date={event['starts_on']}" if event.get("starts_on") else ""), kind="event", event_id=event_id, dedupe=False,
         priority="HIGH" if event["kind"] in ("deuil", "communique") else "NORMAL")


def on_resource_published(conn, tenant_id, resource, class_name, event_id=None):
    parents = parents_of_classes(conn, tenant_id, [resource["class_id"]])
    if resource["kind"] == "devoir":
        title = f"Nouveau devoir — {class_name}"
        body = f"{resource['title']}" + (f" · à rendre le {resource['due_date']}" if resource.get("due_date") else "")
    else:
        title = f"Nouvelle ressource — {class_name}"
        body = f"{resource['title']}" + (f" ({resource['subject']})" if resource.get("subject") else "")
    send(conn, tenant_id, parents, title, body, link=f"ressources.html?class={resource['class_id']}", kind="resource", event_id=event_id)


def on_message(conn, tenant_id, student, sender_id, sender_role, body, recipient_ids, event_id=None):
    name = f"{student['first_name']} {student['last_name']}"
    send(conn, tenant_id, [u for u in recipient_ids if u != sender_id], f"Nouveau message — {name}", body[:160],
         link=f"messages.html?student={student['id']}", kind="message", event_id=event_id)


def on_justification_requested(conn, tenant_id, student, justification, event_id=None):
    staff = class_staff(conn, tenant_id, student["class_id"]) + discipline_officers(conn, tenant_id)
    send(conn, tenant_id, staff, f"Justification d'absence — {student['first_name']} {student['last_name']}",
         f"Le parent justifie l'absence du {justification['date']} : {justification['reason'][:140]}",
         link=f"discipline.html?tab=justifications", kind="justification", event_id=event_id, dedupe=False)


def on_justification_decided(conn, tenant_id, student, justification, event_id=None):
    accepted = justification["status"] == "accepted"
    send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]),
         f"Justification {'acceptée' if accepted else 'refusée'} — {student['first_name']}",
         f"L'absence du {justification['date']} est {'excusée' if accepted else 'restée injustifiée'}." + (f" {justification['decision_note']}" if justification.get("decision_note") else ""),
         link=f"eleve-dossier.html?id={student['id']}&tab=presence", kind="justification", event_id=event_id, dedupe=False)


def on_incident_reply(conn, tenant_id, student, incident, reply_user_role, event_id=None):
    name = f"{student['first_name']} {student['last_name']}"
    link = f"eleve-dossier.html?id={student['id']}&tab=discipline"
    if reply_user_role == "parent":
        send(conn, tenant_id, discipline_officers(conn, tenant_id) + directors(conn, tenant_id),
             f"Réponse du parent — {name}", f"Le parent a répondu à l'incident « {incident['title']} ».", link=link, kind="discipline", event_id=event_id, dedupe=False)
    else:
        send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]),
             f"Réponse de l'établissement — {student['first_name']}", f"L'établissement a répondu concernant « {incident['title']} ».", link=link, kind="discipline", event_id=event_id, dedupe=False)


def on_report_created(conn, tenant_id, student, report, event_id=None):
    name = f"{student['first_name']} {student['last_name']}"
    send(conn, tenant_id, discipline_officers(conn, tenant_id) + directors(conn, tenant_id),
         f"Signalement à qualifier — {name}", report["description"][:160], link="discipline.html?tab=signalements", kind="discipline", event_id=event_id, dedupe=False)


def on_report_handled(conn, tenant_id, student, report, event_id=None):
    label = "qualifié en incident" if report["status"] == "qualified" else "classé sans suite"
    send(conn, tenant_id, [report["reported_by"]], f"Votre signalement a été {label} — {student['first_name']}",
         (report.get("handling_note") or f"Signalement concernant {student['first_name']} {student['last_name']} {label}.")[:200],
         link=f"eleve-dossier.html?id={student['id']}&tab=discipline", kind="discipline", event_id=event_id, dedupe=False)


def on_convocation(conn, tenant_id, student, convocation, event_id=None):
    when = convocation["scheduled_on"] + (f" à {convocation['scheduled_time']}" if convocation.get("scheduled_time") else "")
    send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]),
         f"Convocation — {student['first_name']}", f"Vous êtes convoqué(e) le {when} : {convocation['motif']}.",
         link=f"eleve-dossier.html?id={student['id']}&tab=discipline", kind="discipline", event_id=event_id, dedupe=False, priority="HIGH")
    tit = titulaire_user(conn, tenant_id, student["class_id"])
    if tit:
        send(conn, tenant_id, [tit], f"Convocation planifiée — {student['first_name']} {student['last_name']}", f"Parents convoqués le {when}.",
             link=f"eleve-dossier.html?id={student['id']}&tab=discipline", kind="discipline", event_id=event_id, dedupe=False)


def on_thresholds_crossed(conn, tenant_id, student, crossed, balance, event_id=None):
    name = f"{student['first_name']} {student['last_name']}"
    labels = ", ".join(t["label"] for t in crossed)
    send(conn, tenant_id, discipline_officers(conn, tenant_id) + directors(conn, tenant_id) + ([titulaire_user(conn, tenant_id, student["class_id"])] if titulaire_user(conn, tenant_id, student["class_id"]) else []),
         f"Seuil atteint — {name} : {labels}",
         f"{name} n'a plus que {balance['remaining']} points sur {balance['capital']}. Étape prévue par l'établissement : {labels}. La décision reste humaine.",
         link=f"eleve-dossier.html?id={student['id']}&tab=discipline", kind="discipline", event_id=event_id, priority="HIGH", dedupe=False)


def on_period_published(conn, tenant_id, period, student_ids, event_id=None):
    for sid in student_ids:
        s = conn.execute("SELECT first_name, last_name FROM students WHERE id=?", (sid,)).fetchone()
        if not s:
            continue
        send(conn, tenant_id, guardian_users(conn, tenant_id, sid), f"Bulletin disponible — {s['first_name']}",
             f"Les résultats de {s['first_name']} {s['last_name']} pour « {period['label']} » sont proclamés.",
             link=f"eleve-dossier.html?id={sid}&tab=scolarite", kind="grade", event_id=event_id, dedupe=False)


def on_decision_set(conn, tenant_id, student, decision, event_id=None):
    labels = {"admis": "admis(e)", "ajourne": "ajourné(e)", "doublant": "doublant(e)"}
    send(conn, tenant_id, guardian_users(conn, tenant_id, student["id"]), f"Décision de fin d'année — {student['first_name']}",
         f"{student['first_name']} {student['last_name']} est {labels.get(decision['decision'], decision['decision'])}" + (f" — mention {decision['mention']}" if decision.get("mention") else "") + ".",
         link=f"eleve-dossier.html?id={student['id']}&tab=scolarite", kind="grade", event_id=event_id, dedupe=False, priority="HIGH")


def on_order_ready(conn, tenant_id, order, student, event_id=None):
    send(conn, tenant_id, [order["parent_user_id"]], f"Commande {order['number']} prête",
         f"{student['first_name']} peut la retirer à l'économat avec le code {order['pickup_code']}.",
         link="boutique.html", kind="order", event_id=event_id, dedupe=False)


def on_subscription_notice(conn, tenant_id, title, body, link="abonnement.html", priority="HIGH"):
    send(conn, tenant_id, directors(conn, tenant_id), title, body, link=link, kind="billing", priority=priority)
