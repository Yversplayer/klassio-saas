"""KLASSIO — les bulletins de toute une classe, en un appel.

Le chantier « import des résultats → bulletins » était déjà fait à 90 % :
results_import.py analyse et versionne les fichiers, school.bulletin() compose
le bulletin, 35 tests couvrent la correspondance par identifiant et l'isolation.
Ne manquait que ceci : produire les 42 bulletins d'une classe sans les ouvrir
un par un.

Ces tests éprouvent la seule chose qui compte pour un ajout pareil — que le
lot dise EXACTEMENT la même chose que l'unité, et qu'il respecte les mêmes
périmètres.
"""
import os
import sys
import unittest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, BACKEND)

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "klassio_bull_test.db")
os.environ["KLASSIO_DB_PATH"] = TEST_DB

import db  # noqa: E402
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class Base(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def ecole(self, suffixe, noms=("Kabeya", "Mbuyi", "Ilunga")):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@bull.test", "password": "Secret123!",
            "name": "Directeur", "school_name": f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        d = r.get_json()
        h = {"Authorization": f"Bearer {d['token']}"}
        an = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        cls = self.c.post("/api/classes", json={"academic_year_id": an, "name": "6e A"},
                          headers=h).get_json()
        eleves = []
        for n in noms:
            eleves.append(self.c.post("/api/students", json={
                "academic_year_id": an, "class_id": cls["id"],
                "first_name": "Jean", "last_name": n}, headers=h).get_json())
        return {"h": h, "year": an, "class": cls, "students": eleves, "tenant_id": d["tenant_id"]}

    def noter(self, h, class_id, student_id, matiere, note, periode="Période 1"):
        """La matière et la période sont au niveau du CORPS, pas de l'entrée —
        une saisie porte sur une matière pour toute la classe."""
        r = self.c.post(f"/api/classes/{class_id}/grades", json={
            "subject": matiere, "period": periode, "max_score": 20,
            "entries": [{"student_id": student_id, "score": note}],
        }, headers=h)
        self.assertIn(r.status_code, (200, 201), f"saisie refusée : {r.get_data(as_text=True)[:200]}")
        return r


class BulletinsDeClasse(Base):
    def test_01_le_lot_couvre_tous_les_eleves_actifs(self):
        ctx = self.ecole("grp01")
        r = self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins", headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertEqual(corps["count"], 3)
        self.assertEqual(len(corps["bulletins"]), 3)
        self.assertEqual(corps["class_name"], "6e A")
        noms = sorted(b["student"]["last_name"] for b in corps["bulletins"])
        self.assertEqual(noms, ["Ilunga", "Kabeya", "Mbuyi"])

    def test_02_le_lot_dit_exactement_la_meme_chose_que_l_unite(self):
        """Le seul vrai risque d'un ajout pareil : deux chemins qui divergent.

        Si le lot recalculait de son côté, un parent et la Direction pourraient
        lire deux moyennes différentes pour le même élève. Ici les deux passent
        par `school.bulletin()` — ce test le vérifie plutôt que d'y croire.
        """
        ctx = self.ecole("grp02")
        eleve = ctx["students"][0]
        self.noter(ctx["h"], ctx["class"]["id"], eleve["id"], "Mathématiques", 14)
        self.noter(ctx["h"], ctx["class"]["id"], eleve["id"], "Français", 11)

        seul = self.c.get(f"/api/students/{eleve['id']}/bulletin?period=Période 1",
                          headers=ctx["h"]).get_json()
        lot = self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins?period=Période 1",
                         headers=ctx["h"]).get_json()
        dans_lot = [b for b in lot["bulletins"] if b["student"]["id"] == eleve["id"]][0]

        # D'ABORD s'assurer qu'il Y A quelque chose à comparer : comparer deux
        # bulletins vides passerait au vert sans rien prouver.
        self.assertEqual(len(seul["subjects"]), 2,
                         f"le décor est faux, aucune note n'a été saisie : {seul['subjects']}")
        self.assertIsNotNone(seul["general_average_20"])

        self.assertEqual(seul["general_average_20"], dans_lot["general_average_20"],
                         "la moyenne diffère entre le bulletin seul et le même bulletin en lot")
        self.assertEqual(seul["rank"], dans_lot["rank"])
        self.assertEqual(len(seul["subjects"]), len(dans_lot["subjects"]))

    def test_03_une_periode_ne_ramene_que_ses_notes(self):
        ctx = self.ecole("grp03")
        eleve = ctx["students"][0]
        self.noter(ctx["h"], ctx["class"]["id"], eleve["id"], "Mathématiques", 14, "Période 1")
        self.noter(ctx["h"], ctx["class"]["id"], eleve["id"], "Physique", 8, "Période 2")
        lot = self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins?period=Période 1",
                         headers=ctx["h"]).get_json()
        b = [x for x in lot["bulletins"] if x["student"]["id"] == eleve["id"]][0]
        matieres = [s["subject"] for s in b["subjects"]]
        self.assertIn("Mathématiques", matieres)
        self.assertNotIn("Physique", matieres, "une note d'une autre période s'est glissée")

    def test_04_generer_le_lot_n_ecrit_rien(self):
        """Imprimer n'est pas proclamer. Le lot ne doit rien publier."""
        ctx = self.ecole("grp04")
        eleve = ctx["students"][0]
        self.noter(ctx["h"], ctx["class"]["id"], eleve["id"], "Mathématiques", 15)
        conn = db.get_connection()
        avant = conn.execute("SELECT COUNT(*) n FROM period_publications").fetchone()["n"]
        notes_avant = conn.execute("SELECT COUNT(*) n FROM grades WHERE tenant_id=?",
                                   (ctx["tenant_id"],)).fetchone()["n"]
        conn.close()

        self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins", headers=ctx["h"])

        conn = db.get_connection()
        apres = conn.execute("SELECT COUNT(*) n FROM period_publications").fetchone()["n"]
        notes_apres = conn.execute("SELECT COUNT(*) n FROM grades WHERE tenant_id=?",
                                   (ctx["tenant_id"],)).fetchone()["n"]
        conn.close()
        self.assertEqual(avant, apres, "générer des bulletins a publié une période")
        self.assertEqual(notes_avant, notes_apres, "générer des bulletins a écrit des notes")


