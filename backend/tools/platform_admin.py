"""Outil d'exploitation Klassio — accorder ou retirer l'accès « plateforme ».

L'administration de la plateforme (établissements, abonnements, factures)
n'est jamais accordée depuis l'application : elle se fait ici, sur le serveur,
par une personne qui a déjà accès à la base. Volontairement manuel.

    python backend/tools/platform_admin.py list
    python backend/tools/platform_admin.py grant contact@klassio.cd
    python backend/tools/platform_admin.py revoke contact@klassio.cd
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import db  # noqa: E402


def main(argv):
    action = argv[1] if len(argv) > 1 else "list"
    conn = db.get_connection()
    if action == "list":
        rows = conn.execute(
            """SELECT u.id, u.name, u.email, p.created_at FROM platform_admins p JOIN users u ON u.id = p.user_id
               ORDER BY p.created_at"""
        ).fetchall()
        if not rows:
            print("Aucun administrateur de plateforme.")
        for r in rows:
            print(f"{r['name']} <{r['email'] or '—'}>  depuis {r['created_at']}")
        conn.close()
        return 0

    if len(argv) < 3:
        print(__doc__)
        conn.close()
        return 2
    ident = argv[2].strip().lower()
    user = conn.execute("SELECT * FROM users WHERE lower(email)=? OR phone=?", (ident, argv[2].strip())).fetchone()
    if not user:
        print(f"Aucun utilisateur avec l'identifiant « {argv[2]} ».")
        conn.close()
        return 1

    if action == "grant":
        conn.execute("INSERT OR IGNORE INTO platform_admins (user_id, created_at) VALUES (?,?)", (user["id"], str(time.time())))
        conn.commit()
        print(f"Accès plateforme accordé à {user['name']} <{user['email']}>.")
    elif action == "revoke":
        conn.execute("DELETE FROM platform_admins WHERE user_id=?", (user["id"],))
        conn.commit()
        print(f"Accès plateforme retiré à {user['name']} <{user['email']}>.")
    else:
        print(__doc__)
        conn.close()
        return 2
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
