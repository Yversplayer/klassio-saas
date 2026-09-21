"""KLASSIO — la couche Livraison : ce qui est réellement parti, et ce qui a échoué.

    events  →  notifications  →  DELIVERIES  →  fournisseur  →  appareil

Les trois premières existaient depuis longtemps ; celle-ci manquait. Jusqu'au
21/09, `notifications.py` se terminait sur un INSERT : le produit savait qu'un
parent DEVAIT être informé, jamais si le message lui était parvenu.

CE QUE CE MODULE GARANTIT

1. AUCUN FAUX SUCCÈS. Un statut ne passe à ACCEPTED que si le fournisseur a
   répondu favorablement. S'il refuse, la ligne est FAILED avec son code et son
   message — et l'écran affiche l'échec, pas « envoyé ».

2. ACCEPTED ≠ DELIVERED. « Le fournisseur a pris la demande » n'est pas « le
   parent a reçu ». DELIVERED n'est écrit que sur confirmation réelle du
   fournisseur (webhook). Sans cette confirmation, on reste à ACCEPTED plutôt
   que d'inventer une certitude qu'on n'a pas.

3. UN ÉVÉNEMENT, UN MESSAGE. `idempotency_key` est contrainte UNIQUE par
   établissement, comme les paiements. Double clic, rafraîchissement, rejeu :
   on retombe sur la même ligne au lieu d'écrire une seconde fois à quelqu'un.

4. LE RETRY NE S'INVENTE PAS. Seule une erreur déclarée temporaire par le
   fournisseur (429, 5xx, réseau) peut être rejouée, et le nombre d'essais est
   plafonné. Une adresse invalide ne sera jamais valide au troisième essai.

Il n'y a pas de file d'attente dans Klassio — vérifié à l'audit : ni Celery, ni
RQ, ni scheduler. Le retry est donc DÉCLENCHÉ, pas asynchrone. C'est un choix
assumé : monter une infrastructure distribuée pour quelques centaines de
messages par an coûterait plus cher à exploiter que le problème qu'elle résout.
"""
import time

import db
import mailer
from security import new_id, audit

MAX_TENTATIVES = 3

CREATED, SENDING, ACCEPTED, DELIVERED = "CREATED", "SENDING", "ACCEPTED", "DELIVERED"
FAILED, BOUNCED, CANCELLED = "FAILED", "BOUNCED", "CANCELLED"

CANAL_EMAIL = "EMAIL"
CANAL_WHATSAPP = "WHATSAPP_LINK"


def _maintenant():
    return str(time.time())


def trouver_par_cle(conn, tenant_id, cle):
    if not cle:
        return None
    row = conn.execute(
        "SELECT * FROM deliveries WHERE tenant_id=? AND idempotency_key=?",
        (tenant_id, cle)).fetchone()
    return dict(row) if row else None


