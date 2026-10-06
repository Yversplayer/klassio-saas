"""KLASSIO — l'administration de la plateforme : comptes, second facteur, sessions.

POURQUOI UN MODULE À PART. Jusqu'au 06/10/2026, l'accès « plateforme »
(confirmer les paiements de TOUTES les écoles, suspendre un établissement,
changer un palier) était un drapeau posé sur le compte d'un directeur d'école.
Trois conséquences :
  - une session de directeur volée ouvrait la facturation de tout le réseau ;
  - l'administrateur devait posséder une école (l'inscription lui demandait
    un nom d'établissement) ;
  - un mot de passe suffisait.
Désormais l'administration a ses propres comptes (table platform_accounts),
sa propre session (cookie klassio_admin, 30 min d'inactivité, 8 h au plus) et
un second facteur obligatoire : un code à 6 chiffres (TOTP, RFC 6238), affiché
par une application d'authentification sur le téléphone de l'administrateur.

CE QUI NE PROTÈGE RIEN, ET N'EST DONC PAS COMPTÉ COMME PROTECTION : la page
de connexion (app/admin.html) n'est liée nulle part. Toute la sécurité tient
même pour qui connaît l'adresse, les routes et ce fichier.

  1. Aucune route HTTP ne crée de compte : seul backend/tools/platform_admin.py,
     lancé sur une machine qui a déjà accès à la base, écrit platform_accounts.
  2. Mot de passe ET code : un message d'erreur unique, qui ne dit jamais lequel
     des deux était faux ni si l'adresse existe.
  3. Un code ne sert qu'une fois (totp_last_step) — un code intercepté et rejoué
     dans les 30 secondes est refusé.
  4. 5 échecs par compte, 10 par visiteur, sur 15 minutes : puis plus rien,
     même avec les bons identifiants.
  5. Une session d'école, même de directeur, ne vaut rien ici ; une session
     d'administration ne vaut rien sur les routes des écoles.
  6. Chaque connexion, réussie ou refusée, est journalisée (audit_logs).
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from functools import wraps

from flask import Blueprint, g, jsonify, request

import db
import security
from validation import json_object

bp = Blueprint("platform_auth", __name__)

ADMIN_COOKIE = "klassio_admin"
ADMIN_CSRF_COOKIE = "klassio_admin_csrf"
INACTIVITE_SECONDES = 30 * 60
DUREE_MAX_SECONDES = 8 * 60 * 60
ECHECS_PAR_COMPTE = 5
ECHECS_PAR_VISITEUR = 10
FENETRE_ECHECS = 15 * 60
MESSAGE_REFUS = "Identifiants ou code invalides."

# ---------------------------------------------------------------------------
# TOTP (RFC 6238) — sans dépendance : HMAC-SHA1, pas de 30 s, 6 chiffres.
# Compatible Google Authenticator, Authy, Microsoft Authenticator, 1Password.
# ---------------------------------------------------------------------------
PAS_TOTP = 30


def nouveau_secret_totp() -> str:
    """160 bits aléatoires, en base32 (ce que les applications attendent)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _cle(secret: str) -> bytes:
    s = secret.upper().replace(" ", "")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_totp(secret: str, pas: int, chiffres: int = 6) -> str:
    empreinte = hmac.new(_cle(secret), struct.pack(">Q", pas), hashlib.sha1).digest()
    decalage = empreinte[-1] & 0x0F
    valeur = struct.unpack(">I", empreinte[decalage:decalage + 4])[0] & 0x7FFFFFFF
    return str(valeur % (10 ** chiffres)).zfill(chiffres)


