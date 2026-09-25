"""KLASSIO — configuration par variables d'environnement.

Aucune clé n'est écrite dans le code. Les valeurs viennent, dans l'ordre :
  1. l'environnement du processus (ce qui prime en production) ;
  2. le fichier `backend/.env`, non versionné, pour la machine de développement.

Volontairement sans dépendance externe : le venv du projet ne contient que
Flask, et une ligne `KEY=valeur` se lit très bien sans python-dotenv.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _parse_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
    return values


_FILE_VALUES = _parse_env_file(ENV_PATH)


def get(name, default=None):
    """L'environnement du processus prime toujours sur le fichier .env."""
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    value = _FILE_VALUES.get(name)
    return value if value not in (None, "") else default


def get_bool(name, default=False):
    value = get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "oui", "on")


def mask(secret, keep=4):
    """Affiche une clé sans la divulguer : « eyJh…B7Kq (208 caractères) »."""
    if not secret:
        return "absente"
    if len(secret) <= keep * 2:
        return "•" * len(secret)
    return f"{secret[:keep]}…{secret[-keep:]} ({len(secret)} caractères)"


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

def _normalise_url(url):
    """Accepte l'URL du projet ou l'URL de l'API REST, renvoie la racine."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    for suffix in ("/rest/v1", "/auth/v1", "/storage/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


SUPABASE_URL = _normalise_url(get("SUPABASE_URL"))
# Clé publiable : conçue pour le navigateur, protégée par la RLS. Supabase a
# renommé « anon » en « publishable » (format sb_publishable_…) ; les deux noms
# de variable sont acceptés pour ne pas casser les configurations existantes.
SUPABASE_ANON_KEY = get("SUPABASE_PUBLISHABLE_KEY") or get("SUPABASE_ANON_KEY")
# Clé secrète : serveur uniquement, contourne la RLS. Ne jamais l'exposer.
SUPABASE_SERVICE_KEY = get("SUPABASE_SECRET_KEY") or get("SUPABASE_SERVICE_KEY")
# Chaîne de connexion Postgres. `DATABASE_URL` d'abord : c'est le nom que
# posent d'eux-mêmes Render, Heroku et la plupart des hébergeurs, et c'est la
# convention de fait. `SUPABASE_DB_URL` reste accepté pour ne rien casser.
#
# Le nom historique induisait en erreur : Klassio n'utilise Supabase QUE comme
# hébergeur PostgreSQL. Aucun chemin de requête n'appelle son API REST — voir
# supabase_client.py, dont le seul usage est la bannière de démarrage et un
# outil de diagnostic. N'importe quel PostgreSQL convient donc, et le 18/09 le
# projet Supabase a disparu (« tenant not found ») sans que le code soit en
# cause : c'est l'hébergeur qui manquait, pas une dépendance.
SUPABASE_DB_URL = get("DATABASE_URL") or get("SUPABASE_DB_URL")

# Moteur de stockage effectif. Tant que la migration n'est pas faite et
# vérifiée, Klassio reste sur SQLite : on ne bascule pas une base d'élèves
# sur un simple réglage.
DB_BACKEND = (get("KLASSIO_DB_BACKEND", "sqlite") or "sqlite").strip().lower()

# Schéma PostgreSQL dans lequel Klassio travaille. Vide = `public`, le cas de
# la production. Sert à exécuter la suite de tests contre un vrai PostgreSQL
# sans jamais approcher les données réelles : un schéma séparé dans la même
# base est aussi étanche qu'une base séparée, et Supabase n'en fournit qu'une.
PG_SCHEMA = (get("KLASSIO_PG_SCHEMA", "") or "").strip()
if PG_SCHEMA and not PG_SCHEMA.replace("_", "").isalnum():
    raise ValueError("KLASSIO_PG_SCHEMA : lettres, chiffres et « _ » uniquement.")


# ---------------------------------------------------------------------------
# Où va VRAIMENT la base PostgreSQL
# ---------------------------------------------------------------------------
#
# Les garde-fous qui protègent la production ne se fondent pas sur une
# étiquette du genre ENVIRONMENT=development : une étiquette se copie, s'oublie,
# ment. Ils regardent l'HÔTE de la base visée. Une base sur cette machine est
# jetable par construction ; une base sur un autre hôte peut être celle d'une
# école.
#
# Seul l'hôte est extrait. Le mot de passe ne quitte jamais la chaîne.

HOTES_LOCAUX = {"", "localhost", "127.0.0.1", "::1"}


def hote_postgres(url=None):
    """L'hôte d'une chaîne PostgreSQL (URI ou forme « host=… dbname=… »).

    None si aucune base PostgreSQL n'est configurée.
    """
    url = SUPABASE_DB_URL if url is None else url
    if not url:
        return None
    url = url.strip()
    if "://" in url:
        from urllib.parse import parse_qs, urlsplit
        morceaux = urlsplit(url)
        hote = morceaux.hostname or ""
        if not hote:
            # libpq accepte l'hôte en paramètre : ?host=/var/run/postgresql
            hote = (parse_qs(morceaux.query).get("host") or [""])[0]
        return hote
    for paire in url.split():
        if paire.startswith("host="):
            return paire[len("host="):].strip("'\"")
    return ""


def postgres_est_local(url=None):
    """Vrai si la base PostgreSQL visée est sur cette machine (ou absente)."""
    hote = hote_postgres(url)
    if hote is None:
        return True
    # Un chemin est une socket Unix : forcément locale.
    return hote in HOTES_LOCAUX or hote.startswith("/")


def supabase_configured():
    return bool(SUPABASE_URL and (SUPABASE_ANON_KEY or SUPABASE_SERVICE_KEY))


def summary():
    """État lisible de la configuration, sans jamais révéler une clé."""
    return {
        "supabase_url": SUPABASE_URL or "absente",
        "anon_key": mask(SUPABASE_ANON_KEY),
        "service_key": mask(SUPABASE_SERVICE_KEY),
        "db_url": "configurée" if SUPABASE_DB_URL else "absente",
        "db_backend": DB_BACKEND,
        "pg_schema": PG_SCHEMA or "public",
        "env_file": ENV_PATH if os.path.exists(ENV_PATH) else "absent",
    }
