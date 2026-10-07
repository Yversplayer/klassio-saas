"""KLASSIO backend — abonnement (l'école paie Klassio) et administration de
la plateforme. Circuit STRICTEMENT séparé des frais scolaires : ses tables
(plans, subscriptions, invoices) ne touchent ni obligations, ni paiements,
ni reçus des élèves ; l'argent des parents ne transite jamais ici.

Cycle (depuis le 01/10/2026 — il n'existe PAS de mode gratuit) :
création de l'espace → choix de l'offre (obligatoire) → première facture →
paiement déclaré par la Direction (mobile money / virement, référence) →
confirmation par la plateforme → l'espace s'ouvre → facture mensuelle.
Tant que la première facture n'est pas confirmée, l'espace est FERMÉ : seuls
l'import de départ, l'abonnement et la session répondent. Retard ensuite :
rappel, puis lecture seule après le délai de grâce — jamais de suppression.

Les écoles créées avant cette règle gardent leur période d'essai (statut
« trial ») jusqu'à son terme : on ne retire pas rétroactivement ce qui a été
promis. Les testeurs lèvent les blocages avec KLASSIO_CONTOURNER_ABONNEMENT
(config.py) — un réglage serveur, refusé sur une base distante.
"""
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify, g

import config
import db
import notifications as notif_module
import school
from security import require_auth, new_id, audit
from platform_auth import require_platform_admin, acteur as platform_acteur
from validation import json_object, ValidationError, required_text

bp = Blueprint("billing", __name__)

TRIAL_DAYS = 30
PERIOD_DAYS = 30
# Facturation à l'année (07/10/2026) : « 2 mois offerts ». Une facture porte
# son cycle, et c'est lui qui fixe la période qu'elle ouvre — à la création
# comme à la confirmation.
CYCLES = ("monthly", "yearly")
YEAR_DAYS = 365


def jours_du_cycle(cycle):
    return YEAR_DAYS if cycle == "yearly" else PERIOD_DAYS
INVOICE_DUE_DAYS = 7
WRITE_ALLOWLIST_PREFIXES = ("/api/subscription", "/api/auth/", "/api/me", "/api/notifications", "/api/platform", "/api/ai/")
# Espace pas encore activé : il ne répond qu'à ce qui permet de l'ouvrir — la
# session, l'abonnement, le catalogue des offres, et l'import de départ (les
# fichiers Excel de l'école se déposent AVANT le choix de l'offre).
AWAITING_STATUSES = ("awaiting_plan", "awaiting_payment")
AWAITING_ALLOWLIST_PREFIXES = ("/api/subscription", "/api/plans", "/api/auth/", "/api/me", "/api/onboarding/", "/api/platform", "/api/notifications")
MSG_AWAITING = ("Espace en attente d'activation : choisissez votre offre et réglez la première facture. "
                "Vos données importées sont conservées.")
# Une école qui a DÉCLARÉ son premier paiement entre aussitôt, le temps que la
# plateforme le vérifie : la faire attendre (parfois une nuit, un week-end)
# avant d'importer ou d'inviter son équipe, c'est la perdre au moment où elle
# vient de payer. Une seule fois par école : une fausse référence ne rouvre
# jamais l'espace. Rejet ou délai dépassé → l'espace se referme, rien n'est perdu.
PROVISIONAL_HOURS = 72
MSG_SUSPENDED = "Espace en lecture seule : l'abonnement de l'établissement est en attente de règlement. Vos données sont intactes."


def _autorise(path, entrees):
    """Une entrée est un SEGMENT de chemin, pas un début de chaîne : « /api/me »
    couvre /api/me et /api/me/password, mais pas /api/messages. La première
    version testait `startswith` : une école suspendue pour impayé pouvait
    encore écrire dans le cahier de communication (constaté le 01/10/2026).
    Une entrée finissant par « / » couvre tout ce qui est en dessous."""
    for e in entrees:
        if e.endswith("/"):
            if path.startswith(e):
                return True
        elif path == e or path.startswith(e + "/"):
            return True
    return False


