"""KLASSIO — garde-fou sur le PLAN D'EXÉCUTION des requêtes sensibles.

Pourquoi ce fichier existe.

Le défaut P1 — des sous-requêtes qui omettaient `tenant_id`, colonne de tête
des index — n'a été attrapé par AUCUN des 163 tests existants, et il ne
pouvait pas l'être : les résultats étaient justes. Seul le COÛT était faux.
Sur la base de développement (249 lignes de présence) un balayage complet
coûte moins cher qu'un parcours d'index ; le défaut ne devient visible qu'à
partir de quelques dizaines de milliers de lignes, c'est-à-dire chez le
client, vers janvier, sur la page que le professeur ouvre chaque matin.
Mesuré sur 800 000 lignes : 12 369 ms contre 2,4 ms.

Un test qui compare des valeurs ne verra jamais ça. Il faut interroger le
planificateur lui-même.

Les deux moteurs ne répondent pas de la même façon, et cette différence est
elle-même une raison de tester les deux :

- SQLite décide d'après la STRUCTURE de la requête. `EXPLAIN QUERY PLAN`
  annonce « SEARCH … USING INDEX » ou « SCAN », sur une base vide comme sur
  une base pleine, et nomme l'ALIAS (« SCAN x »), pas la table.
- PostgreSQL décide d'après le COÛT estimé. Sur une table vide il choisit
  toujours un balayage séquentiel, parce que c'est effectivement le moins
  cher — le plan n'y veut donc rien dire. Ce module y insère de quoi rendre
  le choix sans ambiguïté, lance ANALYZE, puis lit le plan. PostgreSQL nomme
  la TABLE (« Seq Scan on attendance x »).

Ajouter une requête ici quand elle agrège une table qui grossit avec l'usage
(attendance, incidents, grades, payments, notifications, events).
"""
import os
import re
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

# Volume injecté sous PostgreSQL pour que le planificateur ait un vrai choix à
# faire. Assez grand pour que l'index gagne largement, assez petit pour rester
# instantané.
LIGNES_PG = 20000


def setUpModule():
    if not db.is_postgres() and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    if db.is_postgres():
        _semer_postgres()


def tearDownModule():
    if db.is_postgres():
        conn = db.get_connection()
        for table in ("attendance", "incidents", "grades", "students",
                      "classes", "academic_years", "tenants"):
            colonne = "id" if table == "tenants" else "tenant_id"
            conn.execute(f"DELETE FROM {table} WHERE {colonne} LIKE 'plan-%'")
        conn.commit()
        conn.close()
    elif os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


