"""KLASSIO backend — Financial Core.

Règle non négociable (docs/FINANCE.md, rappelée dans le recadrage stratégique) :
un solde n'est JAMAIS stocké comme chiffre brut. Il est TOUJOURS recalculé à partir
des obligations et des paiements CONFIRMÉS. Cette fonction est la seule source de
vérité financière du système — le dashboard, la recherche et l'IA future doivent
tous, in fine, passer par elle plutôt que de recalculer un solde eux-mêmes.
"""
import time
import json
import db
from security import new_id, audit
import events as events_module
import notifications as notif_module
from validation import positive_amount, valid_payment_method, ValidationError


def financial_summary(conn, tenant_id: str, student_id: str) -> dict:
    """Reconstruit la situation financière complète d'un élève — jamais un chiffre seul.

    Reflète exactement l'exemple de docs/FINANCE.md §6 / du recadrage stratégique §4 :
    chaque obligation, ses paiements, et le solde qui EN DÉCOULE.
    """
    obligations = conn.execute(
        """SELECT o.*, COALESCE(o.label, c.name) as item_name, c.category AS category FROM obligations o
           JOIN catalog_items c ON c.id = o.catalog_item_id
           WHERE o.tenant_id = ? AND o.student_id = ?
           ORDER BY o.created_at""",
        (tenant_id, student_id),
    ).fetchall()

    lines = []
    total_due = 0.0
    total_paid = 0.0
    for o in obligations:
        payments = conn.execute(
            """SELECT * FROM payments
               WHERE tenant_id = ? AND obligation_id = ? AND status = 'CONFIRMED'
               ORDER BY confirmed_at""",
            (tenant_id, o["id"]),
        ).fetchall()
        paid = sum(p["amount"] for p in payments)
        remaining = round(o["amount"] - paid, 2)
        status = "PAID" if remaining <= 0 else ("PARTIALLY_PAID" if paid > 0 else "ISSUED")
        total_due += o["amount"]
        total_paid += paid
        pending = conn.execute(
            """SELECT id, amount, method, status, created_at FROM payments
               WHERE tenant_id = ? AND obligation_id = ? AND status IN ('CREATED','PENDING','PROCESSING')
               ORDER BY created_at""",
            (tenant_id, o["id"]),
        ).fetchall()
        lines.append({
            "obligation_id": o["id"],
            # La clé du frais, pas seulement son libellé : plusieurs obligations
            # portant le même `catalog_item_id` pour un élève SONT les tranches
            # d'un même frais. C'est ainsi que l'échéancier se reconstitue, sans
            # table `installments` parallèle au Financial Core.
            "catalog_item_id": o["catalog_item_id"],
            "label": o["item_name"],
            "category": o["category"],
            "amount": o["amount"],
            "currency": o["currency"],
            "due_date": o["due_date"],
            "paid": round(paid, 2),
            "remaining": remaining,
            "status": status,
            "payments": [
                {"id": p["id"], "amount": p["amount"], "method": p["method"],
                 "confirmed_at": p["confirmed_at"], "provider_reference": p["provider_reference"],
                 "receipt_number": _receipt_number(conn, tenant_id, p["id"])}
                for p in payments
            ],
            "pending_payments": [dict(p) for p in pending],
        })

    currency = lines[0]["currency"] if lines else None
    return {
        "student_id": student_id,
        "obligations": lines,
        "currency": currency,
        "total_due": round(total_due, 2),
        "total_paid": round(total_paid, 2),
        "balance": round(total_due - total_paid, 2),
    }


def _receipt_number(conn, tenant_id, payment_id):
    # tenant_id : colonne de tête de l'index, et cohérence avec le reste du
    # module — aucune lecture financière ne traverse un établissement.
    row = conn.execute("SELECT number FROM receipts WHERE tenant_id = ? AND payment_id = ?",
                       (tenant_id, payment_id)).fetchone()
    return row["number"] if row else None


