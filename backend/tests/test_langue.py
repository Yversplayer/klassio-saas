"""KLASSIO — langue de l'interface (08/10/2026).

La langue choisie dans Paramètres suit l'utilisateur d'un appareil à l'autre :
elle est enregistrée sur son compte et renvoyée par /api/me. La liste est
fermée : une valeur inconnue finirait dans l'attribut lang de chaque page et
dans le chemin d'un dictionnaire.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
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


class LangueTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = c.post("/api/auth/register-school", json={"email": "dir@langue.test", "password": "Secret123!",
                                                      "name": "Directrice", "school_name": "École Langue"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.h = {"Authorization": "Bearer " + r.get_json()["token"]}
        r2 = c.post("/api/auth/register-school", json={"email": "autre@langue.test", "password": "Secret123!",
                                                       "name": "Autre", "school_name": "Autre École"})
        cls.h2 = {"Authorization": "Bearer " + r2.get_json()["token"]}

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def test_01_francais_par_defaut(self):
        self.assertEqual(self.c.get("/api/me", headers=self.h).get_json()["language"], "fr")
        self.assertEqual(self.c.get("/api/me/preferences", headers=self.h).get_json()["language"], "fr")

    def test_02_choix_suit_le_compte_et_lui_seul(self):
        r = self.c.put("/api/me/preferences", json={"language": "en"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.c.get("/api/me", headers=self.h).get_json()["language"], "en")
        self.assertEqual(self.c.get("/api/me", headers=self.h2).get_json()["language"], "fr", "la langue a fui vers un autre compte")
        # Changer une autre préférence ne remet pas la langue à zéro.
        self.c.put("/api/me/preferences", json={"share_phone": True}, headers=self.h)
        self.assertEqual(self.c.get("/api/me", headers=self.h).get_json()["language"], "en")

    def test_03_langue_inconnue_refusee(self):
        for v in ("xx", "../../etc", "en<script>"):
            self.assertEqual(self.c.put("/api/me/preferences", json={"language": v}, headers=self.h).status_code, 400, v)
        self.assertEqual(self.c.get("/api/me", headers=self.h).get_json()["language"], "en")


if __name__ == "__main__":
    unittest.main()
