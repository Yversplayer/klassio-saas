"""Construit un environnement de test de charge réaliste, et rien d'autre.

Objectif : donner à K6 (ou à tout autre outil) de quoi exercer Klassio dans des
conditions proches du réel — deux établissements peuplés, des comptes de chaque
rôle avec des mots de passe connus, et un fichier d'environnement JSON que les
scripts lisent.

Deux établissements, pas un : la moitié des choses qui cassent en production
sont des fuites entre locataires, et elles ne se voient que sous charge
concurrente, quand deux sessions travaillent en même temps.

    python backend/tools/seed_charge.py --eleves 2000 --sortie tools/k6/env.json

La base visée est celle de KLASSIO_DB_PATH (SQLite) ou SUPABASE_DB_URL
(PostgreSQL). Par sécurité, le script REFUSE de peupler la base de travail
`backend/klassio.db` : un jeu de charge n'a rien à y faire.
"""
import argparse
import json
import os
import random
import sys
import time

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, RACINE)

import config  # noqa: E402
import db  # noqa: E402

MOT_DE_PASSE = "ChargeKlassio2026!"

NOMS = ["Mbala", "Ilunga", "Kabongo", "Cimanga", "Bilonda", "Tshibangu", "Mukendi",
        "Kasongo", "Ngoy", "Mwamba", "Lukusa", "Badibanga", "Nkulu", "Kanyinda"]
PRENOMS = ["Kevin", "Sarah", "Jonas", "Grace", "Patrick", "Esther", "Daniel", "Naomie",
           "Christian", "Deborah", "Emmanuel", "Ruth", "Josue", "Marthe"]
NIVEAUX = ["1e", "2e", "3e", "4e", "5e", "6e"]
SECTIONS = ["A", "B", "C", "D"]


