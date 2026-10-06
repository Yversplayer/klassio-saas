"""Aide des tests : ouvrir une VRAIE session d'administration de la plateforme.

Depuis le 06/10/2026, /api/platform/* ne s'ouvre plus à un directeur promu
(ancienne table platform_admins) mais à un compte d'administration à part,
avec second facteur. Les tests qui éprouvent la facturation (confirmer un
paiement, annuler une facture, modifier un palier) passent donc par ici : le
compte est posé en base comme le ferait backend/tools/platform_admin.py, et
la session s'ouvre par la vraie route de connexion, code TOTP compris.

Ce fichier ne commence pas par « test_ » : la découverte ne le lance pas.
"""
import itertools
import time

import db
import platform_auth
import security

MOT_DE_PASSE = "Plateforme!Test2026"
_numero = itertools.count(1)


def creer_compte_admin(email, mot_de_passe=MOT_DE_PASSE, nom="Administration test", statut="active"):
    secret = platform_auth.nouveau_secret_totp()
    maintenant = str(time.time())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO platform_accounts (id, email, name, password_hash, totp_secret, totp_last_step, "
            "status, created_at, updated_at) VALUES (?,?,?,?,?,0,?,?,?)",
            (security.new_id(), email, nom, security.hash_password(mot_de_passe), secret, statut,
             maintenant, maintenant))
        conn.commit()
    finally:
        conn.close()
    return secret


def code_actuel(secret):
    return platform_auth.code_totp(secret, platform_auth.pas_courant())


def session_admin(app, email=None):
    """→ (client avec cookies, en-têtes CSRF d'administration, email)."""
    email = email or f"admin{next(_numero)}.{int(time.time() * 1000)}@plateforme.test"
    secret = creer_compte_admin(email)
    client = app.test_client(use_cookies=True)
    r = client.post("/api/admin/login",
                    json={"email": email, "password": MOT_DE_PASSE, "code": code_actuel(secret)})
    assert r.status_code == 200, r.get_data(as_text=True)
    csrf = {security.CSRF_HEADER: client.get_cookie(platform_auth.ADMIN_CSRF_COOKIE).value}
    return client, csrf, email