def provisoire(conn, sub):
    """Vrai pendant l'ouverture provisoire : premier paiement déclaré (facture
    « pending »), fenêtre de 72 h non écoulée."""
    if sub is None or sub["status"] != "awaiting_payment":
        return False
    jusqua = sub["provisional_until"] if "provisional_until" in sub.keys() else None
    if not jusqua or datetime.now() >= _dt(jusqua):
        return False
    return bool(conn.execute("SELECT 1 FROM invoices WHERE tenant_id=? AND status='pending'", (sub["tenant_id"],)).fetchone())


def bypass_active():
    """Lu à CHAQUE appel (et non figé à l'import) : les tests le basculent."""
    return bool(getattr(config, "CONTOURNER_ABONNEMENT", False))


def _ts(dt):
    return str(dt.timestamp())


def _dt(ts):
    return datetime.fromtimestamp(float(ts))


def active_students(conn, tenant_id):
    return conn.execute("SELECT COUNT(*) n FROM students WHERE tenant_id=? AND status='active'", (tenant_id,)).fetchone()["n"]


def plan_for(conn, students):
    rows = conn.execute("SELECT * FROM plans WHERE active=1 ORDER BY sort").fetchall()
    for p in rows:
        if students >= p["min_students"] and (p["max_students"] is None or students <= p["max_students"]):
            return dict(p)
    return dict(rows[-1]) if rows else None


def amount_for(plan, students, cycle="monthly"):
    if plan is None:
        return 0.0
    if cycle == "yearly" and plan.get("yearly_price") is not None:
        return round(float(plan["yearly_price"]), 2)
    return round(float(plan["base_price"]) + float(plan["per_student"]) * students, 2)


def equivalent_mensuel(plan, students, cycle="monthly"):
    """Ce que l'école rapporte par mois : une école à l'année compte pour son
    prix annuel divisé par 12 dans le revenu mensuel de la plateforme."""
    montant = amount_for(plan, students, cycle)
    return round(montant / 12, 2) if cycle == "yearly" and plan and plan.get("yearly_price") is not None else montant


def _cycle_de(sub):
    cycle = sub["billing_cycle"] if "billing_cycle" in sub.keys() else None
    return cycle if cycle in CYCLES else "monthly"


