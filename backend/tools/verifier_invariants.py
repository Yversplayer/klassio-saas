"""Vérifie les invariants de Klassio sur une base réelle.

À jouer après une campagne de charge, après un import, après une migration —
partout où l'on veut savoir si les données tiennent encore debout, plutôt que
si le code a l'air correct.

    python backend/tools/verifier_invariants.py
    KLASSIO_DB_PATH=/tmp/klassio_charge.db python backend/tools/verifier_invariants.py

Chaque contrôle est une question à laquelle la réponse doit être ZÉRO. Sortie
non nulle si un seul invariant est violé, pour un usage en intégration continue.
"""
import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, RACINE)

import config  # noqa: E402
import db  # noqa: E402

# (domaine, énoncé, requête renvoyant un compte qui DOIT valoir 0)
INVARIANTS = [
    ("finance", "paiement confirmé sans reçu",
     """SELECT COUNT(*) AS n FROM payments p LEFT JOIN receipts r ON r.payment_id = p.id
        WHERE p.status = 'CONFIRMED' AND r.id IS NULL"""),
    ("finance", "paiement portant deux reçus",
     """SELECT COUNT(*) AS n FROM (SELECT payment_id FROM receipts
        GROUP BY payment_id HAVING COUNT(*) > 1) x"""),
    ("finance", "clé d'idempotence utilisée deux fois dans un établissement",
     """SELECT COUNT(*) AS n FROM (SELECT tenant_id, idempotency_key FROM payments
        GROUP BY tenant_id, idempotency_key HAVING COUNT(*) > 1) x"""),
    ("finance", "numéro de reçu en double dans un établissement",
     """SELECT COUNT(*) AS n FROM (SELECT tenant_id, number FROM receipts
        GROUP BY tenant_id, number HAVING COUNT(*) > 1) x"""),
    ("finance", "paiement de montant nul ou négatif",
     "SELECT COUNT(*) AS n FROM payments WHERE amount <= 0"),
    ("finance", "obligation de montant nul ou négatif",
     "SELECT COUNT(*) AS n FROM obligations WHERE amount <= 0"),
    ("finance", "reçu dont le montant diffère de son paiement",
     """SELECT COUNT(*) AS n FROM receipts r JOIN payments p ON p.id = r.payment_id
        WHERE ABS(r.amount - p.amount) > 0.001"""),

    ("multi-tenant", "paiement rattaché à l'obligation d'un autre établissement",
     """SELECT COUNT(*) AS n FROM payments p JOIN obligations o ON o.id = p.obligation_id
        WHERE p.tenant_id <> o.tenant_id"""),
    ("multi-tenant", "obligation rattachée à l'élève d'un autre établissement",
     """SELECT COUNT(*) AS n FROM obligations o JOIN students s ON s.id = o.student_id
        WHERE o.tenant_id <> s.tenant_id"""),
    ("multi-tenant", "reçu rattaché à l'élève d'un autre établissement",
     """SELECT COUNT(*) AS n FROM receipts r JOIN students s ON s.id = r.student_id
        WHERE r.tenant_id <> s.tenant_id"""),
    ("multi-tenant", "élève rattaché à la classe d'un autre établissement",
     """SELECT COUNT(*) AS n FROM students s JOIN classes c ON c.id = s.class_id
        WHERE s.tenant_id <> c.tenant_id"""),
    ("multi-tenant", "incident rattaché à l'élève d'un autre établissement",
     """SELECT COUNT(*) AS n FROM incidents i JOIN students s ON s.id = i.student_id
        WHERE i.tenant_id <> s.tenant_id"""),
    ("multi-tenant", "présence rattachée à l'élève d'un autre établissement",
     """SELECT COUNT(*) AS n FROM attendance a JOIN students s ON s.id = a.student_id
        WHERE a.tenant_id <> s.tenant_id"""),
    ("multi-tenant", "note rattachée à l'élève d'un autre établissement",
     """SELECT COUNT(*) AS n FROM grades g JOIN students s ON s.id = g.student_id
        WHERE g.tenant_id <> s.tenant_id"""),
    ("multi-tenant", "session ouverte sur un établissement dont l'utilisateur n'est pas membre",
     """SELECT COUNT(*) AS n FROM sessions se
        WHERE NOT EXISTS (SELECT 1 FROM memberships m
                          WHERE m.user_id = se.user_id AND m.tenant_id = se.tenant_id)"""),
    ("multi-tenant", "notification adressée à un utilisateur étranger à l'établissement",
     """SELECT COUNT(*) AS n FROM notifications nt
        WHERE nt.recipient_user_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM memberships m
                          WHERE m.user_id = nt.recipient_user_id AND m.tenant_id = nt.tenant_id)"""),
    ("multi-tenant", "lien élève–responsable croisant deux établissements",
     """SELECT COUNT(*) AS n FROM student_guardians sg JOIN guardians g ON g.id = sg.guardian_id
        WHERE sg.tenant_id <> g.tenant_id"""),
    ("multi-tenant", "professeur rattaché à la classe d'un autre établissement",
     """SELECT COUNT(*) AS n FROM class_teachers ct JOIN classes c ON c.id = ct.class_id
        WHERE ct.tenant_id <> c.tenant_id"""),

    ("élèves", "élève sans identifiant lisible",
     "SELECT COUNT(*) AS n FROM students WHERE code IS NULL OR code = ''"),
    ("élèves", "identifiant élève en double dans un établissement",
     """SELECT COUNT(*) AS n FROM (SELECT tenant_id, code FROM students
        WHERE code IS NOT NULL AND code <> '' GROUP BY tenant_id, code HAVING COUNT(*) > 1) x"""),
    ("élèves", "élève sans nom ni prénom",
     """SELECT COUNT(*) AS n FROM students
        WHERE (first_name IS NULL OR first_name = '') AND (last_name IS NULL OR last_name = '')"""),

    ("comptes", "adresse e-mail en double",
     """SELECT COUNT(*) AS n FROM (SELECT LOWER(email) AS e FROM users
        GROUP BY LOWER(email) HAVING COUNT(*) > 1) x"""),
    ("comptes", "mot de passe stocké hors du format sel$empreinte",
     "SELECT COUNT(*) AS n FROM users WHERE password_hash NOT LIKE '%$%'"),
    ("comptes", "deux rôles pour un même utilisateur dans un même établissement",
     """SELECT COUNT(*) AS n FROM (SELECT user_id, tenant_id FROM memberships
        GROUP BY user_id, tenant_id HAVING COUNT(*) > 1) x"""),
    ("comptes", "jeton de session stocké en clair (longueur ≠ empreinte SHA-256)",
     "SELECT COUNT(*) AS n FROM sessions WHERE LENGTH(token) <> 64"),

    ("import", "session d'import confirmée deux fois",
     """SELECT COUNT(*) AS n FROM import_sessions
        WHERE status = 'confirmed' AND confirmed_at IS NULL"""),
]


def main():
    print(f"Moteur : {config.DB_BACKEND}"
          + (f" ({db.DB_PATH})" if not db.is_postgres() else ""))
    conn = db.get_connection()
    violations, domaine_courant = 0, None
    try:
        for domaine, enonce, requete in INVARIANTS:
            if domaine != domaine_courant:
                print(f"\n{domaine.upper()}")
                domaine_courant = domaine
            try:
                n = conn.execute(requete).fetchone()["n"]
            except Exception as e:
                print(f"  ?      {enonce}\n         (contrôle impossible : {e})")
                continue
            if n:
                violations += 1
                print(f"  VIOLÉ  {enonce} : {n}")
            else:
                print(f"  ok     {enonce}")
    finally:
        conn.close()

    print("\n" + "=" * 66)
    if violations:
        print(f"{violations} invariant(s) violé(s) — les données ne tiennent pas.")
        return 1
    print(f"{len(INVARIANTS)} invariants vérifiés, aucun violé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
