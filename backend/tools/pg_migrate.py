"""KLASSIO — migration SQLite → PostgreSQL (Supabase).

    python backend/tools/pg_migrate.py schema    crée les tables et index
    python backend/tools/pg_migrate.py donnees   copie les données
    python backend/tools/pg_migrate.py tout      EFFACE la base cible, puis les deux
                                                 (refusé si elle contient des écoles,
                                                 sauf --effacer-la-base-cible)
    python backend/tools/pg_migrate.py controle  compare les effectifs table par table

La copie respecte l'ordre des clés étrangères, calculé depuis la base cible
elle-même plutôt que deviné. Rien n'est supprimé côté SQLite : la base locale
reste la référence tant que la bascule n'est pas décidée.
"""
import os
import sqlite3
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND)
import config  # noqa: E402

SCHEMA_PG = os.path.join(BACKEND, "schema_postgres.sql")
LOT = 500  # lignes par lot : compromis entre nombre d'allers-retours et mémoire


def connect_pg():
    import psycopg
    if not config.SUPABASE_DB_URL:
        print("SUPABASE_DB_URL absente. Lancez : bash tools/supabase.sh mot-de-passe")
        sys.exit(1)
    # prepare_threshold=None : le pooler en mode transaction ne conserve pas
    # les requêtes préparées d'une transaction à l'autre.
    return psycopg.connect(config.SUPABASE_DB_URL, prepare_threshold=None, connect_timeout=20)


def connect_sqlite():
    conn = sqlite3.connect(config.get("KLASSIO_SQLITE_PATH") or os.path.join(BACKEND, "klassio.db"))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------

def creer_schema():
    if not os.path.exists(SCHEMA_PG):
        print("schema_postgres.sql absent. Lancez : python backend/tools/pg_schema.py")
        return 1
    with open(SCHEMA_PG, "r", encoding="utf-8") as f:
        ddl = f.read()
    with connect_pg() as pg:
        pg.execute(ddl)
        pg.commit()
        n = pg.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
    print(f"Schéma appliqué : {n} tables dans le schéma public.")
    return 0


def reinitialiser():
    """Repart d'une base vide, puis applique schéma ET migrations de colonnes.

    Indispensable : une partie des colonnes de Klassio (slug, téléphone,
    identifiant élève, périmètre du DD…) n'existe pas dans schema.sql mais est
    ajoutée par db._migrate(). Sans cette étape, la copie les ignorerait.
    """
    # CETTE FONCTION EFFACE TOUTE LA BASE CIBLE. Jusqu'au 25/09 elle le
    # faisait sans rien demander, et `tout` — présenté plus haut comme « les
    # deux » — commence par elle. La chaîne de connexion étant dans
    # backend/.env, une commande recopiée de cette documentation effaçait la
    # base de production. Elle n'agit plus que sur une base VIDE d'écoles, sauf
    # consentement écrit en toutes lettres.
    with connect_pg() as pg:
        try:
            n = pg.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        except Exception:
            pg.rollback()
            n = 0
    if n and "--effacer-la-base-cible" not in sys.argv:
        print(f"Refus : la base cible ({config.hote_postgres()}) contient {n} établissement(s).\n"
              "« reinit » et « tout » commencent par DROP SCHEMA public CASCADE : tout serait\n"
              "effacé, élèves, notes, paiements et reçus compris.\n"
              "Pour ajouter des données sans rien effacer : pg_migrate.py donnees\n"
              "Si l'effacement est VOULU, et une sauvegarde faite : ajoutez --effacer-la-base-cible",
              file=sys.stderr)
        return 3
    with connect_pg() as pg:
        pg.execute("DROP SCHEMA public CASCADE")
        pg.execute("CREATE SCHEMA public")
        pg.commit()
    print("Schéma public remis à zéro.")
    config.DB_BACKEND = "postgres"  # le temps de ce processus uniquement
    import db
    db.config.DB_BACKEND = "postgres"
    db.init_db()
    with connect_pg() as pg:
        n = pg.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
        cols = pg.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='public'").fetchone()[0]
    print(f"Schéma et migrations appliqués : {n} tables, {cols} colonnes.")
    return 0


def ordre_des_tables(pg):
    """Tri topologique à partir des clés étrangères réelles de la base cible."""
    tables = [r[0] for r in pg.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")]
    deps = {t: set() for t in tables}
    for enfant, parent in pg.execute("""
        SELECT tc.table_name, ccu.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'"""):
        if enfant in deps and parent != enfant:
            deps[enfant].add(parent)
    ordonne, restant = [], dict(deps)
    while restant:
        libres = sorted(t for t, d in restant.items() if not (d - set(ordonne)))
        if not libres:  # cycle : on prend le reste tel quel, l'insertion dira si ça coince
            ordonne.extend(sorted(restant))
            break
        ordonne.extend(libres)
        for t in libres:
            restant.pop(t)
    return ordonne


def colonnes_pg(pg, table):
    return {r[0]: r[1] for r in pg.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))}