def ensure_subscription(conn, tenant_id):
    row = conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()
    if row:
        return row
    # Pas d'essai : une école sans abonnement attend le choix de son offre.
    # plan_code est obligatoire dans la table ; il porte ici le palier que la
    # taille de l'école imposerait, en attendant le choix réel.
    plan = plan_for(conn, active_students(conn, tenant_id))
    now = str(time.time())
    conn.execute("INSERT INTO subscriptions (tenant_id, plan_code, status, trial_ends_at, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                 (tenant_id, plan["code"] if plan else "essentiel", "awaiting_plan", None, now, now))
    conn.commit()
    return conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()


def _next_invoice_number(conn):
    """Numéro de facture Klassio : une séquence UNIQUE pour toute la plateforme.

    Trouvé par RLS (07/10/2026) : sous la portée d'une école, la lecture du
    dernier numéro ne voyait que les factures de CETTE école — le numéro
    recalculé était déjà pris par une autre, et l'insertion tombait sur la
    contrainte d'unicité. La lecture passe donc par une connexion globale,
    volontairement : elle ne renvoie qu'un numéro, aucune donnée d'école."""
    year = date.today().year
    prefix = f"INV-{year}-"
    lecture = db.get_connection(globale=True)
    try:
        row = lecture.execute("SELECT number FROM invoices WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
                              (prefix + "%",)).fetchone()
    finally:
        lecture.close()
    seq = int(row["number"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:04d}"


def issue_invoice(conn, tenant_id, period_start, plan=None, cycle=None):
    """plan=None : le palier qu'impose la taille de l'école (renouvellement).
    Le palier CHOISI n'est retenu que s'il couvre l'effectif : une école qui a
    grandi passe d'elle-même au palier au-dessus, jamais l'inverse.
    cycle=None : celui de l'abonnement (au mois par défaut). Un palier sans
    prix annuel (sur devis) est toujours facturé au mois."""
    students = active_students(conn, tenant_id)
    requis = plan_for(conn, students)
    if plan is None or (plan["max_students"] is not None and students > plan["max_students"]):
        plan = requis
    if cycle not in CYCLES:
        sub = conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()
        cycle = _cycle_de(sub) if sub else "monthly"
    if cycle == "yearly" and (plan is None or plan.get("yearly_price") is None):
        cycle = "monthly"
    period_end = period_start + timedelta(days=jours_du_cycle(cycle))
    amount = amount_for(plan, students, cycle)
    iid = new_id()
    conn.execute(
        """INSERT INTO invoices (id, tenant_id, number, plan_code, period_start, period_end, students, amount, currency, status, due_at, created_at, billing_cycle)
           VALUES (?,?,?,?,?,?,?,?,?,'open',?,?,?)""",
        (iid, tenant_id, _next_invoice_number(conn), plan["code"] if plan else "essentiel", period_start.date().isoformat(), period_end.date().isoformat(),
         students, amount, plan["currency"] if plan else "USD", _ts(period_start + timedelta(days=INVOICE_DUE_DAYS)), str(time.time()), cycle))
    conn.execute("UPDATE subscriptions SET plan_code=?, current_period_start=?, current_period_end=?, updated_at=? WHERE tenant_id=?",
                 (plan["code"] if plan else "essentiel", _ts(period_start), _ts(period_end), str(time.time()), tenant_id))
    conn.commit()
    inv = dict(conn.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone())
    notif_module.on_subscription_notice(conn, tenant_id, f"Facture {inv['number']} — abonnement Klassio",
                                        f"{amount:.2f} {inv['currency']} {'pour un an' if cycle == 'yearly' else 'pour un mois'}, {students} élèves actifs (palier {plan['name'] if plan else '—'}), à régler avant le {_dt(inv['due_at']).date().isoformat()}.")
    return inv


def compute_state(conn, tenant_id):
    """État courant (met à jour le statut selon les dates — sans effet de
    bord destructif). Appelé par /api/subscription et /api/me."""
    sub = ensure_subscription(conn, tenant_id)
    now = datetime.now()
    status = sub["status"]
    if status == "cancelled" or status in AWAITING_STATUSES:
        return dict(sub)
    if status == "trial" and now > _dt(sub["trial_ends_at"]):
        issue_invoice(conn, tenant_id, _dt(sub["trial_ends_at"]))
        conn.execute("UPDATE subscriptions SET status='active', updated_at=? WHERE tenant_id=?", (str(time.time()), tenant_id))
        conn.commit()
        status = "active"
    if status in ("active", "past_due", "suspended"):
        open_inv = conn.execute("SELECT * FROM invoices WHERE tenant_id=? AND status IN ('open','pending') ORDER BY due_at LIMIT 1", (tenant_id,)).fetchone()
        if open_inv:
            due = _dt(open_inv["due_at"])
            if now > due + timedelta(days=sub["grace_days"]):
                new_status = "suspended"
            elif now > due:
                new_status = "past_due"
            else:
                new_status = "active"
        else:
            new_status = "active"
            if sub["current_period_end"] and now > _dt(sub["current_period_end"]):
                choisi = conn.execute("SELECT * FROM plans WHERE code=?", (sub["plan_code"],)).fetchone()
                issue_invoice(conn, tenant_id, _dt(sub["current_period_end"]), dict(choisi) if choisi else None)
        if new_status != status:
            conn.execute("UPDATE subscriptions SET status=?, updated_at=? WHERE tenant_id=?", (new_status, str(time.time()), tenant_id))
            conn.commit()
            if new_status == "past_due":
                notif_module.on_subscription_notice(conn, tenant_id, "Abonnement en retard de paiement", f"Votre espace passera en lecture seule après {sub['grace_days']} jours de retard. Réglez la facture depuis Abonnement.")
            elif new_status == "suspended":
                notif_module.on_subscription_notice(conn, tenant_id, "Espace en lecture seule", "Facture impayée au-delà du délai de grâce. Vos données sont intactes ; l'écriture reprend dès confirmation du paiement.")
    return dict(conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone())


def summary(conn, tenant_id):
    sub = compute_state(conn, tenant_id)
    students = active_students(conn, tenant_id)
    requis = plan_for(conn, students)
    plan = requis
    if sub["status"] not in ("awaiting_plan",):
        choisi = conn.execute("SELECT * FROM plans WHERE code=?", (sub["plan_code"],)).fetchone()
        if choisi and (choisi["max_students"] is None or students <= choisi["max_students"]):
            plan = dict(choisi)
    now = datetime.now()
    days_left = None
    attention = None
    ouvert_provisoirement = provisoire(conn, sub)
    if sub["status"] == "awaiting_plan":
        attention = "Choisissez l'offre de votre établissement pour ouvrir votre espace."
    elif ouvert_provisoirement:
        attention = ("Paiement en cours de vérification : votre espace est ouvert jusqu'au "
                     + _dt(sub["provisional_until"]).strftime("%d/%m à %H:%M") + ".")
    elif sub["status"] == "awaiting_payment":
        attention = "Votre espace s'ouvrira dès la confirmation du premier paiement."
    elif sub["status"] == "trial":
        days_left = max(0, (_dt(sub["trial_ends_at"]) - now).days)
        if days_left <= 5:
            attention = f"Votre période d'essai se termine dans {days_left} jour(s)."
    elif sub["status"] == "past_due":
        attention = "Une facture est en retard — réglez-la pour éviter le passage en lecture seule."
    elif sub["status"] == "suspended":
        attention = "Espace en lecture seule : facture impayée. Vos données sont intactes."
    open_inv = conn.execute("SELECT * FROM invoices WHERE tenant_id=? AND status IN ('open','pending') ORDER BY due_at LIMIT 1", (tenant_id,)).fetchone()
    if open_inv is not None and open_inv["status"] == "open" and attention is None and sub["status"] not in AWAITING_STATUSES:
        # Une facture non réglée est la seule chose que la Direction ait à faire
        # ici : c'est ce qui justifie de l'amener sur l'écran d'abonnement.
        attention = (f"Facture {open_inv['number']} de {open_inv['amount']:.2f} {open_inv['currency']} "
                     f"à régler avant le {_dt(open_inv['due_at']).date().isoformat()}.")
    return {
        "status": sub["status"], "plan": plan, "students": students,
        "billing_cycle": _cycle_de(sub),
        "estimated_amount": amount_for(plan, students, _cycle_de(sub)),
        "monthly_equivalent": equivalent_mensuel(plan, students, _cycle_de(sub)),
        "trial_ends_at": sub["trial_ends_at"], "days_left": days_left, "current_period_end": sub["current_period_end"], "grace_days": sub["grace_days"],
        "attention": attention, "read_only": sub["status"] == "suspended",
        "open_invoice": dict(open_inv) if open_inv else None,
        # Espace fermé tant que la première facture n'est pas confirmée —
        # sauf contournement testeur (réglage serveur, jamais navigateur).
        "awaiting": sub["status"] in AWAITING_STATUSES,
        "locked": sub["status"] in AWAITING_STATUSES and not bypass_active() and not ouvert_provisoirement,
        "provisional": ouvert_provisoirement,
        "provisional_until": sub.get("provisional_until") if ouvert_provisoirement else None,
        "bypass": bypass_active(),
        "required_plan": requis,
    }


def write_blocked(conn, ctx, path, method):
    """Garde branchée sur require_auth. Renvoie None (passe) ou le message du
    refus (402).

    - Espace en attente d'activation (offre non choisie, ou première facture
      non confirmée) : TOUT est fermé, lecture comprise, sauf ce qui sert à
      l'ouvrir. Lire les élèves d'une école qui n'a pas payé serait déjà
      utiliser le logiciel.
    - Espace suspendu (retard au-delà du délai de grâce) : lecture libre,
      écriture bloquée sauf abonnement et session.
    - Contournement testeur : aucune garde."""
    if bypass_active():
        return None
    sub = conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (ctx["tenant_id"],)).fetchone()
    if sub is None:
        # École sans ligne d'abonnement (créée par un outil, ou avant le
        # module) : on la crée — en attente d'offre — plutôt que de la
        # laisser ouverte par omission.
        sub = ensure_subscription(conn, ctx["tenant_id"])
    if sub["status"] in AWAITING_STATUSES:
        if _autorise(path, AWAITING_ALLOWLIST_PREFIXES) or provisoire(conn, sub):
            return None
        return MSG_AWAITING
    if method in ("GET", "OPTIONS", "HEAD"):
        return None
    if _autorise(path, WRITE_ALLOWLIST_PREFIXES):
        return None
    return MSG_SUSPENDED if sub["status"] == "suspended" else None


# ===========================================================================
# ROUTES DIRECTION
# ===========================================================================

@bp.get("/api/plans")
def list_plans():
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM plans WHERE active=1 ORDER BY sort")]
    conn.close()
    return jsonify(rows)


@bp.get("/api/subscription")
@require_auth
def get_subscription():
    if g.ctx["role"] != "directeur":
        return jsonify({"error": "Réservé à la Direction."}), 403
    conn = db.get_connection()
    s = summary(conn, g.ctx["tenant_id"])
    s["invoices"] = [dict(r) for r in conn.execute("SELECT * FROM invoices WHERE tenant_id=? ORDER BY created_at DESC LIMIT 36", (g.ctx["tenant_id"],))]
    s["plans"] = [dict(r) for r in conn.execute("SELECT * FROM plans WHERE active=1 ORDER BY sort")]
    tenant = conn.execute("SELECT name FROM tenants WHERE id=?", (g.ctx["tenant_id"],)).fetchone()
    s["school_name"] = tenant["name"]
    conn.close()
    return jsonify(s)


@bp.post("/api/subscription/choose")
@require_auth
def choose_plan():
    """La Direction choisit l'offre de son établissement — étape obligatoire
    avant l'ouverture de l'espace. Le serveur vérifie ce que le navigateur
    affiche : une offre plus petite que l'effectif est refusée, et l'offre
    « sur devis » ne se règle pas en libre-service. La première facture est
    émise aussitôt ; l'espace reste fermé jusqu'à sa confirmation."""
    if g.ctx["role"] != "directeur":
        return jsonify({"error": "Réservé à la Direction."}), 403
    data = json_object(request.get_json(force=True))
    code = str(data.get("plan_code") or "")
    cycle = data.get("billing_cycle") or "monthly"
    if cycle not in CYCLES:
        raise ValidationError("Facturation au mois ou à l'année uniquement.")
    conn = db.get_connection()
    tenant_id = g.ctx["tenant_id"]
    sub = ensure_subscription(conn, tenant_id)
    if sub["status"] not in AWAITING_STATUSES:
        conn.close()
        return jsonify({"error": "L'offre est déjà active ; pour en changer, contactez Klassio."}), 409
    plan = conn.execute("SELECT * FROM plans WHERE code=? AND active=1", (code,)).fetchone()
    if not plan:
        conn.close()
        raise ValidationError("Offre inconnue.")
    plan = dict(plan)
    if cycle == "yearly" and plan.get("yearly_price") is None:
        conn.close()
        raise ValidationError(f"L'offre {plan['name']} ne se règle pas à l'année.")
    if plan["max_students"] is None and float(plan["base_price"]) == 0:
        conn.close()
        return jsonify({"error": "Cette offre est sur devis : écrivez-nous, nous vous répondons avec un tarif adapté.", "quote": True}), 409
    students = active_students(conn, tenant_id)
    if plan["max_students"] is not None and students > plan["max_students"]:
        conn.close()
        raise ValidationError(f"Votre établissement compte {students} élèves actifs : l'offre {plan['name']} s'arrête à {plan['max_students']}.")
    pending = conn.execute("SELECT 1 FROM invoices WHERE tenant_id=? AND status='pending'", (tenant_id,)).fetchone()
    if pending:
        conn.close()
        return jsonify({"error": "Un paiement est déjà déclaré pour cette facture : attendez sa confirmation."}), 409
    # Changer d'avis avant d'avoir payé : la facture précédente est annulée.
    conn.execute("UPDATE invoices SET status='void' WHERE tenant_id=? AND status='open'", (tenant_id,))
    conn.execute("UPDATE subscriptions SET plan_code=?, status='awaiting_payment', billing_cycle=?, updated_at=? WHERE tenant_id=?",
                 (plan["code"], cycle, str(time.time()), tenant_id))
    conn.commit()
    inv = issue_invoice(conn, tenant_id, datetime.now(), plan, cycle)
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "billing.plan_chosen", "plan", plan["code"], "success",
          after={"invoice": inv["number"], "amount": inv["amount"], "billing_cycle": cycle})
    return jsonify({"ok": True, "status": "awaiting_payment", "invoice": inv, "billing_cycle": cycle})