def _semer_postgres():
    """Assez de lignes, réparties sur plusieurs établissements, pour qu'un
    balayage complet soit manifestement plus cher qu'un parcours d'index."""
    conn = db.get_connection()
    eleves, presences, incidents, notes = [], [], [], []
    for t in range(4):
        tenant, annee = f"plan-t{t}", f"plan-y{t}"
        # Les clés étrangères sont réellement contraintes sous PostgreSQL : le
        # décor doit exister avant les lignes qu'on veut mesurer.
        conn.execute("INSERT INTO tenants (id, name, status, created_at) VALUES (?,?,'active','0')",
                     (tenant, f"École plan {t}"))
        conn.execute("INSERT INTO academic_years (id, tenant_id, label, is_active, created_at) VALUES (?,?,?,1,'0')",
                     (annee, tenant, "2026-2027"))
        for k in range(4):
            conn.execute("INSERT INTO classes (id, tenant_id, academic_year_id, name, created_at) VALUES (?,?,?,?,'0')",
                         (f"plan-c{t}-{k}", tenant, annee, f"6e {k}"))
        for i in range(100):
            sid, cid = f"plan-s{t}-{i}", f"plan-c{t}-{i // 25}"
            eleves.append((sid, tenant, annee, cid, "active", "A", "B", "0"))
            for d in range(LIGNES_PG // 400):
                # Dates distinctes : attendance porte UNIQUE(tenant, élève, date).
                jour = (date(2026, 1, 5) + timedelta(days=d)).isoformat()
                presences.append((f"plan-a{t}-{i}-{d}", tenant, sid, cid, jour, "present", "0", "0"))
            incidents.append((f"plan-i{t}-{i}", tenant, sid, "retard", "Retard", -2, "0", "0"))
            notes.append((f"plan-g{t}-{i}", tenant, sid, cid, "Maths", "Période 1", 12.0, 20.0, "0"))
    conn.executemany(
        "INSERT INTO students (id, tenant_id, academic_year_id, class_id, status, first_name, last_name, created_at) VALUES (?,?,?,?,?,?,?,?)",
        eleves)
    conn.executemany(
        "INSERT INTO attendance (id, tenant_id, student_id, class_id, date, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        presences)
    conn.executemany(
        "INSERT INTO incidents (id, tenant_id, student_id, category, title, points, occurred_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
        incidents)
    conn.executemany(
        "INSERT INTO grades (id, tenant_id, student_id, class_id, subject, period, score, max_score, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        notes)
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()


# Chaque entrée : nom lisible, SQL, paramètres, puis ce qui doit être atteint
# par index — par ALIAS pour SQLite, par TABLE pour PostgreSQL, parce que les
# deux moteurs ne désignent pas la même chose dans leur plan.
#
# Le SQL est repris des routes réelles : quand une route change, ce test doit
# changer avec elle, et c'est voulu.
REQUETES_SENSIBLES = [
    (
        "class_students — compteurs de présence et d'incidents",
        """SELECT s.id,
                  (SELECT COUNT(*) FROM attendance x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.status='absent') AS absences_unjustified,
                  (SELECT COUNT(*) FROM attendance x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.status='excused') AS absences_justified,
                  (SELECT COUNT(*) FROM attendance x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.status='late') AS lates,
                  (SELECT COUNT(*) FROM incidents x WHERE x.tenant_id=s.tenant_id AND x.student_id=s.id AND x.points < 0) AS faults
           FROM students s
           WHERE s.tenant_id=? AND s.class_id=? AND s.status='active'""",
        ("plan-t0", "plan-c0-0"),
        {"x"},                          # les quatre sous-requêtes partagent cet alias
        {"attendance", "incidents"},
    ),
    (
        "list_classes — état de l'appel du jour",
        """SELECT c.id,
                  (SELECT COUNT(*) FROM students s WHERE s.tenant_id = c.tenant_id AND s.class_id = c.id AND s.status = 'active') AS student_count,
                  (SELECT COUNT(*) FROM attendance a WHERE a.tenant_id = c.tenant_id AND a.class_id = c.id AND a.date = ?) AS attendance_recorded_today,
                  (SELECT COUNT(*) FROM attendance a WHERE a.tenant_id = c.tenant_id AND a.class_id = c.id AND a.date = ? AND a.status = 'absent') AS absent_today
           FROM classes c WHERE c.tenant_id = ?""",
        ("2026-01-06", "2026-01-06", "plan-t0"),
        {"a", "s"},
        {"attendance"},
    ),
    (
        "grades_for_student — bulletin d'un élève",
        """SELECT g.* FROM grades g WHERE g.tenant_id=? AND g.student_id=?""",
        ("plan-t0", "plan-s0-0"),
        {"g"},
        {"grades"},
    ),
]

# La requête telle qu'elle était AVANT le correctif P1.
REQUETE_FAUTIVE = """SELECT s.id,
       (SELECT COUNT(*) FROM attendance x WHERE x.student_id=s.id AND x.status='absent') AS n
       FROM students s WHERE s.tenant_id=? AND s.class_id=?"""


class PlansDExecutionTests(unittest.TestCase):
    def _plan(self, sql, params):
        conn = db.get_connection()
        try:
            prefixe = "EXPLAIN " if db.is_postgres() else "EXPLAIN QUERY PLAN "
            lignes = []
            for row in conn.execute(prefixe + sql, params).fetchall():
                d = dict(row)
                lignes.append(str(d.get("QUERY PLAN") if db.is_postgres() else d.get("detail")).strip())
            return lignes
        finally:
            conn.close()

    def _balayages(self, lignes, alias, tables):
        """Lignes de plan qui trahissent un balayage complet, selon le moteur."""
        if db.is_postgres():
            return [l for l in lignes
                    for t in tables
                    if re.search(rf"Seq Scan on {re.escape(t)}\b", l)]
        return [l for l in lignes for a in alias if re.match(rf"SCAN {re.escape(a)}\b", l)]

    def _parcours_dindex(self, lignes, alias, tables):
        if db.is_postgres():
            return [l for l in lignes
                    for t in tables
                    if re.search(rf"Index (Only )?Scan.* on {re.escape(t)}\b", l)]
        return [l for l in lignes for a in alias if re.match(rf"SEARCH {re.escape(a)}\b", l)]

    def test_aucune_requete_sensible_ne_balaie_une_table_qui_grossit(self):
        echecs = []
        for nom, sql, params, alias, tables in REQUETES_SENSIBLES:
            lignes = self._plan(sql, params)
            balayages = self._balayages(lignes, alias, tables)
            if balayages:
                echecs.append(f"  {nom}\n      → balayage complet : {balayages[0]}")
            elif not self._parcours_dindex(lignes, alias, tables):
                echecs.append(
                    f"  {nom}\n      → aucun parcours d'index détecté : la requête a changé et "
                    f"ce garde-fou ne la couvre plus. Plan : {lignes}")
        self.assertEqual(
            echecs, [],
            "Des requêtes sensibles balaient une table qui grossit avec l'usage.\n"
            "C'est exactement le défaut P1 : résultats justes, coût faux, invisible\n"
            "en développement et fatal en production.\n\n" + "\n".join(echecs),
        )

    def test_le_garde_fou_detecte_bien_un_balayage(self):
        """Un garde-fou qu'on n'a jamais vu se déclencher ne garde rien.

        On rejoue ici la requête FAUTIVE — sans `tenant_id` dans la
        sous-requête — et on exige que le plan la trahisse. Si cette assertion
        casse un jour, c'est le test ci-dessus qui est devenu aveugle, pas le
        produit qui s'est amélioré.
        """
        lignes = self._plan(REQUETE_FAUTIVE, ("plan-t0", "plan-c0-0"))
        self.assertTrue(
            self._balayages(lignes, {"x"}, {"attendance"}),
            f"la requête fautive d'origine devrait produire un balayage détectable ; plan obtenu : {lignes}",
        )


if __name__ == "__main__":
    unittest.main()