def _enregistrements(nombre, graine):
    """Des lignes d'import réalistes : quelques trous, comme un vrai fichier."""
    alea = random.Random(graine)
    lignes = []
    for i in range(nombre):
        niveau = NIVEAUX[i % len(NIVEAUX)]
        section = SECTIONS[(i // len(NIVEAUX)) % len(SECTIONS)]
        frais = alea.choice([250, 300, 350, 400])
        # ~35 % des élèves ont déjà versé quelque chose, ~10 % n'ont pas de
        # responsable renseigné — proportions observées sur le fichier réel.
        verse = alea.choice([0, 0, frais, frais // 2, frais // 3])
        a_parent = alea.random() > 0.10
        lignes.append({
            "first_name": alea.choice(PRENOMS),
            "last_name": f"{alea.choice(NOMS)}{i}",
            "class_name": f"{niveau} {section}",
            "guardian_name": f"{alea.choice(PRENOMS)} {alea.choice(NOMS)}" if a_parent else None,
            "guardian_phone": f"+243 8{alea.randint(10, 99)} {alea.randint(100, 999)} {alea.randint(100, 999)}" if a_parent else None,
            "fee_amount": frais,
            "paid_amount": verse,
        })
    return lignes


def _creer_etablissement(conn, app_client, etiquette, nombre_eleves, graine):
    import ingestion
    import security

    courriel = f"direction@{etiquette}.charge.test"
    reponse = app_client.post("/api/auth/register-school", json={
        "email": courriel, "password": MOT_DE_PASSE,
        "name": f"Direction {etiquette}", "school_name": f"Complexe {etiquette.title()}"})
    assert reponse.status_code == 201, reponse.get_data(as_text=True)
    corps = reponse.get_json()
    entetes = {"Authorization": "Bearer " + corps["token"]}
    tenant_id = corps["tenant_id"]
    # /api/auth/register-school ne renvoie pas l'identifiant utilisateur ;
    # on le relit par /api/me plutôt que de l'inventer.
    user_id = app_client.get("/api/me", headers=entetes).get_json()["user_id"]

    debut = time.time()
    resultat = ingestion.bootstrap_school(conn, tenant_id, user_id, {
        "school_name": f"Complexe {etiquette.title()}",
        "academic_year": "2026-2027",
        "records": _enregistrements(nombre_eleves, graine)})
    duree = time.time() - debut

    eleves = app_client.get("/api/students", headers=entetes).get_json()
    classes = app_client.get("/api/classes", headers=entetes).get_json()

    def inviter(role, courriel_invite, **extra):
        inv = app_client.post("/api/invitations", json=dict({"role": role}, **extra), headers=entetes)
        assert inv.status_code == 201, inv.get_data(as_text=True)
        acc = app_client.post("/api/invitations/accept", json={
            "token": inv.get_json()["token"], "name": f"{role.title()} {etiquette}",
            "email": courriel_invite, "password": MOT_DE_PASSE})
        assert acc.status_code == 201, acc.get_data(as_text=True)
        return courriel_invite

    prof = inviter("professeur", f"prof@{etiquette}.charge.test",
                   class_ids=[c["id"] for c in classes[:4]],
                   titulaire_class_id=classes[0]["id"])
    dd = inviter("discipline", f"dd@{etiquette}.charge.test")
    parent = inviter("parent", f"parent@{etiquette}.charge.test",
                     student_ids=[e["id"] for e in eleves[:3]])

    print(f"  {etiquette:8s} {len(eleves):>5} élèves, {len(classes):>3} classes, "
          f"{resultat['guardians_count']:>5} responsables, "
          f"{resultat['payments_count']:>5} règlements   ({duree:.1f}s)")
    return {
        "etiquette": etiquette,
        "tenant_id": tenant_id,
        "comptes": {"directeur": courriel, "professeur": prof, "discipline": dd, "parent": parent},
        "eleves_count": len(eleves),
        "classes_count": len(classes),
        # Quelques identifiants réels, pour que les scripts n'aient pas à
        # deviner — et pour que les tests d'isolation aient de vraies cibles.
        "exemples": {
            "eleve_id": eleves[0]["id"],
            "eleve_code": eleves[0]["code"],
            "eleve_nom": eleves[0]["last_name"],
            "class_id": classes[0]["id"],
        },
    }


def main(argv=None):
    parseur = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parseur.add_argument("--eleves", type=int, default=2000,
                         help="élèves par établissement (défaut : 2000)")
    parseur.add_argument("--sortie", default="tools/k6/env.json",
                         help="fichier d'environnement pour les scripts de charge")
    parseur.add_argument("--base-url", default="http://127.0.0.1:5001",
                         help="adresse du serveur que les scripts viseront")
    parseur.add_argument("--base-distante-jetable", action="store_true",
                         help="autoriser une base PostgreSQL DISTANTE, uniquement si elle est vide")
    args = parseur.parse_args(argv)

    # AVANT toute connexion : une base distante n'est jamais peuplée par
    # défaut — voir db.exiger_base_jetable.
    db.exiger_base_jetable("seed_charge.py", args.base_distante_jetable)

    if not db.is_postgres():
        chemin = os.path.abspath(db.DB_PATH)
        defaut = os.path.abspath(os.path.join(RACINE, "klassio.db"))
        if chemin == defaut:
            raise SystemExit(
                "Refus : ce script peuplerait backend/klassio.db, la base de travail.\n"
                "Visez une base jetable :\n"
                "  KLASSIO_DB_PATH=/tmp/klassio_charge.db python backend/tools/seed_charge.py")

    print(f"Moteur : {config.DB_BACKEND}"
          + (f" ({db.DB_PATH})" if not db.is_postgres() else ""))
    db.init_db()

    import app as application
    import security
    client = application.app.test_client()
    security.reset_rate_limits_for_tests()

    conn = db.get_connection()
    try:
        etablissements = [
            _creer_etablissement(conn, client, "alpha", args.eleves, graine=1),
            _creer_etablissement(conn, client, "beta", max(args.eleves // 4, 50), graine=2),
        ]
    finally:
        conn.close()

    environnement = {
        "base_url": args.base_url.rstrip("/"),
        "mot_de_passe": MOT_DE_PASSE,
        "etablissements": etablissements,
        "genere_le": time.strftime("%Y-%m-%d %H:%M:%S"),
        "moteur": config.DB_BACKEND,
    }
    chemin_sortie = os.path.abspath(os.path.join(RACINE, "..", args.sortie)) \
        if not os.path.isabs(args.sortie) else args.sortie
    os.makedirs(os.path.dirname(chemin_sortie), exist_ok=True)
    with open(chemin_sortie, "w", encoding="utf-8") as f:
        json.dump(environnement, f, indent=2, ensure_ascii=False)
    print(f"\nEnvironnement écrit dans {chemin_sortie}")
    print(f"Tous les comptes ont le mot de passe : {MOT_DE_PASSE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
