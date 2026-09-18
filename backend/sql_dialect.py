"""KLASSIO — traduction de dialecte SQL (SQLite → PostgreSQL).

Le backend compte près de 500 appels `conn.execute("… ?", params)`. Plutôt
que de réécrire chacun d'eux — et d'y introduire des fautes — on traduit les
marqueurs au moment de l'exécution, en un seul endroit. Les requêtes elles-
mêmes restent identiques et continuent de tourner sur SQLite.

Trois pièges évités ici :
  - un `?` à l'intérieur d'une chaîne SQL ('a?b') ne doit pas être traduit ;
  - un `%` déjà présent (LIKE '%x%') doit être doublé pour psycopg, qui
    interprète `%` comme le début d'un marqueur ;
  - un commentaire SQL (`-- …` ou `/* … */`) n'est pas du code : une apostrophe
    qui s'y trouve — « n'accepte pas », en français c'est vite arrivé — ne doit
    pas être lue comme l'ouverture d'une chaîne. Sans cette précaution, tous les
    `?` situés après le commentaire cessaient d'être traduits, et PostgreSQL
    recevait des `?` littéraux qu'il rejette.
"""

_QUOTES = "'\""


def to_pyformat(sql):
    """`SELECT … WHERE a=? AND b LIKE '%x%'` → `… WHERE a=%s AND b LIKE '%%x%%'`."""
    out = []
    i, n = 0, len(sql)
    quote = None
    while i < n:
        c = sql[i]
        if quote:
            # Dans une chaîne : on ne traduit rien, on protège seulement les %.
            if c == "%":
                out.append("%%")
            else:
                out.append(c)
            if c == quote:
                # '' et "" échappent le délimiteur en SQL.
                if i + 1 < n and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        # Commentaire de fin de ligne : recopié tel quel jusqu'au saut de ligne.
        # Seuls les % y sont doublés — psycopg lit le pourcentage partout dans
        # la requête, commentaires compris.
        if c == "-" and sql[i + 1:i + 2] == "-":
            fin = sql.find("\n", i)
            fin = n if fin == -1 else fin
            out.append(sql[i:fin].replace("%", "%%"))
            i = fin
            continue
        # Commentaire encadré. Un /* non refermé va jusqu'à la fin, comme le
        # ferait le serveur.
        if c == "/" and sql[i + 1:i + 2] == "*":
            fin = sql.find("*/", i + 2)
            fin = n if fin == -1 else fin + 2
            out.append(sql[i:fin].replace("%", "%%"))
            i = fin
            continue
        if c in _QUOTES:
            quote = c
            out.append(c)
        elif c == "?":
            out.append("%s")
        elif c == "%":
            out.append("%%")
        else:
            out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Traduction du schéma
# ---------------------------------------------------------------------------

_TYPE_MAP = (
    ("REAL", "DOUBLE PRECISION"),
    ("BLOB", "BYTEA"),
)


def schema_to_postgres(sql):
    """Traduit `schema.sql` (SQLite) en DDL PostgreSQL.

    Le schéma de Klassio est volontairement simple — TEXT, INTEGER, REAL, des
    clés primaires textuelles (UUID générés en Python), aucune colonne
    AUTOINCREMENT — ce qui rend la traduction mécanique et sûre.
    """
    import re

    out = sql
    # Les PRAGMA n'existent pas en PostgreSQL (les clés étrangères y sont
    # toujours appliquées : le PRAGMA de SQLite n'a pas d'équivalent utile).
    out = re.sub(r"^\s*PRAGMA[^;]*;\s*$", "", out, flags=re.MULTILINE | re.IGNORECASE)
    # Types
    for src, dst in _TYPE_MAP:
        out = re.sub(rf"\b{src}\b", dst, out)
    # SQLite tolère `IF NOT EXISTS` partout : Postgres aussi pour TABLE/INDEX.
    # Les contraintes CHECK, FOREIGN KEY, UNIQUE et DEFAULT sont compatibles.
    # `AUTOINCREMENT` n'existe pas dans ce schéma (vérifié) ; on le signale si
    # jamais il apparaissait un jour.
    if "AUTOINCREMENT" in out:
        raise ValueError("AUTOINCREMENT rencontré : traduction manuelle nécessaire (GENERATED AS IDENTITY).")
    # SQLite écrit parfois `DEFAULT (datetime('now'))` — absent ici, mais on refuse
    # silencieusement de produire du DDL faux.
    for fonction in ("datetime(", "strftime(", "julianday("):
        if fonction in out:
            raise ValueError(f"Fonction SQLite `{fonction}` dans le schéma : traduction manuelle nécessaire.")
    return out