def convertir(valeur, type_pg):
    if valeur is None:
        return None
    if type_pg == "integer" or type_pg == "bigint":
        if isinstance(valeur, str) and valeur.strip() == "":
            return None
        return int(float(valeur))
    if type_pg == "double precision" or type_pg == "numeric":
        if isinstance(valeur, str) and valeur.strip() == "":
            return None
        return float(valeur)
    if type_pg == "boolean":
        return bool(valeur)
    if isinstance(valeur, bytes):
        return valeur.decode("utf-8", "replace")
    return valeur


def copier_donnees():
    sl = connect_sqlite()
    tables_sqlite = {r["name"] for r in sl.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    total_lignes, echecs = 0, []
    with connect_pg() as pg:
        ordre = ordre_des_tables(pg)
        print(f"{len(ordre)} tables à traiter\n")
        for table in ordre:
            if table not in tables_sqlite:
                continue
            cols_pg = colonnes_pg(pg, table)
            cols_sl = [r["name"] for r in sl.execute(f"PRAGMA table_info({table})")]
            cols = [c for c in cols_sl if c in cols_pg]
            if not cols:
                continue
            lignes = sl.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            if not lignes:
                print(f"  {table:<34} vide")
                continue
            liste = ", ".join(f'"{c}"' for c in cols)
            marqueurs = ", ".join(["%s"] * len(cols))
            requete = f'INSERT INTO "{table}" ({liste}) VALUES ({marqueurs}) ON CONFLICT DO NOTHING'
            copiees = 0
            try:
                with pg.cursor() as cur:
                    for debut in range(0, len(lignes), LOT):
                        lot = [tuple(convertir(r[c], cols_pg[c]) for c in cols) for r in lignes[debut:debut + LOT]]
                        cur.executemany(requete, lot)
                        copiees += len(lot)
                pg.commit()
                print(f"  {table:<34} {copiees} ligne(s)")
                total_lignes += copiees
            except Exception:
                # Un lot entier échoue dès qu'une seule ligne pose problème.
                # On reprend ligne par ligne pour copier ce qui est valide et
                # nommer précisément ce qui ne l'est pas : une migration doit
                # rendre des comptes, pas abandonner une table en silence.
                pg.rollback()
                copiees, rejets = 0, []
                for r in lignes:
                    valeurs = tuple(convertir(r[c], cols_pg[c]) for c in cols)
                    try:
                        with pg.cursor() as cur:
                            cur.execute(requete, valeurs)
                        pg.commit()
                        copiees += 1
                    except Exception as e:
                        pg.rollback()
                        rejets.append((dict(zip(cols, valeurs)), " ".join(str(e).split())[:110]))
                total_lignes += copiees
                if rejets:
                    print(f"  {table:<34} {copiees} ligne(s), {len(rejets)} refusée(s)")
                    echecs.append((table, rejets))
                else:
                    print(f"  {table:<34} {copiees} ligne(s)")
    sl.close()
    print(f"\n{total_lignes} lignes copiées.")
    if echecs:
        print("\nLignes refusées par PostgreSQL (intégrité non respectée dans SQLite) :")
        for table, rejets in echecs:
            print(f"  {table} : {len(rejets)} ligne(s)")
            for valeurs, motif in rejets[:10]:
                apercu = ", ".join(f"{k}={v}" for k, v in list(valeurs.items())[:3])
                print(f"    - {apercu}")
                print(f"      {motif}")
        return 1
    return 0


def controler():
    sl = connect_sqlite()
    tables_sqlite = {r["name"] for r in sl.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    ecarts = 0
    with connect_pg() as pg:
        print(f"{'table':<34}{'SQLite':>10}{'Postgres':>10}")
        for table in sorted(tables_sqlite):
            try:
                n_pg = pg.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except Exception:
                pg.rollback()
                n_pg = None
            n_sl = sl.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if n_pg is None:
                print(f"{table:<34}{n_sl:>10}{'absente':>10}")
                ecarts += 1
            elif n_pg != n_sl:
                print(f"{table:<34}{n_sl:>10}{n_pg:>10}   écart")
                ecarts += 1
            elif n_sl:
                print(f"{table:<34}{n_sl:>10}{n_pg:>10}")
    sl.close()
    print("\nAucun écart." if not ecarts else f"\n{ecarts} écart(s).")
    return 0 if not ecarts else 1


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "controle"
    if action == "schema":
        return creer_schema()
    if action in ("reinit", "reinitialiser"):
        return reinitialiser()
    if action in ("donnees", "data"):
        return copier_donnees()
    if action == "tout":
        code = reinitialiser()
        return code or copier_donnees()
    if action in ("controle", "check"):
        return controler()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
