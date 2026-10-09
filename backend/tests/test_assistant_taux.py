"""KLASSIO — l'assistant et le taux d'encaissement (trouvé le 09/10/2026).

« Quel est le taux d'encaissement ? » recevait « Votre établissement a encaissé
0,00 $ ce mois-ci » : la branche du MONTANT encaissé (`encaiss[ée]`) passait
avant celle du TAUX, et « encaissement » commence par « encaisse ». Une
Direction qui demandait un pourcentage recevait un montant — la réponse avait
l'air juste et ne l'était pas.
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


class TauxEncaissementTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = cls.c.post("/api/auth/register-school", json={"email": "dir@taux.test", "password": "Secret123!",
                                                          "name": "Direction", "school_name": "École du taux"}).get_json()
        cls.h = {"Authorization": "Bearer " + r["token"]}

    def _ask(self, q):
        security.reset_rate_limits_for_tests()
        r = self.c.post("/api/ai/ask", json={"message": q}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()

    def test_01_le_taux_repond_par_un_taux(self):
        for q in ("Quel est le taux d'encaissement ?", "Quel est notre taux d'encaissement ce trimestre ?",
                  "Pourcentage d'encaissement", "Quel est le pourcentage encaissé ?"):
            with self.subTest(q=q):
                b = self._ask(q)
                self.assertEqual(b["intent"], "collection_rate")
                self.assertIn("%", b["text"])

    def test_02_le_montant_repond_toujours_par_un_montant(self):
        self.assertEqual(self._ask("Combien avons-nous encaissé ce mois-ci ?")["intent"], "collected_this_month")
        self.assertEqual(self._ask("Combien avons-nous encaissé le mois dernier ?")["intent"], "collected_last_month")
        self.assertEqual(self._ask("Analyse ma situation financière")["intent"], "financial_summary")


if __name__ == "__main__":
    unittest.main()
