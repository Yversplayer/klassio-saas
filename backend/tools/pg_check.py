"""KLASSIO — vérifie la chaîne de connexion PostgreSQL de Supabase.

Teste, dans l'ordre, ce qui peut échouer, et dit lequel de ces quatre points
bloque : le format de la chaîne, le DNS, le réseau, l'authentification.

    python backend/tools/pg_check.py

La chaîne est lue depuis `backend/.env` (SUPABASE_DB_URL) : le mot de passe ne
transite ni par la ligne de commande ni par l'historique du shell.
"""
import os
import re
import socket
import sys
from urllib.parse import urlparse, unquote

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND)
import config  # noqa: E402

PLACEHOLDERS = ("[your-password]", "your-password", "[password]", "mot_de_passe", "motdepasse")


def _resolve(host):
    """Renvoie (adresses IPv4, adresses IPv6)."""
    v4, v6 = [], []
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            if family == socket.AF_INET and sockaddr[0] not in v4:
                v4.append(sockaddr[0])
            elif family == socket.AF_INET6 and sockaddr[0] not in v6:
                v6.append(sockaddr[0])
    except socket.gaierror:
        pass
    return v4, v6


def main():
    url = config.SUPABASE_DB_URL
    print("1. Chaîne de connexion")
    if not url:
        print("   absente. Lancez : bash tools/supabase.sh mot-de-passe")
        return 1
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        print(f"   schéma inattendu : {parsed.scheme!r} (attendu postgresql://)")
        return 1
    password = unquote(parsed.password or "")
    host, port = parsed.hostname, parsed.port or 5432
    print(f"   hôte        {host}")
    print(f"   port        {port}")
    print(f"   utilisateur {parsed.username}")
    print(f"   mot de passe {config.mask(password) if password else 'absent'}")
    if not password or password.lower() in PLACEHOLDERS or password.startswith("["):
        print("\n   Le mot de passe n'est pas encore renseigné.")
        print("   Lancez : bash tools/supabase.sh mot-de-passe")
        return 1

    print("\n2. Résolution DNS")
    v4, v6 = _resolve(host)
    print(f"   IPv4 {', '.join(v4) if v4 else 'aucune adresse'}")
    print(f"   IPv6 {', '.join(v6) if v6 else 'aucune adresse'}")
    if not v4 and v6:
        print("\n   Cet hôte n'existe qu'en IPv6. Les connexions directes Supabase")
        print("   (db.<ref>.supabase.co) le sont toutes. Depuis un réseau IPv4,")
        print("   utilisez l'adresse du pooler (…pooler.supabase.com), donnée par")
        print("   le bouton « Connect » du tableau de bord.")
        return 1
    if not v4 and not v6:
        if re.match(r"^db\.[a-z0-9]+\.supabase\.co$", host or ""):
            # Supabase ne publie plus d'adresse IPv4 pour la connexion directe.
            # Un poste sans IPv6 ne voit alors aucune adresse du tout.
            print("\n   Cet hôte est la connexion DIRECTE de Supabase, publiée en IPv6")
            print("   uniquement. Votre réseau étant en IPv4, il reste invisible.")
            print("   Utilisez l'adresse du pooler (…pooler.supabase.com), donnée par")
            print("   le bouton « Connect » du tableau de bord.")
        else:
            print("   Nom introuvable : vérifiez l'orthographe de l'hôte.")
        return 1

    print("\n3. Connexion réseau")
    try:
        with socket.create_connection((host, port), timeout=10):
            print(f"   port {port} ouvert")
    except OSError as e:
        print(f"   injoignable : {e}")
        return 1

    print("\n4. Authentification PostgreSQL")
    try:
        import psycopg
    except ImportError:
        print("   pilote absent : backend_venv/bin/pip install 'psycopg[binary]'")
        return 1
    try:
        with psycopg.connect(url, connect_timeout=20) as conn:
            row = conn.execute("SELECT version(), current_database(), current_user").fetchone()
            print(f"   connecté à {row[1]} en tant que {row[2]}")
            print(f"   {row[0].split(' on ')[0]}")
            tables = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'"
            ).fetchone()[0]
            print(f"   tables dans le schéma public : {tables}")
    except Exception as e:
        msg = " ".join(str(e).split())
        print(f"   échec : {msg[:220]}")
        if "password authentication failed" in msg.lower():
            print("\n   L'hôte est le bon, le mot de passe ne l'est pas.")
            print("   Réinitialisez-le : Project Settings → Database → Reset database password.")
        return 1

    print("\nChaîne de connexion valide. La migration peut être lancée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
