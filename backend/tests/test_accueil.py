"""KLASSIO — Welcome Experience : ce que l'accueil a le droit d'affirmer.

L'accueil d'invitation présente à l'utilisateur des faits sur SON établissement :
« vous êtes titulaire de la 6e A », « voici vos trois enfants ». Ces phrases
n'ont de valeur que si elles viennent du serveur et correspondent à ce qui est
réellement enregistré.

Ces tests vérifient donc trois choses, dans cet ordre d'importance :

1. Ce que l'accueil AFFICHE vient de l'invitation créée par la Direction, et
   rien d'autre n'est joignable depuis cette page publique.
2. Ce que l'accueil ANNONCE en fin de parcours correspond à ce qui a été écrit
   — la réponse d'acceptation relit la base après le commit, elle ne recopie
   pas ce que le navigateur affichait.
3. Ce que le client ENVOIE ne décide de rien : rôle, classes, enfants et
   identifiant interne sont imposés par le serveur.
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


class BaseAccueil(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def ecole(self, suffixe, nom="École Test"):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@test.local", "password": "Secret123!",
            "name": "Directeur", "school_name": nom})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        h = {"Authorization": f"Bearer {r.get_json()['token']}"}
        an = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        return h, an

    def classe(self, h, an, nom):
        return self.c.post("/api/classes", json={
            "name": nom, "academic_year_id": an, "cycle": "secondaire"}, headers=h).get_json()["id"]

    def eleve(self, h, an, cls, prenom, nom="Mukendi"):
        return self.c.post("/api/students", json={
            "first_name": prenom, "last_name": nom,
            "academic_year_id": an, "class_id": cls}, headers=h).get_json()["id"]


class ContexteAffiche(BaseAccueil):
    def test_01_professeur_voit_ses_classes_sa_titularite_et_ses_effectifs(self):
        h, an = self.ecole("prof", "Lycée Bel-Air")
        c6, c5 = self.classe(h, an, "6e A"), self.classe(h, an, "5e B")
        self.eleve(h, an, c6, "Audrey")
        self.eleve(h, an, c6, "Kevin")

        inv = self.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": [c6, c5],
            "titulaire_class_id": c6, "label": "Jean Kabasele"}, headers=h).get_json()
        d = self.c.get(f"/api/invitations/lookup?token={inv['token']}").get_json()

        self.assertEqual(d["role"], "professeur")
        self.assertEqual(d["tenant_name"], "Lycée Bel-Air")
        self.assertEqual(d["suggested_name"], "Jean Kabasele")
        self.assertEqual(d["titulaire_of"], ["6e A"],
                         "la titularité affichée doit venir de l'invitation, pas d'une déduction")
        par_nom = {c["name"]: c for c in d["classes"]}
        self.assertEqual(par_nom["6e A"]["student_count"], 2)
        self.assertEqual(par_nom["5e B"]["student_count"], 0,
                         "un effectif affiché doit être compté, jamais arrondi ni inventé")

    def test_02_parent_ne_voit_que_les_enfants_de_son_invitation(self):
        h, an = self.ecole("parent")
        cls = self.classe(h, an, "6e A")
        mien = self.eleve(h, an, cls, "Audrey")
        autre = self.eleve(h, an, cls, "Enfant", "Inconnu")

        inv = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [mien]}, headers=h).get_json()
        d = self.c.get(f"/api/invitations/lookup?token={inv['token']}").get_json()

        ids = [s["id"] for s in d["students"]]
        self.assertEqual(ids, [mien])
        self.assertNotIn(autre, ids,
                         "un élève hors invitation ne doit jamais apparaître sur une page publique")

    def test_03_aucune_recherche_libre_deleves_depuis_la_page_publique(self):
        """Le parent doit pouvoir confirmer ses enfants, jamais les chercher.
        On vérifie qu'aucune route d'élèves n'est joignable sans session."""
        h, an = self.ecole("recherche")
        cls = self.classe(h, an, "6e A")
        sid = self.eleve(h, an, cls, "Audrey")
        for chemin in ("/api/students", f"/api/students/{sid}", "/api/classes", "/api/team"):
            r = self.c.get(chemin)
            self.assertEqual(r.status_code, 401, f"{chemin} répond {r.status_code} sans authentification")


