"""KLASSIO — faits en lot, récidivistes, pastilles (08/10/2026).

Le propriétaire : « on saisit leurs faits sur un document, le logiciel
analyse les noms et ce qu'ils ont mal fait, et le DD décide en une fois » ;
« il y a la liste des dérangeurs qui revient de beaucoup de classes » ;
« une pastille de notification dès qu'il entre ».
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402

TODAY = date.today().isoformat()


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class LotTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

        def ecole(n):
            r = c.post("/api/auth/register-school", json={"email": f"dir{n}@lot.test", "password": "Secret123!",
                                                          "name": "Direction", "school_name": f"École Lot {n}"})
            return {"Authorization": "Bearer " + r.get_json()["token"]}

        cls.h, cls.h2 = ecole("a"), ecole("b")
        annee = c.get("/api/academic-years", headers=cls.h).get_json()[0]["id"]
        a = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee}, headers=cls.h).get_json()
        b = c.post("/api/classes", json={"name": "5e B", "academic_year_id": annee}, headers=cls.h).get_json()
        mk = lambda f, l, k: c.post("/api/students", json={"first_name": f, "last_name": l, "academic_year_id": annee, "class_id": k["id"]}, headers=cls.h).get_json()
        cls.grace, cls.jean, cls.ruth = mk("Grace", "Mbuyi", a), mk("Jean", "Kabeya", a), mk("Ruth", "Tshala", b)
        annee2 = c.get("/api/academic-years", headers=cls.h2).get_json()[0]["id"]
        k2 = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee2}, headers=cls.h2).get_json()
        cls.etranger = c.post("/api/students", json={"first_name": "Grace", "last_name": "Mbuyi", "academic_year_id": annee2, "class_id": k2["id"]}, headers=cls.h2).get_json()
        cls.derangement = c.post("/api/discipline/rules", json={"label": "Dérangement", "category": "comportement", "points": -10,
                                                                "measure": "Travail manuel"}, headers=cls.h).get_json()
        cls.retard = c.post("/api/discipline/rules", json={"label": "Retard injustifié", "category": "retard", "points": -2}, headers=cls.h).get_json()

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _nb_incidents(self):
        return len(self.c.get("/api/incidents?limit=500", headers=self.h).get_json())

    def test_01_la_liste_est_lue_noms_et_faits(self):
        texte = "Grace Mbuyi : dérangement pendant le cours\nKABEYA Jean et Ruth Tshala ont bavardé\nUntel Inconnu en retard"
        r = self.c.post("/api/discipline/lot/analyze", json={"text": texte}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        lu = r.get_json()
        par = {i["student_id"]: i for i in lu["items"]}
        self.assertEqual(set(par), {self.grace["id"], self.jean["id"], self.ruth["id"]})
        self.assertEqual(par[self.grace["id"]]["rule_id"], self.derangement["id"])
        self.assertEqual(par[self.jean["id"]]["rule_id"], self.derangement["id"], "« bavardé » n'a pas été rapproché du dérangement")
        self.assertEqual(lu["unmatched"], ["Untel Inconnu en retard"])

    def test_02_un_homonyme_d_une_autre_ecole_n_est_jamais_reconnu(self):
        lu = self.c.post("/api/discipline/lot/analyze", json={"text": "Grace Mbuyi dérangement"}, headers=self.h).get_json()
        self.assertEqual([i["student_id"] for i in lu["items"]], [self.grace["id"]])
        self.assertNotIn(self.etranger["id"], str(lu))

    def test_03_decision_commune_pour_tous(self):
        avant = self._nb_incidents()
        r = self.c.post("/api/discipline/lot/confirm", json={
            "items": [{"student_id": self.grace["id"], "rule_id": self.derangement["id"]},
                      {"student_id": self.jean["id"], "rule_id": self.derangement["id"]}],
            "common": {"action_taken": "Travail manuel pendant 3 jours", "occurred_at": TODAY}}, headers=self.h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["created"], 2)
        incs = [i for i in self.c.get("/api/incidents?limit=500", headers=self.h).get_json()][: self._nb_incidents() - avant]
        self.assertEqual(self._nb_incidents(), avant + 2)
        self.assertTrue(all(i["points"] == -10 for i in incs))
        self.assertTrue(all(i["action_taken"] == "Travail manuel pendant 3 jours" for i in incs))

    def test_04_un_eleve_etranger_refuse_tout_le_lot(self):
        avant = self._nb_incidents()
        r = self.c.post("/api/discipline/lot/confirm", json={
            "items": [{"student_id": self.grace["id"], "rule_id": self.retard["id"]},
                      {"student_id": self.etranger["id"], "rule_id": self.retard["id"]}]}, headers=self.h)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._nb_incidents(), avant, "la moitié du lot a été écrite")

    def test_05_la_mesure_du_reglement_s_applique_par_defaut(self):
        r = self.c.post("/api/discipline/lot/confirm", json={"items": [{"student_id": self.ruth["id"], "rule_id": self.derangement["id"]}]}, headers=self.h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        inc = next(i for i in self.c.get("/api/incidents?limit=500", headers=self.h).get_json() if i["student_id"] == self.ruth["id"])
        self.assertEqual(inc["action_taken"], "Travail manuel")

    def test_06_les_recidivistes(self):
        self.c.post("/api/discipline/lot/confirm", json={"items": [{"student_id": self.grace["id"], "rule_id": self.derangement["id"]}]}, headers=self.h)
        rows = self.c.get("/api/discipline/recurrents?days=30&min=2", headers=self.h).get_json()
        grace = [r for r in rows if r["student_id"] == self.grace["id"] and r["fait"] == "Dérangement"]
        self.assertTrue(grace and grace[0]["n"] >= 2)
        self.assertEqual(self.c.get("/api/discipline/recurrents", headers=self.h2).get_json(), [])

    def test_07_pastilles_du_menu(self):
        inv = self.c.post("/api/invitations", json={"role": "professeur"}, headers=self.h).get_json()
        acc = self.c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Prof", "email": "prof@lot.test", "password": "Secret123!"}).get_json()
        prof = {"Authorization": "Bearer " + acc["token"]}
        self.assertEqual(self.c.post("/api/discipline/lot/analyze", json={"text": "x y z"}, headers=prof).status_code, 403)
        self.assertEqual(self.c.post("/api/discipline/lot/confirm", json={"items": [{"student_id": self.grace["id"]}]}, headers=prof).status_code, 403)
        avant = self.c.get("/api/me/badges", headers=self.h).get_json().get("discipline", 0)
        self.c.post("/api/incident-reports", json={"student_id": self.grace["id"], "rule_id": self.derangement["id"], "occurred_at": TODAY}, headers=self.h)
        self.assertEqual(self.c.get("/api/me/badges", headers=self.h).get_json().get("discipline", 0), avant + 1)
        self.assertNotIn("discipline", self.c.get("/api/me/badges", headers=self.h2).get_json())


if __name__ == "__main__":
    unittest.main()
