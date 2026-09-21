"""KLASSIO backend — connexion base de données.

Deux moteurs, une seule interface. Par défaut SQLite, fichier local, qui a
porté tout le produit jusqu'ici. Au besoin PostgreSQL (Supabase), choisi par
`KLASSIO_DB_BACKEND=postgres` dans backend/.env.

Le reste du backend ne voit pas la différence : les 500 appels
`conn.execute("… ?", params)` restent écrits une seule fois, et c'est ici que
les marqueurs sont traduits pour psycopg. Les lignes sont des dictionnaires
dans les deux cas, donc `row["colonne"]` fonctionne partout.
"""
import atexit
import os
import sqlite3
import threading
import time

import config
import sql_dialect

# Chemin de la base SQLite. Surchargeable par KLASSIO_DB_PATH : les tests
# l'écrasent déjà en Python, mais lancer le serveur sur une base jetable
# demandait jusqu'ici de modifier le code.
JOURNAL_SQLITE = (config.get("KLASSIO_SQLITE_JOURNAL", "delete") or "delete").strip().lower()
DB_PATH = config.get("KLASSIO_DB_PATH") or os.path.join(os.path.dirname(__file__), "klassio.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
SCHEMA_PG_PATH = os.path.join(os.path.dirname(__file__), "schema_postgres.sql")


def is_postgres():
    return config.DB_BACKEND == "postgres"


def verrouiller_ligne(conn, table, row_id):
    """Prend un verrou d'ÉCRITURE qui tient jusqu'au prochain commit/rollback.

    Sert à sérialiser deux requêtes qui lisent puis écrivent la même grandeur.
    L'exemple qui a motivé cette fonction : deux guichets confirment en même
    temps deux paiements différents sur le MÊME frais. Chacun relit « reste dû »
    avant l'autre n'ait écrit, chacun se juge légitime, et l'établissement
    encaisse plus que ce qui était dû. Mesuré le 18/09 par tools/k6/concurrence.js :
    une dette de 350 $ avait encaissé 1 046 $.

    Deux moteurs, deux mécaniques, même garantie :

    - PostgreSQL (la production) : `SELECT … FOR UPDATE` verrouille la LIGNE.
      Deux confirmations sur le même frais s'attendent ; deux confirmations sur
      des frais différents ne se gênent pas. La connexion est en autocommit=False,
      le verrou court donc jusqu'au commit de l'appelant.

    - SQLite (développement et tests) : il n'y a pas de verrou de ligne. On
      ouvre une transaction IMMEDIATE, qui prend le verrou RESERVED du fichier :
      les autres écrivains attendent (busy timeout de 5 s par défaut). C'est
      plus large que nécessaire — tout le fichier plutôt qu'une ligne — mais
      SQLite sérialise de toute façon ses écritures.

    À n'utiliser que sur un chemin d'écriture : sur une simple lecture, ce
    verrou ne sert à rien et ferait attendre les autres pour rien.
    """
    if is_postgres():
        # `id` suffit : on ne veut pas les données, seulement le verrou.
        conn.execute(f"SELECT id FROM {table} WHERE id = ? FOR UPDATE", (row_id,)).fetchone()
        return
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        # Transaction déjà ouverte par l'appelant, ou base verrouillée plus
        # longtemps que le busy timeout. Dans les deux cas, poursuivre est
        # préférable à refuser un encaissement réel : la vérification de
        # montant qui suit reste faite, simplement sans exclusion mutuelle.
        pass


def integrity_errors():
    """Les classes d'erreur d'intégrité à intercepter, selon le moteur actif.

    Trouvé à l'audit : app.py n'interceptait que `sqlite3.IntegrityError`. En
    mode Postgres, une contrainte d'unicité violée (email déjà pris dans une
    course concurrente, idempotency_key rejouée) remontait donc en 500 brut
    au lieu du 409 prévu. On renvoie un tuple pour que les deux moteurs
    soient couverts quel que soit le réglage.
    """
    classes = [sqlite3.IntegrityError]
    try:
        import psycopg
        classes.append(psycopg.errors.IntegrityError)
    except Exception:
        # psycopg n'est pas installé sur une machine de développement
        # purement SQLite : ce n'est pas une erreur.
        pass
    return tuple(classes)


# ---------------------------------------------------------------------------
# Réserve de connexions PostgreSQL
#
# Mesure faite depuis Kinshasa : 1,9 s pour ouvrir une connexion, ~300 ms par
# requête. Or une seule requête HTTP authentifiée en ouvre DEUX — une dans
# security.require_auth pour résoudre la session, une dans la route elle-même
# — soit près de 4 s de poignée de main avant la moindre lecture utile.
#
# Héberger le backend en Europe fait tomber ces 1,9 s à quelques millisecondes,
# mais ne supprime pas les deux ouvertures : TCP + TLS + authentification, deux
# fois, à chaque requête. Garder les connexions ouvertes entre les requêtes
# supprime le coût au lieu de le réduire.
#
# Volontairement sans psycopg_pool : la réserve tient en trente lignes, et le
# projet garde une dépendance de moins. `close()` ne ferme plus la socket, il
# rend la connexion à la réserve — après un rollback, exactement comme
# sqlite3.Connection.close() abandonne une transaction non validée. Les 500
# appels `conn.close()` du backend n'ont donc pas changé de sens.
# ---------------------------------------------------------------------------

PG_POOL_SIZE = int(config.get("KLASSIO_PG_POOL_SIZE", "5") or 5)
# Au-delà de ce repos, la connexion peut avoir été coupée par le pooler
# Supabase sans que le client le sache : on la vérifie avant de la réutiliser.
PG_IDLE_CHECK_SECONDS = 60

_PG_POOL = []          # connexions au repos, prêtes à resservir
_PG_LOCK = threading.Lock()


def _pool_acquire():
    """Retourne une connexion au repos encore valide, ou None."""
    while True:
        with _PG_LOCK:
            if not _PG_POOL:
                return None
            conn = _PG_POOL.pop()
        if conn._est_reutilisable():
            return conn
        conn._fermer_vraiment()


def _pool_release(conn):
    """Rend une connexion à la réserve, ou la ferme si la réserve est pleine."""
    with _PG_LOCK:
        if len(_PG_POOL) < PG_POOL_SIZE:
            _PG_POOL.append(conn)
            return True
    return False


def close_pool():
    """Ferme toutes les connexions au repos (arrêt du processus, tests)."""
    with _PG_LOCK:
        connexions, _PG_POOL[:] = list(_PG_POOL), []
    for conn in connexions:
        conn._fermer_vraiment()


# Sans ça, les connexions encore en réserve sont ramassées par le garbage
# collector à l'arrêt du processus, socket ouverte — psycopg le signale, et le
# serveur garde la connexion jusqu'à son propre délai d'expiration.
atexit.register(close_pool)


class PgConnection:
    """Connexion PostgreSQL présentant l'interface de sqlite3.Connection."""

    def __init__(self, dsn):
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None : le pooler Supabase en mode transaction ne
        # garde pas les requêtes préparées d'une transaction à l'autre.
        # search_path passé en option de démarrage plutôt qu'en `SET` : le
        # pooler Supabase est en mode transaction et ne garantit pas qu'un
        # `SET` survive à la transaction suivante, alors qu'une option de
        # connexion est attachée à la connexion physique elle-même.
        options = f"-c search_path={config.PG_SCHEMA},public" if config.PG_SCHEMA else None
        self._conn = psycopg.connect(dsn, row_factory=dict_row, prepare_threshold=None,
                                     autocommit=False, options=options)
        self._repos_depuis = None

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql_dialect.to_pyformat(sql), tuple(params))
        return cur

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(sql_dialect.to_pyformat(sql), [tuple(p) for p in seq])
        return cur

    def executescript(self, sql):
        self._conn.execute(sql)
        return self

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def _est_reutilisable(self):
        """La connexion est-elle encore utilisable ? Vérifiée par un aller-retour
        seulement si elle a suffisamment dormi pour avoir pu être coupée."""
        if self._conn.closed or self._conn.broken:
            return False
        if self._repos_depuis is None or (time.time() - self._repos_depuis) < PG_IDLE_CHECK_SECONDS:
            return True
        try:
            self._conn.execute("SELECT 1")
            self._conn.rollback()
            return True
        except Exception:
            return False

    def _fermer_vraiment(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def close(self):
        """Rend la connexion à la réserve plutôt que de fermer la socket.

        Le rollback préalable garantit qu'aucune transaction entamée et non
        validée ne survit à la requête — même sémantique que
        sqlite3.Connection.close(), qui abandonne le travail non commité.
        """
        try:
            self._conn.rollback()
        except Exception:
            self._fermer_vraiment()
            return
        if self._conn.closed or self._conn.broken:
            self._fermer_vraiment()
            return
        self._repos_depuis = time.time()
        if not _pool_release(self):
            self._fermer_vraiment()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def get_connection():
    if is_postgres():
        if not config.SUPABASE_DB_URL:
            raise RuntimeError("KLASSIO_DB_BACKEND=postgres mais SUPABASE_DB_URL est absente.")
        conn = _pool_acquire()
        if conn is not None:
            conn._repos_depuis = None
            return conn
        return PgConnection(config.SUPABASE_DB_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Mode de journalisation SQLite. Par défaut `delete`, celui de SQLite.
    #
    # WAL a été essayé et mesuré : sous 30 utilisateurs simultanés, il apporte
    # +8 % de débit et surtout une meilleure queue (pire réponse 2 154 ms →
    # 1 455 ms), parce que lecteurs et écrivain cessent de se bloquer. Mais il
    # fait passer la suite de tests de 42 s à 97 s : Klassio ouvre et ferme une
    # connexion par appel, et en WAL chaque fermeture de la dernière connexion
    # déclenche un point de contrôle.
    #
    # Le calcul est vite fait : la production tourne sur PostgreSQL, où rien de
    # tout cela ne s'applique, alors que la suite de tests est jouée des
    # dizaines de fois par jour. On garde donc `delete` par défaut, et WAL
    # disponible pour qui mesure la charge sur SQLite :
    #
    #     KLASSIO_SQLITE_JOURNAL=wal
    try:
        conn.execute(f"PRAGMA journal_mode={JOURNAL_SQLITE}")
    except sqlite3.DatabaseError:
        # Système de fichiers réseau, ou base en lecture seule : le mode par
        # défaut reste fonctionnel. Ce n'est pas une raison de refuser de
        # démarrer.
        pass
    return conn


def init_db():
    conn = get_connection()
    chemin = SCHEMA_PG_PATH if is_postgres() else SCHEMA_PATH
    with open(chemin, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    _migrate(conn)
    conn.close()


def _add_column_if_missing(conn, table, column, ddl):
    if is_postgres():
        # PostgreSQL sait le faire lui-même, et traduit les types au passage.
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_dialect.schema_to_postgres(ddl)}")
        return
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _unicite_periodes(conn):
    """Pose l'unicité (tenant, année, division, libellé) sur academic_periods,
    et retire l'ancienne qui ignorait la division.

    Pourquoi c'est nécessaire. L'ancienne contrainte, `UNIQUE(tenant_id,
    academic_year_id, label)`, interdisait à une école d'appeler « Période 1 »
    à la fois sa première période du primaire et celle du secondaire. C'est
    pourtant exactement ce que font les établissements qui ont des structures
    différentes par division — le cas que le produit doit couvrir.

    `COALESCE(division, '*')` : dans un index unique, deux NULL sont considérés
    distincts par SQLite comme par PostgreSQL. Sans cette substitution, deux
    périodes communes de même libellé passeraient toutes les deux.

    Le produit n'a jamais été déployé : les seules bases existantes sont de
    développement et de test. Cette reprise est donc sans risque aujourd'hui,
    et ne le serait plus après la première mise en production.
    """
    cible = ("CREATE UNIQUE INDEX IF NOT EXISTS uq_periods_division "
             "ON academic_periods(tenant_id, academic_year_id, COALESCE(division, '*'), label)")
    if is_postgres():
        # PostgreSQL nomme ses contraintes : on retire celle qui porte sur le
        # triplet sans division, quelle que soit la façon dont elle a été créée.
        rows = conn.execute("""
            SELECT c.conname FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'academic_periods' AND c.contype = 'u'""").fetchall()
        for r in rows:
            nom = r["conname"] if hasattr(r, "keys") else r[0]
            colonnes = conn.execute("""
                SELECT a.attname FROM pg_constraint c
                JOIN unnest(c.conkey) k(attnum) ON TRUE
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                WHERE c.conname = %s""" .replace("%s", "'" + nom.replace("'", "''") + "'")).fetchall()
            noms = {(x["attname"] if hasattr(x, "keys") else x[0]) for x in colonnes}
            if "division" not in noms and {"tenant_id", "label"} <= noms:
                conn.execute(f'ALTER TABLE academic_periods DROP CONSTRAINT "{nom}"')
        conn.execute(cible)
        conn.commit()
        return

    # SQLite : une contrainte de table ne se retire pas, il faut reconstruire.
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='academic_periods'").fetchone()
    if not ddl or "UNIQUE(tenant_id, academic_year_id, label)" not in (ddl["sql"] or ""):
        conn.execute(cible)
        conn.commit()
        return

    colonnes = [dict(r) for r in conn.execute("PRAGMA table_info(academic_periods)")]
    noms = [c["name"] for c in colonnes]
    avant = conn.execute("SELECT COUNT(*) n FROM academic_periods").fetchone()["n"]

    def declaration(c):
        bout = f'"{c["name"]}" {c["type"] or "TEXT"}'
        if c["notnull"]:
            bout += " NOT NULL"
        if c["dflt_value"] is not None:
            bout += f' DEFAULT {c["dflt_value"]}'
        if c["pk"]:
            bout += " PRIMARY KEY"
        return bout

    # Les clés étrangères sont désactivées le temps du remplacement : le DROP
    # d'une table référencée les ferait autrement échouer ou cascader.
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(f"CREATE TABLE academic_periods_migr ({', '.join(declaration(c) for c in colonnes)})")
    liste = ", ".join(f'"{n}"' for n in noms)
    conn.execute(f"INSERT INTO academic_periods_migr ({liste}) SELECT {liste} FROM academic_periods")
    apres = conn.execute("SELECT COUNT(*) n FROM academic_periods_migr").fetchone()["n"]
    if apres != avant:
        # On ne remplace pas une table dont la copie est incomplète.
        conn.execute("DROP TABLE academic_periods_migr")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        raise RuntimeError(
            f"Reprise de academic_periods interrompue : {avant} lignes avant, {apres} copiées.")
    conn.execute("DROP TABLE academic_periods")
    conn.execute("ALTER TABLE academic_periods_migr RENAME TO academic_periods")
    conn.execute(cible)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_periods_year ON academic_periods(tenant_id, academic_year_id, division, sort)")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def _migrate(conn):
    """Migrations additives non destructives (ALTER TABLE ... ADD COLUMN).

    Les nouvelles TABLES sont créées par schema.sql (CREATE TABLE IF NOT
    EXISTS) ; seules les nouvelles COLONNES sur des tables existantes passent
    ici, pour ne jamais effacer une base déjà remplie.
    """
    # Notifications groupées (docs/RAPPORT_SIMULATION.md)
    _add_column_if_missing(conn, "notifications", "count", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "notifications", "amount_total", "REAL")
    _add_column_if_missing(conn, "notifications", "updated_at", "TEXT")
    conn.execute("UPDATE notifications SET updated_at = created_at WHERE updated_at IS NULL")
    # Lien profond porté par une notification (ex. dossier de l'élève concerné)
    _add_column_if_missing(conn, "notifications", "link", "TEXT")
    _add_column_if_missing(conn, "notifications", "kind", "TEXT")

    # Dossier central de l'élève : identifiant lisible, identité, photo réelle
    # (jamais une photo de stock — NULL tant que l'établissement n'en fournit pas).
    _add_column_if_missing(conn, "students", "code", "TEXT")
    _add_column_if_missing(conn, "students", "gender", "TEXT")
    _add_column_if_missing(conn, "students", "birth_date", "TEXT")
    _add_column_if_missing(conn, "students", "photo_data", "TEXT")

    # Cycle d'une classe (maternelle | primaire | secondaire) — utilisé pour le
    # périmètre du Directeur des disciplines.
    _add_column_if_missing(conn, "classes", "cycle", "TEXT")

    # Libellé spécifique d'une obligation (ex. "Commande ORD-0012 — 3 cahiers")
    # qui prime sur le nom générique de l'article de catalogue.
    _add_column_if_missing(conn, "obligations", "label", "TEXT")

    # Traçabilité de la révocation d'une invitation. Une invitation révoquée
    # n'est JAMAIS supprimée : l'établissement doit pouvoir dire qui a coupé
    # quel accès, quand et pourquoi — surtout quand l'accès avait été accepté
    # et réellement utilisé.
    _add_column_if_missing(conn, "invitations", "revoked_at", "TEXT")
    _add_column_if_missing(conn, "invitations", "revoked_by", "TEXT")
    _add_column_if_missing(conn, "invitations", "revoked_reason", "TEXT")

    # Même chose côté membership : on ne détruit pas la ligne, on la désactive,
    # et on garde la date. `resolve_session` refuse tout membership dont le
    # statut n'est pas 'active' — c'est là que la coupure prend effet.
    _add_column_if_missing(conn, "memberships", "revoked_at", "TEXT")
    _add_column_if_missing(conn, "memberships", "revoked_by", "TEXT")

    # Suppression de compte : l'identité est neutralisée, la ligne conservée —
    # des paiements, des audits et des invitations pointent dessus.
    _add_column_if_missing(conn, "users", "deleted_at", "TEXT")

    # Portail par établissement (lot 1) : adresse, logo, photo, couleur,
    # drapeau optionnel, format des identifiants élèves. Téléphone de
    # connexion sur les comptes.
    _add_column_if_missing(conn, "tenants", "slug", "TEXT")
    _add_column_if_missing(conn, "tenants", "logo_data", "TEXT")
    _add_column_if_missing(conn, "tenants", "cover_data", "TEXT")
    _add_column_if_missing(conn, "tenants", "accent_color", "TEXT")
    _add_column_if_missing(conn, "tenants", "show_flag", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "tenants", "tagline", "TEXT")
    _add_column_if_missing(conn, "tenants", "code_prefix", "TEXT")
    _add_column_if_missing(conn, "tenants", "code_mode", "TEXT NOT NULL DEFAULT 'random'")
    _add_column_if_missing(conn, "users", "phone", "TEXT")

    # Lots 2–5
    _add_column_if_missing(conn, "incidents", "status", "TEXT NOT NULL DEFAULT 'open'")
    _add_column_if_missing(conn, "incidents", "decided_at", "TEXT")
    _add_column_if_missing(conn, "incidents", "closed_at", "TEXT")
    _add_column_if_missing(conn, "incidents", "report_id", "TEXT")
    _add_column_if_missing(conn, "attendance", "arrival_time", "TEXT")
    _add_column_if_missing(conn, "attendance", "source", "TEXT NOT NULL DEFAULT 'class'")
    _add_column_if_missing(conn, "memberships", "title", "TEXT")
    _add_column_if_missing(conn, "memberships", "scope_cycles", "TEXT")
    _add_column_if_missing(conn, "store_products", "options", "TEXT")
    _add_column_if_missing(conn, "order_items", "variant", "TEXT")
    _add_column_if_missing(conn, "orders", "pickup_code", "TEXT")
    _add_column_if_missing(conn, "orders", "ready_at", "TEXT")
    _add_column_if_missing(conn, "orders", "delivered_at", "TEXT")
    _add_column_if_missing(conn, "orders", "prepared_by", "TEXT")
    _add_column_if_missing(conn, "tenant_settings", "discipline_capital", "INTEGER NOT NULL DEFAULT 100")
    _add_column_if_missing(conn, "tenant_settings", "conduct_scale", "TEXT")
    _add_column_if_missing(conn, "tenant_settings", "pass_threshold", "REAL NOT NULL DEFAULT 50")
    _add_column_if_missing(conn, "tenant_settings", "store_cutoff_time", "TEXT NOT NULL DEFAULT '20:00'")
    _add_column_if_missing(conn, "tenant_settings", "parent_notify_present", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "tenant_settings", "exam_period_starts", "TEXT")
    _add_column_if_missing(conn, "tenant_settings", "exam_period_ends", "TEXT")
    _add_column_if_missing(conn, "tenant_settings", "teacher_contact_visible", "INTEGER NOT NULL DEFAULT 0")
    # Politique de diffusion des résultats, propre à chaque établissement.
    # NULL = « toujours diffuser » : aucune école ne se voit imposer une
    # condition financière qu'elle n'a pas demandée.
    _add_column_if_missing(conn, "tenant_settings", "results_policy", "TEXT")
    _add_column_if_missing(conn, "guardians", "notify_present_daily", "INTEGER NOT NULL DEFAULT 1")

    # Année scolaire d'un résultat. Sans elle, la proclamation d'une période se
    # décidait sur le seul libellé, toutes années confondues (fuite reproduite,
    # voir le rétro-remplissage en fin de _migrate).
    _add_column_if_missing(conn, "grades", "academic_year_id", "TEXT")
    _add_column_if_missing(conn, "appreciations", "academic_year_id", "TEXT")

    # ---------------------------------------------------------------------
    # SYSTÈME ACADÉMIQUE — calendrier configurable, résultats officiels.
    #
    # Rien ici n'impose un nombre de périodes : une école peut en déclarer 3,
    # 4, 6 ou 10, et en déclarer un nombre DIFFÉRENT selon la division
    # (maternelle / primaire / secondaire). Le code ne connaît ni
    # « trimestre » ni « semestre » — seulement des périodes ordonnées.
    # ---------------------------------------------------------------------

    # L'année scolaire devient une vraie période de temps, avec un état.
    # Statut d'une année. `is_active` disait seulement « c'est celle-ci » ;
    # il ne permettait pas de distinguer une année qu'on PRÉPARE d'une année
    # CLOSE. Sans cette nuance, ouvrir la préparation de 2027-2028 pendant que
    # 2026-2027 tourne encore mélangerait les deux — ce que le passage d'année
    # interdit formellement.
    #   ACTIVE      l'année en cours, celle que tout le monde voit
    #   PREPARATION en cours de construction, pas encore ouverte aux usagers
    #   ARCHIVED    close. Consultable, jamais modifiable, JAMAIS supprimée.
    _add_column_if_missing(conn, "tenant_settings", "delib_max_absences", "INTEGER")
    _add_column_if_missing(conn, "academic_years", "status", "TEXT NOT NULL DEFAULT 'ACTIVE'")
    _add_column_if_missing(conn, "academic_years", "starts_on", "TEXT")
    _add_column_if_missing(conn, "academic_years", "ends_on", "TEXT")
    _add_column_if_missing(conn, "academic_years", "status", "TEXT NOT NULL DEFAULT 'ACTIVE'")
    _add_column_if_missing(conn, "academic_years", "updated_at", "TEXT")

    # Division concernée par une période. NULL = toutes les divisions, ce qui
    # préserve exactement le comportement des périodes déjà créées.
    _add_column_if_missing(conn, "academic_periods", "division", "TEXT")
    # État explicite. Ce que les DATES disent (à venir / en cours / terminée)
    # est calculé à la lecture ; ce que la DIRECTION décide (brouillon,
    # verrouillé, archivé) est stocké ici. Voir school.period_state().
    _add_column_if_missing(conn, "academic_periods", "admin_state", "TEXT NOT NULL DEFAULT 'READY'")
    _add_column_if_missing(conn, "academic_periods", "result_entry_deadline", "TEXT")
    _add_column_if_missing(conn, "academic_periods", "validation_deadline", "TEXT")
    _add_column_if_missing(conn, "academic_periods", "proclamation_at", "TEXT")
    _add_column_if_missing(conn, "academic_periods", "locked_at", "TEXT")
    _add_column_if_missing(conn, "academic_periods", "locked_by", "TEXT")
    _add_column_if_missing(conn, "academic_periods", "updated_at", "TEXT")

    # Rattachement d'un résultat à SA période, par clé et non plus par libellé.
    # Le libellé reste en place : il est lu par le bulletin, les vues de classe
    # et le dossier élève, et le remplacer partout d'un coup casserait ces
    # lectures pour rien. La clé est la source de vérité, le libellé l'affichage.
    _add_column_if_missing(conn, "grades", "period_id", "TEXT")
    _add_column_if_missing(conn, "appreciations", "period_id", "TEXT")

    # Versionnage des résultats officiels. Une correction après proclamation
    # n'écrase pas : elle crée une version, et l'ancienne reste consultable.
    _add_column_if_missing(conn, "grades", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "grades", "is_current", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "grades", "superseded_at", "TEXT")
    _add_column_if_missing(conn, "grades", "superseded_by", "TEXT")
    _add_column_if_missing(conn, "grades", "result_import_id", "TEXT")
    _add_column_if_missing(conn, "grades", "source", "TEXT NOT NULL DEFAULT 'saisie'")

    # Accueil (Welcome Experience) : la séquence complète ne se joue qu'à la
    # PREMIÈRE activation. Ensuite, connexion → tableau de bord, sans détour.
    _add_column_if_missing(conn, "memberships", "onboarding_completed_at", "TEXT")

    # Identifiant interne de l'enseignant (TCH-XXXX-XXXX). Stable, généré par
    # le serveur, jamais choisi par l'utilisateur, et volontairement distinct
    # du compte de connexion : un enseignant peut changer de téléphone ou
    # d'e-mail, son identifiant dans l'établissement ne bouge pas.
    _add_column_if_missing(conn, "memberships", "staff_code", "TEXT")

    # Plans d'abonnement par défaut (modifiables par l'administration de la plateforme).
    if not conn.execute("SELECT 1 FROM plans LIMIT 1").fetchone():
        conn.executemany(
            "INSERT INTO plans (code, name, min_students, max_students, base_price, per_student, currency, description, sort, active) VALUES (?,?,?,?,?,?,?,?,?,1)",
            [
                ("essentiel", "Essentiel", 0, 300, 49.0, 0.0, "USD", "Jusqu'à 300 élèves — forfait fixe, toutes les fonctionnalités.", 1),
                ("ecole", "École", 301, 1000, 60.0, 0.30, "USD", "301 à 1 000 élèves — forfait + 0,30 $ par élève actif et par mois.", 2),
                ("complexe", "Complexe", 1001, 3000, 120.0, 0.20, "USD", "1 001 à 3 000 élèves — forfait + 0,20 $ par élève actif (dégressif).", 3),
                ("reseau", "Réseau", 3001, None, 0.0, 0.0, "USD", "Plusieurs établissements ou plus de 3 000 élèves — sur devis.", 4),
            ],
        )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_slug ON tenants(slug)")

    # Index manquants relevés à l'audit de mise en production. Aucun n'était
    # visible en développement : sur une base de démonstration, un parcours de
    # table complet coûte moins qu'un index. Sur les 137 000 lignes réelles, et
    # surtout à travers le réseau, ils comptent.
    #
    # - memberships : UNIQUE(user_id, tenant_id) n'aide pas une recherche par
    #   tenant_id seul — or c'est le filtre d'une douzaine de requêtes, dont le
    #   tableau de bord et chaque envoi de notification à la Direction.
    # - guardians(user_id) : c'est par là que school.py résout le périmètre d'un
    #   parent, à chaque requête d'un parent.
    # - student_guardians(guardian_id) : UNIQUE(student_id, guardian_id) couvre
    #   le sens élève → tuteurs, pas le sens tuteur → élèves, qui est celui du
    #   portail parent.
    # - sessions(user_id) : révocation de toutes les sessions d'un compte lors
    #   d'un changement ou d'une réinitialisation de mot de passe.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memberships_tenant ON memberships(tenant_id, role, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_guardians_user ON guardians(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_guardians_tenant ON guardians(tenant_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_student_guardians_guardian ON student_guardians(guardian_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    # Résultats d'une année : lus à chaque bulletin et à chaque proclamation.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grades_year ON grades(tenant_id, academic_year_id, period)")
    # Lectures du système académique : résultats courants d'une période, et
    # périodes d'une année par division.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grades_period ON grades(tenant_id, period_id, is_current)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_periods_year ON academic_periods(tenant_id, academic_year_id, division, sort)")

    conn.commit()

    # Rétro-remplissage des identifiants élèves manquants (base existante).
    import school  # import tardif : school importe db
    missing = conn.execute("SELECT id, tenant_id FROM students WHERE code IS NULL OR code = ''").fetchall()
    for row in missing:
        conn.execute("UPDATE students SET code = ? WHERE id = ?", (school.generate_student_code(conn, row["tenant_id"]), row["id"]))
    for row in conn.execute("SELECT id, name FROM tenants WHERE slug IS NULL OR slug = ''").fetchall():
        conn.execute("UPDATE tenants SET slug = ? WHERE id = ?", (school.unique_slug(conn, row["name"]), row["id"]))
    no_cycle = conn.execute("SELECT id, level, name FROM classes WHERE cycle IS NULL OR cycle = ''").fetchall()
    for row in no_cycle:
        conn.execute("UPDATE classes SET cycle = ? WHERE id = ?", (school.infer_cycle(row["level"], row["name"]), row["id"]))
    conn.commit()

    # Rattachement des résultats à leur ANNÉE SCOLAIRE.
    #
    # `grades.period` et `appreciations.period` ne portent qu'un LIBELLÉ
    # ("Période 1"). La proclamation, elle, se décidait sur ce seul libellé,
    # tous millésimes confondus : une "Période 1" proclamée en 2025-2026
    # rendait visible aux parents la "Période 1" de 2026-2027, jamais
    # proclamée. Reproduit, puis corrigé — voir school.published_period_keys().
    #
    # L'année se déduit de la classe, toujours renseignée à l'écriture ; à
    # défaut (classe supprimée depuis), l'année active de l'établissement.
    for table in ("grades", "appreciations"):
        conn.execute(
            f"""UPDATE {table} SET academic_year_id = (
                    SELECT c.academic_year_id FROM classes c
                    WHERE c.id = {table}.class_id AND c.tenant_id = {table}.tenant_id)
                WHERE academic_year_id IS NULL AND class_id IS NOT NULL"""
        )
        conn.execute(
            f"""UPDATE {table} SET academic_year_id = (
                    SELECT y.id FROM academic_years y
                    WHERE y.tenant_id = {table}.tenant_id
                    ORDER BY y.is_active DESC, y.created_at DESC LIMIT 1)
                WHERE academic_year_id IS NULL"""
        )
        # Rattachement à la période PAR CLÉ. Le couple (tenant, année, libellé)
        # est unique par construction (UNIQUE sur academic_periods), donc la
        # correspondance est exacte — pas une heuristique.
        #
        # Une ligne sans correspondance garde period_id NULL : cela signifie que
        # l'établissement n'avait pas déclaré cette période. Elle reste lisible
        # du personnel, et invisible du parent (fermeture par défaut).
        conn.execute(
            f"""UPDATE {table} SET period_id = (
                    SELECT p.id FROM academic_periods p
                    WHERE p.tenant_id = {table}.tenant_id
                      AND p.academic_year_id = {table}.academic_year_id
                      AND p.label = {table}.period)
                WHERE period_id IS NULL"""
        )
    # Une année scolaire sans dates est celle d'avant le calendrier configurable.
    # On ne lui en invente pas : l'absence de dates est une information (« cette
    # année n'a pas de calendrier »), pas un trou à combler.
    conn.execute("UPDATE academic_years SET status='ACTIVE' WHERE status IS NULL OR status=''")
    conn.commit()

    # En dernier : la reprise d'unicité reconstruit potentiellement la table,
    # elle doit donc voir toutes les colonnes déjà ajoutées.
    _unicite_periodes(conn)


def reset_db():
    """Supprime le fichier de base — utilisé uniquement par les tests."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