class EtatsDInvitation(BaseAccueil):
    def test_04_chaque_etat_a_son_propre_message(self):
        """Confondre « déjà utilisée » et « révoquée » envoie l'utilisateur au
        mauvais endroit : le premier doit se connecter, le second doit
        réclamer un nouveau lien."""
        h, an = self.ecole("etats")
        cls = self.classe(h, an, "6e A")
        sid = self.eleve(h, an, cls, "Audrey")

        # Inconnue
        r = self.c.get("/api/invitations/lookup?token=jeton-qui-nexiste-pas")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["state"], "inconnue")

        # Révoquée
        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [sid]}, headers=h).get_json()
        self.c.post(f"/api/invitations/{inv['id']}/revoke", headers=h)
        security.reset_rate_limits_for_tests()
        self.assertEqual(self.c.get(f"/api/invitations/lookup?token={inv['token']}").get_json()["state"], "revoquee")

        # Utilisée
        inv2 = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [sid]}, headers=h).get_json()
        security.reset_rate_limits_for_tests()
        self.c.post("/api/invitations/accept", json={
            "token": inv2["token"], "name": "Parent", "email": "etats.parent@test.local",
            "password": "Secret123!"})
        security.reset_rate_limits_for_tests()
        corps = self.c.get(f"/api/invitations/lookup?token={inv2['token']}").get_json()
        self.assertEqual(corps["state"], "utilisee")
        self.assertIn("Connectez-vous", corps["error"],
                      "après une activation réussie, l'utilisateur doit être orienté vers la connexion")


class CeQueLeServeurConfirme(BaseAccueil):
    def test_05_lacceptation_renvoie_ce_qui_a_ete_reellement_ecrit(self):
        h, an = self.ecole("confirme")
        c6, c5 = self.classe(h, an, "6e A"), self.classe(h, an, "5e B")
        inv = self.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": [c6, c5], "titulaire_class_id": c6}, headers=h).get_json()
        security.reset_rate_limits_for_tests()
        corps = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Jean Kabasele",
            "email": "confirme.prof@test.local", "password": "Secret123!"}).get_json()

        noms = sorted(c["name"] for c in corps["confirmed"]["classes"])
        self.assertEqual(noms, ["5e B", "6e A"])
        self.assertEqual(corps["confirmed"]["titulaire_of"], ["6e A"])

        # …et cela correspond bien à la base, pas seulement à la réponse.
        conn = db.get_connection()
        reel = conn.execute(
            """SELECT c.name, ct.is_titulaire FROM class_teachers ct
               JOIN classes c ON c.id = ct.class_id
               JOIN users u ON u.id = ct.user_id WHERE u.email=?""",
            ("confirme.prof@test.local",)).fetchall()
        conn.close()
        self.assertEqual(sorted(r["name"] for r in reel), ["5e B", "6e A"])
        self.assertEqual([r["name"] for r in reel if r["is_titulaire"]], ["6e A"])

    def test_06_identifiant_enseignant_genere_par_le_serveur_et_refuse_au_client(self):
        h, an = self.ecole("code")
        cls = self.classe(h, an, "6e A")
        inv = self.c.post("/api/invitations", json={"role": "professeur", "class_ids": [cls]}, headers=h).get_json()
        security.reset_rate_limits_for_tests()
        corps = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof", "email": "code.prof@test.local",
            "password": "Secret123!",
            # Tentative d'imposer son propre identifiant.
            "staff_code": "TCH-0000-0000"}).get_json()

        self.assertTrue(corps["staff_code"].startswith("TCH-"), corps["staff_code"])
        self.assertNotEqual(corps["staff_code"], "TCH-0000-0000",
                            "l'identifiant interne ne doit jamais venir du client")
        self.assertRegex(corps["staff_code"], r"^TCH-[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}$")

    def test_07_le_parent_ne_recoit_pas_didentifiant_de_personnel(self):
        h, an = self.ecole("codeparent")
        cls = self.classe(h, an, "6e A")
        sid = self.eleve(h, an, cls, "Audrey")
        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [sid]}, headers=h).get_json()
        security.reset_rate_limits_for_tests()
        corps = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "codeparent@test.local",
            "password": "Secret123!"}).get_json()
        self.assertIsNone(corps["staff_code"])

    def test_08_le_role_envoye_par_le_client_est_ignore(self):
        """Le frontend ne déclare jamais « je suis professeur »."""
        h, an = self.ecole("role")
        cls = self.classe(h, an, "6e A")
        sid = self.eleve(h, an, cls, "Audrey")
        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [sid]}, headers=h).get_json()
        security.reset_rate_limits_for_tests()
        corps = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "role@test.local",
            "password": "Secret123!",
            "role": "directeur", "tenant_id": "une-autre-ecole"}).get_json()
        self.assertEqual(corps["role"], "parent")
        self.assertNotEqual(corps["tenant_id"], "une-autre-ecole")


