"""KLASSIO — reprendre le calendrier de l'année précédente (08/10/2026).

Le propriétaire : « pour chaque début d'année, que le système propose au
directeur de garder le même calendrier ou d'apporter des modifications ».
Une année neuve naissait sans aucune période : P1, P2, examens, dates et
pondérations étaient à ressaisir chaque année.
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


class CalendrierReconduitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c = flask_app_module.app.test_client()

    def _ecole(self, nom):
        security.reset_rate_limits_for_tests()
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir@{nom.lower().replace(' ', '-')}.cal.test", "password": "Secret123!",
            "name": "Directrice", "school_name": nom})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.tenant = r.get_json()["tenant_id"]
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def _nouvelle_annee(self, h, libelle):
        r = self.c.post("/api/academic-years", json={"label": libelle}, headers=h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(self.c.post(f"/api/academic-years/{r.get_json()['id']}/activate", headers=h).status_code, 200)

    def _periodes(self, h):
        return [p for d in self.c.get("/api/academic-calendar", headers=h).get_json()["divisions"] for p in d["periods"]]

    def test_01_garder_le_meme_calendrier(self):
        h = self._ecole("Ecole Reconduite")
        for corps in ({"label": "Période 1", "starts_on": "2025-09-02", "ends_on": "2025-10-31", "weight": 1, "sort": 0},
                      {"label": "Examen 1er semestre", "starts_on": "2025-12-08", "ends_on": "2025-12-19",
                       "weight": 2, "is_exam": True, "sort": 1, "proclamation_at": "2026-01-10"},
                      {"label": "Période 3", "starts_on": "2026-02-02", "ends_on": "2026-02-29", "weight": 1.5, "sort": 2}):
            r = self.c.post("/api/periods", json=corps, headers=h)
            # 2026 n'est pas bissextile : le 29 février est refusé à la saisie ;
            # on le force en base pour éprouver le décalage d'un 29 février.
            if r.status_code != 201:
                self.assertEqual(corps["label"], "Période 3")
                corps = {**corps, "ends_on": "2026-02-27"}
                self.assertEqual(self.c.post("/api/periods", json=corps, headers=h).status_code, 201)
        ancienne = {p["label"]: p for p in self._periodes(h)}
        conn = db.get_connection()
        conn.execute("UPDATE academic_periods SET published_at='1', ends_on='2024-02-29' WHERE id=?",
                     (ancienne["Période 3"]["id"],))
        conn.commit(); conn.close()

        self._nouvelle_annee(h, "2026-2027")
        self.assertEqual(self._periodes(h), [], "une année neuve hérite déjà d'un calendrier")
        apercu = self.c.get("/api/periods/previous-calendar", headers=h).get_json()
        self.assertTrue(apercu["available"])
        prop = {p["label"]: p for p in apercu["periods"]}
        self.assertEqual(prop["Période 1"]["starts_on"], "2026-09-02", "dates non décalées d'un an")
        self.assertEqual(prop["Examen 1er semestre"]["proclamation_at"], "2027-01-10")
        self.assertEqual(prop["Période 3"]["ends_on"], "2025-02-28", "29 février mal décalé")

        r = self.c.post("/api/periods/copy-previous", json={"mode": "garder"}, headers=h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["created"], 3)
        nouvelle = {p["label"]: p for p in self._periodes(h)}
        self.assertEqual(set(nouvelle), {"Période 1", "Examen 1er semestre", "Période 3"})
        self.assertEqual(nouvelle["Examen 1er semestre"]["weight"], 2, "pondération perdue")
        self.assertEqual(nouvelle["Période 3"]["weight"], 1.5)
        self.assertTrue(nouvelle["Examen 1er semestre"]["is_exam"])
        self.assertFalse(nouvelle["Période 3"].get("published_at"), "la proclamation de l'an dernier a été reprise")
        # L'année passée n'a pas bougé.
        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM academic_periods WHERE id=?", (ancienne["Période 1"]["id"],)).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 1)

        # Jamais d'écrasement : un second appel est refusé, et l'aperçu se tait.
        self.assertEqual(self.c.post("/api/periods/copy-previous", json={"mode": "garder"}, headers=h).status_code, 409)
        self.assertFalse(self.c.get("/api/periods/previous-calendar", headers=h).get_json()["available"])

    def test_02_modifier_cree_des_brouillons(self):
        h = self._ecole("Ecole Brouillon")
        self.assertEqual(self.c.post("/api/periods", json={"label": "P1", "starts_on": "2025-09-01",
                                                           "ends_on": "2025-11-01"}, headers=h).status_code, 201)
        self._nouvelle_annee(h, "2026-2027")
        r = self.c.post("/api/periods/copy-previous", json={"mode": "modifier"}, headers=h)
        self.assertEqual(r.status_code, 201)
        conn = db.get_connection()
        etats = {row["admin_state"] for row in conn.execute(
            """SELECT p.admin_state FROM academic_periods p JOIN academic_years y ON y.id = p.academic_year_id
                WHERE p.tenant_id=? AND y.label='2026-2027'""", (self.tenant,)).fetchall()}
        conn.close()
        self.assertEqual(etats, {"DRAFT"})
        self.assertEqual(self.c.post("/api/periods/copy-previous", json={"mode": "modifier"}, headers=h).status_code, 409)

    def test_03_le_calendrier_d_une_autre_ecole_n_est_jamais_propose(self):
        h_a = self._ecole("Ecole Voisine A")
        self.assertEqual(self.c.post("/api/periods", json={"label": "P1"}, headers=h_a).status_code, 201)
        self._nouvelle_annee(h_a, "2026-2027")
        h_b = self._ecole("Ecole Voisine B")
        self._nouvelle_annee(h_b, "2026-2027")
        self.assertFalse(self.c.get("/api/periods/previous-calendar", headers=h_b).get_json()["available"])
        self.assertEqual(self.c.post("/api/periods/copy-previous", json={"mode": "garder"}, headers=h_b).status_code, 404)
        self.assertEqual(self.c.post("/api/periods/copy-previous", json={"mode": "n'importe"}, headers=h_b).status_code, 400)


if __name__ == "__main__":
    unittest.main()
