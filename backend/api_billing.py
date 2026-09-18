"""KLASSIO backend — abonnement (l'école paie Klassio) et administration de
la plateforme. Circuit STRICTEMENT séparé des frais scolaires : ses tables
(plans, subscriptions, invoices) ne touchent ni obligations, ni paiements,
ni reçus des élèves ; l'argent des parents ne transite jamais ici.

Cycle : essai 30 jours → facture mensuelle (palier selon élèves actifs) →
paiement déclaré par la Direction (mobile money / virement, référence) →
confirmation par la plateforme → période suivante. Retard : rappel, puis
lecture seule après le délai de grâce — jamais de suppression de données.
"""
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify, g

import db
import notifications as notif_module
import school
from security import require_auth, new_id, audit
from validation import json_object, ValidationError, required_text

bp = Blueprint("billing", __name__)

TRIAL_DAYS = 30
PERIOD_DAYS = 30
INVOICE_DUE_DAYS = 7
WRITE_ALLOWLIST_PREFIXES = ("/api/subscription", "/api/auth/", "/api/me", "/api/notifications", "/api/platform", "/api/ai/")


def _ts(dt):
    return str(dt.timestamp())


def _dt(ts):
    return datetime.fromtimestamp(float(ts))


def is_platform_admin(conn, user_id):
    return bool(conn.execute("SELECT 1 FROM platform_admins WHERE user_id=?", (user_id,)).fetchone())


def active_students(conn, tenant_id):
    return conn.execute("SELECT COUNT(*) n FROM students WHERE tenant_id=? AND status='active'", (tenant_id,)).fetchone()["n"]


def plan_for(conn, students):
    rows = conn.execute("SELECT * FROM plans WHERE active=1 ORDER BY sort").fetchall()
    for p in rows:
        if students >= p["min_students"] and (p["max_students"] is None or students <= p["max_students"]):
            return dict(p)
    return dict(rows[-1]) if rows else None


def amount_for(plan, students):
    if plan is None:
        return 0.0
    return round(float(plan["base_price"]) + float(plan["per_student"]) * students, 2)


