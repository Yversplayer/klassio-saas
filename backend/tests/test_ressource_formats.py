"""KLASSIO — fichiers de cours de tout format (08/10/2026).

Le propriétaire : « en n'importe quel format et pas seulement 3 Mo ». Un Word,
un PowerPoint ou un audio se publient ; la forme du data URI reste stricte
(une chaîne piégée ne s'échappe pas d'un attribut) et le plafond existe
toujours.
"""
import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402
import api_life  # noqa: E402

DOCX = "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64," + base64.b64encode(b"PK\x03\x04 docx").decode()


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class RessourceFormatsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = c.post("/api/auth/register-school", json={"email": "dir@res.test", "password": "Secret123!",
                                                      "name": "Direction", "school_name": "École Ressources"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["token"]}
        annee = c.get("/api/academic-years", headers=cls.h).get_json()[0]["id"]
        cls.classe = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee}, headers=cls.h).get_json()

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _publier(self, data, nom="cours.docx"):
        return self.c.post("/api/resources", json={"class_id": self.classe["id"], "kind": "lecon", "title": "Cours",
                                                   "file_name": nom, "file_data": data}, headers=self.h)

    def test_01_un_document_word_se_publie(self):
        r = self._publier(DOCX)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        f = self.c.get(f"/api/resources/{r.get_json()['id']}/file", headers=self.h).get_json()
        self.assertEqual(f["file_data"], DOCX)
        self.assertEqual(f["file_name"], "cours.docx")

    def test_02_une_chaine_piegee_reste_refusee(self):
        piege = 'data:application/pdf;base64,AAAA" onerror="alert(1)'
        self.assertEqual(self._publier(piege).status_code, 400)
        self.assertEqual(self._publier('data:text/html";base64,AAAA').status_code, 400)
        # Les formats actifs restent refusés, même bien formés.
        for actif in ("data:text/html;base64,PHNjcmlwdD4=", "data:image/svg+xml;base64,PHN2Zz4=",
                      "data:application/x-msdownload;base64,TVo=", "data:application/javascript;base64,YWxlcnQoMSk="):
            self.assertEqual(self._publier(actif, "piege.html").status_code, 400, actif)

    def test_03_le_plafond_existe_toujours(self):
        self.assertGreater(api_life.MAX_RESOURCE_BYTES, 3_500_000, "le plafond de 3 Mo n'a pas été relevé")
        trop = "data:application/pdf;base64," + "A" * (api_life.MAX_RESOURCE_BYTES + 4)
        self.assertIn(self._publier(trop).status_code, (400, 413))


if __name__ == "__main__":
    unittest.main()
