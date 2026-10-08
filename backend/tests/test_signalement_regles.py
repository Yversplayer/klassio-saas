"""KLASSIO — signalements fondés sur les règles de la Direction (08/10/2026).

Le propriétaire : « le prof écrit ce qu'il veut ; il doit signaler à partir
des choix faits au préalable par la Direction, et la demande doit être
analysée par le DD ». Dès qu'une école a des règles, un signalement en cite
une — de cette école-là, active — et l'enseignant n'en voit pas les points.
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


class SignalementReglesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

        def ecole(n):
            r = c.post("/api/auth/register-school", json={"email": f"dir{n}@sig.test", "password": "Secret123!",
                                                          "name": "Direction", "school_name": f"École {n}"})
            assert r.status_code == 201, r.get_data(as_text=True)
            h = {"Authorization": "Bearer " + r.get_json()["token"]}
            annee = c.get("/api/academic-years", headers=h).get_json()[0]["id"]
            classe = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee}, headers=h).get_json()
            eleve = c.post("/api/students", json={"first_name": "Grace", "last_name": "Mbuyi", "academic_year_id": annee,
                                                  "class_id": classe["id"]}, headers=h).get_json()
            return h, classe, eleve

        cls.dir_h, cls.classe, cls.eleve = ecole("a")
        cls.dir_b, _, _ = ecole("b")
        inv = c.post("/api/invitations", json={"role": "professeur"}, headers=cls.dir_h).get_json()
        acc = c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Prof", "email": "prof@sig.test",
                                                       "password": "Secret123!"}).get_json()
        cls.prof_h = {"Authorization": "Bearer " + acc["token"]}
        me = c.get("/api/me", headers=cls.prof_h).get_json()
        r = c.post(f"/api/classes/{cls.classe['id']}/teachers", json={"user_id": me["user_id"], "is_titulaire": True}, headers=cls.dir_h)
        assert r.status_code in (200, 201), r.get_data(as_text=True)

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _signaler(self, **corps):
        return self.c.post("/api/incident-reports", json={"student_id": self.eleve["id"], "occurred_at": TODAY, **corps}, headers=self.prof_h)

    def test_01_sans_regles_la_description_libre_reste_possible(self):
        self.assertEqual(self.c.get("/api/incident-reports/rules", headers=self.prof_h).get_json(), [])
        self.assertEqual(self._signaler(description="A crié en classe").status_code, 201)

    def test_02_avec_regles_le_professeur_choisit_dans_la_liste(self):
        regle = self.c.post("/api/discipline/rules", json={"label": "Usage du téléphone en classe", "category": "comportement", "points": -5},
                            headers=self.dir_h).get_json()
        etrangere = self.c.post("/api/discipline/rules", json={"label": "Règle d'une autre école", "category": "comportement", "points": -5},
                                headers=self.dir_b).get_json()
        choix = self.c.get("/api/incident-reports/rules", headers=self.prof_h).get_json()
        self.assertEqual([r["id"] for r in choix], [regle["id"]])
        self.assertNotIn("points", choix[0], "le professeur voit le barème des points")
        self.assertIn("points", self.c.get("/api/incident-reports/rules", headers=self.dir_h).get_json()[0])
        # Description libre seule : refusée.
        self.assertEqual(self._signaler(description="Il a fait n'importe quoi").status_code, 400)
        # Règle d'une autre école ou inventée : refusée.
        self.assertEqual(self._signaler(rule_id=etrangere["id"]).status_code, 400)
        self.assertEqual(self._signaler(rule_id="inventee").status_code, 400)
        r = self._signaler(rule_id=regle["id"], description="pendant l'interrogation")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        rep = next(x for x in self.c.get("/api/incident-reports", headers=self.dir_h).get_json() if x["id"] == r.get_json()["id"])
        self.assertEqual(rep["rule_id"], regle["id"])
        self.assertEqual(rep["rule_label"], "Usage du téléphone en classe")
        self.assertEqual(rep["description"], "Usage du téléphone en classe — pendant l'interrogation")
        # La Direction qualifie : la règle citée s'applique par défaut, avec ses points.
        q = self.c.post(f"/api/incident-reports/{rep['id']}/qualify", json={"severity": "medium"}, headers=self.dir_h)
        self.assertEqual(q.status_code, 201, q.get_data(as_text=True))
        inc = self.c.get(f"/api/incidents/{q.get_json()['incident_id']}", headers=self.dir_h).get_json()
        self.assertEqual(inc["rule_id"], regle["id"])
        self.assertEqual(inc["points"], -5)

    def test_03_une_regle_desactivee_ne_se_cite_plus(self):
        regle = self.c.post("/api/discipline/rules", json={"label": "Retard répété", "category": "retard", "points": -2},
                            headers=self.dir_h).get_json()
        self.c.delete(f"/api/discipline/rules/{regle['id']}", headers=self.dir_h)
        ids = [r["id"] for r in self.c.get("/api/incident-reports/rules", headers=self.prof_h).get_json()]
        self.assertNotIn(regle["id"], ids)
        self.assertEqual(self._signaler(rule_id=regle["id"]).status_code, 400)


if __name__ == "__main__":
    unittest.main()