@bp.post("/api/subscription/pay")
@require_auth
def declare_payment():
    """La Direction déclare son paiement (mobile money ou virement) avec sa
    référence ; la plateforme le confirme après vérification réelle — aucun
    fournisseur de paiement n'est branché, donc aucun faux succès."""
    if g.ctx["role"] != "directeur":
        return jsonify({"error": "Réservé à la Direction."}), 403
    data = json_object(request.get_json(force=True))
    method = data.get("method")
    if method not in ("mobile_money", "bank"):
        raise ValidationError("method doit être mobile_money ou bank.")
    reference = required_text(data.get("reference"), "reference", 80)
    conn = db.get_connection()
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND tenant_id=?", (data.get("invoice_id"), g.ctx["tenant_id"])).fetchone()
    if not inv or inv["status"] not in ("open", "pending"):
        conn.close()
        return jsonify({"error": "Facture introuvable ou déjà réglée."}), 404
    conn.execute("UPDATE invoices SET status='pending', method=?, reference=? WHERE id=?", (method, reference, inv["id"]))
    sub = ensure_subscription(conn, g.ctx["tenant_id"])
    ouverture = None
    if sub["status"] == "awaiting_payment" and not (sub["provisional_until"] if "provisional_until" in sub.keys() else None):
        ouverture = datetime.now() + timedelta(hours=PROVISIONAL_HOURS)
        conn.execute("UPDATE subscriptions SET provisional_until=?, updated_at=? WHERE tenant_id=?",
                     (_ts(ouverture), str(time.time()), g.ctx["tenant_id"]))
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "billing.payment_declared", "invoice", inv["id"], "success", after={"method": method})
    if ouverture:
        return jsonify({"ok": True, "status": "pending", "provisional_until": _ts(ouverture),
                        "message": "Paiement déclaré. Votre espace est ouvert pendant que Klassio le vérifie (jusqu'au "
                                   + ouverture.strftime("%d/%m à %H:%M") + ")."})
    return jsonify({"ok": True, "status": "pending", "message": "Paiement déclaré — il sera confirmé par Klassio après vérification."})


