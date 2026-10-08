"""KLASSIO — boutique : stock tracé, photos, statistiques (08/10/2026).

Le propriétaire : « seul le directeur peut ajouter ou retirer des éléments ;
réfléchis à un système de vente, de rupture de stock, de vidage de stock, de
mauvais produit, d'augmentation d'éléments ». Le stock ne bouge plus sans une
ligne au journal, il ne passe jamais sous zéro, et seule la Direction le gère.
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

# Un vrai PNG d'un pixel.
PNG = "data:image/png;base64," + base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class BoutiqueStockTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = c.post("/api/auth/register-school", json={"email": "dir@boutique.test", "password": "Secret123!",
                                                      "name": "Directrice", "school_name": "École Boutique"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.dir_h = {"Authorization": "Bearer " + r.get_json()["token"]}
        annee = c.get("/api/academic-years", headers=cls.dir_h).get_json()[0]["id"]
        classe = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee}, headers=cls.dir_h).get_json()
        cls.eleve = c.post("/api/students", json={"first_name": "Grace", "last_name": "Kabongo", "academic_year_id": annee,
                                                  "class_id": classe["id"]}, headers=cls.dir_h).get_json()
        inv = c.post("/api/invitations", json={"role": "parent", "student_ids": [cls.eleve["id"]]}, headers=cls.dir_h)
        acc = c.post("/api/invitations/accept", json={"token": inv.get_json()["token"], "name": "Jean Kabongo",
                                                       "email": "parent@boutique.test", "password": "Secret123!"})
        cls.par_h = {"Authorization": "Bearer " + acc.get_json()["token"]}

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _produit(self, **kw):
        corps = {"name": kw.pop("name", "Chemise blanche"), "price": 12, "stock": 5, "category": "uniformes", **kw}
        r = self.c.post("/api/store/products", json=corps, headers=self.dir_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    def _stock(self, pid):
        return next(p for p in self.c.get("/api/store/products", headers=self.dir_h).get_json() if p["id"] == pid)["stock"]

    def _mvt(self, pid, h=None, **corps):
        return self.c.post(f"/api/store/products/{pid}/stock", json=corps, headers=h or self.dir_h)

    def test_01_chaque_mouvement_laisse_une_trace(self):
        pid = self._produit()
        self.assertEqual(self._mvt(pid, kind="reception", quantity=10).status_code, 201)
        self.assertEqual(self._mvt(pid, kind="defectueux", quantity=2).status_code, 400, "défectueux sans raison accepté")
        self.assertEqual(self._mvt(pid, kind="defectueux", quantity=2, reason="Couture défaite").status_code, 201)
        self.assertEqual(self._mvt(pid, kind="retrait", quantity=3, reason="Ancien modèle").status_code, 201)
        self.assertEqual(self._stock(pid), 10)
        self.assertEqual(self._mvt(pid, kind="inventaire", quantity=7).status_code, 201)
        self.assertEqual(self._stock(pid), 7, "l'inventaire ne fixe pas le stock compté")
        journal = [m for m in self.c.get("/api/store/movements", headers=self.dir_h).get_json() if m["product_id"] == pid]
        self.assertEqual(sorted(m["kind"] for m in journal),
                         ["defectueux", "inventaire", "reception", "reception", "retrait"])
        self.assertEqual(sum(m["quantity"] for m in journal), 7, "le journal ne refait pas le stock")

    def test_02_le_stock_ne_passe_jamais_sous_zero(self):
        pid = self._produit(stock=2)
        r = self._mvt(pid, kind="perte", quantity=5, reason="Inventaire")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self._stock(pid), 2)
        journal = [m for m in self.c.get("/api/store/movements", headers=self.dir_h).get_json() if m["product_id"] == pid]
        self.assertEqual(len(journal), 1, "un mouvement refusé a été écrit au journal")

    def test_03_seule_la_direction_gere_le_stock(self):
        pid = self._produit()
        self.assertEqual(self._mvt(pid, self.par_h, kind="reception", quantity=10).status_code, 403)
        self.assertEqual(self.c.get("/api/store/stats", headers=self.par_h).status_code, 403)
        self.assertEqual(self.c.get("/api/store/movements", headers=self.par_h).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/store/products/{pid}", headers=self.par_h).status_code, 403)
        self.assertEqual(self.c.post("/api/store/products", json={"name": "X", "price": 1}, headers=self.par_h).status_code, 403)

    def test_04_vente_et_annulation_passent_au_journal(self):
        pid = self._produit(name="Cravate", stock=4)
        r = self.c.post("/api/store/orders", json={"student_id": self.eleve["id"], "items": [{"product_id": pid, "quantity": 3}]},
                        headers=self.par_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(self._stock(pid), 1)
        stats = {p["id"]: p for p in self.c.get("/api/store/stats", headers=self.dir_h).get_json()["produits"]}
        self.assertEqual(stats[pid]["vendus"], 3)
        self.assertEqual(stats[pid]["etat"], "bas", "1 en stock sous le seuil de 3 : pas signalé")
        self.assertEqual(self.c.post(f"/api/store/orders/{r.get_json()['id']}/status", json={"status": "cancelled"},
                                     headers=self.dir_h).status_code, 200)
        self.assertEqual(self._stock(pid), 4)
        kinds = [m["kind"] for m in self.c.get("/api/store/movements", headers=self.dir_h).get_json() if m["product_id"] == pid]
        self.assertIn("vente", kinds)
        self.assertIn("annulation", kinds)
        # Rupture : plus rien à vendre, le parent ne peut pas commander.
        self.assertEqual(self._mvt(pid, kind="retrait", quantity=4, reason="Fin de saison").status_code, 201)
        r = self.c.post("/api/store/orders", json={"student_id": self.eleve["id"], "items": [{"product_id": pid, "quantity": 1}]},
                        headers=self.par_h)
        self.assertEqual(r.status_code, 409)
        stats = {p["id"]: p for p in self.c.get("/api/store/stats", headers=self.dir_h).get_json()["produits"]}
        self.assertEqual(stats[pid]["etat"], "rupture")
        self.assertEqual(stats[pid]["retires"], 4)

    def test_05_photo_valide_servie_photo_piegee_refusee(self):
        pid = self._produit(name="Pull vert", image_data=PNG)
        liste = next(p for p in self.c.get("/api/store/products", headers=self.par_h).get_json() if p["id"] == pid)
        self.assertEqual(liste["has_image"], 1)
        self.assertNotIn("image_data", liste, "la photo voyage dans la liste")
        img = self.c.get(f"/api/store/products/{pid}/image", headers=self.par_h)
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.mimetype, "image/png")
        self.assertTrue(img.data.startswith(b"\x89PNG"))
        piege = 'data:image/png;base64,AAAA" onerror="alert(1)'
        self.assertEqual(self.c.put(f"/api/store/products/{pid}", json={"image_data": piege}, headers=self.dir_h).status_code, 400)

    def test_06_supprimer_seulement_ce_qui_n_a_jamais_ete_vendu(self):
        jamais = self._produit(name="Erreur de saisie")
        self.assertEqual(self.c.delete(f"/api/store/products/{jamais}", headers=self.dir_h).status_code, 200)
        vendu = self._produit(name="Journal de classe")
        self.c.post("/api/store/orders", json={"student_id": self.eleve["id"], "items": [{"product_id": vendu, "quantity": 1}]},
                    headers=self.par_h)
        self.assertEqual(self.c.delete(f"/api/store/products/{vendu}", headers=self.dir_h).status_code, 409)


if __name__ == "__main__":
    unittest.main()