class PerimetresDuLot(Base):
    def test_10_une_classe_d_une_autre_ecole_est_introuvable(self):
        a = self.ecole("per10a")
        b = self.ecole("per10b")
        r = self.c.get(f"/api/classes/{b['class']['id']}/bulletins", headers=a["h"])
        self.assertEqual(r.status_code, 404)

    def test_11_un_professeur_n_obtient_que_ses_classes(self):
        ctx = self.ecole("per11")
        autre = self.c.post("/api/classes", json={
            "academic_year_id": ctx["year"], "name": "5e B"}, headers=ctx["h"]).get_json()
        inv = self.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": [ctx["class"]["id"]]}, headers=ctx["h"]).get_json()
        prof = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof", "email": "prof11@bull.test",
            "password": "Secret123!"}).get_json()
        h = {"Authorization": f"Bearer {prof['token']}"}

        self.assertEqual(self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins",
                                    headers=h).status_code, 200,
                         "le professeur n'accède pas à SA classe")
        self.assertEqual(self.c.get(f"/api/classes/{autre['id']}/bulletins",
                                    headers=h).status_code, 403,
                         "le professeur a obtenu les bulletins d'une classe qui n'est pas la sienne")

    def test_12_un_parent_n_imprime_pas_la_classe_de_son_enfant(self):
        """Il a le bulletin de SON enfant. Le reste du groupe ne le regarde pas."""
        ctx = self.ecole("per12")
        inv = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [ctx["students"][0]["id"]]},
            headers=ctx["h"]).get_json()
        par = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "parent12@bull.test",
            "password": "Secret123!"}).get_json()
        h = {"Authorization": f"Bearer {par['token']}"}
        self.assertEqual(self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins",
                                    headers=h).status_code, 403)

    def test_13_sans_session_rien(self):
        ctx = self.ecole("per13")
        self.assertEqual(self.c.get(f"/api/classes/{ctx['class']['id']}/bulletins").status_code, 401)


if __name__ == "__main__":
    unittest.main()