def ensure_subscription(conn, tenant_id):
    row = conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()
    if row:
        return row
    tenant = conn.execute("SELECT created_at FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    created = _dt(tenant["created_at"]) if tenant else datetime.now()
    plan = plan_for(conn, active_students(conn, tenant_id))
    now = str(time.time())
    conn.execute("INSERT INTO subscriptions (tenant_id, plan_code, status, trial_ends_at, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                 (tenant_id, plan["code"] if plan else "essentiel", "trial", _ts(created + timedelta(days=TRIAL_DAYS)), now, now))
    conn.commit()
    return conn.execute("SELECT * FROM subscriptions WHERE tenant_id=?", (tenant_id,)).fetchone()


def _next_invoice_number(conn):
    year = date.today().year
    prefix = f"INV-{year}-"
    row = conn.execute("SELECT number FROM invoices WHERE number LIKE ? ORDER BY number DESC LIMIT 1", (prefix + "%",)).fetchone()
    seq = int(row["number"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:04d}"


def issue_invoice(conn, tenant_id, period_start):
    students = active_students(conn, tenant_id)
    plan = plan_for(conn, students)
    period_end = period_start + timedelta(days=PERIOD_DAYS)
    amount = amount_for(plan, students)
    iid = new_id()
    conn.execute(
        """INSERT INTO invoices (id, tenant_id, number, plan_code, period_start, period_end, students, amount, currency, status, due_at, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,'open',?,?)""",
        (iid, tenant_id, _next_invoice_number(conn), plan["code"] if plan else "essentiel", period_start.date().isoformat(), period_end.date().isoformat(),
         students, amount, plan["currency"] if plan else "USD", _ts(period_start + timedelta(days=INVOICE_DUE_DAYS)), str(time.time())))
    conn.execute("UPDATE subscriptions SET plan_code=?, current_period_start=?, current_period_end=?, updated_at=? WHERE tenant_id=?",
                 (plan["code"] if plan else "essentiel", _ts(period_start), _ts(period_end), str(time.time()), tenant_id))
    conn.commit()
    inv = dict(conn.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone())
    notif_module.on_subscription_notice(conn, tenant_id, f"Facture {inv['number']} — abonnement Klassio",
                                        f"{amount:.2f} {inv['currency']} pour {students} élèves actifs (palier {plan['name'] if plan else '—'}), à régler avant le {_dt(inv['due_at']).date().isoformat()}.")
    return inv


def compute_state(conn, tenant_id):
    """État courant (met à jour le statut selon les dates — sans effet de
    bord destructif). Appelé par /api/subscription et /api/me."""
    sub = ensure_subscription(conn, tenant_id)
    now = datetime.now()
    status = sub["status"]
    if status == "cancelled":
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
                issue_invoice(conn, tenant_id, _dt(sub["current_period_end"]))
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
    plan = plan_for(conn, students)
    now = datetime.now()
    days_left = None
    attention = None
    if sub["status"] == "trial":
        days_left = max(0, (_dt(sub["trial_ends_at"]) - now).days)
        if days_left <= 5:
            attention = f"Votre période d'essai se termine dans {days_left} jour(s)."
    elif sub["status"] == "past_due":
        attention = "Une facture est en retard — réglez-la pour éviter le passage en lecture seule."
    elif sub["status"] == "suspended":
        attention = "Espace en lecture seule : facture impayée. Vos données sont intactes."
    open_inv = conn.execute("SELECT * FROM invoices WHERE tenant_id=? AND status IN ('open','pending') ORDER BY due_at LIMIT 1", (tenant_id,)).fetchone()
    if open_inv is not None and open_inv["status"] == "open" and attention is None:
        # Une facture non réglée est la seule chose que la Direction ait à faire
        # ici : c'est ce qui justifie de l'amener sur l'écran d'abonnement.
        attention = (f"Facture {open_inv['number']} de {open_inv['amount']:.2f} {open_inv['currency']} "
                     f"à régler avant le {_dt(open_inv['due_at']).date().isoformat()}.")
    return {
        "status": sub["status"], "plan": plan, "students": students, "estimated_amount": amount_for(plan, students),
        "trial_ends_at": sub["trial_ends_at"], "days_left": days_left, "current_period_end": sub["current_period_end"], "grace_days": sub["grace_days"],
        "attention": attention, "read_only": sub["status"] == "suspended",
        "open_invoice": dict(open_inv) if open_inv else None,
    }


def write_blocked(conn, ctx, path, method):
    """Espace suspendu : lecture libre, écriture bloquée sauf abonnement/session."""
    if method in ("GET", "OPTIONS", "HEAD"):
        return False
    if any(path.startswith(p) for p in WRITE_ALLOWLIST_PREFIXES):
        return False
    sub = conn.execute("SELECT status FROM subscriptions WHERE tenant_id=?", (ctx["tenant_id"],)).fetchone()
    return bool(sub and sub["status"] == "suspended")


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
    conn.commit()
    conn.close()
    audit(g.ctx["tenant_id"], g.ctx["user_id"], "billing.payment_declared", "invoice", inv["id"], "success", after={"method": method})
    return jsonify({"ok": True, "status": "pending", "message": "Paiement déclaré — il sera confirmé par Klassio après vérification."})


# ===========================================================================
# ADMINISTRATION DE LA PLATEFORME (rôle global)
# ===========================================================================

def _admin_only():
    conn = db.get_connection()
    ok = is_platform_admin(conn, g.ctx["user_id"])
    conn.close()
    if not ok:
        audit(g.ctx["tenant_id"], g.ctx["user_id"], "platform.denied", status="denied")
        return jsonify({"error": "Réservé à l'administration de la plateforme."}), 403
    return None


@bp.get("/api/platform/overview")
@require_auth
def platform_overview():
    denied = _admin_only()
    if denied:
        return denied
    conn = db.get_connection()
    tenants = []
    mrr = 0.0
    for t in conn.execute("SELECT * FROM tenants ORDER BY created_at DESC"):
        s = summary(conn, t["id"])
        director = conn.execute("SELECT u.name, u.email, u.phone FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? AND m.role='directeur' ORDER BY m.created_at LIMIT 1", (t["id"],)).fetchone()
        if s["status"] in ("active", "past_due"):
            mrr += s["estimated_amount"]
        tenants.append({"id": t["id"], "name": t["name"], "slug": t["slug"], "created_at": t["created_at"], "status": s["status"], "students": s["students"],
                        "plan": s["plan"]["name"] if s["plan"] else None, "amount": s["estimated_amount"], "days_left": s["days_left"],
                        "open_invoice": s["open_invoice"], "director": dict(director) if director else None})
    pending = [dict(r) for r in conn.execute("SELECT i.*, t.name AS tenant_name FROM invoices i JOIN tenants t ON t.id=i.tenant_id WHERE i.status='pending' ORDER BY i.created_at")]
    plans = [dict(r) for r in conn.execute("SELECT * FROM plans ORDER BY sort")]
    conn.close()
    return jsonify({"tenants": tenants, "mrr": round(mrr, 2), "pending_invoices": pending, "plans": plans,
                    "counts": {"total": len(tenants), "trial": sum(1 for x in tenants if x["status"] == "trial"), "active": sum(1 for x in tenants if x["status"] == "active"),
                               "past_due": sum(1 for x in tenants if x["status"] == "past_due"), "suspended": sum(1 for x in tenants if x["status"] == "suspended")}})


@bp.post("/api/platform/invoices/<invoice_id>/confirm")
@require_auth
def confirm_invoice(invoice_id):
    denied = _admin_only()
    if denied:
        return denied
    conn = db.get_connection()
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv or inv["status"] == "paid":
        conn.close()
        return jsonify({"error": "Facture introuvable ou déjà payée."}), 404
    now = str(time.time())
    conn.execute("UPDATE invoices SET status='paid', paid_at=? WHERE id=?", (now, invoice_id))
    conn.execute("UPDATE subscriptions SET status='active', updated_at=? WHERE tenant_id=?", (now, inv["tenant_id"]))
    conn.commit()
    notif_module.on_subscription_notice(conn, inv["tenant_id"], f"Paiement confirmé — {inv['number']}", "Merci. Votre abonnement Klassio est à jour.", priority="NORMAL")
    conn.close()
    audit(inv["tenant_id"], g.ctx["user_id"], "billing.invoice_confirmed", "invoice", invoice_id, "success")
    return jsonify({"ok": True})


@bp.post("/api/platform/invoices/<invoice_id>/void")
@require_auth
def void_invoice(invoice_id):
    denied = _admin_only()
    if denied:
        return denied
    conn = db.get_connection()
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        conn.close()
        return jsonify({"error": "Facture introuvable."}), 404
    conn.execute("UPDATE invoices SET status='void' WHERE id=?", (invoice_id,))
    conn.commit()
    compute_state(conn, inv["tenant_id"])
    conn.close()
    audit(inv["tenant_id"], g.ctx["user_id"], "billing.invoice_voided", "invoice", invoice_id, "success")
    return jsonify({"ok": True})


@bp.put("/api/platform/tenants/<tenant_id>")
@require_auth
def update_tenant_subscription(tenant_id):
    denied = _admin_only()
    if denied:
        return denied
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
    if "status" in data and data["status"] in ("active", "suspended", "cancelled", "trial"):
        fields.append("status=?"); params.append(data["status"])
    if not fields:
        conn.close()
        return jsonify({"error": "Aucune modification."}), 400
    fields.append("updated_at=?"); params.append(str(time.time()))
    conn.execute(f"UPDATE subscriptions SET {', '.join(fields)} WHERE tenant_id=?", params + [tenant_id])
    conn.commit()
    conn.close()
    audit(tenant_id, g.ctx["user_id"], "billing.subscription_updated", "tenant", tenant_id, "success", after=data)
    return jsonify({"ok": True})


@bp.put("/api/platform/plans/<code>")
@require_auth
def update_plan(code):
    denied = _admin_only()
    if denied:
        return denied
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
    audit(None, g.ctx["user_id"], "billing.plan_updated", "plan", code, "success", after=data)
    return jsonify({"ok": True})
