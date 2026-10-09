"""KLASSIO — IA générative, palier 1 (décisions du propriétaire, 09/10/2026).

Ce que ces tests verrouillent, décision par décision :
  1. seulement dans les écoles ouvertes par la plateforme (KLASSIO_IA_ECOLES) ;
  2. aucun nom ne part chez le fournisseur, et aucune donnée de l'école non plus ;
  3. aucun brouillon, aucune écriture : le modèle choisit une question type,
     c'est l'assistant déterministe qui répond ;
  4. la Direction seulement ;
  5. un plafond d'appels par école et par mois ;
  6. sans clé, rien ne part.
Et le cercle 3 du séminaire : une demande d'écriture n'atteint jamais le modèle.

Le fournisseur (Anthropic, Claude) n'est JAMAIS appelé pour de vrai :
`_appeler_claude` (ou le client du SDK, pour le test de la requête) est remplacé.
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import ia_generative  # noqa: E402
import security  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class IAGenerativeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = c.post("/api/auth/register-school", json={"email": "dir@iagen.test", "password": "Secret123!",
                                                      "name": "Direction", "school_name": "École IA générative"}).get_json()
        cls.tenant_id = r["tenant_id"]
        cls.dir_h = {"Authorization": "Bearer " + r["token"]}
        annee = c.get("/api/academic-years", headers=cls.dir_h).get_json()[0]["id"]
        cls.classe = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee}, headers=cls.dir_h).get_json()
        cls.amani = c.post("/api/students", json={"first_name": "Amani", "last_name": "Kabeya", "academic_year_id": annee,
                                                  "class_id": cls.classe["id"]}, headers=cls.dir_h).get_json()
        c.post("/api/students", json={"first_name": "Grâce", "last_name": "Mbuyi", "academic_year_id": annee,
                                      "class_id": cls.classe["id"]}, headers=cls.dir_h)
        inv = c.post("/api/invitations", json={"role": "professeur"}, headers=cls.dir_h).get_json()
        acc = c.post("/api/invitations/accept", json={"token": inv["token"], "name": "Prof", "email": "prof@iagen.test",
                                                      "password": "Secret123!"}).get_json()
        cls.prof_h = {"Authorization": "Bearer " + acc["token"]}

        # Une autre école, avec ses propres élèves : son nom ne doit jamais être
        # retrouvé par la Direction de la première.
        r2 = c.post("/api/auth/register-school", json={"email": "dir@voisine.test", "password": "Secret123!",
                                                       "name": "Direction", "school_name": "École voisine"}).get_json()
        h2 = {"Authorization": "Bearer " + r2["token"]}
        annee2 = c.get("/api/academic-years", headers=h2).get_json()[0]["id"]
        cl2 = c.post("/api/classes", json={"name": "6e A", "academic_year_id": annee2}, headers=h2).get_json()
        c.post("/api/students", json={"first_name": "Zola", "last_name": "Voisin", "academic_year_id": annee2,
                                      "class_id": cl2["id"]}, headers=h2)

    def setUp(self):
        security.reset_rate_limits_for_tests()
        self.env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "cle-de-test", "KLASSIO_IA_ECOLES": self.tenant_id,
                                                "KLASSIO_IA_PLAFOND_MENSUEL": "1000"})
        self.env.start()
        self.envoyes = []

    def tearDown(self):
        self.env.stop()
        conn = db.get_connection()
        conn.execute("DELETE FROM ai_messages WHERE tenant_id = ?", (self.tenant_id,))
        conn.commit()
        conn.close()

    def _fournisseur(self, reponse):
        """Remplace le fournisseur : note ce qui lui est envoyé, rend `reponse`."""
        def faux(question_masquee):
            self.envoyes.append(question_masquee)
            return reponse
        return mock.patch.object(ia_generative, "_appeler_claude", side_effect=faux)

    def _ask(self, q, h=None):
        r = self.c.post("/api/ai/ask", json={"message": q}, headers=h or self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()

    # --- Le catalogue fermé ---------------------------------------------------

    def test_01_chaque_question_type_mene_a_son_intention(self):
        """Un gabarit qui dériverait ferait répondre l'assistant à côté."""
        attendu = {
            "situation_financiere": "financial_summary", "encaisse_ce_mois": "collected_this_month",
            "encaisse_mois_dernier": "collected_last_month", "taux_recouvrement": "collection_rate",
            "plus_gros_impayes": "biggest_unpaid", "eleves_sans_paiement": "students_no_payment",
            "nombre_eleves": "count_students", "nombre_classes": "count_classes",
            "absences_repetees": "attendance_repeat", "retards_repetes": "attendance_repeat",
            "incidents_recents": "incidents_recent", "absents_classe": "attendance_class",
            "eleves_classe": "students_by_class", "situation_eleve": "student_overview",
            "recus_eleve": "receipts_student", "expliquer_import": "explain_import",
            "expliquer_finance_paiements": "explain_finance_vs_paiements",
            "expliquer_invitations": "explain_invitations",
        }
        self.assertEqual(set(attendu), set(ia_generative.CATALOGUE))
        conn = db.get_connection()
        ctx = {"tenant_id": self.tenant_id, "user_id": self.c.get("/api/me", headers=self.dir_h).get_json()["user_id"],
               "role": "directeur", "permissions": security.ROLE_PERMISSIONS["directeur"]}
        try:
            for cle, intention in attendu.items():
                q = ia_generative._question_type({"question_type": cle, "classe": "6e A", "eleve": "Élève 1"},
                                                 {"Élève 1": "Amani Kabeya"})
                rep = flask_app_module.ai_assistant.answer_question(conn, ctx, q)
                self.assertEqual(rep["intent"], intention, f"{cle} → « {q} »")
        finally:
            conn.close()

    # --- Décision 6 : sans clé, rien ne part ------------------------------------

    def test_02_sans_cle_rien_ne_part(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        with self._fournisseur({"question_type": "situation_financiere"}):
            b = self._ask("Comment se porte la caisse ?")
        self.assertEqual(b["intent"], "fallback")
        self.assertEqual(self.envoyes, [])

    # --- Le cas nominal ---------------------------------------------------------

    def test_03_reformule_puis_l_assistant_repond(self):
        with self._fournisseur({"question_type": "situation_financiere"}):
            b = self._ask("Comment se porte la caisse ?")
        self.assertEqual(b["intent"], "gen:financial_summary")
        self.assertTrue(b["text"].startswith("Compris ainsi : « Analyse ma situation financière »"))
        self.assertEqual(b["rich"]["type"], "stats")
        self.assertTrue(b.get("generatif"))

    def test_04_une_question_comprise_n_appelle_pas_le_fournisseur(self):
        with self._fournisseur({"question_type": "nombre_classes"}):
            b = self._ask("Quels sont les plus gros impayés ?")
        self.assertEqual(b["intent"], "biggest_unpaid")
        self.assertEqual(self.envoyes, [])

    # --- Décision 2 : aucun nom ne part -----------------------------------------

    def test_05_les_noms_sont_masques_puis_retrouves_ici(self):
        with self._fournisseur({"question_type": "situation_eleve", "eleve": "Élève 1"}):
            b = self._ask("Où en est Amani Kabeya ce trimestre, côté dossier ?")
        self.assertEqual(len(self.envoyes), 1)
        parti = self.envoyes[0]
        self.assertNotIn("Amani", parti)
        self.assertNotIn("Kabeya", parti)
        self.assertIn("Élève 1", parti)
        self.assertEqual(b["intent"], "gen:student_overview")
        self.assertIn("Amani", b["text"])

    def test_06_un_prenom_seul_avec_accent_est_masque_aussi(self):
        with self._fournisseur({"question_type": AUCUNE}):
            self._ask("Est-ce que grace a des soucis en ce moment ?")
        self.assertNotIn("grace", self.envoyes[0].lower())

    def test_07_le_modele_ne_designe_que_ce_qui_a_ete_masque(self):
        """Le modèle ne peut désigner un élève que par un repère masqué dans
        CETTE question. Un repère inventé, ou un vrai nom de l'école que la
        Direction n'a pas écrit, n'ouvre aucun dossier."""
        for eleve in ("Élève 7", "Amani Kabeya"):
            with self.subTest(eleve=eleve), self._fournisseur({"question_type": "situation_eleve", "eleve": eleve}):
                b = self._ask("Fais-moi le point sur un élève au hasard")
                self.assertEqual(b["intent"], "gen:fallback")
                self.assertNotIn("Amani", b["text"])

    def test_08_un_nom_d_une_autre_ecole_ne_ressort_jamais(self):
        """« Zola » n'est pas un nom de CETTE école : il n'est pas masqué, donc
        le modèle ne peut pas le désigner par un repère — et même s'il le
        recopiait, l'assistant ne cherche que dans le périmètre de la Direction."""
        with self._fournisseur({"question_type": "situation_eleve", "eleve": "Zola Voisin"}):
            b = self._ask("Où en est Zola Voisin, côté dossier ?")
        self.assertEqual(b["intent"], "gen:fallback")
        self.assertNotIn("Voisin", json.dumps(b["rich"], ensure_ascii=False))

    def test_09_aucune_donnee_de_l_ecole_dans_la_requete(self):
        """La requête réellement construite pour Claude : question masquée et
        catalogue, rien d'autre. Pas de solde, pas de classe, pas de nom ; la
        réponse est contrainte par un schéma ; pas de nouvel essai automatique."""
        capture = {}

        class Bloc:
            type = "text"
            text = json.dumps({"question_type": "nombre_eleves", "classe": "", "eleve": ""})

        class Reponse:
            stop_reason = "end_turn"
            content = [Bloc()]

        class FauxMessages:
            def create(self, **kwargs):
                capture["requete"] = kwargs
                return Reponse()

        class FauxClient:
            def __init__(self, **kwargs):
                capture["client"] = kwargs
                self.messages = FauxMessages()

        with mock.patch.object(ia_generative.anthropic, "Anthropic", FauxClient):
            b = self._ask("Dis-moi l'effectif, et parle-moi d'Amani")
        self.assertEqual(b["intent"], "gen:count_students")
        self.assertEqual(capture["client"]["api_key"], "cle-de-test")
        self.assertEqual(capture["client"]["max_retries"], 0)
        self.assertLessEqual(capture["client"]["timeout"], 10)
        req = capture["requete"]
        self.assertEqual(req["model"], "claude-haiku-5-5")
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(set(req["output_config"]["format"]["schema"]["properties"]["question_type"]["enum"]),
                         set(ia_generative.CATALOGUE) | {AUCUNE})
        self.assertEqual([m["role"] for m in req["messages"]], ["user"])
        envoye = json.dumps(req, ensure_ascii=False)
        for interdit in ("Amani", "Kabeya", "Mbuyi", "École IA générative", self.tenant_id, self.amani["id"]):
            self.assertNotIn(interdit, envoye)

    def test_09bis_refus_ou_panne_du_fournisseur(self):
        """Un refus, une réponse tronquée, un JSON illisible ou une erreur de
        l'API rendent la réponse d'origine — jamais une exception."""
        class Bloc:
            type = "text"

            def __init__(self, text):
                self.text = text

        def client(stop_reason="end_turn", text="{}", erreur=None):
            class Messages:
                def create(self, **kwargs):
                    if erreur:
                        raise erreur
                    return type("R", (), {"stop_reason": stop_reason, "content": [Bloc(text)]})()
            return type("C", (), {"messages": Messages()})()

        erreur = ia_generative.anthropic.APIConnectionError(request=mock.Mock())
        for c in (client(stop_reason="refusal", text='{"question_type": "nombre_eleves"}'),
                  client(stop_reason="max_tokens", text='{"question_type": "nombre_eleves"}'),
                  client(text="pas du json"), client(erreur=erreur)):
            with self.subTest(), mock.patch.object(ia_generative, "_client", return_value=c):
                self.assertIsNone(ia_generative._appeler_claude("question"))

    # --- Le catalogue est fermé -------------------------------------------------

    def test_10_un_choix_hors_catalogue_est_ignore(self):
        for reponse in ({"question_type": "supprimer_eleve"}, {"question_type": "eleves_classe", "classe": "x" * 80},
                        {"question_type": "eleves_classe", "classe": "6e A; DROP TABLE students"}, None, "texte libre"):
            with self.subTest(reponse=reponse), self._fournisseur(reponse):
                b = self._ask("Fais-moi un point sur l'ambiance générale")
                self.assertEqual(b["intent"], "gen:fallback")
                self.assertTrue(b["text"].startswith("Je n'ai pas suffisamment"))

    def test_11_fournisseur_en_panne_l_assistant_reste_la(self):
        with self._fournisseur(None):
            b = self._ask("Comment se porte la caisse ?")
        self.assertEqual(b["intent"], "gen:fallback")
        self.assertEqual(b["rich"]["type"], "suggestions")

    # --- Cercle 3 : une écriture n'atteint jamais le modèle ---------------------

    def test_12_une_demande_d_ecriture_est_refusee_avant_le_modele(self):
        with self._fournisseur({"question_type": "situation_eleve", "eleve": "Élève 1"}):
            b = self._ask("Supprime l'élève Amani Kabeya")
        self.assertTrue(b["refused"])
        self.assertEqual(self.envoyes, [])

    def test_13_le_module_n_ecrit_rien(self):
        with open(os.path.join(ICI, "..", "ia_generative.py"), encoding="utf-8") as f:
            source = f.read()
        for mot in ("INSERT", "UPDATE", "DELETE", "commit(", "save_settings"):
            self.assertNotIn(mot, source, mot)

    # --- Décisions 1 et 4 : qui y a droit ---------------------------------------

    def test_14_le_professeur_n_y_a_pas_droit(self):
        with self._fournisseur({"question_type": "nombre_eleves"}):
            b = self._ask("Quelle est la météo à Kinshasa ?", h=self.prof_h)
        self.assertEqual(b["intent"], "fallback")
        self.assertEqual(self.envoyes, [])

    def test_15_une_ecole_non_ouverte_n_y_a_pas_droit(self):
        os.environ["KLASSIO_IA_ECOLES"] = "une-autre-ecole"
        with self._fournisseur({"question_type": "nombre_eleves"}):
            b = self._ask("Comment se porte la caisse ?")
        self.assertEqual(b["intent"], "fallback")
        self.assertEqual(self.envoyes, [])
        os.environ["KLASSIO_IA_ECOLES"] = ""
        with self._fournisseur({"question_type": "nombre_eleves"}):
            self._ask("Comment se porte la caisse ?")
        self.assertEqual(self.envoyes, [])

    def test_16_la_direction_peut_couper_l_ia(self):
        r = self.c.put("/api/settings", json={"ai_generative": False}, headers=self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertFalse(self.c.get("/api/settings", headers=self.dir_h).get_json()["ai_generative"])
        try:
            with self._fournisseur({"question_type": "nombre_eleves"}):
                b = self._ask("Comment se porte la caisse ?")
            self.assertEqual(b["intent"], "fallback")
            self.assertEqual(self.envoyes, [])
        finally:
            self.c.put("/api/settings", json={"ai_generative": True}, headers=self.dir_h)

    def test_16bis_l_interrupteur_n_apparait_que_dans_une_ecole_ouverte(self):
        """Ailleurs, Paramètres décrirait une fonction absente (règle du site :
        rien d'autre que le logiciel)."""
        self.assertTrue(self.c.get("/api/settings", headers=self.dir_h).get_json()["ai_generative_ouverte"])
        os.environ["KLASSIO_IA_ECOLES"] = "une-autre-ecole"
        self.assertFalse(self.c.get("/api/settings", headers=self.dir_h).get_json()["ai_generative_ouverte"])
        os.environ["KLASSIO_IA_ECOLES"] = "*"
        os.environ.pop("ANTHROPIC_API_KEY")
        self.assertFalse(self.c.get("/api/settings", headers=self.dir_h).get_json()["ai_generative_ouverte"])
        self.assertNotIn("ai_generative_ouverte", self.c.get("/api/settings", headers=self.prof_h).get_json())

    # --- Décision 5 : le plafond --------------------------------------------------

    def test_17_le_plafond_mensuel_arrete_les_appels(self):
        os.environ["KLASSIO_IA_PLAFOND_MENSUEL"] = "2"
        with self._fournisseur(None):
            for _ in range(4):
                self._ask("Comment se porte la caisse ?")
        self.assertEqual(len(self.envoyes), 2)


AUCUNE = ia_generative.AUCUNE

if __name__ == "__main__":
    unittest.main()