class ClotureDeLAccueil(BaseAccueil):
    def _compte_parent(self, suffixe):
        h, an = self.ecole(suffixe)
        cls = self.classe(h, an, "6e A")
        sid = self.eleve(h, an, cls, "Audrey")
        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [sid]}, headers=h).get_json()
        security.reset_rate_limits_for_tests()
        corps = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": f"{suffixe}.p@test.local",
            "password": "Secret123!"}).get_json()
        return {"Authorization": f"Bearer {corps['token']}"}

    def test_09_laccueil_ne_se_rejoue_pas_et_la_cloture_est_idempotente(self):
        ph = self._compte_parent("cloture")
        self.assertFalse(self.c.get("/api/me/onboarding", headers=ph).get_json()["completed"])

        premier = self.c.post("/api/me/onboarding", json={}, headers=ph).get_json()
        self.assertTrue(premier["completed"])

        # Double clic / rejeu réseau : la date de première complétion ne bouge pas.
        second = self.c.post("/api/me/onboarding", json={}, headers=ph).get_json()
        self.assertEqual(second["completed_at"], premier["completed_at"],
                         "une seconde clôture a réécrit la date de première complétion")

        # À la connexion suivante, l'accueil ne doit plus se jouer.
        self.assertTrue(self.c.get("/api/me/onboarding", headers=ph).get_json()["completed"])

    def test_10_revoir_lintroduction_rouvre_laccueil(self):
        ph = self._compte_parent("revoir")
        self.c.post("/api/me/onboarding", json={}, headers=ph)
        rejoue = self.c.post("/api/me/onboarding", json={"replay": True}, headers=ph).get_json()
        self.assertFalse(rejoue["completed"])
        self.assertIsNone(rejoue["completed_at"])

    def test_11_letat_daccueil_est_propre_a_chaque_compte(self):
        a = self._compte_parent("isoA")
        b = self._compte_parent("isoB")
        self.c.post("/api/me/onboarding", json={}, headers=a)
        self.assertTrue(self.c.get("/api/me/onboarding", headers=a).get_json()["completed"])
        self.assertFalse(self.c.get("/api/me/onboarding", headers=b).get_json()["completed"],
                         "la clôture d'un compte a marqué l'accueil d'un autre comme terminé")

    def test_12_laccueil_exige_une_session(self):
        self.assertEqual(self.c.get("/api/me/onboarding").status_code, 401)
        self.assertEqual(self.c.post("/api/me/onboarding", json={}).status_code, 401)


class CorpsJsonMalforme(BaseAccueil):
    """Un corps JSON qui n'est pas un objet doit produire un refus propre (400),
    pas une erreur interne (500).

    Trouvé pendant l'audit : POST /api/invitations avec un corps `"texte"`
    levait AttributeError sur `data.get(...)`, c'est-à-dire une 500 pour une
    entrée simplement malformée. `or {}` ne protégeait pas — une chaîne JSON
    non vide est vraie.
    """

    def test_13_un_corps_non_objet_est_refuse_proprement(self):
        h, _ = self.ecole("json")
        cas = [('"texte"', "chaîne"), ("[1,2,3]", "tableau"), ("42", "nombre"), ("true", "booléen")]
        for brut, quoi in cas:
            with self.subTest(corps=quoi):
                r = self.c.post("/api/invitations", data=brut,
                                content_type="application/json", headers=h)
                self.assertEqual(r.status_code, 400,
                                 f"corps {quoi} → {r.status_code} (attendu 400) : {r.get_data(as_text=True)[:120]}")

    def test_14_les_routes_publiques_aussi(self):
        for chemin in ("/api/auth/login", "/api/invitations/accept"):
            security.reset_rate_limits_for_tests()
            r = self.c.post(chemin, data='"texte"', content_type="application/json")
            self.assertNotEqual(r.status_code, 500,
                                f"{chemin} renvoie 500 sur un corps malformé")


if __name__ == "__main__":
    unittest.main()