def creer(conn, tenant_id, *, canal, gabarit, adresse, sujet=None,
          notification_id=None, recipient_user_id=None, cle_idempotence=None):
    """Enregistre l'INTENTION d'acheminer, avant toute tentative.

    L'ordre compte : la ligne existe avant l'appel au fournisseur. Si le
    processus meurt pendant l'envoi, il reste une trace en SENDING — une
    incertitude visible, qu'on peut examiner. L'inverse (envoyer puis
    enregistrer) perdrait le message sans laisser d'indice.
    """
    existante = trouver_par_cle(conn, tenant_id, cle_idempotence)
    if existante:
        return existante, False
    ligne = {
        "id": new_id(), "tenant_id": tenant_id, "notification_id": notification_id,
        "channel": canal, "template": gabarit, "recipient_user_id": recipient_user_id,
        "recipient_address": adresse, "subject": sujet, "status": CREATED,
        "provider": None, "provider_message_id": None, "error_code": None,
        "error_message": None, "attempts": 0, "idempotency_key": cle_idempotence,
        "created_at": _maintenant(), "updated_at": None, "sent_at": None, "failed_at": None,
    }
    conn.execute(
        """INSERT INTO deliveries (id, tenant_id, notification_id, channel, template,
               recipient_user_id, recipient_address, subject, status, attempts,
               idempotency_key, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ligne["id"], tenant_id, notification_id, canal, gabarit, recipient_user_id,
         adresse, sujet, CREATED, 0, cle_idempotence, ligne["created_at"]))
    conn.commit()
    return ligne, True


def _consigner(conn, livraison_id, **champs):
    champs["updated_at"] = _maintenant()
    colonnes = ", ".join(f"{k}=?" for k in champs)
    conn.execute(f"UPDATE deliveries SET {colonnes} WHERE id=?",
                 tuple(champs.values()) + (livraison_id,))
    conn.commit()


def envoyer_email(conn, tenant_id, livraison, sujet, html, texte, actor_id=None):
    """Tente l'envoi et consigne le résultat RÉEL.

    Retourne la livraison à jour. Ne lève pas : un échec d'acheminement est une
    information à afficher, pas une exception qui ferait échouer l'action
    métier qui l'a déclenchée. Créer une invitation doit réussir même si
    l'e-mail ne part pas — le lien reste copiable à la main.
    """
    # DÉJÀ ACHEMINÉ : ON NE RENVOIE PAS.
    #
    # Retomber sur la même ligne ne suffit pas : sans cette garde, le second
    # clic réutilisait la livraison ET rappelait le fournisseur — le
    # destinataire recevait deux fois le même message. Vérifié le 21/09 sur le
    # serveur réel : `attempts` passait à 2 après un double clic. L'idempotence
    # doit porter sur L'ENVOI, pas seulement sur l'enregistrement.
    if livraison.get("status") in (ACCEPTED, DELIVERED):
        return relire(conn, livraison["id"]) or livraison

    lid = livraison["id"]
    essais = (livraison.get("attempts") or 0) + 1
    _consigner(conn, lid, status=SENDING, attempts=essais, subject=sujet)
    try:
        identifiant, fournisseur = mailer.envoyer(livraison["recipient_address"], sujet, html, texte)
    except mailer.EmailError as e:
        definitif = (not e.retryable) or essais >= MAX_TENTATIVES
        _consigner(conn, lid,
                   status=BOUNCED if e.code == "invalid_address" else FAILED,
                   error_code=e.code, error_message=str(e)[:500],
                   failed_at=_maintenant(), provider=mailer.PROVIDER)
        if actor_id:
            audit(tenant_id, actor_id, "delivery.failed", "delivery", lid, "error",
                  after={"code": e.code, "attempts": essais, "retryable": bool(e.retryable and not definitif)})
        return relire(conn, lid)

    # ACCEPTED, pas SENT ni DELIVERED : le fournisseur a pris la demande. Ce
    # qu'il en fera ensuite ne nous est pas encore connu.
    _consigner(conn, lid, status=ACCEPTED, provider=fournisseur,
               provider_message_id=identifiant or None, sent_at=_maintenant(),
               error_code=None, error_message=None)
    if actor_id:
        audit(tenant_id, actor_id, "delivery.accepted", "delivery", lid, "success",
              after={"channel": livraison["channel"], "template": livraison["template"]})
    return relire(conn, lid)


def relire(conn, livraison_id):
    row = conn.execute("SELECT * FROM deliveries WHERE id=?", (livraison_id,)).fetchone()
    return dict(row) if row else None


def rejouable(livraison):
    """Un nouvel essai a-t-il une chance d'aboutir ?

    Non si l'adresse est invalide (BOUNCED), non si la configuration manque,
    non si le plafond d'essais est atteint. Réessayer dans ces cas-là, c'est
    occuper le serveur à répéter une erreur.
    """
    if not livraison or livraison["status"] != FAILED:
        return False
    if (livraison.get("attempts") or 0) >= MAX_TENTATIVES:
        return False
    return (livraison.get("error_code") or "").startswith(("http_5", "http_429", "network", "simulated"))


def lister(conn, tenant_id, limite=50, statut=None):
    extra, params = "", [tenant_id]
    if statut:
        extra, params = " AND status=?", [tenant_id, statut]
    rows = conn.execute(
        f"""SELECT id, channel, template, recipient_address, subject, status, provider,
                   error_code, attempts, created_at, sent_at, failed_at
            FROM deliveries WHERE tenant_id=?{extra}
            ORDER BY created_at DESC LIMIT ?""", tuple(params) + (limite,)).fetchall()
    return [dict(r) for r in rows]
