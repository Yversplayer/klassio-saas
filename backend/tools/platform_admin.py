"""Outil d'exploitation Klassio — les comptes d'administration de la plateforme.

C'est la SEULE manière de créer un administrateur : aucune route HTTP n'écrit
la table platform_accounts (tests/test_plateforme_admin.py le vérifie). Il se
lance sur une machine qui a déjà accès à la base — c'est cet accès, et non une
page web, qui fait foi.

    python backend/tools/platform_admin.py list
    python backend/tools/platform_admin.py create  contact@klassio.example
    python backend/tools/platform_admin.py reset-2fa      contact@klassio.example
    python backend/tools/platform_admin.py reset-password contact@klassio.example
    python backend/tools/platform_admin.py disable contact@klassio.example
    python backend/tools/platform_admin.py enable  contact@klassio.example

LE MOT DE PASSE est demandé en saisie masquée, deux fois, jamais en argument
(il resterait dans l'historique du shell). 12 caractères au moins, avec
majuscule, minuscule, chiffre et caractère spécial.

LE SECOND FACTEUR. `create` et `reset-2fa` affichent une clé à saisir dans une
application d'authentification (Google Authenticator : « + » → « Saisir une clé
de configuration »), puis exigent le premier code à 6 chiffres. Rien n'est
enregistré tant que ce code n'est pas juste : on ne peut pas s'enfermer dehors
avec une clé mal recopiée. La clé n'est affichée qu'une fois.

À lancer dans SON PROPRE terminal : la clé du second facteur s'y affiche.
Contre la base de production :

    read -rs "DATABASE_URL?Chaîne Supabase (invisible) : "; echo
    export DATABASE_URL KLASSIO_DB_BACKEND=postgres
    backend_venv/bin/python backend/tools/platform_admin.py create vous@exemple.com
    unset DATABASE_URL KLASSIO_DB_BACKEND
"""
import getpass
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import db  # noqa: E402
import platform_auth  # noqa: E402
import security  # noqa: E402
from validation import ValidationError, valid_password  # noqa: E402

LONGUEUR_MIN = 12
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def _mot_de_passe(lire_secret, ecrire):
    for _ in range(3):
        premier = lire_secret("Mot de passe (invisible) : ")
        try:
            valid_password(premier)
            if len(premier) < LONGUEUR_MIN:
                raise ValidationError(f"{LONGUEUR_MIN} caractères minimum pour un administrateur.")
        except ValidationError as e:
            ecrire(f"  Refusé : {e}")
            continue
        if lire_secret("Le même, encore une fois : ") != premier:
            ecrire("  Les deux saisies diffèrent.")
            continue
        return premier
    return None


def _enroler(email, lire, ecrire):
    """Affiche la clé, exige un premier code juste. → (secret, pas) ou None."""
    secret = platform_auth.nouveau_secret_totp()
    groupes = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
    ecrire("")
    ecrire("Second facteur — dans Google Authenticator : « + » → « Saisir une clé de configuration »")
    ecrire("  Nom du compte : Klassio (" + email + ")")
    ecrire("  Clé           : " + groupes)
    ecrire("  Type          : basé sur l'heure")
    ecrire("  (ou, pour une application qui lit un lien : " + platform_auth.uri_otpauth(email, secret) + ")")
    ecrire("")
    for _ in range(3):
        pas = platform_auth.verifier_totp(secret, lire("Code à 6 chiffres affiché par l'application : "), 0)
        if pas is not None:
            return secret, pas
        ecrire("  Code incorrect. Vérifiez la clé saisie et l'heure du téléphone.")
    return None


def main(argv, lire=input, lire_secret=getpass.getpass, ecrire=print):
    action = argv[1] if len(argv) > 1 else "list"
    conn = db.get_connection()
    try:
        try:
            conn.execute("SELECT 1 FROM platform_accounts LIMIT 1").fetchall()
        except Exception:
            ecrire("La table platform_accounts n'existe pas encore sur cette base : "
                   "déployez d'abord le backend (le déploiement applique le schéma).")
            return 3

        if action == "list":
            rows = conn.execute("SELECT email, name, status, created_at FROM platform_accounts ORDER BY created_at").fetchall()
            if not rows:
                ecrire("Aucun compte d'administration.")
            for r in rows:
                ecrire(f"{r['name']} <{r['email']}>  {r['status']}")
            return 0

        if len(argv) < 3 or action not in ("create", "reset-2fa", "reset-password", "disable", "enable"):
            ecrire(__doc__)
            return 2
        email = argv[2].strip().lower()
        compte = conn.execute("SELECT * FROM platform_accounts WHERE email=?", (email,)).fetchone()
        maintenant = str(time.time())

        if action == "create":
            if not _EMAIL.match(email):
                ecrire("Adresse e-mail invalide.")
                return 1
            if compte:
                ecrire("Un compte d'administration existe déjà avec cette adresse.")
                return 1
            nom = (lire("Nom affiché : ") or "").strip()[:120]
            if not nom:
                ecrire("Nom obligatoire.")
                return 1
            mot_de_passe = _mot_de_passe(lire_secret, ecrire)
            if not mot_de_passe:
                ecrire("Abandon : aucun compte créé.")
                return 1
            enrolement = _enroler(email, lire, ecrire)
            if not enrolement:
                ecrire("Abandon : aucun compte créé.")
                return 1
            secret, pas = enrolement
            conn.execute(
                "INSERT INTO platform_accounts (id, email, name, password_hash, totp_secret, totp_last_step, "
                "status, created_at, updated_at) VALUES (?,?,?,?,?,?, 'active', ?, ?)",
                (security.new_id(), email, nom, security.hash_password(mot_de_passe), secret, pas,
                 maintenant, maintenant))
            conn.commit()
            ecrire(f"Compte d'administration créé pour {nom} <{email}>.")
            return 0

        if not compte:
            ecrire(f"Aucun compte d'administration « {email} ».")
            return 1

        if action == "reset-2fa":
            enrolement = _enroler(email, lire, ecrire)
            if not enrolement:
                ecrire("Abandon : l'ancien second facteur reste en place.")
                return 1
            secret, pas = enrolement
            conn.execute("UPDATE platform_accounts SET totp_secret=?, totp_last_step=?, updated_at=? WHERE id=?",
                         (secret, pas, maintenant, compte["id"]))
            message = "Second facteur remplacé ; l'ancien ne vaut plus rien."
        elif action == "reset-password":
            mot_de_passe = _mot_de_passe(lire_secret, ecrire)
            if not mot_de_passe:
                ecrire("Abandon : mot de passe inchangé.")
                return 1
            conn.execute("UPDATE platform_accounts SET password_hash=?, updated_at=? WHERE id=?",
                         (security.hash_password(mot_de_passe), maintenant, compte["id"]))
            message = "Mot de passe remplacé."
        elif action == "disable":
            conn.execute("UPDATE platform_accounts SET status='disabled', updated_at=? WHERE id=?",
                         (maintenant, compte["id"]))
            message = "Compte désactivé."
        else:
            conn.execute("UPDATE platform_accounts SET status='active', updated_at=? WHERE id=?",
                         (maintenant, compte["id"]))
            message = "Compte réactivé."
        # Toute modification de sécurité ferme les sessions ouvertes.
        platform_auth.revoquer_sessions(conn, compte["id"])
        conn.commit()
        ecrire(message + " Sessions ouvertes fermées.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