# ===========================================================================
# ADMINISTRATION DE LA PLATEFORME (rôle global)
# ===========================================================================

# Depuis le 06/10/2026, ces routes ne s'ouvrent qu'à une session
# d'administration (platform_auth.require_platform_admin) : compte à part,
# second facteur, cookie distinct. Une session d'école — même de directeur, même
# inscrit dans l'ancienne table platform_admins — reçoit 403.


def _etat_rls(conn):
    """État de la sécurité au niveau des lignes, pour l'administration :
    vérifier en production, sans accès à la base, que chaque table à
    établissement est bien sous RLS et que les requêtes passent par le rôle
    applicatif (db._activer_rls). None sous SQLite (pas de RLS)."""
    if not db.is_postgres():
        return None
    tables = [r["table_name"] for r in conn.execute(
        """SELECT c.table_name FROM information_schema.columns c
           JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
           WHERE c.table_schema = current_schema() AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE'""")]
    proteges = {r["relname"] for r in conn.execute(
        """SELECT k.relname FROM pg_class k JOIN pg_namespace n ON n.oid = k.relnamespace
           JOIN pg_policies p ON p.schemaname = n.nspname AND p.tablename = k.relname
           WHERE n.nspname = current_schema() AND k.relrowsecurity AND p.policyname = 'klassio_isolation'""")}
    role = conn.execute("SELECT current_user AS r").fetchone()["r"]
    return {"tenant_tables": len(tables), "protected": len([t for t in tables if t in proteges]),
            "unprotected": sorted(t for t in tables if t not in proteges), "role": role}


