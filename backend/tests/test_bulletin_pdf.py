"""KLASSIO — Tests des bulletins scolaires imprimables PDF.

Vérifie :
  1. Génération conforme du PDF (format A4, en-tête EPST, matières, moyennes, rang, conduite).
  2. Multi-pages pour la classe entière (1 page par élève).
  3. Respect de la proclamation : le parent ne voit que les périodes proclamées.
  4. Isolation multi-tenant et périmètres de rôles : le parent ne peut pas exporter la classe,
     une école concurrente ne peut pas télécharger les bulletins d'une autre école.
"""
import io
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module
import security
from pypdf import PdfReader


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class BulletinPDFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

        # 1. Établissement A
        r = cls.c.post("/api/auth/register-school", json={
            "email": "dir.pdf@ecole-alpha.test", "password": "Secret123!",
            "name": "Directrice Alpha", "school_name": "Complexe Scolaire Alpha"
        })
        assert r.status_code == 201
        cls.a_dir = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.a_tenant = r.get_json()["tenant_id"]

        c_tmp = db.get_connection()
        try:
            m = c_tmp.execute("SELECT user_id FROM memberships WHERE tenant_id=?", (cls.a_tenant,)).fetchone()
            cls.a_user_id = m["user_id"]
        finally:
            c_tmp.close()

        an = cls.c.get("/api/academic-years", headers=cls.a_dir).get_json()[0]["id"]
        cls.an_id = an

        # Classe avec 2 élèves
        klass = cls.c.post("/api/classes", json={"name": "6e Primaire A", "level": "6e", "academic_year_id": an},
                           headers=cls.a_dir).get_json()
        cls.classe = klass

        e1 = cls.c.post("/api/students", json={"first_name": "Moïse", "last_name": "Katumbi",
                                               "academic_year_id": an, "class_id": klass["id"]},
                        headers=cls.a_dir).get_json()
        e2 = cls.c.post("/api/students", json={"first_name": "Grâce", "last_name": "Kabasele",
                                               "academic_year_id": an, "class_id": klass["id"]},
                        headers=cls.a_dir).get_json()
        cls.eleve1 = e1
        cls.eleve2 = e2

        # Professeur titulaire
        inv_prof = cls.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": [klass["id"]], "titulaire_class_id": klass["id"]
        }, headers=cls.a_dir).get_json()
        acc_prof = cls.c.post("/api/invitations/accept", json={
            "token": inv_prof["token"], "name": "Professeur Titulaire",
            "email": "titulaire@ecole-alpha.test", "password": "Secret123!"
        }).get_json()
        cls.a_prof = {"Authorization": "Bearer " + acc_prof["token"]}

        # Parent de Moïse
        inv_par = cls.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [e1["id"]]
        }, headers=cls.a_dir).get_json()
        acc_par = cls.c.post("/api/invitations/accept", json={
            "token": inv_par["token"], "name": "Parent Moise",
            "email": "parent.moise@ecole-alpha.test", "password": "Secret123!"
        }).get_json()
        cls.a_parent = {"Authorization": "Bearer " + acc_par["token"]}

        # Enregistrement de notes
        c_db = db.get_connection()
        try:
            # Notes pour Moïse (Maths 16/20, Français 14/20)
            c_db.execute(
                """INSERT INTO grades (id, tenant_id, student_id, class_id, subject, period, score, max_score, is_current, recorded_by, created_at)
                   VALUES ('g1', ?, ?, ?, 'Mathématiques', 'Période 1', 16, 20, 1, ?, '2026-01-01')""",
                (cls.a_tenant, e1["id"], klass["id"], cls.a_user_id)
            )
            c_db.execute(
                """INSERT INTO grades (id, tenant_id, student_id, class_id, subject, period, score, max_score, is_current, recorded_by, created_at)
                   VALUES ('g2', ?, ?, ?, 'Français', 'Période 1', 14, 20, 1, ?, '2026-01-01')""",
                (cls.a_tenant, e1["id"], klass["id"], cls.a_user_id)
            )
            # Notes pour Grâce (Maths 18/20, Français 17/20)
            c_db.execute(
                """INSERT INTO grades (id, tenant_id, student_id, class_id, subject, period, score, max_score, is_current, recorded_by, created_at)
                   VALUES ('g3', ?, ?, ?, 'Mathématiques', 'Période 1', 18, 20, 1, ?, '2026-01-01')""",
                (cls.a_tenant, e2["id"], klass["id"], cls.a_user_id)
            )
            c_db.execute(
                """INSERT INTO grades (id, tenant_id, student_id, class_id, subject, period, score, max_score, is_current, recorded_by, created_at)
                   VALUES ('g4', ?, ?, ?, 'Français', 'Période 1', 17, 20, 1, ?, '2026-01-01')""",
                (cls.a_tenant, e2["id"], klass["id"], cls.a_user_id)
            )
            # Décision officielle pour Moïse
            c_db.execute(
                """INSERT INTO bulletin_decisions (id, tenant_id, student_id, academic_year_id, decision, mention, note, set_by, created_at)
                   VALUES ('bd1', ?, ?, ?, 'admis', 'Satisfaction', 'Très bonne progression', ?, '2026-06-30')""",
                (cls.a_tenant, e1["id"], an, cls.a_user_id)
            )
            c_db.commit()
        finally:
            c_db.close()

        # 2. Établissement B (Attaquant / concurrent)
        rb = cls.c.post("/api/auth/register-school", json={
            "email": "dir.pdf@ecole-beta.test", "password": "Secret123!",
            "name": "Directeur Beta", "school_name": "Institut Beta"
        })
        assert rb.status_code == 201
        cls.b_dir = {"Authorization": "Bearer " + rb.get_json()["token"]}
        cls.b_tenant = rb.get_json()["tenant_id"]

    def test_01_student_bulletin_pdf_success(self):
        """Le bulletin PDF individuel est produit en A4, valide, avec toutes les données."""
        r = self.c.get(f"/api/students/{self.eleve1['id']}/bulletin/pdf?period=Période 1", headers=self.a_dir)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF-1.4"))

        # Vérification structurelle avec pypdf
        reader = PdfReader(io.BytesIO(r.data))
        self.assertEqual(len(reader.pages), 1, "Le bulletin individuel doit faire exactement 1 page A4")
        text = reader.pages[0].extract_text()
        self.assertIn("RÉPUBLIQUE DÉMOCRATIQUE DU CONGO", text)
        self.assertIn("COMPLEXE SCOLAIRE ALPHA", text)
        self.assertIn("KATUMBI", text)
        self.assertIn("Mathématiques", text)
        self.assertIn("15.00 / 20", text)  # Moyenne (16+14)/2 = 15.00
        self.assertIn("DÉCISION DU CONSEIL : ADMIS", text)

    def test_02_class_bulletins_pdf_multipage_success(self):
        """L'export de toute la classe produit un PDF multipages (1 page par élève)."""
        r = self.c.get(f"/api/classes/{self.classe['id']}/bulletins/pdf?period=Période 1", headers=self.a_dir)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF-1.4"))

        reader = PdfReader(io.BytesIO(r.data))
        self.assertEqual(len(reader.pages), 2, "La classe compte 2 élèves, donc 2 pages A4")
        text_p1 = reader.pages[0].extract_text()
        text_p2 = reader.pages[1].extract_text()
        # Les 2 élèves doivent être présents
        eleves_trouves = [t for t in (text_p1, text_p2) if "KATUMBI" in t or "KABASELE" in t]
        self.assertEqual(len(eleves_trouves), 2)

    def test_03_parent_cannot_export_entire_class(self):
        """Un parent n'a pas le droit d'exporter les bulletins de toute la classe."""
        r = self.c.get(f"/api/classes/{self.classe['id']}/bulletins/pdf", headers=self.a_parent)
        self.assertEqual(r.status_code, 403)

    def test_04_parent_can_download_child_bulletin(self):
        """Un parent peut télécharger le bulletin officiel de son propre enfant."""
        r = self.c.get(f"/api/students/{self.eleve1['id']}/bulletin/pdf", headers=self.a_parent)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")

    def test_04b_le_parent_ne_recoit_pas_une_periode_non_proclamee(self):
        """LE TEST QUE test_04 CROYAIT FAIRE.

        `test_04` ne vérifiait que le code HTTP : le PDF arrivait, son CONTENU
        n'était jamais lu. Neutraliser `only_published` dans la route ne le
        faisait pas tomber — il ne testait donc rien de la proclamation.

        Il tombait aussi dans le seul cas où la règle est inerte : sans
        calendrier déclaré, `visible_results_for_student` laisse tout passer,
        volontairement (une école sans périodes n'a rien à proclamer). Le test
        doit donc DÉCLARER une période pour que la règle existe.

        Garantie vérifiée ici : tant que la période n'est pas proclamée, le
        bulletin du parent ne porte aucune note — alors que celui du personnel
        les porte toutes. Import ≠ publication, jusque dans le PDF.
        """
        # Une école qui a un calendrier : c'est la condition d'existence de la
        # règle de proclamation.
        r = self.c.post("/api/periods", json={"label": "Trimestre 1", "sort": 0},
                        headers=self.a_dir)
        self.assertIn(r.status_code, (200, 201), r.get_data(as_text=True))
        periodes = self.c.get("/api/periods", headers=self.a_dir).get_json()["periods"]
        p1 = [p for p in periodes if p["label"] == "Trimestre 1"][0]

        # Des notes saisies par la voie normale : elles portent leur period_id.
        r = self.c.post(f"/api/classes/{self.classe['id']}/grades", json={
            "period": "Trimestre 1", "subject": "Histoire",
            "entries": [{"student_id": self.eleve1["id"], "score": 17, "max_score": 20}],
        }, headers=self.a_dir)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        def texte(entetes):
            rep = self.c.get(
                f"/api/students/{self.eleve1['id']}/bulletin/pdf?period=Trimestre 1",
                headers=entetes)
            # Le corps d'une réponse PDF n'est pas de l'UTF-8 : on ne le décode
            # que si la requête a échoué, pour lire le message d'erreur.
            detail = "" if rep.status_code == 200 else rep.get_data(as_text=True)
            self.assertEqual(rep.status_code, 200, detail)
            return PdfReader(io.BytesIO(rep.data)).pages[0].extract_text()

        # Le personnel voit la note dès la saisie.
        self.assertIn("Histoire", texte(self.a_dir),
                      "le bulletin du personnel devrait porter la note saisie")

        # Le parent, lui, ne la voit pas : rien n'a été proclamé.
        avant = texte(self.a_parent)
        self.assertNotIn("Histoire", avant,
                         "une période NON PROCLAMÉE est arrivée dans le PDF du parent")
        self.assertNotIn("17", avant,
                         "la note d'une période non proclamée est arrivée chez le parent")

        # Après proclamation, et seulement après, elle lui parvient.
        pub = self.c.post(f"/api/periods/{p1['id']}/publish", json={}, headers=self.a_dir)
        self.assertEqual(pub.status_code, 200, pub.get_data(as_text=True))
        self.assertIn("Histoire", texte(self.a_parent),
                      "après proclamation, le parent devrait recevoir la note")

    def test_05_cross_tenant_isolation_bulletin_pdf(self):
        """Une autre école (Beta) ne peut pas accéder aux bulletins PDF de l'école Alpha."""
        # Tentative d'accès à l'élève de Alpha
        r1 = self.c.get(f"/api/students/{self.eleve1['id']}/bulletin/pdf", headers=self.b_dir)
        self.assertEqual(r1.status_code, 404)

        # Tentative d'accès à la classe de Alpha
        r2 = self.c.get(f"/api/classes/{self.classe['id']}/bulletins/pdf", headers=self.b_dir)
        self.assertEqual(r2.status_code, 404)


if __name__ == "__main__":
    unittest.main()
