"""Émet les reçus manquants d'anciens paiements confirmés.

Pourquoi cet outil existe : `verifier_invariants.py` a relevé 6 896 paiements
confirmés sans reçu dans la base de développement. L'enquête a montré qu'ils
sont TOUS antérieurs au premier reçu jamais émis — le mécanisme d'émission a
été ajouté après coup, et il est correct depuis. Aucun paiement récent n'est
concerné.

Mais une base qui viole son propre invariant n'est pas une base sur laquelle on
commence une campagne de tests sérieuse : on ne saurait plus distinguer un
défaut ancien d'une régression nouvelle. Cet outil remet la base en accord avec
ses règles.

Strictement additif : il n'écrit que des lignes `receipts`, ne touche à aucun
paiement, ne supprime rien. Simulation par défaut.

    python backend/tools/reparer_recus.py                # simulation
    python backend/tools/reparer_recus.py --appliquer    # écrit réellement
"""
import argparse
import os
import sys

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, RACINE)

import config  # noqa: E402
import db  # noqa: E402
import financial  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--appliquer", action="store_true",
                   help="écrit réellement (sans ce drapeau, simulation seule)")
    p.add_argument("--limite", type=int, default=0, help="s'arrêter après N reçus (0 = tous)")
    args = p.parse_args(argv)

    print(f"Moteur : {config.DB_BACKEND}"
          + (f" ({db.DB_PATH})" if not db.is_postgres() else ""))
    conn = db.get_connection()
    try:
        orphelins = conn.execute(
            """SELECT p.id, p.tenant_id, p.obligation_id, p.amount, p.currency, p.method,
                      p.confirmed_at
               FROM payments p LEFT JOIN receipts r ON r.payment_id = p.id
               WHERE p.status = 'CONFIRMED' AND r.id IS NULL
               ORDER BY p.confirmed_at"""
        ).fetchall()
        print(f"Paiements confirmés sans reçu : {len(orphelins)}")
        if not orphelins:
            print("Rien à faire.")
            return 0
        if not args.appliquer:
            print("\nSimulation — rien ne sera écrit. Relancez avec --appliquer.\n")

        emis, ignores = 0, 0
        for ligne in orphelins:
            if args.limite and emis >= args.limite:
                break
            obligation = conn.execute("SELECT * FROM obligations WHERE id=?",
                                      (ligne["obligation_id"],)).fetchone()
            if not obligation:
                ignores += 1
                continue
            eleve = conn.execute("SELECT * FROM students WHERE id=?",
                                 (obligation["student_id"],)).fetchone()
            if not eleve:
                ignores += 1
                continue
            if args.appliquer:
                # Exactement la même fonction que le circuit normal : le reçu
                # réparé est indiscernable d'un reçu émis à l'encaissement.
                financial.issue_receipt(conn, ligne["tenant_id"], dict(ligne),
                                        dict(obligation), dict(eleve))
            emis += 1
            if emis % 500 == 0:
                print(f"  … {emis} reçus")

        print(f"\nReçus {'émis' if args.appliquer else 'à émettre'} : {emis}")
        if ignores:
            print(f"Paiements ignorés (obligation ou élève supprimé) : {ignores}")
            print("Ces paiements ne peuvent pas recevoir de reçu : le reçu nomme un élève.")
    finally:
        conn.close()

    if args.appliquer:
        print("\nRelancez backend/tools/verifier_invariants.py pour contrôler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