@bp.get("/api/platform/overview")
@require_platform_admin
def platform_overview():
    conn = db.get_connection()
    tenants = []
    mrr = 0.0
    for t in conn.execute("SELECT * FROM tenants ORDER BY created_at DESC"):
        s = summary(conn, t["id"])
        director = conn.execute("SELECT u.name, u.email, u.phone FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? AND m.role='directeur' ORDER BY m.created_at LIMIT 1", (t["id"],)).fetchone()
        if s["status"] in ("active", "past_due"):
            mrr += s["monthly_equivalent"]
        tenants.append({"id": t["id"], "name": t["name"], "slug": t["slug"], "created_at": t["created_at"], "status": s["status"], "students": s["students"],
                        "plan": s["plan"]["name"] if s["plan"] else None, "amount": s["monthly_equivalent"],
                        "billing_cycle": s["billing_cycle"], "days_left": s["days_left"],
                        "open_invoice": s["open_invoice"], "director": dict(director) if director else None})
    pending = [dict(r) for r in conn.execute("SELECT i.*, t.name AS tenant_name FROM invoices i JOIN tenants t ON t.id=i.tenant_id WHERE i.status='pending' ORDER BY i.created_at")]
    plans = [dict(r) for r in conn.execute("SELECT * FROM plans ORDER BY sort")]
    securite = _etat_rls(conn)
    conn.close()
    return jsonify({"tenants": tenants, "mrr": round(mrr, 2), "pending_invoices": pending, "plans": plans,
                    "security": securite,
                    "counts": {"total": len(tenants), "trial": sum(1 for x in tenants if x["status"] == "trial"), "active": sum(1 for x in tenants if x["status"] == "active"),
                               "past_due": sum(1 for x in tenants if x["status"] == "past_due"), "suspended": sum(1 for x in tenants if x["status"] == "suspended"),
                               "awaiting": sum(1 for x in tenants if x["status"] in AWAITING_STATUSES)}})


