"""KLASSIO — l'assistant du professeur (08/10/2026).

Le propriétaire : « l'assistant du professeur me répond qu'il n'a pas assez
d'informations ». Il répond désormais aux questions d'un enseignant — mais
toujours sur SES classes : l'effectif ou les devoirs d'une autre classe
n'entrent jamais dans sa réponse.
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402

DEMAIN = (date.today() + timedelta(days=1)).isoformat()


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class IAProfesseurTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = c.post("/api/auth/register-school", json={"email": "dir@iaprof.test", "password": "Secret123!",
                                                      "name": "Direction", "school_name": "École IA"})
        cls.dir_h = {"Authorization": "Bearer " + r.get_json()["token"]}
        annee = c.get("/api/academic-years", headers=cls.dir_h).get_json()[0]["id"]
        cls.mienne = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee}, headers=cls.dir_h).get_json()
        cls.autre = c.post("/api/classes", json={"name": "5e B", "academic_year_id": annee}, headers=cls.dir_h).get_json()
        for i in range(3):
            c.post("/api/students", json={"first_name": f"Mien{i}", "last_name": "Kabila", "academic_year_id": annee, "class_id": cls.mienne["id"]}, headers=cls.dir_h)
        for i in range(5):
            c.post("/api/students", json={"first_name": f"Autre{i}", "last_name": "Tshala", "academic_year_id": annee, "class_id": cls.autre["id"]}, headers=cls.dir_h)
        inv = c.post("/api/invitations", json={"role": "professeur"}, headers=cls.dir_h).get_json()
        acc = c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Prof", "email": "prof@iaprof.test", "password": "Secret123!"}).get_json()
        cls.prof_h = {"Authorization": "Bearer " + acc["token"]}
        me = c.get("/api/me", headers=cls.prof_h).get_json()
        c.post(f"/api/classes/{cls.mienne['id']}/teachers", json={"user_id": me["user_id"], "is_titulaire": True}, headers=cls.dir_h)
        c.post("/api/resources", json={"class_id": cls.mienne["id"], "kind": "devoir", "title": "Exercices de fractions", "due_date": DEMAIN}, headers=cls.dir_h)
        c.post("/api/resources", json={"class_id": cls.autre["id"], "kind": "devoir", "title": "Devoir d'une autre classe", "due_date": DEMAIN}, headers=cls.dir_h)

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _ask(self, q):
        r = self.c.post("/api/ai/ask", json={"message": q}, headers=self.prof_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()

    def test_01_ses_classes_et_son_effectif_seulement(self):
        b = self._ask("Combien d'élèves sont inscrits ?")
        self.assertIn("**3**", b["text"])
        self.assertNotIn("8", b["text"])
        b = self._ask("Mes classes")
        self.assertEqual(b["intent"], "teacher_classes")
        self.assertEqual([r[0] for r in b["rich"]["rows"]], ["6e A"])

    def test_02_devoirs_de_ses_classes_seulement(self):
        b = self._ask("Quels devoirs sont à rendre ?")
        self.assertEqual(b["intent"], "teacher_homework")
        titres = [r[0] for r in b["rich"]["rows"]]
        self.assertIn("Exercices de fractions", titres)
        self.assertNotIn("Devoir d'une autre classe", titres)

    def test_03_appel_et_absents(self):
        self.assertEqual(self._ask("L'appel est-il fait dans mes classes ?")["intent"], "teacher_roll")
        self.assertEqual(self._ask("Quels élèves sont absents aujourd'hui ?")["intent"], "teacher_absents")

    def test_04_question_inconnue_aveu_et_suggestions(self):
        b = self._ask("Quelle est la météo à Kinshasa ?")
        self.assertEqual(b["intent"], "fallback")
        self.assertIn("pas suffisamment d'informations", b["text"])
        self.assertEqual(b["rich"]["type"], "suggestions")
        self.assertTrue(b["rich"]["items"])


if __name__ == "__main__":
    unittest.main()