def pas_courant(instant=None) -> int:
    return int((time.time() if instant is None else instant) // PAS_TOTP)


def verifier_totp(secret: str, code: str, dernier_pas: int, instant=None):
    """Le pas accepté, ou None. Tolère un pas d'écart (horloge du téléphone en
    avance ou en retard de 30 s) ; refuse tout pas déjà consommé (rejeu)."""
    code = (code or "").replace(" ", "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    pas = pas_courant(instant)
    for ecart in (0, -1, 1):
        candidat = pas + ecart
        if candidat <= int(dernier_pas or 0):
            continue
        if hmac.compare_digest(code_totp(secret, candidat), code):
            return candidat
    return None


def uri_otpauth(email: str, secret: str) -> str:
    from urllib.parse import quote
    return (f"otpauth://totp/Klassio:{quote(email)}?secret={secret}"
            f"&issuer=Klassio&algorithm=SHA1&digits=6&period={PAS_TOTP}")


# ---------------------------------------------------------------------------
# Sessions d'administration
# ---------------------------------------------------------------------------
def _empreinte(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_admin(token: str) -> str:
    # Préfixe propre : le jeton CSRF d'une session d'école ne vaut rien ici.
    return hashlib.sha256(("klassio-admin-csrf:" + token).encode()).hexdigest()


def ouvrir_session(conn, account_id: str) -> str:
    token = secrets.token_urlsafe(32)
    maintenant = time.time()
    conn.execute(
        "INSERT INTO platform_sessions (token, account_id, created_at, last_seen_at, expires_at) VALUES (?,?,?,?,?)",
        (_empreinte(token), account_id, str(maintenant), str(maintenant), str(maintenant + DUREE_MAX_SECONDES)))
    conn.commit()
    return token


def resoudre_session(conn, token: str):
    """Le compte de la session, ou None. Une session expirée (inactivité ou
    durée maximale) ou d'un compte désactivé est détruite sur-le-champ."""
    if not token:
        return None
    row = conn.execute("SELECT * FROM platform_sessions WHERE token=?", (_empreinte(token),)).fetchone()
    if not row:
        return None
    maintenant = time.time()
    compte = conn.execute("SELECT * FROM platform_accounts WHERE id=?", (row["account_id"],)).fetchone()
    expiree = (float(row["expires_at"]) < maintenant
               or float(row["last_seen_at"]) + INACTIVITE_SECONDES < maintenant)
    if expiree or not compte or compte["status"] != "active":
        conn.execute("DELETE FROM platform_sessions WHERE token=?", (_empreinte(token),))
        conn.commit()
        return None
    conn.execute("UPDATE platform_sessions SET last_seen_at=? WHERE token=?", (str(maintenant), _empreinte(token)))
    conn.commit()
    return {"account_id": compte["id"], "email": compte["email"], "name": compte["name"]}


def revoquer_sessions(conn, account_id: str):
    conn.execute("DELETE FROM platform_sessions WHERE account_id=?", (account_id,))


def _poser_cookies(resp, token):
    secure = security._en_https()
    resp.set_cookie(ADMIN_COOKIE, token, max_age=DUREE_MAX_SECONDES, path="/",
                    secure=secure, httponly=True, samesite="Strict")
    resp.set_cookie(ADMIN_CSRF_COOKIE, csrf_admin(token), max_age=DUREE_MAX_SECONDES, path="/",
                    secure=secure, httponly=False, samesite="Strict")
    return resp


def _effacer_cookies(resp):
    secure = security._en_https()
    resp.delete_cookie(ADMIN_COOKIE, path="/", secure=secure, httponly=True, samesite="Strict")
    resp.delete_cookie(ADMIN_CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="Strict")
    return resp


def acteur():
    """Identifiant d'auteur pour audit_logs : préfixé, pour qu'une action de
    la plateforme ne soit jamais confondue avec celle d'un utilisateur d'école."""
    return "plateforme:" + g.platform["account_id"]


def require_platform_admin(fn):
    """Seule porte des routes /api/platform/*. Ne regarde QUE le cookie
    d'administration : un « Authorization: Bearer » ou une session d'école,
    même de directeur, reçoivent 403."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.cookies.get(ADMIN_COOKIE, "")
        conn = db.get_connection()
        try:
            compte = resoudre_session(conn, token)
        finally:
            conn.close()
        if not compte:
            security.audit(None, None, "platform.denied", "request", request.path, "denied")
            resp = jsonify({"error": "Réservé à l'administration de la plateforme."})
            resp.status_code = 403
            return _effacer_cookies(resp) if token else resp
        if request.method in security.METHODES_MUTANTES:
            recu = request.headers.get(security.CSRF_HEADER, "")
            if not recu or not hmac.compare_digest(recu.encode(), csrf_admin(token).encode()):
                security.audit(None, "plateforme:" + compte["account_id"], "platform.csrf_refused",
                               "request", request.path, "denied")
                return jsonify({"error": "Requête refusée : jeton de sécurité absent ou invalide. "
                                         "Rechargez la page."}), 403
        g.platform = compte
        return fn(*args, **kwargs)
    return wrapper


# Le temps de vérification d'un mot de passe ne doit pas révéler si l'adresse
# existe : une adresse inconnue est comparée à une empreinte factice, au même coût.
_EMPREINTE_FACTICE = security.hash_password(secrets.token_urlsafe(16))


@bp.post("/api/admin/login")
def connexion():
    data = json_object(request.get_json(force=True))
    email = (data.get("email") or "").strip().lower()[:200]
    mot_de_passe = data.get("password") or ""
    code = str(data.get("code") or "")
    ip = security.client_ip()

    for seau, cle, plafond in (("admin_login_compte", email, ECHECS_PAR_COMPTE),
                               ("admin_login_visiteur", ip, ECHECS_PAR_VISITEUR)):
        autorise, attente = security.check_rate_limit(seau, cle, plafond, FENETRE_ECHECS)
        if not autorise:
            security.audit(None, None, "platform.login_locked", "platform_account", email, "denied",
                           after={"ip": ip, "seau": seau})
            return jsonify({"error": f"Trop de tentatives. Réessayez dans {attente // 60 + 1} minute(s)."}), 429

    conn = db.get_connection()
    try:
        compte = conn.execute("SELECT * FROM platform_accounts WHERE email=?", (email,)).fetchone()
        mot_de_passe_ok = security.verify_password(
            mot_de_passe, compte["password_hash"] if compte else _EMPREINTE_FACTICE)
        pas = None
        if compte and mot_de_passe_ok and compte["status"] == "active":
            pas = verifier_totp(compte["totp_secret"], code, compte["totp_last_step"])
        if pas is not None:
            # Consommation atomique du pas : deux connexions simultanées avec le
            # même code ne peuvent pas réussir toutes les deux.
            curseur = conn.execute(
                "UPDATE platform_accounts SET totp_last_step=? WHERE id=? AND totp_last_step < ?",
                (pas, compte["id"], pas))
            conn.commit()
            if not curseur.rowcount:
                pas = None
        if pas is None:
            security.record_attempt("admin_login_compte", email)
            security.record_attempt("admin_login_visiteur", ip)
            security.audit(None, ("plateforme:" + compte["id"]) if compte else None, "platform.login_failed",
                           "platform_account", email, "denied", after={"ip": ip})
            return jsonify({"error": MESSAGE_REFUS}), 401
        security.clear_attempts("admin_login_compte", email)
        token = ouvrir_session(conn, compte["id"])
    finally:
        conn.close()
    security.audit(None, "plateforme:" + compte["id"], "platform.login_success", "platform_account",
                   compte["id"], "success", after={"ip": ip})
    resp = jsonify({"name": compte["name"], "email": compte["email"]})
    return _poser_cookies(resp, token)


@bp.post("/api/admin/logout")
@require_platform_admin
def deconnexion():
    conn = db.get_connection()
    conn.execute("DELETE FROM platform_sessions WHERE token=?",
                 (_empreinte(request.cookies.get(ADMIN_COOKIE, "")),))
    conn.commit()
    conn.close()
    security.audit(None, acteur(), "platform.logout", "platform_account", g.platform["account_id"], "success")
    return _effacer_cookies(jsonify({"ok": True}))


@bp.get("/api/admin/session")
@require_platform_admin
def session_courante():
    return jsonify({"name": g.platform["name"], "email": g.platform["email"],
                    "inactivity_seconds": INACTIVITE_SECONDES})