@bp.post("/api/platform/invoices/<invoice_id>/confirm")
@require_platform_admin
def confirm_invoice(invoice_id):
    conn = db.get_connection()
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv or inv["status"] == "paid":
        conn.close()
        return jsonify({"error": "Facture introuvable ou déjà payée."}), 404
    now = str(time.time())
    sub = ensure_subscription(conn, inv["tenant_id"])
    conn.execute("UPDATE invoices SET status='paid', paid_at=? WHERE id=?", (now, invoice_id))
    if sub["status"] in AWAITING_STATUSES:
        # Premier paiement : l'espace s'ouvre MAINTENANT, et la période payée
        # commence le jour de l'ouverture — pas le jour du choix de l'offre,
        # pendant lequel l'école n'avait pas accès.
        debut = datetime.now()
        fin = debut + timedelta(days=jours_du_cycle(inv["billing_cycle"] if "billing_cycle" in inv.keys() else "monthly"))
        conn.execute("UPDATE invoices SET period_start=?, period_end=? WHERE id=?", (debut.date().isoformat(), fin.date().isoformat(), invoice_id))
        conn.execute("UPDATE subscriptions SET status='active', current_period_start=?, current_period_end=?, updated_at=? WHERE tenant_id=?",
                     (_ts(debut), _ts(fin), now, inv["tenant_id"]))
    else:
        conn.execute("UPDATE subscriptions SET status='active', updated_at=? WHERE tenant_id=?", (now, inv["tenant_id"]))
    conn.commit()
    notif_module.on_subscription_notice(conn, inv["tenant_id"], f"Paiement confirmé — {inv['number']}", "Merci. Votre abonnement Klassio est à jour.", priority="NORMAL")
    conn.close()
    audit(inv["tenant_id"], platform_acteur(), "billing.invoice_confirmed", "invoice", invoice_id, "success")
    return jsonify({"ok": True})


