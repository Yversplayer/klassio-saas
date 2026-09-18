"""Exécute la suite de tests contre un vrai PostgreSQL.

Pourquoi cet outil : les 65 tests d'origine ne tournaient que sur SQLite. Or
c'est PostgreSQL qui portera le produit — et un dialecte qui « passe la
traduction » n'est pas la même chose qu'un dialecte que le serveur accepte.
Quatre requêtes refusées par PostgreSQL ont été trouvées ainsi.

Deux modes, dans cet ordre d'usage.

  local     (défaut) Un PostgreSQL 16 réel, démarré sur cette machine dans un
            dossier temporaire, détruit à la fin. Pas de Docker, pas de droits
            administrateur, pas de réseau : la campagne complète prend le même
            temps que sur SQLite au lieu de plusieurs heures depuis Kinshasa.
            Et par construction, elle ne peut approcher aucune donnée réelle.

  supabase  La vraie base du projet, dans un SCHÉMA séparé (`klassio_test`)
            recréé vide puis supprimé. Deux schémas ne partagent aucune table :
            les 137 000 lignes du schéma `public` ne sont jamais touchées.
            Plus lent — chaque requête est un aller-retour vers l'Irlande —
            mais c'est le seul mode qui exerce le pooler Supabase en mode
            transaction, la configuration réelle de production. À réserver à la
            vérification finale avant bascule.

    python backend/tools/pg_tests.py                        # local, toute la suite
    python backend/tools/pg_tests.py tests.test_school      # local, un module
    python backend/tools/pg_tests.py --supabase             # contre Supabase
    python backend/tools/pg_tests.py --supabase --garder    # garder le schéma

Le mode local demande `pgserver` : `pip install -r requirements-dev.txt`.
"""
import os
import shutil
import subprocess
import sys
import tempfile

RACINE_BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, RACINE_BACKEND)

import config  # noqa: E402

SCHEMA = "klassio_test"


# ---------------------------------------------------------------------------
# Exécution de la suite
# ---------------------------------------------------------------------------

def modules_de_test():
    """Les modules de tests, dans l'ordre alphabétique — celui de `discover`."""
    dossier = os.path.join(RACINE_BACKEND, "tests")
    return ["tests." + f[:-3] for f in sorted(os.listdir(dossier))
            if f.startswith("test_") and f.endswith(".py")]


def lancer(modules, variables, remettre_a_zero):
    """Joue chaque module dans une base VIDE, comme le fait la suite SQLite.

    Sur SQLite, chaque `setUpModule` supprime le fichier de base : tout module
    démarre à vide. En PostgreSQL ce `os.remove()` ne fait rien, et les modules
    se partagent alors la même base — les données du précédent restent. Un test
    passait seul et échouait dans la suite. Ce n'était pas un défaut de
    Klassio, mais de cet outil : il rendait la campagne PostgreSQL non
    comparable à la campagne SQLite, donc peu digne de confiance.

    On remet donc le schéma à zéro entre les modules.
    """
    env = dict(os.environ)
    env["KLASSIO_DB_BACKEND"] = "postgres"
    env.update(variables)
    cibles = list(modules) or modules_de_test()
    echecs, total = [], 0
    for module in cibles:
        remettre_a_zero()
        cmd = [sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest", module, "-v"]
        print(f"\n───── {module} ─────", flush=True)
        code = subprocess.call(cmd, cwd=RACINE_BACKEND, env=env)
        total += 1
        if code != 0:
            echecs.append(module)
    print(f"\n═══ {total - len(echecs)}/{total} modules verts ═══")
    if echecs:
        print("modules en échec : " + ", ".join(echecs))
    return 1 if echecs else 0


# ---------------------------------------------------------------------------
# Mode local : PostgreSQL embarqué
# ---------------------------------------------------------------------------

def mode_local(modules):
    try:
        import pgserver
    except ImportError:
        print("Le mode local demande `pgserver` (PostgreSQL 16 embarqué) :", file=sys.stderr)
        print("    backend_venv/bin/pip install -r requirements-dev.txt", file=sys.stderr)
        print("Sinon : python backend/tools/pg_tests.py --supabase", file=sys.stderr)
        return 2

    dossier = tempfile.mkdtemp(prefix="klassio_pg_test_")
    print(f"Démarrage d'un PostgreSQL local dans {dossier} …", flush=True)
    serveur = pgserver.get_server(dossier)
    try:
        version = serveur.psql("SHOW server_version;").split("\n")[2].strip()
        print(f"PostgreSQL {version} — base jetable, aucune donnée réelle accessible.", flush=True)

        def remettre_a_zero():
            serveur.psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

        return lancer(modules, {"SUPABASE_DB_URL": serveur.get_uri()}, remettre_a_zero)
    finally:
        serveur.cleanup()
        shutil.rmtree(dossier, ignore_errors=True)
        print("\nServeur local arrêté, dossier supprimé.")


# ---------------------------------------------------------------------------
# Mode Supabase : schéma isolé dans la vraie base
# ---------------------------------------------------------------------------

def _connexion_admin():
    """Connexion hors schéma de test, pour le créer et le supprimer."""
    import psycopg
    if not config.SUPABASE_DB_URL:
        raise SystemExit("SUPABASE_DB_URL absente — voir backend/.env.example.")
    return psycopg.connect(config.SUPABASE_DB_URL, autocommit=True)


def creer_schema():
    with _connexion_admin() as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
    print(f"Schéma « {SCHEMA} » recréé vide (le schéma public n'est pas touché).", flush=True)


def supprimer_schema():
    with _connexion_admin() as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    print(f"Schéma « {SCHEMA} » supprimé.")


def mode_supabase(modules, garder):
    creer_schema()
    try:
        return lancer(modules, {"KLASSIO_PG_SCHEMA": SCHEMA}, creer_schema)
    finally:
        if garder:
            print(f"\nSchéma « {SCHEMA} » conservé (--garder). Le supprimer ensuite :")
            print("  python backend/tools/pg_tests.py --supprimer")
        else:
            supprimer_schema()


# ---------------------------------------------------------------------------

def main(argv):
    if "--supprimer" in argv:
        supprimer_schema()
        return 0
    modules = [a for a in argv if not a.startswith("--")]
    if "--supabase" in argv:
        return mode_supabase(modules, garder="--garder" in argv)
    return mode_local(modules)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
