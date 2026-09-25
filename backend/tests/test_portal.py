"""KLASSIO — lot 1 : portail par établissement, connexion par téléphone,
réinitialisation de mot de passe par la Direction, identifiants personnalisés."""
import unittest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db  # noqa: E402
db.DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "klassio_test.db"))
import app as flask_app_module  # noqa: E402
import security  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def _school(self, email, name):
        r = self.c.post("/api/auth/register-school", json={"email": email, "password": "Secret123!", "name": "Dir", "school_name": name})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()

    def test_01_slug_generated_unique_and_portal_is_public_without_business_data(self):
        a = self._school("d1@portal.test", "Collège Sainte-Thérèse")
        b = self._school("d2@portal.test", "Collège Sainte Thérèse")  # même nom → slug distinct
        self.assertEqual(a["slug"], "college-sainte-therese")
        self.assertEqual(b["slug"], "college-sainte-therese-2")
        r = self.c.get("/api/portal/college-sainte-therese")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.get_json().keys()), {"slug", "name", "tagline", "logo_data", "cover_data", "accent_color", "show_flag"})
        self.assertEqual(self.c.get("/api/portal/inconnue").status_code, 404)
        # La Direction habille son portail ; le public le voit ; l'adresse est modifiable si libre
        h = {"Authorization": "Bearer " + a["token"]}
        r = self.c.put("/api/settings", json={"accent_color": "#1f5fa8", "tagline": "Une école, une famille", "slug": "sainte-therese", "show_flag": True,
                                            "logo_data": "data:image/png;base64,iVBORw0KGgo="}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        p = self.c.get("/api/portal/sainte-therese").get_json()
        self.assertEqual(p["accent_color"], "#1F5FA8"); self.assertTrue(p["show_flag"]); self.assertEqual(p["tagline"], "Une école, une famille")
        self.assertEqual(self.c.get("/api/portal/college-sainte-therese").status_code, 404)
        hb = {"Authorization": "Bearer " + b["token"]}
        self.assertEqual(self.c.put("/api/settings", json={"slug": "sainte-therese"}, headers=hb).status_code, 409)
        self.assertEqual(self.c.put("/api/settings", json={"accent_color": "bleu"}, headers=h).status_code, 400)
        self.assertEqual(self.c.put("/api/settings", json={"logo_data": "data:text/html,<script>"}, headers=h).status_code, 400)

    def test_02_parent_can_join_and_log_in_with_phone_only(self):
        s = self._school("d3@portal.test", "École du Téléphone")
        h = {"Authorization": "Bearer " + s["token"]}
        year = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        kid = self.c.post("/api/students", json={"first_name": "Kevin", "last_name": "M", "academic_year_id": year}, headers=h).get_json()
        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [kid["id"]]}, headers=h).get_json()
        # Sans email ni téléphone : refusé
        self.assertEqual(self.c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Jean", "password": "Secret123!"}).status_code, 400)
        # Téléphone saisi « à la congolaise »
        r = self.c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Jean M", "phone": "0900 00 01 23", "password": "Secret123!"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        me = self.c.get("/api/me", headers={"Authorization": "Bearer " + r.get_json()["token"]}).get_json()
        self.assertEqual(me["phone"], "+243900000123"); self.assertIsNone(me["email"])  # email technique jamais exposé
        self.assertEqual(me["branding"]["name"], "École du Téléphone")
        # Connexion par téléphone, formats variés ; mauvais mot de passe refusé
        for ident in ("+243900000123", "0900000123", "243 900 000 123"):
            self.assertEqual(self.c.post("/api/auth/login", json={"identifier": ident, "password": "Secret123!"}).status_code, 200, ident)
        self.assertEqual(self.c.post("/api/auth/login", json={"identifier": "0900000123", "password": "Faux!1234"}).status_code, 401)
        # Le numéro est unique
        inv2 = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [kid["id"]]}, headers=h).get_json()
        self.assertEqual(self.c.post("/api/invitations/accept", json={"token": inv2["token"], "name": "Autre", "phone": "+243900000123", "password": "Secret123!"}).status_code, 409)
        # Le parent complète son profil (email) puis se connecte par email aussi
        ph = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.assertEqual(self.c.put("/api/me", json={"email": "jean@portal.test"}, headers=ph).status_code, 200)
        self.assertEqual(self.c.post("/api/auth/login", json={"identifier": "jean@portal.test", "password": "Secret123!"}).status_code, 200)

    def test_03_direction_reset_link_single_use_scoped_and_revokes_sessions(self):
        s = self._school("d4@portal.test", "École Reset")
        h = {"Authorization": "Bearer " + s["token"]}
        inv = self.c.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()
        acc = self.c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Prof", "email": "prof@portal.test", "password": "Secret123!"}).get_json()
        prof_h = {"Authorization": "Bearer " + acc["token"]}
        prof_id = self.c.get("/api/me", headers=prof_h).get_json()["user_id"]
        # Le professeur ne peut pas générer de lien ; une autre école non plus
        self.assertEqual(self.c.post(f"/api/team/{prof_id}/reset-link", headers=prof_h).status_code, 403)
        other = self._school("d5@portal.test", "Autre École")
        self.assertEqual(self.c.post(f"/api/team/{prof_id}/reset-link", headers={"Authorization": "Bearer " + other["token"]}).status_code, 404)
        # La Direction génère le lien
        r = self.c.post(f"/api/team/{prof_id}/reset-link", headers=h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        token = r.get_json()["token"]
        look = self.c.get("/api/password-reset/lookup?token=" + token)
        self.assertEqual(look.status_code, 200); self.assertEqual(look.get_json()["name"], "Prof")
        self.assertEqual(self.c.post("/api/password-reset", json={"token": token, "password": "faible"}).status_code, 400)
        r2 = self.c.post("/api/password-reset", json={"token": token, "password": "Nouveau123!"})
        self.assertEqual(r2.status_code, 200, r2.get_data(as_text=True))
        # Ancienne session révoquée, ancien mot de passe refusé, nouveau accepté, lien consommé
        self.assertEqual(self.c.get("/api/me", headers=prof_h).status_code, 401)
        self.assertEqual(self.c.post("/api/auth/login", json={"identifier": "prof@portal.test", "password": "Secret123!"}).status_code, 401)
        self.assertEqual(self.c.post("/api/auth/login", json={"identifier": "prof@portal.test", "password": "Nouveau123!"}).status_code, 200)
        self.assertEqual(self.c.get("/api/password-reset/lookup?token=" + token).status_code, 404)
        self.assertEqual(self.c.post("/api/password-reset", json={"token": token, "password": "Encore123!"}).status_code, 404)

    def test_04_student_code_format_chosen_by_school(self):
        s = self._school("d6@portal.test", "Complexe Scolaire La Référence")
        h = {"Authorization": "Bearer " + s["token"]}
        year = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        r = self.c.put("/api/settings", json={"code_prefix": "cslr", "code_mode": "sequential"}, headers=h)
        self.assertEqual(r.status_code, 200); self.assertEqual(r.get_json()["code_prefix"], "CSLR")
        codes = [self.c.post("/api/students", json={"first_name": f"E{i}", "last_name": "X", "academic_year_id": year}, headers=h).get_json()["code"] for i in range(3)]
        self.assertEqual(codes, ["CSLR-0001", "CSLR-0002", "CSLR-0003"])
        self.c.put("/api/settings", json={"code_mode": "random"}, headers=h)
        c = self.c.post("/api/students", json={"first_name": "E4", "last_name": "X", "academic_year_id": year}, headers=h).get_json()["code"]
        self.assertRegex(c, r"^CSLR-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertEqual(self.c.put("/api/settings", json={"code_prefix": "!"}, headers=h).status_code, 400)


if __name__ == "__main__":
    unittest.main()