def next_receipt_number(conn, tenant_id):
    """REC-AAAA-NNNNN, séquence par établissement et par année civile."""
    from datetime import date
    year = date.today().year
    prefix = f"REC-{year}-"
    row = conn.execute("SELECT number FROM receipts WHERE tenant_id=? AND number LIKE ? ORDER BY number DESC LIMIT 1",
                       (tenant_id, prefix + "%")).fetchone()
    seq = int(row["number"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:05d}"


def issue_receipt(conn, tenant_id, payment, obligation, student):
    """Un reçu par paiement CONFIRMÉ — jamais avant, jamais deux fois
    (UNIQUE(payment_id)). Retourne la ligne créée ou existante."""
    existing = conn.execute("SELECT * FROM receipts WHERE tenant_id=? AND payment_id=?",
                            (tenant_id, payment["id"])).fetchone()
    if existing:
        return dict(existing)
    label_row = conn.execute("SELECT COALESCE(o.label, c.name) AS label FROM obligations o JOIN catalog_items c ON c.id=o.catalog_item_id WHERE o.id=?",
                             (obligation["id"],)).fetchone()
    # 25 essais, pas 5.
    #
    # Trouvé par la campagne k6 du 17/09 : sous 8 guichets simultanés, sur
    # 1 067 paiements, UN a épuisé les cinq essais. `next_receipt_number` est un
    # « max + 1 » : entre le SELECT et le COMMIT, un autre encaissement peut
    # prendre le même numéro. Cinq pertes consécutives arrivent donc pour de
    # vrai. Le paiement était déjà CONFIRMÉ et inscrit au grand livre (l'argent
    # était juste), mais la requête finissait en 500 : le guichetier lisait
    # « échec » sur un paiement réussi, et le reçu manquait.
    #
    # C'est la cause de l'anomalie historique « paiements confirmés sans reçu »
    # notée dans REPRISE. L'outil `backend/tools/reparer_recus.py` la répare
    # après coup ; mieux vaut ne plus la produire.
    for _ in range(25):
        number = next_receipt_number(conn, tenant_id)
        try:
            rid = new_id()
            conn.execute(
                """INSERT INTO receipts (id, tenant_id, number, payment_id, student_id, amount, currency, method, label, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (rid, tenant_id, number, payment["id"], student["id"], payment["amount"], payment["currency"],
                 payment["method"], label_row["label"] if label_row else "Paiement", str(time.time())),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone())
        except db.integrity_errors():
            # SEULE une collision de numéro justifie un nouvel essai : la
            # séquence REC-AAAA-NNNNN est calculée par « max + 1 », donc deux
            # encaissements simultanés peuvent viser le même numéro.
            #
            # `except Exception` avalait auparavant n'importe quelle erreur —
            # une faute de frappe dans une colonne, une panne de connexion —
            # la rejouait cinq fois, puis la remplaçait par un RuntimeError
            # sans cause. Le vrai défaut était invisible dans les logs.
            conn.rollback()
    # Épuisement : on NE transforme PAS un paiement réussi en erreur.
    #
    # À ce point, le paiement est confirmé et l'écriture comptable est passée.
    # Lever ici renvoyait un 500 au guichet, qui recommençait — alors que
    # l'argent était bien encaissé. Un faux échec sur un encaissement réel est
    # plus grave qu'un reçu à rééditer : il pousse à encaisser deux fois.
    #
    # On renvoie donc None, on le journalise bruyamment, et le reçu se rattrape
    # avec `backend/tools/reparer_recus.py --appliquer`.
    print(f"[RECU] ÉCHEC d'émission après 25 essais — paiement {payment['id']} "
          f"(tenant {tenant_id}) est CONFIRMÉ mais sans reçu. "
          f"Rattraper avec backend/tools/reparer_recus.py --appliquer", flush=True)
    return None


def _sync_order_after_payment(conn, tenant_id, obligation, student, actor_id):
    """Une obligation liée à une commande boutique passe la commande en
    'paid' dès qu'elle est soldée — même Financial Core, pas un second système."""
    order = conn.execute("SELECT * FROM orders WHERE tenant_id=? AND obligation_id=?", (tenant_id, obligation["id"])).fetchone()
    if not order or order["status"] != "pending":
        return
    summary = financial_summary(conn, tenant_id, student["id"])
    line = next((l for l in summary["obligations"] if l["obligation_id"] == obligation["id"]), None)
    if line and line["remaining"] <= 0:
        conn.execute("UPDATE orders SET status='paid', updated_at=? WHERE id=?", (str(time.time()), order["id"]))
        conn.commit()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
        notif_module.on_order_status(conn, tenant_id, dict(order), student)


def create_payment(conn, tenant_id, obligation_id, amount, method, idempotency_key, created_by,
                   allow_overpayment=False):
    """Crée une tentative de paiement. Idempotent : une même clé renvoie le paiement existant,
    jamais une seconde écriture (docs/FINANCE.md §9.3, docs/SECURITE.md invariant idempotence).

    Validation ajoutée après pentest : amount=-500 était accepté et confirmé (solde
    négatif fabriqué), amount="abc" était stocké tel quel et corrompait les SUM() SQL.
    """
    amount = positive_amount(amount, "amount")
    method = valid_payment_method(method)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValidationError("idempotency_key est requis.")

    existing = conn.execute(
        "SELECT * FROM payments WHERE tenant_id = ? AND idempotency_key = ?",
        (tenant_id, idempotency_key),
    ).fetchone()
    if existing:
        # Une clé d'idempotence identifie UN paiement. La réutiliser avec un
        # autre montant, une autre méthode ou une autre obligation n'est pas
        # un rejeu : c'est un conflit. Sans ce contrôle, POST /payments
        # auto-confirmait un Mobile Money encore CREATED dès qu'un second
        # appel renvoyait method=cash avec la même clé.
        same_payload = (
            existing["obligation_id"] == obligation_id
            and existing["method"] == method
            and float(existing["amount"]) == float(amount)
        )
        if not same_payload:
            raise ValidationError(
                "Cette clé d'idempotence a déjà été utilisée pour un autre paiement."
            )
        return dict(existing), False

    obligation = conn.execute(
        "SELECT * FROM obligations WHERE tenant_id = ? AND id = ?", (tenant_id, obligation_id)
    ).fetchone()
    if not obligation:
        raise ValueError("Obligation introuvable pour ce tenant")

    # Le MONTANT se valide ici, contre la dette réelle — jamais côté navigateur.
    #
    # Trouvé à l'audit du 17/09 : le formulaire portait un `max` HTML, et rien
    # d'autre. Un parent modifiant le JSON envoyait 999 999 $ sur une obligation
    # qui en devait 90 ; le serveur l'acceptait (201). Mesuré ensuite sur une
    # copie de base : dès que la Direction confirmait la demande — un clic, sans
    # que le montant lui soit opposé — le solde passait de 90 à **-999 909**, un
    # REÇU OFFICIEL de 999 999 $ était émis et le grand livre enregistrait la
    # somme. Un document faux et une comptabilité fausse, à partir d'un champ de
    # formulaire.
    #
    # On compare au reste dû, pas au montant de l'obligation : un paiement
    # partiel reste parfaitement légitime, et deux paiements partiels ne doivent
    # pas pouvoir dépasser ensemble ce qui est dû. Les paiements encore en
    # attente ne sont PAS déduits : tant qu'ils ne sont pas confirmés, ils ne
    # sont rien — les déduire laisserait une demande jamais confirmée bloquer
    # indéfiniment la possibilité de payer autrement.
    # `allow_overpayment` n'est PAS une porte dérobée : un seul appelant l'ouvre,
    # la reprise d'historique (`ingestion.confirm_import`). Une école qui migre
    # déclare son propre passé — « frais 250, déjà versé 400 » arrive, et c'est
    # sa comptabilité, pas une saisie à corriger. L'analyse d'import SIGNALE
    # déjà cette anomalie à la Direction avant toute écriture ; la refuser ici
    # ferait échouer la migration entière pour une ligne, et lui ferait perdre
    # l'information plutôt que de la lui montrer.
    #
    # Tout le reste — parent, caissier, Direction, API — passe par la règle
    # stricte ci-dessous.
    deja_paye = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS n FROM payments "
        "WHERE tenant_id = ? AND obligation_id = ? AND status = 'CONFIRMED'",
        (tenant_id, obligation_id),
    ).fetchone()["n"]
    reste = round(float(obligation["amount"]) - float(deja_paye), 2)
    if not allow_overpayment:
        if reste <= 0:
            raise ValidationError("Cette obligation est déjà entièrement payée.")
        # Tolérance d'un centime : les montants sont des flottants, et un parent
        # qui paie « tout le reste » ne doit pas être refusé pour un arrondi.
        if round(float(amount), 2) > reste + 0.01:
            raise ValidationError(
                f"Le montant dépasse ce qui reste dû sur cette obligation ({reste:g} {obligation['currency']})."
            )

    payment_id = new_id()
    now = str(time.time())
    conn.execute(
        """INSERT INTO payments
           (id, tenant_id, obligation_id, amount, currency, method, status, idempotency_key, created_by, created_at)
           VALUES (?,?,?,?,?,?, 'CREATED', ?, ?, ?)""",
        (payment_id, tenant_id, obligation_id, amount, obligation["currency"], method,
         idempotency_key, created_by, now),
    )
    conn.commit()
    audit(tenant_id, created_by, "payment.created", "payment", payment_id, "success",
          after={"amount": amount, "obligation_id": obligation_id})
    return {
        "id": payment_id, "tenant_id": tenant_id, "obligation_id": obligation_id,
        "amount": amount, "currency": obligation["currency"], "method": method,
        "status": "CREATED", "idempotency_key": idempotency_key,
    }, True


def _deja_confirme(conn, tenant_id, payment_id):
    """Réponse pour un paiement déjà confirmé — par un appel précédent ou par
    une requête concurrente qui a gagné la course. Aucune écriture.

    Le reçu peut ne pas encore exister si le gagnant est en train de l'émettre :
    on renvoie alors le paiement sans numéro de reçu plutôt que d'échouer. Le
    paiement, lui, est bien confirmé.
    """
    payment = conn.execute(
        "SELECT * FROM payments WHERE tenant_id = ? AND id = ?", (tenant_id, payment_id)
    ).fetchone()
    result = dict(payment)
    receipt = conn.execute(
        "SELECT id, number FROM receipts WHERE tenant_id = ? AND payment_id = ?",
        (tenant_id, payment_id),
    ).fetchone()
    if receipt:
        result["receipt_number"] = receipt["number"]
        result["receipt_id"] = receipt["id"]
    return result


def confirm_payment(conn, tenant_id, payment_id, provider_reference, actor_id,
                    allow_overpayment=False):
    """Confirme un paiement — jamais déclenché par une simple affirmation du frontend
    (ici simulé comme un webhook/action serveur explicite, cf. docs/FINANCE.md §9.4).
    Idempotent : confirmer un paiement déjà CONFIRMED ne le crédite pas deux fois.
    """
    payment = conn.execute(
        "SELECT * FROM payments WHERE tenant_id = ? AND id = ?", (tenant_id, payment_id)
    ).fetchone()
    if not payment:
        raise ValueError("Paiement introuvable pour ce tenant")

    if payment["status"] == "CONFIRMED":
        # Déjà confirmé — idempotence, pas de double crédit ni de second reçu.
        return _deja_confirme(conn, tenant_id, payment_id)

    # LE MONTANT SE REVALIDE ICI, SOUS VERROU. C'est le seul endroit qui compte.
    #
    # `create_payment` contrôle déjà qu'un paiement ne dépasse pas le reste dû.
    # Ce contrôle est utile — il refuse tout de suite une saisie aberrante — mais
    # il ne protège PAS de deux guichets simultanés : chacun lit le même « reste
    # dû » avant que l'autre n'ait confirmé, chacun se juge légitime.
    #
    # Mesuré le 18/09 (tools/k6/concurrence.js, six guichets soldant ensemble le
    # même frais) : une obligation de 350 $ avait encaissé 1 046 $, en sept
    # paiements tous CONFIRMED, tous avec un reçu officiel. Le grand livre était
    # faux, la famille avait un trop-perçu, et rien n'avait protesté.
    #
    # La confirmation est le moment où l'argent entre réellement au grand livre :
    # la règle doit donc être appliquée ICI, après avoir verrouillé l'obligation.
    # Le verrou fait attendre l'autre guichet ; quand il repart, il lit la somme
    # à jour et se voit refusé — un refus honnête vaut mieux qu'un trop-perçu.
    #
    # `allow_overpayment` ne s'ouvre que pour la reprise d'historique
    # (`ingestion.confirm_import`) : une école qui déclare « frais 250, déjà
    # versé 400 » décrit son propre passé, l'analyse d'import l'a déjà signalé à
    # la Direction, et refuser ferait échouer la migration entière pour une ligne.
    if not allow_overpayment:
        db.verrouiller_ligne(conn, "obligations", payment["obligation_id"])
        # SOUS LE VERROU, RELIRE LE PAIEMENT LUI-MÊME.
        #
        # La lecture du statut en tête de fonction date d'AVANT l'attente : si
        # le verrou nous a fait patienter, c'est peut-être parce qu'une autre
        # requête confirmait CE paiement-ci — double clic de la caissière, ou
        # webhook rejoué par l'opérateur Mobile Money.
        #
        # Sans cette relecture, son montant figure désormais dans la somme
        # confirmée : le reste dû tombe à zéro et l'on refuserait « ce frais est
        # déjà entièrement payé » — alors qu'il l'a été par nous-mêmes. C'est le
        # chemin IDEMPOTENT, pas un dépassement, et il doit répondre 200 avec le
        # même reçu. (Régression attrapée par test_audit_prerelease
        # DoubleConfirmationDePaiement, qui joue 20 tours de la course.)
        courant = conn.execute(
            "SELECT status FROM payments WHERE tenant_id = ? AND id = ?", (tenant_id, payment_id)
        ).fetchone()
        if courant is not None and courant["status"] == "CONFIRMED":
            conn.rollback()
            return _deja_confirme(conn, tenant_id, payment_id)
        ob = conn.execute(
            "SELECT amount, currency FROM obligations WHERE tenant_id = ? AND id = ?",
            (tenant_id, payment["obligation_id"]),
        ).fetchone()
        if ob is not None:
            deja_paye = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS n FROM payments "
                "WHERE tenant_id = ? AND obligation_id = ? AND status = 'CONFIRMED'",
                (tenant_id, payment["obligation_id"]),
            ).fetchone()["n"]
            reste = round(float(ob["amount"]) - float(deja_paye), 2)
            # Même tolérance d'un centime qu'à la création : les montants sont
            # des flottants, et solder « tout le reste » ne doit pas échouer
            # sur un arrondi.
            if round(float(payment["amount"]), 2) > reste + 0.01:
                conn.rollback()
                if reste <= 0:
                    raise ValidationError(
                        "Ce frais a été entièrement payé entre-temps : ce paiement ne peut pas être confirmé."
                    )
                raise ValidationError(
                    f"Ce paiement dépasse ce qui reste dû sur ce frais ({reste:g} {ob['currency']}) — "
                    "une autre confirmation est passée entre-temps."
                )

    now = str(time.time())
    # Transition ATOMIQUE. La lecture de `status` ci-dessus ne suffit pas : entre
    # elle et cette écriture, une seconde requête peut lire le même statut. Cela
    # arrive pour de vrai — double clic de la caissière, ou webhook rejoué par
    # l'opérateur Mobile Money, ce que tout fournisseur fait en cas de doute sur
    # la réception.
    #
    # Mesuré avant correctif, sur 40 doubles confirmations simultanées : 8 tours
    # produisaient DEUX écritures au grand livre et DEUX notifications au parent
    # pour un seul paiement. Le reçu, lui, était protégé par UNIQUE(payment_id),
    # et le solde restait juste (il se recalcule depuis `payments`) — mais le
    # journal comptable comptait l'argent deux fois et le parent était prévenu
    # deux fois.
    #
    # La condition porte donc sur l'UPDATE lui-même : un seul appelant peut
    # faire passer le paiement à CONFIRMED, les autres repartent sur le chemin
    # idempotent sans rien écrire.
    passage = conn.execute(
        "UPDATE payments SET status = 'CONFIRMED', provider_reference = ?, confirmed_at = ? "
        "WHERE id = ? AND status <> 'CONFIRMED'",
        (provider_reference, now, payment_id),
    )
    if not (passage.rowcount or 0):
        conn.rollback()
        return _deja_confirme(conn, tenant_id, payment_id)
    conn.execute(
        """INSERT INTO ledger_entries (id, tenant_id, entry_type, reference_type, reference_id, amount, currency, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (new_id(), tenant_id, "payment_confirmed", "payment", payment_id,
         payment["amount"], payment["currency"], now),
    )
    conn.commit()

    audit(tenant_id, actor_id, "payment.confirmed", "payment", payment_id, "success",
          before={"status": payment["status"]}, after={"status": "CONFIRMED"})

    obligation = conn.execute(
        "SELECT * FROM obligations WHERE id = ?", (payment["obligation_id"],)
    ).fetchone()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (obligation["student_id"],)).fetchone()

    receipt = issue_receipt(conn, tenant_id, dict(payment), obligation, student)

    event = events_module.emit(
        conn, tenant_id, "payment.confirmed", "payment", payment_id, actor_id,
        payload={"student_id": student["id"], "amount": payment["amount"], "currency": payment["currency"],
                 "method": payment["method"], "receipt_number": receipt["number"] if receipt else None},
    )
    notif_module.on_payment_confirmed(conn, tenant_id, student, payment, event, receipt=receipt)
    _sync_order_after_payment(conn, tenant_id, obligation, student, actor_id)

    payment = dict(conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone())
    # `receipt` peut être None : l'émission a épuisé ses essais. Le paiement
    # reste valide et confirmé — c'est le reçu qui manque, pas l'argent.
    payment["receipt_number"] = receipt["number"] if receipt else None
    payment["receipt_id"] = receipt["id"] if receipt else None
    return payment
