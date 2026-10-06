"""KLASSIO — l'abonnement sans mode gratuit (décision du propriétaire, 01/10/2026).

Une école naît FERMÉE : elle dépose ses fichiers Excel, choisit son offre
(obligatoire), règle la première facture, et ne s'ouvre qu'à la confirmation
du paiement par la plateforme. Le serveur décide de tout — l'offre trop petite
pour l'effectif, l'offre sur devis, le contournement réservé aux testeurs.

Ce module remet config.CONTOURNER_ABONNEMENT à False (tests/__init__.py le
met à True pour les autres modules) : c'est la vraie règle qu'on éprouve.
"""
import unittest, sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402
import db  # noqa: E402
db.DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "klassio_test.db"))
import app as flask_app_module  # noqa: E402
from tests.outils_plateforme import session_admin  # noqa: E402
import security  # noqa: E402
from security import new_id  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class AbonnementTests(unittest.TestCase):
    compteur = 0

    @classmethod
    def setUpClass(cls):
        cls.c = flask_app_module.app.test_client()

    def setUp(self):
        security.reset_rate_limits_for_tests()
        self._ancien = config.CONTOURNER_ABONNEMENT
        config.CONTOURNER_ABONNEMENT = False

    def tearDown(self):
        config.CONTOURNER_ABONNEMENT = self._ancien

    # ------------------------------------------------------------ outils
    def _ecole(self, nom=None):
        AbonnementTests.compteur += 1
        n = AbonnementTests.compteur
        r = self.c.post("/api/auth/register-school", json={"email": f"dir{n}@abo.test", "password": "Secret123!",
                                                            "name": "Directeur Abo", "school_name": nom or f"École Abo {n}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        b = r.get_json()
        return b["tenant_id"], {"Authorization": "Bearer " + b["token"]}

    def _eleves(self, tenant_id, nombre):
        conn = db.get_connection()
        an = conn.execute("SELECT id FROM academic_years WHERE tenant_id=?", (tenant_id,)).fetchone()["id"]
        now = str(time.time())
        for i in range(nombre):
            conn.execute("INSERT INTO students (id, tenant_id, academic_year_id, first_name, last_name, status, created_at) VALUES (?,?,?,?,?,'active',?)",
                         (new_id(), tenant_id, an, f"E{i}", "Test", now))
        conn.commit(); conn.close()

    def _admin(self):
        """Une session d'ADMINISTRATION de la plateforme : compte à part, second
        facteur (backend/platform_auth.py). Jusqu'au 06/10/2026, ces tests
        promouvaient le directeur lui-même — ce qui n'ouvre plus rien."""
        client, csrf, _ = session_admin(flask_app_module.app)
        return client, csrf

    def _activer(self, h, plan="essentiel"):
        inv = self.c.post("/api/subscription/choose", json={"plan_code": plan}, headers=h).get_json()["invoice"]
        self.assertEqual(self.c.post("/api/subscription/pay", json={"invoice_id": inv["id"], "method": "bank", "reference": "VIR-1"}, headers=h).status_code, 200)
        admin, csrf = self._admin()
        self.assertEqual(admin.post(f"/api/platform/invoices/{inv['id']}/confirm", headers=csrf).status_code, 200)

    # ------------------------------------------------------------ règles
    def test_ecole_neuve_fermee_sauf_ce_qui_sert_a_l_ouvrir(self):
        tid, h = self._ecole()
        s = self.c.get("/api/subscription", headers=h).get_json()
        self.assertEqual(s["status"], "awaiting_plan")
        self.assertTrue(s["locked"]); self.assertFalse(s["bypass"]); self.assertIsNone(s["trial_ends_at"])
        # Fermée : lecture comprise.
        for chemin in ("/api/students", "/api/classes", "/api/messages/threads", "/api/dashboard"):
            self.assertEqual(self.c.get(chemin, headers=h).status_code, 402, chemin)
        self.assertEqual(self.c.post("/api/students", json={"first_name": "A", "last_name": "B"}, headers=h).status_code, 402)
        # Ce qui sert à l'ouvrir répond : session, offres, abonnement, import de départ.
        self.assertEqual(self.c.get("/api/me", headers=h).status_code, 200)
        self.assertEqual(self.c.get("/api/plans").status_code, 200)
        r = self.c.post("/api/onboarding/analyze-import", headers=h)
        self.assertNotEqual(r.status_code, 402, "l'import de départ doit rester possible avant le choix de l'offre")

    def test_offre_plus_petite_que_l_effectif_refusee(self):
        tid, h = self._ecole()
        self._eleves(tid, 320)
        r = self.c.post("/api/subscription/choose", json={"plan_code": "essentiel"}, headers=h)
        self.assertEqual(r.status_code, 400)
        self.assertIn("320", r.get_json()["error"])
        self.assertEqual(self.c.get("/api/subscription", headers=h).get_json()["required_plan"]["code"], "ecole")
        r = self.c.post("/api/subscription/choose", json={"plan_code": "ecole"}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["invoice"]["amount"], 149.9)

    def test_offre_sur_devis_pas_en_libre_service(self):
        tid, h = self._ecole()
        r = self.c.post("/api/subscription/choose", json={"plan_code": "reseau"}, headers=h)
        self.assertEqual(r.status_code, 409); self.assertTrue(r.get_json()["quote"])
        self.assertEqual(self.c.get("/api/subscription", headers=h).get_json()["status"], "awaiting_plan")
        self.assertEqual(self.c.post("/api/subscription/choose", json={"plan_code": "inexistant"}, headers=h).status_code, 400)

    def test_changer_d_offre_avant_paiement_annule_la_facture(self):
        tid, h = self._ecole()
        a = self.c.post("/api/subscription/choose", json={"plan_code": "essentiel"}, headers=h).get_json()["invoice"]
        b = self.c.post("/api/subscription/choose", json={"plan_code": "complexe"}, headers=h).get_json()["invoice"]
        self.assertEqual(b["amount"], 249.9)
        conn = db.get_connection()
        statuts = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM invoices WHERE tenant_id=?", (tid,))}
        conn.close()
        self.assertEqual(statuts[a["id"]], "void"); self.assertEqual(statuts[b["id"]], "open")
        # Un paiement déclaré fige le choix.
        self.c.post("/api/subscription/pay", json={"invoice_id": b["id"], "method": "mobile_money", "reference": "MP-9"}, headers=h)
        self.assertEqual(self.c.post("/api/subscription/choose", json={"plan_code": "essentiel"}, headers=h).status_code, 409)

    def test_seule_la_confirmation_ouvre_l_espace(self):
        tid, h = self._ecole()
        self._activer(h)
        s = self.c.get("/api/subscription", headers=h).get_json()
        self.assertEqual(s["status"], "active"); self.assertFalse(s["locked"])
        self.assertIsNotNone(s["current_period_end"])
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 200)
        # Une offre active ne se change pas en libre-service.
        self.assertEqual(self.c.post("/api/subscription/choose", json={"plan_code": "ecole"}, headers=h).status_code, 409)

    def test_reserve_a_la_direction(self):
        tid, h = self._ecole()
        config.CONTOURNER_ABONNEMENT = True  # inviter un professeur suppose un espace utilisable
        inv = self.c.post("/api/invitations", json={"role": "professeur"}, headers=h)
        self.assertEqual(inv.status_code, 201, inv.get_data(as_text=True))
        acc = self.c.post("/api/invitations/accept", json={"token": inv.get_json()["token"], "name": "Prof", "email": f"prof{tid[:6]}@abo.test", "password": "Secret123!"})
        prof = {"Authorization": "Bearer " + acc.get_json()["token"]}
        config.CONTOURNER_ABONNEMENT = False
        self.assertEqual(self.c.post("/api/subscription/choose", json={"plan_code": "essentiel"}, headers=prof).status_code, 403)
        self.assertEqual(self.c.get("/api/students", headers=prof).status_code, 402)

    def test_contournement_testeur_ouvre_sans_payer(self):
        tid, h = self._ecole()
        config.CONTOURNER_ABONNEMENT = True
        s = self.c.get("/api/subscription", headers=h).get_json()
        self.assertEqual(s["status"], "awaiting_plan"); self.assertTrue(s["bypass"]); self.assertFalse(s["locked"])
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 200)

    def test_contournement_refuse_sur_une_base_distante(self):
        with self.assertRaises(ValueError):
            config.verifier_contournement(True, "postgres", "postgresql://db.ecole-exemple.cd:5432/klassio")
        self.assertTrue(config.verifier_contournement(True, "postgres", "postgresql://localhost:5432/klassio"))
        self.assertTrue(config.verifier_contournement(True, "sqlite"))
        self.assertFalse(config.verifier_contournement(False, "postgres", "postgresql://db.ecole-exemple.cd:5432/klassio"))

    def test_lecture_seule_bloque_aussi_le_cahier_de_communication(self):
        """« /api/me » était testé comme un début de chaîne : il laissait passer
        /api/messages. Une école suspendue pour impayé écrivait encore dans le
        cahier de communication."""
        tid, h = self._ecole()
        self._activer(h)
        annee = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        eleve = self.c.post("/api/students", json={"first_name": "Kevin", "last_name": "Mbala", "academic_year_id": annee}, headers=h).get_json()
        conn = db.get_connection(); conn.execute("UPDATE subscriptions SET status='suspended' WHERE tenant_id=?", (tid,)); conn.commit(); conn.close()
        r = self.c.post(f"/api/messages/{eleve['id']}", json={"body": "Bonjour"}, headers=h)
        self.assertEqual(r.status_code, 402, r.get_data(as_text=True))
        # La vraie route « /api/me/… », elle, reste ouverte (ici : refus de validation, pas 402).
        self.assertNotEqual(self.c.post("/api/me/password", json={}, headers=h).status_code, 402)

    # ---- Ouverture provisoire : une école qui a payé ne reste pas à la porte ----
    def _declarer(self, h, plan="essentiel", ref="MP-1"):
        inv = self.c.post("/api/subscription/choose", json={"plan_code": plan}, headers=h).get_json()["invoice"]
        r = self.c.post("/api/subscription/pay", json={"invoice_id": inv["id"], "method": "mobile_money", "reference": ref}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return inv, r.get_json()

    def test_paiement_declare_ouvre_provisoirement(self):
        tid, h = self._ecole()
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 402)
        inv, rep = self._declarer(h)
        self.assertIn("provisional_until", rep)
        s = self.c.get("/api/subscription", headers=h).get_json()
        self.assertEqual(s["status"], "awaiting_payment")
        self.assertTrue(s["provisional"]); self.assertFalse(s["locked"])
        self.assertIn("vérification", s["attention"])
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 200)
        self.assertTrue(self.c.get("/api/me", headers=h).get_json()["subscription"]["provisional"])
        # ~72 h : ni plus, ni moins
        conn = db.get_connection()
        jusqua = float(conn.execute("SELECT provisional_until FROM subscriptions WHERE tenant_id=?", (tid,)).fetchone()["provisional_until"])
        conn.close()
        self.assertAlmostEqual(jusqua - time.time(), 72 * 3600, delta=120)

    def test_ouverture_provisoire_expiree_referme(self):
        tid, h = self._ecole()
        self._declarer(h)
        conn = db.get_connection()
        conn.execute("UPDATE subscriptions SET provisional_until=? WHERE tenant_id=?", (str(time.time() - 60), tid)); conn.commit(); conn.close()
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 402)
        s = self.c.get("/api/subscription", headers=h).get_json()
        self.assertTrue(s["locked"]); self.assertFalse(s["provisional"])

    def test_reference_rejetee_referme_et_ne_rouvre_jamais(self):
        tid, h = self._ecole()
        inv, _ = self._declarer(h, ref="FAUSSE-REF")
        admin, csrf = self._admin()
        self.assertEqual(admin.post(f"/api/platform/invoices/{inv['id']}/void", headers=csrf).status_code, 200)
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 402)
        titres = [n["title"] for n in self.c.get("/api/notifications", headers=h).get_json()]
        self.assertTrue(any("Paiement non retrouvé" in t for t in titres))
        # Nouvelle déclaration : pas de seconde ouverture provisoire.
        inv2, rep2 = self._declarer(h, ref="AUTRE-REF")
        self.assertNotIn("provisional_until", rep2)
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 402)
        # La confirmation, elle, ouvre toujours.
        self.assertEqual(admin.post(f"/api/platform/invoices/{inv2['id']}/confirm", headers=csrf).status_code, 200)
        self.assertEqual(self.c.get("/api/students", headers=h).status_code, 200)

    def test_prix_des_offres(self):
        plans = {p["code"]: p for p in self.c.get("/api/plans").get_json()}
        self.assertEqual((plans["essentiel"]["base_price"], plans["essentiel"]["max_students"]), (99.9, 300))
        self.assertEqual((plans["ecole"]["base_price"], plans["ecole"]["max_students"]), (149.9, 1000))
        self.assertEqual((plans["complexe"]["base_price"], plans["complexe"]["max_students"]), (249.9, 3000))
        self.assertIsNone(plans["reseau"]["max_students"])
        self.assertTrue(all(p["per_student"] == 0 for p in plans.values()))


if __name__ == "__main__":
    unittest.main()
