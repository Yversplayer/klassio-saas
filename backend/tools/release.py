"""Phase `release` du déploiement : prépare le schéma avant la bascule.

Joué par le Procfile. Gunicorn importe `app:app` directement, sans passer par
le bloc `if __name__ == "__main__"` de backend/app.py — sans ce script,
`db.init_db()` ne serait jamais appelé en production et les migrations
additives (nouvelles colonnes) ne seraient jamais appliquées.

Non destructif par construction : `init_db()` ne fait que CREATE TABLE IF NOT
EXISTS et ALTER TABLE … ADD COLUMN.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import config  # noqa: E402
import db      # noqa: E402


def main():
    print(f"Klassio release — moteur : {config.DB_BACKEND}")
    if config.DB_BACKEND == "postgres" and not config.SUPABASE_DB_URL:
        print("ERREUR : KLASSIO_DB_BACKEND=postgres mais SUPABASE_DB_URL est absente.", file=sys.stderr)
        return 1
    db.init_db()
    print("Schéma et migrations additives appliqués.")

    # Hygiène : les sessions expirées ne sont effacées que si quelqu'un
    # présente leur jeton — ce qui n'arrive jamais. Sans ce passage, la table
    # grossit indéfiniment et conserve des secrets périmés.
    import security
    conn = db.get_connection()
    try:
        supprimees = security.purger_sessions_expirees(conn)
    finally:
        conn.close()
    print(f"Sessions expirées purgées : {supprimees}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
