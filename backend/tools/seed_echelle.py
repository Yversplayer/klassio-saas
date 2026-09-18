"""Génère un jeu de données à grande échelle pour l'audit de performance.

`seed_charge.py` crée deux établissements via l'API : réaliste, mais lent, et
il ne produit ni présences, ni notes, ni incidents, ni notifications. Or c'est
précisément la croissance de ces tables-là qui use les requêtes du tableau de
bord (voir DEPLOIEMENT.md : plusieurs agrégats balayent tout l'historique du
locataire).

Cet outil écrit directement en base, par lots, pour atteindre des volumes
qu'aucune API ne produirait en un temps raisonnable. Il reste fidèle au modèle :
mêmes tables, mêmes clés étrangères, mêmes invariants — `verifier_invariants.py`
doit rester vert après son passage.

    python backend/tools/seed_echelle.py --ecoles 5 --eleves 2000 --jours 30

L'option `--ajouter-jours` ajoute de l'historique de présences à un jeu déjà
généré, sans rien recréer : c'est ce qui permet de mesurer l'effet du VOLUME à
charge constante.

Refuse de toucher `backend/klassio.db`.
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
from security import hash_password, new_id  # noqa: E402

MOT_DE_PASSE = "ChargeKlassio2026!"
LOT = 2000  # lignes par executemany

NOMS = ["Mbala", "Ilunga", "Kabongo", "Cimanga", "Bilonda", "Tshibangu", "Mukendi", "Kasongo",
        "Ngoy", "Mwamba", "Lukusa", "Badibanga", "Nkulu", "Kanyinda", "Mutombo", "Kalala"]
PRENOMS = ["Kevin", "Sarah", "Jonas", "Grace", "Patrick", "Esther", "Daniel", "Naomie",
           "Christian", "Deborah", "Emmanuel", "Ruth", "Josue", "Marthe", "Gloire", "Benie"]
MATIERES = ["Mathématiques", "Français", "Sciences", "Histoire", "Anglais", "Éducation civique"]
CYCLES = [("1e", "primaire"), ("2e", "primaire"), ("3e", "primaire"),
          ("4e", "secondaire"), ("5e", "secondaire"), ("6e", "secondaire")]
SECTIONS = ["A", "B", "C", "D", "E", "F", "G"]
CATEGORIES_INCIDENT = ["retard", "absence", "comportement", "autre"]
STATUTS_PRESENCE = ["present"] * 88 + ["absent"] * 7 + ["late"] * 4 + ["excused"]


def _horodatage(decalage_jours=0):
    return str(time.time() - decalage_jours * 86400)


def _jours_ouvres(nombre, fin=None):
    """N derniers jours de classe, week-ends exclus."""
    from datetime import date, timedelta
    jour = fin or date.today()
    sortie = []
    while len(sortie) < nombre:
        if jour.weekday() < 5:
            sortie.append(jour.isoformat())
        jour -= timedelta(days=1)
    return sortie


def _inserer(conn, sql, lignes):
    for i in range(0, len(lignes), LOT):
        conn.executemany(sql, lignes[i:i + LOT])
    conn.commit()
    return len(lignes)


def creer_ecole(conn, indice, nb_eleves, jours, alea):
    etiquette = f"ecole{indice}"
    tenant_id, annee_id = new_id(), new_id()
    maintenant = _horodatage()
    nom_ecole = f"Complexe Scolaire {etiquette.title()}"

    conn.execute("INSERT INTO tenants (id, name, status, created_at, slug) VALUES (?,?,'active',?,?)",
                 (tenant_id, nom_ecole, maintenant, etiquette))
    conn.execute("INSERT INTO academic_years (id, tenant_id, label, is_active, created_at) VALUES (?,?,?,1,?)",
                 (annee_id, tenant_id, "2026-2027", maintenant))

    # ---- comptes : un par rôle, plus des professeurs et des parents ----
    empreinte = hash_password(MOT_DE_PASSE)
    comptes, membres = {}, []

    def compte(role, suffixe, nom_affiche):
        uid = new_id()
        courriel = f"{suffixe}@{etiquette}.charge.test"
        conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?,?,?,?,?)",
                     (uid, courriel, empreinte, nom_affiche, maintenant))
        membres.append((new_id(), uid, tenant_id, role, "active", maintenant))
        return uid, courriel

    uid_dir, comptes["directeur"] = compte("directeur", "direction", f"Direction {etiquette}")[0], f"direction@{etiquette}.charge.test"
    uid_dd, comptes["discipline"] = compte("discipline", "discipline", f"Discipline {etiquette}")[0], f"discipline@{etiquette}.charge.test"
    profs = []
    for n in range(8):
        uid, courriel = compte("professeur", f"prof{n}", f"Professeur {n} {etiquette}")
        profs.append(uid)
        if n == 0:
            comptes["professeur"] = courriel
    parents_uid = []
    for n in range(12):
        uid, courriel = compte("parent", f"parent{n}", f"Parent {n} {etiquette}")
        parents_uid.append(uid)
        if n == 0:
            comptes["parent"] = courriel
    _inserer(conn, "INSERT INTO memberships (id, user_id, tenant_id, role, status, created_at) VALUES (?,?,?,?,?,?)", membres)

    # ---- classes ----
    classes = []
    for niveau, cycle in CYCLES:
        for section in SECTIONS:
            classes.append((new_id(), tenant_id, annee_id, f"{niveau} {section}", niveau, cycle, maintenant))
    _inserer(conn, "INSERT INTO classes (id, tenant_id, academic_year_id, name, level, cycle, created_at) VALUES (?,?,?,?,?,?,?)", classes)
    ids_classes = [c[0] for c in classes]

    # les professeurs se partagent les classes ; le premier est titulaire
    rattachements = []
    for i, cid in enumerate(ids_classes):
        rattachements.append((new_id(), tenant_id, cid, profs[i % len(profs)], MATIERES[i % len(MATIERES)], 1 if i % len(profs) == 0 else 0, maintenant))
    _inserer(conn, "INSERT INTO class_teachers (id, tenant_id, class_id, user_id, subject, is_titulaire, created_at) VALUES (?,?,?,?,?,?,?)", rattachements)

    # ---- élèves, responsables ----
    eleves, tuteurs, liens = [], [], []
    for i in range(nb_eleves):
        sid = new_id()
        cid = ids_classes[i % len(ids_classes)]
        code = f"STU-{indice}{i:06d}"
        eleves.append((sid, tenant_id, annee_id, cid, alea.choice(PRENOMS), f"{alea.choice(NOMS)}{i}",
                       code, alea.choice(["F", "M"]), "active", maintenant))
        if alea.random() > 0.10:                      # ~90 % ont un responsable
            gid = new_id()
            uid_parent = parents_uid[i % len(parents_uid)] if i < len(parents_uid) * 3 else None
            tuteurs.append((gid, tenant_id, alea.choice(PRENOMS), alea.choice(NOMS),
                            f"+243 8{alea.randint(10,99)} {alea.randint(100,999)} {alea.randint(100,999)}",
                            None, uid_parent, maintenant))
            liens.append((new_id(), tenant_id, sid, gid, "Parent"))
    _inserer(conn, "INSERT INTO students (id, tenant_id, academic_year_id, class_id, first_name, last_name, code, gender, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", eleves)
    _inserer(conn, "INSERT INTO guardians (id, tenant_id, first_name, last_name, phone, email, user_id, created_at) VALUES (?,?,?,?,?,?,?,?)", tuteurs)
    _inserer(conn, "INSERT INTO student_guardians (id, tenant_id, student_id, guardian_id, relationship) VALUES (?,?,?,?,?)", liens)
    ids_eleves = [e[0] for e in eleves]

    # ---- finance : catalogue, obligations, paiements confirmés, reçus ----
    item_id = new_id()
    conn.execute("INSERT INTO catalog_items (id, tenant_id, name, category, amount, currency, created_at) VALUES (?,?,?,?,?,?,?)",
                 (item_id, tenant_id, "Frais de scolarité", "Scolarité", 300.0, "USD", maintenant))
    obligations, paiements, recus, ecritures = [], [], [], []
    numero = 0
    for i, sid in enumerate(ids_eleves):
        oid = new_id()
        montant = alea.choice([250.0, 300.0, 350.0, 400.0])
        obligations.append((oid, tenant_id, sid, annee_id, item_id, montant, "USD", None, "ISSUED", maintenant))
        if alea.random() < 0.60:                       # ~60 % ont payé
            pid, verse = new_id(), round(montant * alea.choice([0.25, 0.5, 1.0]), 2)
            quand = _horodatage(alea.randint(0, 60))
            paiements.append((pid, tenant_id, oid, verse, "USD", "cash", "CONFIRMED",
                              f"seed-{indice}-{i}", uid_dir, quand, quand, "SEED"))
            numero += 1
            recus.append((new_id(), tenant_id, f"REC-2026-{indice}{numero:05d}", pid, sid, verse,
                          "USD", "cash", "Frais de scolarité", quand))
            ecritures.append((new_id(), tenant_id, "payment_confirmed", "payment", pid, verse, "USD", quand))
    _inserer(conn, "INSERT INTO obligations (id, tenant_id, student_id, academic_year_id, catalog_item_id, amount, currency, due_date, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", obligations)
    _inserer(conn, "INSERT INTO payments (id, tenant_id, obligation_id, amount, currency, method, status, idempotency_key, created_by, created_at, confirmed_at, provider_reference) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", paiements)
    _inserer(conn, "INSERT INTO receipts (id, tenant_id, number, payment_id, student_id, amount, currency, method, label, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", recus)
    _inserer(conn, "INSERT INTO ledger_entries (id, tenant_id, entry_type, reference_type, reference_id, amount, currency, created_at) VALUES (?,?,?,?,?,?,?,?)", ecritures)

    # ---- notes : 6 matières × 2 périodes ----
    notes = []
    for e in eleves:
        for periode in ("Période 1", "Période 2"):
            for matiere in MATIERES:
                notes.append((new_id(), tenant_id, e[0], e[3], matiere, periode,
                              float(alea.randint(4, 20)), 20.0, uid_dir, maintenant))
    _inserer(conn, "INSERT INTO grades (id, tenant_id, student_id, class_id, subject, period, score, max_score, recorded_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", notes)

    # ---- discipline ----
    incidents = []
    for _ in range(nb_eleves // 10):
        e = alea.choice(eleves)
        incidents.append((new_id(), tenant_id, e[0], alea.choice(CATEGORIES_INCIDENT),
                          "Incident de discipline", alea.choice(["low", "medium", "high"]),
                          -alea.choice([2, 5, 10, 15]), uid_dd,
                          alea.choice(_jours_ouvres(20)),
                          maintenant, "open"))
    _inserer(conn, "INSERT INTO incidents (id, tenant_id, student_id, category, title, severity, points, recorded_by, occurred_at, created_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", incidents)

    # ---- notifications ----
    notifs = []
    for i in range(min(nb_eleves, 3000)):
        dest = alea.choice(parents_uid + [uid_dir, uid_dd])
        notifs.append((new_id(), tenant_id, dest, None, "Information", "Message de l'établissement",
                       "NORMAL", 1, None, maintenant, maintenant, None, "info", "unread"))
    _inserer(conn, "INSERT INTO notifications (id, tenant_id, recipient_user_id, event_id, title, body, priority, count, amount_total, created_at, updated_at, link, kind, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", notifs)

    n_presences = ajouter_presences(conn, tenant_id, eleves, jours, uid_dir, alea)

    return {
        "etiquette": etiquette, "tenant_id": tenant_id, "nom": nom_ecole,
        "comptes": comptes,
        "eleves_count": len(eleves), "classes_count": len(classes),
        "exemples": {"eleve_id": ids_eleves[0], "eleve_code": eleves[0][6],
                     "eleve_nom": eleves[0][5], "class_id": ids_classes[0]},
        "volumes": {"eleves": len(eleves), "tuteurs": len(tuteurs), "obligations": len(obligations),
                    "paiements": len(paiements), "recus": len(recus), "notes": len(notes),
                    "incidents": len(incidents), "notifications": len(notifs),
                    "presences": n_presences},
    }


def ajouter_presences(conn, tenant_id, eleves, jours, auteur, alea, depuis=0):
    """Historique d'appel : une ligne par élève et par jour de classe."""
    if jours <= 0:
        return 0
    total = 0
    for date_jour in _jours_ouvres(jours + depuis)[depuis:]:
        maintenant = _horodatage()
        lignes = [(new_id(), tenant_id, e[0], e[3], date_jour, alea.choice(STATUTS_PRESENCE),
                   None, auteur, maintenant, maintenant, "class") for e in eleves]
        total += _inserer(conn,
            "INSERT INTO attendance (id, tenant_id, student_id, class_id, date, status, note, recorded_by, created_at, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            lignes)
    return total


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ecoles", type=int, default=5)
    p.add_argument("--eleves", type=int, default=2000, help="élèves par établissement")
    p.add_argument("--jours", type=int, default=20, help="jours d'appel générés")
    p.add_argument("--ajouter-jours", type=int, default=0,
                   help="ajoute N jours d'appel à un jeu existant, sans rien recréer")
    p.add_argument("--sortie", default="tools/k6/env-echelle.json")
    p.add_argument("--base-url", default="http://127.0.0.1:5010")
    p.add_argument("--graine", type=int, default=42)
    args = p.parse_args(argv)

    if not db.is_postgres() and os.path.abspath(db.DB_PATH) == os.path.abspath(os.path.join(RACINE, "klassio.db")):
        raise SystemExit("Refus : ce script peuplerait backend/klassio.db, la base de travail.\n"
                         "Visez une base jetable : KLASSIO_DB_PATH=/tmp/klassio_echelle.db …")

    chemin_sortie = args.sortie if os.path.isabs(args.sortie) else os.path.join(RACINE, "..", args.sortie)
    alea = random.Random(args.graine)

    if args.ajouter_jours:
        with open(chemin_sortie, encoding="utf-8") as f:
            env = json.load(f)
        conn = db.get_connection()
        try:
            deja = env.get("jours_appel", 0)
            for etab in env["etablissements"]:
                eleves = conn.execute(
                    "SELECT id, tenant_id, academic_year_id, class_id FROM students WHERE tenant_id=?",
                    (etab["tenant_id"],)).fetchall()
                lot = [(r["id"], r["tenant_id"], r["academic_year_id"], r["class_id"]) for r in eleves]
                debut = time.time()
                n = ajouter_presences(conn, etab["tenant_id"], lot, args.ajouter_jours,
                                      None, alea, depuis=deja)
                etab["volumes"]["presences"] = etab["volumes"].get("presences", 0) + n
                print(f"  {etab['etiquette']:8s} +{n} présences ({time.time()-debut:.1f}s)")
            env["jours_appel"] = deja + args.ajouter_jours
        finally:
            conn.close()
        with open(chemin_sortie, "w", encoding="utf-8") as f:
            json.dump(env, f, indent=2, ensure_ascii=False)
        print(f"\nHistorique porté à {env['jours_appel']} jours d'appel.")
        return 0

    print(f"Moteur : {config.DB_BACKEND}" + (f" ({db.DB_PATH})" if not db.is_postgres() else ""))
    db.init_db()
    conn = db.get_connection()
    etablissements = []
    try:
        for i in range(1, args.ecoles + 1):
            debut = time.time()
            etab = creer_ecole(conn, i, args.eleves, args.jours, alea)
            v = etab["volumes"]
            print(f"  {etab['etiquette']:8s} {v['eleves']:>6} élèves  {v['notes']:>7} notes  "
                  f"{v['presences']:>7} présences  {v['paiements']:>6} paiements   ({time.time()-debut:.1f}s)")
            etablissements.append(etab)
    finally:
        conn.close()

    env = {"base_url": args.base_url.rstrip("/"), "mot_de_passe": MOT_DE_PASSE,
           "etablissements": etablissements, "jours_appel": args.jours,
           "moteur": config.DB_BACKEND, "genere_le": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.dirname(chemin_sortie), exist_ok=True)
    with open(chemin_sortie, "w", encoding="utf-8") as f:
        json.dump(env, f, indent=2, ensure_ascii=False)
    total = {k: sum(e["volumes"][k] for e in etablissements) for k in etablissements[0]["volumes"]}
    print(f"\nTotal : " + "  ".join(f"{k}={v}" for k, v in total.items()))
    print(f"Environnement : {os.path.abspath(chemin_sortie)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
