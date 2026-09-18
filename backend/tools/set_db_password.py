"""KLASSIO — enregistre le mot de passe de la base Supabase dans backend/.env.

Le mot de passe est saisi sans écho : il n'apparaît ni à l'écran, ni dans
l'historique du shell, ni dans un message. Les caractères spéciaux sont
encodés automatiquement, ce qui est la première cause d'échec quand on colle
une chaîne de connexion à la main.

    python3 backend/tools/set_db_password.py

Puis la connexion est vérifiée dans la foulée.
"""
import getpass
import os
import re
import sys
from urllib.parse import quote, urlparse

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND)
import config  # noqa: E402

ENV_PATH = config.ENV_PATH
# Session pooler du projet : joignable en IPv4, contrairement à la connexion directe.
DEFAULT_URI = ("postgresql://postgres.zpcbppwibrdpblnpslvf:MOT_DE_PASSE"
               "@aws-1-eu-west-1.pooler.supabase.com:5432/postgres")


def write_env(key, value):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    remplace = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            remplace = True
            break
    if not remplace:
        lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)


def main():
    existant = config.SUPABASE_DB_URL or ""
    gabarit = existant if ("@" in existant and "pooler.supabase.com" in existant) else DEFAULT_URI
    parsed = urlparse(gabarit)
    print("Base Supabase à configurer")
    print(f"  hôte        {parsed.hostname}")
    print(f"  port        {parsed.port}")
    print(f"  utilisateur {parsed.username}")
    print("\nCollez le mot de passe de la base (celui obtenu au moment de la")
    print("réinitialisation). Rien ne s'affichera pendant la saisie.")
    try:
        mot_de_passe = getpass.getpass("  Mot de passe : ")
    except (KeyboardInterrupt, EOFError):
        print("\nAnnulé.")
        return 1
    mot_de_passe = mot_de_passe.strip()
    if not mot_de_passe:
        print("Aucun mot de passe saisi.")
        return 1
    if mot_de_passe.startswith("[") or mot_de_passe.lower() in ("your-password", "[your-password]"):
        print("C'est le marqueur affiché par Supabase, pas le mot de passe.")
        return 1

    # Les caractères spéciaux doivent être encodés dans une URL de connexion.
    encode = quote(mot_de_passe, safe="")
    uri = f"postgresql://{parsed.username}:{encode}@{parsed.hostname}:{parsed.port}{parsed.path}"
    write_env("SUPABASE_DB_URL", uri)
    print(f"\nEnregistré dans {ENV_PATH} (lecture seule pour vous).")
    if encode != mot_de_passe:
        print("Des caractères spéciaux ont été encodés pour l'URL.")

    try:
        import psycopg  # noqa: F401
    except ImportError:
        print("\nLe pilote PostgreSQL n'est pas installé pour cet interpréteur :")
        print(f"  {sys.executable}")
        print("La chaîne est enregistrée ; la vérification, elle, demande le pilote.")
        print("Installez-le, ou relancez via tools/supabase.sh qui choisit le bon Python :")
        print("  bash tools/supabase.sh mot-de-passe")
        return 0

    print("\nVérification de la connexion…\n")
    import importlib
    importlib.reload(config)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pg_check
    return pg_check.main()


if __name__ == "__main__":
    sys.exit(main())
