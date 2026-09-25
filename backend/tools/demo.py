"""Crée la base de DÉMONSTRATION de Klassio : une école fictive, un compte par rôle.

    cp backend/.env.example backend/.env        # une fois : désigne klassio_demo.db
    python backend/tools/demo.py                # crée la base si elle n'existe pas
    python backend/tools/demo.py --recreer      # la reconstruit à l'identique

POURQUOI CET OUTIL, ALORS QUE seed_echelle.py EXISTE

Il ne génère rien lui-même : il appelle seed_echelle.py avec des réglages de
démonstration, et c'est voulu — un seul générateur, déjà éprouvé par la
campagne de charge et par verifier_invariants.py. Ce qu'il ajoute, ce sont les
protections qu'une commande destinée à un inconnu doit porter :

  • il n'écrit QUE dans une base SQLite désignée par KLASSIO_DB_PATH, jamais
    dans backend/klassio.db, la base de travail du propriétaire ;
  • il ne reconstruit une base existante que s'il peut prouver qu'elle est
    fictive : chaque compte doit appartenir au domaine réservé `.charge.test`.
    Une base qui contient un seul compte réel n'est jamais effacée ;
  • il nomme l'école « … — DÉMONSTRATION » : le nom s'affiche en tête de chaque
    écran, et personne ne peut confondre ces données avec celles d'une école.

Les données sont reproductibles (graine fixe) : deux développeurs obtiennent
les mêmes élèves, les mêmes classes, les mêmes identifiants.

Le mot de passe des comptes est publié dans le README. C'est pourquoi aucun de
ces comptes ne doit exister ailleurs que sur une machine de développement — et
pourquoi seed_echelle.py refuse désormais toute base PostgreSQL distante.
"""
import argparse
import json
import os
import sys
import tempfile

OUTILS = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.abspath(os.path.join(OUTILS, ".."))
sys.path.insert(0, RACINE)
sys.path.insert(0, OUTILS)

import config  # noqa: E402
import db  # noqa: E402

# Le domaine `.test` est réservé par la RFC 2606 : aucune adresse n'y existe.
DOMAINE_DEMO = ".charge.test"
SUFFIXE_NOM = " — DÉMONSTRATION"
REGLAGES = ["--ecoles", "1", "--eleves", "300", "--jours", "10", "--graine", "42"]


def _base_de_travail():
    return os.path.abspath(os.path.join(RACINE, "klassio.db"))


def _comptes_non_fictifs(chemin):
    """Les adresses qui NE sont PAS des comptes de démonstration."""
    import sqlite3
    conn = sqlite3.connect(chemin)
    try:
        return [r[0] for r in conn.execute("SELECT email FROM users")
                if not (r[0] or "").endswith(DOMAINE_DEMO)]
    except sqlite3.DatabaseError:
        return ["<fichier illisible : pas une base Klassio>"]
    finally:
        conn.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="Base de démonstration de Klassio (données fictives).")
    p.add_argument("--recreer", action="store_true",
                   help="reconstruire la base — uniquement si elle ne contient que des comptes fictifs")
    args = p.parse_args(argv)

    if config.DB_BACKEND != "sqlite":
        raise SystemExit(
            "Refus : la démonstration se construit sur SQLite (KLASSIO_DB_BACKEND=sqlite).\n"
            "Pour un PostgreSQL LOCAL : python backend/tools/seed_echelle.py " + " ".join(REGLAGES))

    chemin = os.path.abspath(db.DB_PATH)
    if chemin == _base_de_travail():
        raise SystemExit(
            "Refus : aucune base de démonstration n'est désignée — l'outil écrirait dans\n"
            "backend/klassio.db, la base de travail. Copiez d'abord le modèle :\n"
            "  cp backend/.env.example backend/.env\n"
            "(il désigne klassio_demo.db, une base fictive distincte).")

    if os.path.exists(chemin):
        if not args.recreer:
            print(f"La base de démonstration existe déjà : {chemin}")
            print("Pour la reconstruire à l'identique : python backend/tools/demo.py --recreer")
            return 0
        reels = _comptes_non_fictifs(chemin)
        if reels:
            raise SystemExit(
                f"Refus : {chemin} contient {len(reels)} compte(s) hors du domaine fictif "
                f"« {DOMAINE_DEMO} ».\n"
                "Ce n'est pas une base de démonstration : elle ne sera pas effacée.\n"
                "Désignez un autre fichier dans KLASSIO_DB_PATH.")
        for suffixe in ("", "-wal", "-shm"):
            if os.path.exists(chemin + suffixe):
                os.remove(chemin + suffixe)

    import seed_echelle
    with tempfile.TemporaryDirectory() as dossier:
        sortie = os.path.join(dossier, "comptes.json")
        seed_echelle.main(REGLAGES + ["--sortie", sortie])
        with open(sortie, encoding="utf-8") as f:
            env = json.load(f)

    conn = db.get_connection()
    conn.execute("UPDATE tenants SET name = name || ? WHERE name NOT LIKE ?",
                 (SUFFIXE_NOM, "%" + SUFFIXE_NOM))
    conn.commit()
    nom = conn.execute("SELECT name FROM tenants LIMIT 1").fetchone()[0]
    conn.close()

    comptes = env["etablissements"][0]["comptes"]
    libelles = {"directeur": "Direction", "discipline": "Directeur des disciplines",
                "professeur": "Professeur", "parent": "Parent"}
    print()
    print(f"  {nom}")
    print("  DONNÉES FICTIVES — aucune personne réelle, aucun e-mail n'existe.")
    print(f"  Base : {chemin}")
    print()
    for role in ("directeur", "discipline", "professeur", "parent"):
        print(f"    {libelles[role]:<27} {comptes[role]}")
    print(f"\n    Mot de passe, pour tous : {env['mot_de_passe']}")
    print("\n  Ensuite, depuis la racine du dépôt :")
    print("    python backend/app.py            (API, port 5001 — laissez tourner)")
    print("    python -m http.server 4173       (dans un second terminal)")
    print("    → http://localhost:4173/app/connexion.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
