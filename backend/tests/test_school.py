"""KLASSIO backend — tests des flux "l'élève au centre".

Chaque test exerce un parcours RÉEL de bout en bout via l'API (invitation →
activation → action → notification → consultation), et vérifie qu'un rôle
ne voit jamais plus que son périmètre. Base SQLite dédiée (klassio_test.db).

Exécution : depuis backend/ :  python3 -m unittest tests.test_school -v
"""
import unittest
import sys
import os
import io
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402

TODAY = date.today().isoformat()


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class SchoolCoreTests(unittest.TestCase):
    """Un établissement complet est construit une fois pour toute la classe :
    Direction, 2 classes (6e A primaire, 7e B secondaire), 3 élèves,
    2 professeurs, 1 DD, 2 parents."""

    @classmethod
    def setUpClass(cls):
        cls.client = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        c = cls.client

        r = c.post("/api/auth/register-school", json={"email": "dir@core.test", "password": "Secret123!", "name": "Marie Directrice", "school_name": "Institut Core"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.dir_h = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.tenant_id = r.get_json()["tenant_id"]
        year = c.get("/api/academic-years", headers=cls.dir_h).get_json()[0]["id"]
        cls.year_id = year

        cls.class_a = c.post("/api/classes", json={"name": "6e A", "level": "6e", "academic_year_id": year}, headers=cls.dir_h).get_json()
        cls.class_b = c.post("/api/classes", json={"name": "7e B", "level": "7e", "academic_year_id": year}, headers=cls.dir_h).get_json()
        assert cls.class_a["cycle"] == "primaire" and cls.class_b["cycle"] == "secondaire"

        def student(first, last, class_id):
            return c.post("/api/students", json={"first_name": first, "last_name": last, "academic_year_id": year, "class_id": class_id}, headers=cls.dir_h).get_json()
        cls.kevin = student("Kevin", "Mbala", cls.class_a["id"])       # 6e A (primaire)
        cls.sarah = student("Sarah", "Ilunga", cls.class_a["id"])      # 6e A
        cls.jonas = student("Jonas", "Kabeya", cls.class_b["id"])      # 7e B (secondaire)

        item = c.post("/api/catalog-items", json={"name": "Frais scolaires", "amount": 300, "currency": "USD"}, headers=cls.dir_h).get_json()
        for s in (cls.kevin, cls.sarah, cls.jonas):
            c.post("/api/obligations", json={"student_id": s["id"], "catalog_item_id": item["id"], "academic_year_id": year}, headers=cls.dir_h)

        # Professeur titulaire de 6e A, rattaché aussi à 7e B (matière)
        cls.prof_a_h = cls._invite_and_accept(c, cls.dir_h, "professeur", "profa@core.test", "Paul Prof",
                                              class_ids=[cls.class_a["id"], cls.class_b["id"]], titulaire_class_id=cls.class_a["id"])
        # Professeur rattaché uniquement à 7e B (titulaire)
        cls.prof_b_h = cls._invite_and_accept(c, cls.dir_h, "professeur", "profb@core.test", "Brigitte Prof",
                                              class_ids=[cls.class_b["id"]], titulaire_class_id=cls.class_b["id"])
        # Directeur des disciplines
        cls.dd_h = cls._invite_and_accept(c, cls.dir_h, "discipline", "dd@core.test", "Didier Discipline")
        # Parents
        cls.parent_kevin_h = cls._invite_and_accept(c, cls.dir_h, "parent", "pkevin@core.test", "Jean Mbala", student_ids=[cls.kevin["id"]])
        cls.parent_jonas_h = cls._invite_and_accept(c, cls.dir_h, "parent", "pjonas@core.test", "Grace Kabeya", student_ids=[cls.jonas["id"]])

    @staticmethod
    def _invite_and_accept(c, dir_h, role, email, name, student_ids=None, class_ids=None, titulaire_class_id=None):
        payload = {"role": role, "student_ids": student_ids, "class_ids": class_ids, "titulaire_class_id": titulaire_class_id}
        inv = c.post("/api/invitations", json=payload, headers=dir_h)
        assert inv.status_code == 201, inv.get_data(as_text=True)
        acc = c.post("/api/invitations/accept", json={"token": inv.get_json()["token"], "name": name, "email": email, "password": "Secret123!",
                                                       "role": "directeur"})  # rôle envoyé par le client : IGNORÉ
        assert acc.status_code == 201, acc.get_data(as_text=True)
        assert acc.get_json()["role"] == role
        return {"Authorization": "Bearer " + acc.get_json()["token"]}

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _notifs(self, h):
        return self.client.get("/api/notifications", headers=h).get_json()

    # ------------------------------------------------------------------
    # Identifiant unique & dossier central
    # ------------------------------------------------------------------
    def test_01_student_code_is_generated_unique_and_visible_in_dossier(self):
        self.assertRegex(self.kevin["code"], r"^STU-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertNotEqual(self.kevin["code"], self.sarah["code"])
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.dir_h).get_json()
        self.assertEqual(d["student"]["code"], self.kevin["code"])
        self.assertEqual(d["student"]["class"]["name"], "6e A")
        self.assertEqual(d["student"]["titulaire"]["name"], "Paul Prof")
        self.assertIn("finance", d["sections"])
        self.assertIn("recus", d["sections"])
        self.assertEqual(d["finance"]["total_due"], 300)

    # ------------------------------------------------------------------
    # Professeur : périmètre = classes rattachées, titulaire explicite
    # ------------------------------------------------------------------
    def test_02_teacher_sees_only_assigned_classes_and_students(self):
        classes = self.client.get("/api/classes", headers=self.prof_b_h).get_json()
        self.assertEqual([c["name"] for c in classes], ["7e B"])
        self.assertTrue(classes[0]["is_titulaire"])
        students = self.client.get("/api/students", headers=self.prof_b_h).get_json()
        self.assertEqual([s["first_name"] for s in students], ["Jonas"])
        # Kevin (6e A) est hors périmètre de Brigitte
        r = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.prof_b_h)
        self.assertEqual(r.status_code, 404)
        # Paul voit les deux classes, titulaire seulement de 6e A
        classes = self.client.get("/api/classes", headers=self.prof_a_h).get_json()
        self.assertEqual({c["name"]: c["is_titulaire"] for c in classes}, {"6e A": True, "7e B": False})
        dash = self.client.get("/api/dashboard", headers=self.prof_a_h).get_json()
        self.assertEqual(dash["role"], "professeur")
        self.assertEqual(dash["student_count"], 3)
        self.assertNotIn("scope_note", dash)

    def test_03_teacher_finance_visibility_is_a_server_side_permission(self):
        # Par défaut : pas de solde pour le professeur, ni dans la liste ni dans le dossier
        s = self.client.get("/api/students", headers=self.prof_a_h).get_json()[0]
        self.assertNotIn("balance", s)
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.prof_a_h).get_json()
        self.assertIsNone(d["finance"]); self.assertFalse(d["finance_visible"]); self.assertNotIn("finance", d["sections"])
        r = self.client.get(f"/api/students/{self.kevin['id']}/financial-summary", headers=self.prof_a_h)
        self.assertEqual(r.status_code, 404)
        # Le professeur ne peut pas s'accorder ce droit lui-même
        r = self.client.put("/api/settings", json={"teacher_sees_finance": True}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 403)
        # La Direction l'active → visible
        r = self.client.put("/api/settings", json={"teacher_sees_finance": True}, headers=self.dir_h)
        self.assertEqual(r.status_code, 200)
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.prof_a_h).get_json()
        self.assertEqual(d["finance"]["total_due"], 300)
        self.client.put("/api/settings", json={"teacher_sees_finance": False}, headers=self.dir_h)

    # ------------------------------------------------------------------
    # Présences : une donnée centrale → parent, titulaire, DD, Direction
    # ------------------------------------------------------------------
    def test_04_attendance_recorded_by_assigned_teacher_reaches_all_authorized_spaces(self):
        # Brigitte (7e B uniquement) ne peut pas faire l'appel de 6e A
        r = self.client.post(f"/api/classes/{self.class_a['id']}/attendance",
                             json={"date": TODAY, "records": [{"student_id": self.kevin["id"], "status": "absent"}]}, headers=self.prof_b_h)
        self.assertEqual(r.status_code, 403)
        # Un parent ne peut jamais enregistrer une présence
        r = self.client.post(f"/api/classes/{self.class_a['id']}/attendance",
                             json={"date": TODAY, "records": [{"student_id": self.kevin["id"], "status": "present"}]}, headers=self.parent_kevin_h)
        self.assertEqual(r.status_code, 403)
        # Paul (rattaché) enregistre : Kevin absent, Sarah présente
        r = self.client.post(f"/api/classes/{self.class_a['id']}/attendance", json={"date": TODAY, "records": [
            {"student_id": self.kevin["id"], "status": "absent"}, {"student_id": self.sarah["id"], "status": "present"}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["saved"], 2)
        # Dossier de Kevin (Direction) : l'absence est là
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.dir_h).get_json()
        self.assertEqual(d["attendance"]["today"]["status"], "absent")
        self.assertEqual(d["attendance"]["summary"]["absent"], 1)
        # Parent de Kevin notifié (réglage par défaut : oui)
        titles = [n["title"] for n in self._notifs(self.parent_kevin_h)]
        self.assertTrue(any("absence" in t.lower() for t in titles), titles)
        # Parent de Jonas : rien (pas son enfant)
        self.assertFalse(any("Kevin" in n["title"] for n in self._notifs(self.parent_jonas_h)))
        # Espace parent : le dossier de Kevin montre l'absence du jour
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.parent_kevin_h).get_json()
        self.assertEqual(d["attendance"]["today"]["status"], "absent")
        # Vue Direction : l'appel de 6e A est fait, celui de 7e B non
        ov = self.client.get("/api/attendance/overview", headers=self.dir_h).get_json()
        by_name = {c["name"]: c for c in ov["classes"]}
        self.assertEqual(by_name["6e A"]["recorded"], 2); self.assertEqual(by_name["6e A"]["absent"], 1)
        self.assertEqual(by_name["7e B"]["recorded"], 0)
        # Modifier le statut le même jour = mise à jour, jamais un doublon
        self.client.post(f"/api/classes/{self.class_a['id']}/attendance", json={"date": TODAY, "records": [
            {"student_id": self.kevin["id"], "status": "excused", "note": "Certificat médical"}]}, headers=self.prof_a_h)
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.dir_h).get_json()
        self.assertEqual(d["attendance"]["summary"]["total"], 1)
        self.assertEqual(d["attendance"]["today"]["status"], "excused")
        # Impossible dans le futur ; élève d'une autre classe refusé
        r = self.client.post(f"/api/classes/{self.class_a['id']}/attendance", json={"date": "2999-01-01", "records": [{"student_id": self.kevin["id"], "status": "present"}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/classes/{self.class_a['id']}/attendance", json={"date": TODAY, "records": [{"student_id": self.jonas["id"], "status": "present"}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 400)

    def test_05_dd_scope_is_secondary_only_and_notified_of_secondary_absences(self):
        classes = self.client.get("/api/classes", headers=self.dd_h).get_json()
        self.assertEqual([c["name"] for c in classes], ["7e B"])
        r = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.dd_h)  # primaire : hors périmètre
        self.assertEqual(r.status_code, 404)
        d = self.client.get(f"/api/students/{self.jonas['id']}", headers=self.dd_h).get_json()
        self.assertIsNone(d["finance"]); self.assertNotIn("finance", d["sections"])  # le DD ne gère pas les finances
        # Le DD peut faire l'appel d'une classe secondaire ; il est notifié quand un prof le fait
        r = self.client.post(f"/api/classes/{self.class_b['id']}/attendance", json={"date": TODAY, "records": [{"student_id": self.jonas["id"], "status": "late"}]}, headers=self.prof_b_h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("retard" in n["title"].lower() and "Jonas" in n["title"] for n in self._notifs(self.dd_h)))
        # Le titulaire de 7e B est l'auteur → pas auto-notifié ; Paul (non titulaire de 7e B) non plus
        self.assertFalse(any("Jonas" in n["title"] for n in self._notifs(self.prof_b_h)))

    # ------------------------------------------------------------------
    # Discipline : règles (Direction), incidents (DD), notifications ciblées
    # ------------------------------------------------------------------
    def test_06_discipline_incident_flow_respects_roles_and_parent_communication_rules(self):
        # Règles : Direction seulement
        r = self.client.post("/api/discipline/rules", json={"label": "Retard répété", "category": "retard", "points": -2}, headers=self.dd_h)
        self.assertEqual(r.status_code, 403)
        rule = self.client.post("/api/discipline/rules", json={"label": "Incident comportemental", "category": "comportement", "points": -10}, headers=self.dir_h).get_json()
        self.assertIn("id", rule)
        self.assertEqual(len(self.client.get("/api/discipline/rules", headers=self.dd_h).get_json()), 1)
        # Un professeur ne crée jamais d'incident ; un parent non plus
        for h in (self.prof_b_h, self.parent_jonas_h):
            r = self.client.post("/api/incidents", json={"student_id": self.jonas["id"], "title": "Test"}, headers=h)
            self.assertEqual(r.status_code, 403)
        # Le DD ne peut pas enregistrer un incident sur un élève du primaire
        r = self.client.post("/api/incidents", json={"student_id": self.kevin["id"], "title": "Hors périmètre"}, headers=self.dd_h)
        self.assertEqual(r.status_code, 404)
        # Incident réel sur Jonas (7e B), non communiqué au parent
        r = self.client.post("/api/incidents", json={"student_id": self.jonas["id"], "rule_id": rule["id"], "title": "Bagarre dans la cour",
                                                     "description": "Altercation à la récréation", "severity": "high",
                                                     "action_taken": "Entretien avec la Direction", "internal_note": "Contexte familial difficile — confidentiel",
                                                     "notify_parent": False}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["points_total"], -10)
        self.assertEqual(r.get_json()["balance"]["remaining"], 90)   # capital 100 par défaut
        self.assertFalse(r.get_json()["threshold_reached"])          # premier seuil : 70 points restants
        # Titulaire de 7e B (Brigitte) notifié ; Direction notifiée ; Paul (non titulaire de 7e B) non
        self.assertTrue(any("incident" in n["title"].lower() and "Jonas" in n["title"] for n in self._notifs(self.prof_b_h)))
        self.assertTrue(any("incident" in n["title"].lower() for n in self._notifs(self.dir_h)))
        self.assertFalse(any("incident" in n["title"].lower() and "Jonas" in n["title"] for n in self._notifs(self.prof_a_h)))
        # Un second retrait fait franchir le seuil « Convocation des parents » (70) → alerte humaine DD + Direction + titulaire
        r = self.client.post("/api/incidents", json={"student_id": self.jonas["id"], "title": "Absence injustifiée répétée", "category": "absence", "points": -25, "severity": "medium", "notify_parent": False}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.get_json()["threshold_reached"]); self.assertEqual(r.get_json()["balance"]["remaining"], 65)
        self.assertEqual(r.get_json()["crossed"][0]["label"], "Convocation des parents")
        self.assertTrue(any("Seuil atteint" in n["title"] for n in self._notifs(self.dd_h)))
        self.assertTrue(any("Seuil atteint" in n["title"] for n in self._notifs(self.prof_b_h)))
        # Parent de Jonas : PAS notifié de l'incident (il a légitimement reçu le
        # retard du test 05 — c'est une présence, pas un incident), et
        # l'incident n'apparaît pas dans son dossier
        self.assertFalse(any(n["kind"] == "discipline" for n in self._notifs(self.parent_jonas_h)))
        d = self.client.get(f"/api/students/{self.jonas['id']}", headers=self.parent_jonas_h).get_json()
        self.assertEqual(d["discipline"]["incidents"], [])
        # Titulaire : voit l'incident, la mesure communicable, mais JAMAIS la note interne
        d = self.client.get(f"/api/students/{self.jonas['id']}", headers=self.prof_b_h).get_json()
        self.assertEqual(len(d["discipline"]["incidents"]), 2)
        bagarre = next(i for i in d["discipline"]["incidents"] if i["title"] == "Bagarre dans la cour")
        self.assertEqual(bagarre["action_taken"], "Entretien avec la Direction")
        self.assertNotIn("internal_note", bagarre)
        # DD et Direction : note interne visible ; capital et seuils exposés
        d = self.client.get(f"/api/students/{self.jonas['id']}", headers=self.dd_h).get_json()
        self.assertIn("confidentiel", next(i for i in d["discipline"]["incidents"] if i["title"] == "Bagarre dans la cour")["internal_note"])
        self.assertEqual(d["discipline"]["balance"]["remaining"], 65); self.assertEqual(len(d["discipline"]["thresholds"]), 3)
        # Direction autorise la communication aux parents + DD coche notify_parent → parent informé, sans note interne
        self.client.put("/api/settings", json={"parent_notify_incidents": True}, headers=self.dir_h)
        r = self.client.post("/api/incidents", json={"student_id": self.jonas["id"], "title": "Retard répété", "category": "retard", "points": -2,
                                                     "action_taken": "Avertissement", "internal_note": "secret", "notify_parent": True}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201)
        parent_notifs = self._notifs(self.parent_jonas_h)
        self.assertTrue(any(n["kind"] == "discipline" and "Jonas" in n["title"] for n in parent_notifs), parent_notifs)
        d = self.client.get(f"/api/students/{self.jonas['id']}", headers=self.parent_jonas_h).get_json()
        self.assertEqual(len(d["discipline"]["incidents"]), 1)
        self.assertEqual(d["discipline"]["incidents"][0]["title"], "Retard répété")
        self.assertNotIn("internal_note", d["discipline"]["incidents"][0])
        # Vue d'ensemble DD (sémantique capital : Jonas a 63 points restants < seuil 70)
        ov = self.client.get("/api/discipline/overview", headers=self.dd_h).get_json()
        self.assertEqual(ov["incidents_week"], 3)
        self.assertEqual(ov["students_below_threshold"][0]["first_name"], "Jonas")
        self.assertEqual(ov["students_below_threshold"][0]["step"], "Convocation des parents")
        # Liste des incidents : Brigitte (7e B) → 3 ; parent → 1 (seul l'incident communiqué)
        self.assertEqual(len(self.client.get("/api/incidents", headers=self.prof_b_h).get_json()), 3)
        self.assertEqual(len(self.client.get("/api/incidents", headers=self.parent_jonas_h).get_json()), 1)
        self.assertEqual(len(self.client.get("/api/incidents", headers=self.parent_kevin_h).get_json()), 0)

    # ------------------------------------------------------------------
    # Résultats & bulletin calculé
    # ------------------------------------------------------------------
    def test_07_grades_recorded_by_assigned_teacher_and_bulletin_is_computed(self):
        r = self.client.post(f"/api/classes/{self.class_a['id']}/grades", json={"subject": "Mathématiques", "period": "Période 1", "max_score": 20,
                             "entries": [{"student_id": self.kevin["id"], "score": 14}, {"student_id": self.sarah["id"], "score": 17}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        r = self.client.post(f"/api/classes/{self.class_a['id']}/grades", json={"subject": "Français", "period": "Période 1", "max_score": 10,
                             "entries": [{"student_id": self.kevin["id"], "score": 8}, {"student_id": self.sarah["id"], "score": 5}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 200)
        # Brigitte n'est pas rattachée à 6e A
        r = self.client.post(f"/api/classes/{self.class_a['id']}/grades", json={"subject": "X", "period": "P1", "entries": [{"student_id": self.kevin["id"], "score": 1}]}, headers=self.prof_b_h)
        self.assertEqual(r.status_code, 403)
        # Score hors barème refusé
        r = self.client.post(f"/api/classes/{self.class_a['id']}/grades", json={"subject": "X", "period": "P1", "max_score": 20, "entries": [{"student_id": self.kevin["id"], "score": 25}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 400)
        # Bulletin de Kevin : maths 14/20, français 8/10 = 16/20 → moyenne 15 ; Sarah : 17 et 10 → 13.5 → Kevin 1er
        b = self.client.get(f"/api/students/{self.kevin['id']}/bulletin", headers=self.parent_kevin_h).get_json()
        self.assertEqual(b["period"], "Période 1")
        self.assertEqual({s["subject"]: s["average_20"] for s in b["subjects"]}, {"Français": 16.0, "Mathématiques": 14.0})
        self.assertEqual(b["general_average_20"], 15.0)
        self.assertEqual(b["rank"], 1); self.assertEqual(b["class_size"], 2)
        # Parent notifié d'une nouvelle note
        self.assertTrue(any("note" in n["title"].lower() for n in self._notifs(self.parent_kevin_h)))
        # Le parent de Jonas ne peut pas lire le bulletin de Kevin
        self.assertEqual(self.client.get(f"/api/students/{self.kevin['id']}/bulletin", headers=self.parent_jonas_h).status_code, 404)

    # ------------------------------------------------------------------
    # Horaires & examens rattachés à la classe → visibles par le parent
    # ------------------------------------------------------------------
    def test_08_schedule_and_exams_flow_from_class_to_parent(self):
        r = self.client.post(f"/api/classes/{self.class_a['id']}/schedule", json={"weekday": 1, "start_time": "08:00", "end_time": "09:00", "subject": "Mathématiques", "room": "Salle 4"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        r = self.client.post(f"/api/classes/{self.class_a['id']}/schedule", json={"weekday": 1, "start_time": "10:00", "end_time": "09:00", "subject": "Erreur"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/classes/{self.class_a['id']}/exams", json={"subject": "Mathématiques", "date": "2999-10-12", "start_time": "08:00", "room": "Salle 4"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 201)
        # Un professeur ne modifie pas l'horaire
        self.assertEqual(self.client.post(f"/api/classes/{self.class_a['id']}/schedule", json={"weekday": 2, "start_time": "08:00", "end_time": "09:00", "subject": "X"}, headers=self.prof_a_h).status_code, 403)
        d = self.client.get(f"/api/students/{self.kevin['id']}", headers=self.parent_kevin_h).get_json()
        self.assertEqual(d["schedule"][0]["subject"], "Mathématiques"); self.assertEqual(d["schedule"][0]["weekday"], 1)
        self.assertEqual(d["exams"][0]["date"], "2999-10-12")
        dash = self.client.get("/api/dashboard", headers=self.parent_kevin_h).get_json()
        self.assertEqual(dash["children"][0]["next_exam"]["subject"], "Mathématiques")

    # ------------------------------------------------------------------
    # Boutique → Financial Core → paiement → reçu
    # ------------------------------------------------------------------
    def test_09_store_order_uses_financial_core_and_payment_produces_receipt(self):
        prod = self.client.post("/api/store/products", json={"name": "Cahier 100 pages", "category": "fournitures", "price": 2.5, "stock": 10}, headers=self.dir_h).get_json()
        self.assertIn("id", prod)
        self.assertEqual(self.client.post("/api/store/products", json={"name": "X", "price": 1, "stock": 1}, headers=self.parent_kevin_h).status_code, 403)
        # Le parent de Jonas ne peut pas commander pour Kevin
        r = self.client.post("/api/store/orders", json={"student_id": self.kevin["id"], "items": [{"product_id": prod["id"], "quantity": 1}]}, headers=self.parent_jonas_h)
        self.assertEqual(r.status_code, 404)
        # Stock insuffisant refusé
        r = self.client.post("/api/store/orders", json={"student_id": self.kevin["id"], "items": [{"product_id": prod["id"], "quantity": 11}]}, headers=self.parent_kevin_h)
        self.assertEqual(r.status_code, 409)
        # Commande réelle : 3 cahiers = 7.50
        r = self.client.post("/api/store/orders", json={"student_id": self.kevin["id"], "items": [{"product_id": prod["id"], "quantity": 3}]}, headers=self.parent_kevin_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        order = r.get_json()
        self.assertEqual(order["total"], 7.5); self.assertEqual(order["number"], "ORD-0001")
        # → l'obligation existe dans le dossier financier de Kevin (même Financial Core)
        fin = self.client.get(f"/api/students/{self.kevin['id']}/financial-summary", headers=self.dir_h).get_json()
        line = next(l for l in fin["obligations"] if l["obligation_id"] == order["obligation_id"])
        self.assertIn("ORD-0001", line["label"]); self.assertEqual(line["amount"], 7.5)
        self.assertEqual(fin["total_due"], 307.5)
        # Stock décrémenté ; Direction notifiée
        self.assertEqual(self.client.get("/api/store/products", headers=self.parent_kevin_h).get_json()[0]["stock"], 7)
        self.assertTrue(any("commande" in n["title"].lower() for n in self._notifs(self.dir_h)))
        # Le parent initie un paiement Mobile Money → CREATED, jamais auto-confirmé
        r = self.client.post("/api/payments", json={"obligation_id": order["obligation_id"], "amount": 7.5, "method": "mobile_money", "idempotency_key": "ord1-pay"}, headers=self.parent_kevin_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["status"], "CREATED")
        pay_id = r.get_json()["id"]
        # ... en cash c'est refusé (pas de preuve) ; sur l'obligation d'un autre enfant : refusé
        self.assertEqual(self.client.post("/api/payments", json={"obligation_id": order["obligation_id"], "amount": 7.5, "method": "cash", "idempotency_key": "ord1-cash"}, headers=self.parent_kevin_h).status_code, 400)
        jonas_ob = self.client.get(f"/api/students/{self.jonas['id']}/financial-summary", headers=self.dir_h).get_json()["obligations"][0]["obligation_id"]
        self.assertEqual(self.client.post("/api/payments", json={"obligation_id": jonas_ob, "amount": 1, "method": "mobile_money", "idempotency_key": "x"}, headers=self.parent_kevin_h).status_code, 404)
        # La commande reste 'pending' tant que rien n'est confirmé
        self.assertEqual(self.client.get("/api/store/orders", headers=self.parent_kevin_h).get_json()[0]["status"], "pending")
        # La Direction confirme → reçu numéroté, commande 'paid', parent notifié avec le numéro de reçu
        r = self.client.post(f"/api/payments/{pay_id}/confirm", json={"provider_reference": "MM-123"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.get_json()["receipt_number"], r"^REC-\d{4}-00001$")
        receipt_number = r.get_json()["receipt_number"]
        self.assertEqual(self.client.get("/api/store/orders", headers=self.parent_kevin_h).get_json()[0]["status"], "paid")
        self.assertTrue(any(receipt_number in n["body"] for n in self._notifs(self.parent_kevin_h)))
        # Le reçu : visible par le parent concerné et la Direction, pas par l'autre parent
        receipts = self.client.get("/api/receipts", headers=self.parent_kevin_h).get_json()
        self.assertEqual(len(receipts), 1); self.assertEqual(receipts[0]["number"], receipt_number)
        self.assertEqual(self.client.get("/api/receipts", headers=self.parent_jonas_h).get_json(), [])
        full = self.client.get(f"/api/receipts/{receipts[0]['id']}", headers=self.parent_kevin_h).get_json()
        self.assertEqual(full["student"]["first_name"], "Kevin"); self.assertEqual(full["payment"]["method"], "mobile_money")
        self.assertEqual(self.client.get(f"/api/receipts/{receipts[0]['id']}", headers=self.parent_jonas_h).status_code, 404)
        self.assertEqual(self.client.get("/api/receipts", headers=self.dd_h).status_code, 403)
        # Un second paiement confirmé → REC-...-00002 ; confirmer deux fois ne crée pas deux reçus
        self.assertEqual(self.client.post(f"/api/payments/{pay_id}/confirm", json={}, headers=self.dir_h).get_json()["receipt_number"], receipt_number)
        # Annuler une commande payée est refusé ; livrer est possible
        self.assertEqual(self.client.post(f"/api/store/orders/{order['id']}/status", json={"status": "cancelled"}, headers=self.dir_h).status_code, 409)
        self.assertEqual(self.client.post(f"/api/store/orders/{order['id']}/status", json={"status": "delivered"}, headers=self.dir_h).status_code, 200)
        self.assertTrue(any("livrée" in n["title"] for n in self._notifs(self.parent_kevin_h)))
        # Une commande annulée avant paiement libère le stock et retire l'obligation
        r = self.client.post("/api/store/orders", json={"student_id": self.kevin["id"], "items": [{"product_id": prod["id"], "quantity": 2}]}, headers=self.parent_kevin_h).get_json()
        self.assertEqual(self.client.get("/api/store/products", headers=self.parent_kevin_h).get_json()[0]["stock"], 5)
        # une intention de paiement non confirmée ne bloque pas l'annulation
        self.client.post("/api/payments", json={"obligation_id": r["obligation_id"], "amount": 5, "method": "mobile_money", "idempotency_key": "ord2-pay"}, headers=self.parent_kevin_h)
        cancel = self.client.post(f"/api/store/orders/{r['id']}/status", json={"status": "cancelled"}, headers=self.dir_h)
        self.assertEqual(cancel.status_code, 200, cancel.get_data(as_text=True))
        self.assertEqual(self.client.get("/api/store/products", headers=self.parent_kevin_h).get_json()[0]["stock"], 7)
        self.assertEqual(self.client.get(f"/api/students/{self.kevin['id']}/financial-summary", headers=self.dir_h).get_json()["total_due"], 307.5)

    # ------------------------------------------------------------------
    # Sécurité transversale
    # ------------------------------------------------------------------
    def test_10_cross_role_and_cross_tenant_attempts_are_refused_server_side(self):
        # Parent : pas d'équipe, pas de réglages, pas de liste d'appel, pas d'aperçu discipline
        for path in ("/api/team", "/api/attendance/overview", "/api/discipline/overview", "/api/discipline/rules"):
            self.assertEqual(self.client.get(path, headers=self.parent_kevin_h).status_code, 403, path)
        # Professeur : ne gère ni l'équipe ni la boutique ni les réglages
        self.assertEqual(self.client.post(f"/api/classes/{self.class_a['id']}/teachers", json={"user_id": "x"}, headers=self.prof_a_h).status_code, 403)
        self.assertEqual(self.client.put(f"/api/students/{self.kevin['id']}", json={"first_name": "Hack"}, headers=self.prof_a_h).status_code, 403)
        # tenant_id envoyé dans le JSON : ignoré — un autre établissement ne voit rien
        other = self.client.post("/api/auth/register-school", json={"email": "dir@other.test", "password": "Secret123!", "name": "Autre", "school_name": "Autre École"}).get_json()
        oh = {"Authorization": "Bearer " + other["token"]}
        self.assertEqual(self.client.get(f"/api/students/{self.kevin['id']}", headers=oh).status_code, 404)
        self.assertEqual(self.client.get(f"/api/classes/{self.class_a['id']}/students", headers=oh).status_code, 404)
        self.assertEqual(self.client.post("/api/incidents", json={"student_id": self.jonas["id"], "title": "x", "tenant_id": self.tenant_id}, headers=oh).status_code, 404)
        self.assertEqual(self.client.get("/api/incidents", headers=oh).get_json(), [])
        self.assertEqual(self.client.get("/api/receipts", headers=oh).get_json(), [])
        # Le rôle envoyé à l'acceptation d'invitation est ignoré (vérifié dans _invite_and_accept) ; invitation 'directeur' impossible
        self.assertEqual(self.client.post("/api/invitations", json={"role": "directeur"}, headers=self.dir_h).status_code, 400)
        # Un professeur ne peut pas inviter
        self.assertEqual(self.client.post("/api/invitations", json={"role": "parent", "student_ids": [self.kevin["id"]]}, headers=self.prof_a_h).status_code, 403)

    # ------------------------------------------------------------------
    # IA : nouveaux outils de lecture, mêmes périmètres, toujours read-only
    # ------------------------------------------------------------------
    def test_11_ai_reads_attendance_discipline_receipts_within_scope_and_never_acts(self):
        def ask(h, q):
            return self.client.post("/api/ai/ask", json={"message": q}, headers=h).get_json()
        r = ask(self.dir_h, "Combien d'élèves de la 6e A sont absents aujourd'hui ?")
        self.assertEqual(r["intent"], "attendance_class"); self.assertIn("6e A", r["text"])
        r = ask(self.prof_b_h, "Combien d'élèves de la 6e A sont absents aujourd'hui ?")  # hors périmètre
        self.assertIn("Aucune classe visible", r["text"])
        r = ask(self.parent_kevin_h, "Montre-moi le reçu de Kevin")
        self.assertEqual(r["intent"], "receipts_student"); self.assertIn("REC-", r["rich"]["rows"][0][0])
        r = ask(self.parent_jonas_h, "Montre-moi le reçu de Kevin")  # pas son enfant
        self.assertNotEqual(r["intent"], "receipts_student")
        r = ask(self.dd_h, "Analyse la situation de Jonas")
        self.assertEqual(r["intent"], "student_overview"); self.assertIn("incident", r["text"].lower()); self.assertNotIn("Finances", r["text"])
        r = ask(self.dir_h, "Analyse la situation de Jonas")
        self.assertIn("Finances", r["text"])
        r = ask(self.prof_a_h, "Quelle est la situation financière de ma classe ?")
        self.assertEqual(r["intent"], "denied_financial_professeur")
        # Jamais une action
        for q in ("Sanctionne Jonas", "Marque Kevin absent", "Mets une note de 15 à Kevin", "Annule la commande ORD-0001"):
            r = ask(self.dd_h, q)
            self.assertTrue(r["refused"], q)

    # ------------------------------------------------------------------
    # Import : aucune donnée fabriquée
    # ------------------------------------------------------------------
    def test_12_import_never_fabricates_fees_guardians_or_classes(self):
        reg = self.client.post("/api/auth/register-school", json={"email": "dir@import.test", "password": "Secret123!", "name": "D", "school_name": "École Import"}).get_json()
        h = {"Authorization": "Bearer " + reg["token"]}
        csv = "Nom,Prénom\nMbala,Kevin\nIlunga,Sarah\n"  # ni classe, ni frais, ni parent
        r = self.client.post("/api/onboarding/analyze-import", data={"file": (io.BytesIO(csv.encode()), "eleves.csv")}, headers=h, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        a = r.get_json()
        self.assertEqual(a["students_count"], 2); self.assertFalse(a["fees_detected"]); self.assertEqual(a["guardians_count"], 0)
        self.assertEqual(a["classes_detected"], ["Non affecté"])
        r = self.client.post("/api/onboarding/confirm-import", json={"import_session_id": a["import_session_id"]}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["obligations_count"], 0); self.assertEqual(r.get_json()["guardians_count"], 0)
        students = self.client.get("/api/students", headers=h).get_json()
        self.assertEqual(len(students), 2)
        self.assertTrue(all(s["code"].startswith("STU-") for s in students))
        self.assertEqual(students[0]["total_due"], 0)
        d = self.client.get(f"/api/students/{students[0]['id']}", headers=h).get_json()
        self.assertEqual(d["guardians"], [])


if __name__ == "__main__":
    unittest.main()