@bp.post("/api/platform/invoices/<invoice_id>/void")
@require_platform_admin
def void_invoice(invoice_id):
    conn = db.get_connection()
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        return jsonify({"error": "Facture introuvable."}), 404
    conn.execute("UPDATE invoices SET status='void' WHERE id=?", (invoice_id,))
    sub = ensure_subscription(conn, inv["tenant_id"])
    if sub["status"] in AWAITING_STATUSES:
        # Référence non retrouvée : l'ouverture provisoire s'arrête MAINTENANT
        # (date passée, et non NULL : elle ne sera pas accordée une seconde fois).
        conn.execute("UPDATE subscriptions SET provisional_until=?, updated_at=? WHERE tenant_id=?",
                     (str(time.time()), str(time.time()), inv["tenant_id"]))
        conn.commit()
        notif_module.on_subscription_notice(conn, inv["tenant_id"], f"Paiement non retrouvé — {inv['number']}",
                                            "Klassio n'a pas retrouvé ce paiement. Votre espace est refermé, vos données sont intactes : vérifiez la référence ou écrivez-nous.")
    conn.commit()
    compute_state(conn, inv["tenant_id"])
    conn.close()
    audit(inv["tenant_id"], platform_acteur(), "billing.invoice_voided", "invoice", invoice_id, "success")
    return jsonify({"ok": True})


@bp.put("/api/platform/tenants/<tenant_id>")
@require_platform_admin
def update_tenant_subscription(tenant_id):
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    sub = ensure_subscription(conn, tenant_id)
    fields, params = [], []
    if "extend_trial_days" in data:
        try:
            days = int(data["extend_trial_days"])
        except (TypeError, ValueError):
            raise ValidationError("extend_trial_days doit être un entier.")
        base = max(datetime.now(), _dt(sub["trial_ends_at"])) if sub["trial_ends_at"] else datetime.now()
        fields.append("trial_ends_at=?"); params.append(_ts(base + timedelta(days=days)))
        fields.append("status='trial'")
    if "grace_days" in data:
        fields.append("grace_days=?"); params.append(int(data["grace_days"]))
    if "status" in data and data["status"] in ("active", "suspended", "cancelled", "trial", "awaiting_plan", "awaiting_payment"):
        fields.append("status=?"); params.append(data["status"])
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification."}), 400
    fields.append("updated_at=?"); params.append(str(time.time()))
    conn.execute(f"UPDATE subscriptions SET {', '.join(fields)} WHERE tenant_id=?", params + [tenant_id])
    conn.commit()
    conn.close()
    audit(tenant_id, platform_acteur(), "billing.subscription_updated", "tenant", tenant_id, "success", after=data)
    return jsonify({"ok": True})


@bp.put("/api/platform/plans/<code>")
@require_platform_admin
def update_plan(code):
    data = json_object(request.get_json(force=True))
    conn = db.get_connection()
    if not conn.execute("SELECT 1 FROM plans WHERE code=?", (code,)).fetchone():
        conn.close()
        return jsonify({"error": "Palier introuvable."}), 404
    fields, params = [], []
    for k in ("name", "description"):
        if k in data:
            fields.append(f"{k}=?"); params.append(str(data[k])[:200])
    for k in ("base_price", "per_student"):
        if k in data:
            try:
                v = float(data[k])
            except (TypeError, ValueError):
                raise ValidationError(f"{k} doit être un nombre.")
            if v < 0:
                raise ValidationError(f"{k} ne peut pas être négatif.")
            fields.append(f"{k}=?"); params.append(v)
    for k in ("min_students", "max_students"):
        if k in data:
            fields.append(f"{k}=?"); params.append(int(data[k]) if data[k] not in (None, "") else None)
    if "active" in data:
        fields.append("active=?"); params.append(1 if data["active"] else 0)
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification."}), 400
    conn.execute(f"UPDATE plans SET {', '.join(fields)} WHERE code=?", params + [code])
    conn.commit()
    conn.close()
    audit(None, platform_acteur(), "billing.plan_updated", "plan", code, "success", after=data)
    return jsonify({"ok": True})
