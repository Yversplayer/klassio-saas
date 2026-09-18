"""KLASSIO — lots 2 à 5 + abonnement : calendrier, ressources, documents,
cahier de communication, justifications, droit de réponse, appel finalisé et
pointage portail, signalements, convocations, capital de points, règlement,
registres, périodes/proclamation, appréciations, conduite, décisions, boutique
(retrait), abonnement (essai → facture → paiement → suspension → reprise)."""
import unittest, sys, os, io, json, time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db  # noqa: E402
db.DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "klassio_test.db"))
import app as flask_app_module  # noqa: E402
import security  # noqa: E402

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
PDF_DATA = "data:application/pdf;base64,JVBERi0xLjQKJcOkw7zDtsOfCg=="


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class LotsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        c = cls.c
        r = c.post("/api/auth/register-school", json={"email": "dir@lots.test", "password": "Secret123!", "name": "Marie Dir", "school_name": "École des Lots"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.dir_h = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.tenant_id = r.get_json()["tenant_id"]
        cls.year = c.get("/api/academic-years", headers=cls.dir_h).get_json()[0]["id"]
        mk = lambda name, level, cycle=None: c.post("/api/classes", json={"name": name, "level": level, "academic_year_id": cls.year, **({"cycle": cycle} if cycle else {})}, headers=cls.dir_h).get_json()
        cls.cA = mk("5e Primaire A", "5e")            # primaire
        cls.cB = mk("2e Secondaire Scientifique", "2e", "secondaire")
        cls.cM = mk("Maternelle 2", "Maternelle", "maternelle")
        st = lambda f, l, cid: c.post("/api/students", json={"first_name": f, "last_name": l, "academic_year_id": cls.year, "class_id": cid}, headers=cls.dir_h).get_json()
        cls.kevin = st("Kevin", "Mbala", cls.cA["id"]); cls.sarah = st("Sarah", "Ilunga", cls.cA["id"])
        cls.jonas = st("Jonas", "Kabeya", cls.cB["id"]); cls.lea = st("Léa", "Tshala", cls.cM["id"])
        item = c.post("/api/catalog-items", json={"name": "Frais scolaires", "amount": 300, "currency": "USD"}, headers=cls.dir_h).get_json()
        for s in (cls.kevin, cls.sarah, cls.jonas):
            c.post("/api/obligations", json={"student_id": s["id"], "catalog_item_id": item["id"], "academic_year_id": cls.year, "due_date": TODAY}, headers=cls.dir_h)
        cls.prof_a_h = cls._join(c, cls.dir_h, "professeur", "profa@lots.test", "Paul Prof", class_ids=[cls.cA["id"]], titulaire_class_id=cls.cA["id"])
        cls.prof_b_h = cls._join(c, cls.dir_h, "professeur", "profb@lots.test", "Brigitte Prof", class_ids=[cls.cB["id"]], titulaire_class_id=cls.cB["id"])
        cls.prof_m_h = cls._join(c, cls.dir_h, "professeur", "profm@lots.test", "Mado Matern", class_ids=[cls.cM["id"]], titulaire_class_id=cls.cM["id"])
        cls.dd_h = cls._join(c, cls.dir_h, "discipline", "dd@lots.test", "Didier DD")
        cls.dd2_h = cls._join(c, cls.dir_h, "discipline", "dd2@lots.test", "Alice Adjointe", title="Adjoint", scope_cycles=["primaire"])
        cls.pk_h = cls._join(c, cls.dir_h, "parent", "pk@lots.test", "Jean Mbala", student_ids=[cls.kevin["id"]])
        cls.pj_h = cls._join(c, cls.dir_h, "parent", "pj@lots.test", "Grace Kabeya", student_ids=[cls.jonas["id"]])
        cls.pl_h = cls._join(c, cls.dir_h, "parent", "pl@lots.test", "Nadine Tshala", student_ids=[cls.lea["id"]])

    @staticmethod
    def _join(c, dir_h, role, email, name, **kw):
        inv = c.post("/api/invitations", json={"role": role, **kw}, headers=dir_h)
        assert inv.status_code == 201, inv.get_data(as_text=True)
        acc = c.post("/api/invitations/accept", json={"token": inv.get_json()["token"], "name": name, "email": email, "password": "Secret123!"})
        assert acc.status_code == 201, acc.get_data(as_text=True)
        return {"Authorization": "Bearer " + acc.get_json()["token"]}

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _n(self, h):
        return self.c.get("/api/notifications", headers=h).get_json()

    def _titles(self, h):
        return [n["title"] for n in self._n(h)]

    # ---------------- DD adjoint & périmètre par cycle ----------------
    def test_01_dd_scope_by_cycle_and_title(self):
        me = self.c.get("/api/me", headers=self.dd2_h).get_json()
        self.assertEqual(me["title"], "Adjoint"); self.assertEqual(me["scope_cycles"], ["primaire"])
        self.assertEqual([x["name"] for x in self.c.get("/api/classes", headers=self.dd2_h).get_json()], ["5e Primaire A"])
        self.assertEqual([x["name"] for x in self.c.get("/api/classes", headers=self.dd_h).get_json()], ["2e Secondaire Scientifique"])
        self.assertEqual(self.c.get(f"/api/students/{self.jonas['id']}", headers=self.dd2_h).status_code, 404)
        dd2_id = me["user_id"]
        # La Direction élargit le périmètre de l'adjoint
        self.assertEqual(self.c.put(f"/api/team/{dd2_id}", json={"scope_cycles": ["primaire", "maternelle"]}, headers=self.dir_h).status_code, 200)
        self.assertEqual(len(self.c.get("/api/classes", headers=self.dd2_h).get_json()), 2)
        self.assertEqual(self.c.put(f"/api/team/{dd2_id}", json={"scope_cycles": ["primaire"]}, headers=self.dd_h).status_code, 403)

    # ---------------- Appel finalisé + pointage portail ----------------
    def test_02_roll_finalize_notifies_presence_once_and_gate_late_wins(self):
        # DD pointe Kevin en retard au portail
        r = self.c.post("/api/attendance/gate", json={"student_id": self.kevin["id"], "arrival_time": "07:52"}, headers=self.dd2_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(any("retard" in t.lower() for t in self._titles(self.pk_h)))
        # Le DD du secondaire ne peut pas pointer un élève du primaire
        self.assertEqual(self.c.post("/api/attendance/gate", json={"student_id": self.kevin["id"]}, headers=self.dd_h).status_code, 404)
        # Le titulaire fait l'appel : tous présents + finalise → le retard du portail est conservé
        r = self.c.post(f"/api/classes/{self.cA['id']}/attendance", json={"date": TODAY, "finalize": True, "records": [
            {"student_id": self.kevin["id"], "status": "present"}, {"student_id": self.sarah["id"], "status": "present"}]}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["kept_gate"], 1)
        self.assertEqual(r.get_json()["present_notified"], 1)  # seul Kevin a un parent connecté
        d = self.c.get(f"/api/students/{self.kevin['id']}", headers=self.dir_h).get_json()
        self.assertEqual(d["attendance"]["today"]["status"], "late")
        self.assertTrue(any("est à l'école" in t for t in self._titles(self.pk_h)))
        # Une seconde finalisation le même jour n'envoie rien de plus
        r = self.c.post(f"/api/classes/{self.cA['id']}/attendance", json={"date": TODAY, "finalize": True, "records": [{"student_id": self.sarah["id"], "status": "present"}]}, headers=self.prof_a_h)
        self.assertEqual(r.get_json()["present_notified"], 0)
        # Le parent désactive la notification quotidienne
        self.assertEqual(self.c.put("/api/me/preferences", json={"notify_present_daily": False}, headers=self.pk_h).status_code, 200)
        self.assertFalse(self.c.get("/api/me/preferences", headers=self.pk_h).get_json()["notify_present_daily"])
        # Un statut explicite « absent » écrase le retard du portail
        self.c.post(f"/api/classes/{self.cA['id']}/attendance", json={"date": YESTERDAY, "records": [{"student_id": self.kevin["id"], "status": "absent"}]}, headers=self.prof_a_h)
        # Aujourd'hui DD : liste des retards, appels manquants
        today = self.c.get("/api/discipline/today", headers=self.dd2_h).get_json()
        self.assertEqual(today["late_today"][0]["first_name"], "Kevin"); self.assertEqual(today["late_today"][0]["arrival_time"], "07:52")
        self.assertEqual(self.c.get("/api/discipline/today", headers=self.pk_h).status_code, 403)
        # Recherche portail
        self.assertEqual(self.c.get("/api/attendance/search?q=kev", headers=self.dd2_h).get_json()[0]["first_name"], "Kevin")

    # ---------------- Justification d'absence ----------------
    def test_03_justification_flow(self):
        r = self.c.post(f"/api/students/{self.kevin['id']}/justifications", json={"date": YESTERDAY, "reason": "Consultation médicale", "attachment_data": PDF_DATA, "attachment_name": "certificat.pdf"}, headers=self.pk_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(self.c.post(f"/api/students/{self.kevin['id']}/justifications", json={"date": YESTERDAY, "reason": "Doublon"}, headers=self.pk_h).status_code, 409)
        self.assertEqual(self.c.post(f"/api/students/{self.kevin['id']}/justifications", json={"date": YESTERDAY, "reason": "x"}, headers=self.pj_h).status_code, 404)
        self.assertTrue(any("Justification" in t for t in self._titles(self.prof_a_h)))
        self.assertTrue(any("Justification" in t for t in self._titles(self.dd2_h)))
        pending = self.c.get("/api/justifications?status=pending", headers=self.prof_a_h).get_json()
        self.assertEqual(len(pending), 1); self.assertTrue(pending[0]["has_attachment"])
        jid = pending[0]["id"]
        # Brigitte (autre classe) ne voit pas et ne décide pas
        self.assertEqual(self.c.get("/api/justifications?status=pending", headers=self.prof_b_h).get_json(), [])
        self.assertEqual(self.c.post(f"/api/justifications/{jid}/decide", json={"status": "accepted"}, headers=self.prof_b_h).status_code, 404)
        self.assertEqual(self.c.get(f"/api/justifications/{jid}/attachment", headers=self.prof_a_h).get_json()["file_name"], "certificat.pdf")
        r = self.c.post(f"/api/justifications/{jid}/decide", json={"status": "accepted", "note": "Certificat conforme"}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = self.c.get(f"/api/students/{self.kevin['id']}", headers=self.pk_h).get_json()
        self.assertEqual(d["attendance"]["summary"]["excused"], 1); self.assertEqual(d["attendance"]["summary"]["absent"], 0)
        self.assertEqual(d["justifications"][0]["status"], "accepted")
        self.assertTrue(any("acceptée" in t for t in self._titles(self.pk_h)))
        self.assertEqual(self.c.post(f"/api/justifications/{jid}/decide", json={"status": "refused"}, headers=self.dd2_h).status_code, 409)

    # ---------------- Signalement → qualification → convocation → décision ----------------
    def test_04_report_qualify_convocation_and_points(self):
        r = self.c.post("/api/incident-reports", json={"student_id": self.jonas["id"], "description": "A jeté une chaise en classe", "occurred_at": TODAY}, headers=self.prof_b_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        rid = r.get_json()["id"]
        self.assertEqual(self.c.post("/api/incident-reports", json={"student_id": self.kevin["id"], "description": "x"}, headers=self.prof_b_h).status_code, 404)
        self.assertTrue(any("Signalement" in t for t in self._titles(self.dd_h)))
        self.assertEqual(self.c.post(f"/api/incident-reports/{rid}/qualify", json={"title": "x"}, headers=self.prof_b_h).status_code, 403)
        self.assertEqual(self.c.post(f"/api/incident-reports/{rid}/qualify", json={"title": "x"}, headers=self.dd2_h).status_code, 404)  # hors périmètre
        rule = self.c.post("/api/discipline/rules", json={"label": "Violence en classe", "category": "comportement", "points": -35}, headers=self.dir_h).get_json()
        r = self.c.post(f"/api/incident-reports/{rid}/qualify", json={"rule_id": rule["id"], "title": "Violence en classe", "severity": "high", "action_taken": "Convocation des parents", "notify_parent": True}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        body = r.get_json(); inc_id = body["incident_id"]
        self.assertEqual(body["balance"]["remaining"], 65); self.assertEqual(body["crossed"][0]["label"], "Convocation des parents")
        self.assertTrue(any("qualifié" in t for t in self._titles(self.prof_b_h)))
        self.assertEqual(self.c.get("/api/incident-reports", headers=self.prof_b_h).get_json()[0]["status"], "qualified")
        # Parent non informé tant que l'établissement n'a pas activé la communication
        self.assertFalse(any(n["kind"] == "discipline" for n in self._n(self.pj_h)))
        self.c.put("/api/settings", json={"parent_notify_incidents": True}, headers=self.dir_h)
        # Convocation → parent notifié (prioritaire), titulaire informé
        r = self.c.post("/api/convocations", json={"student_id": self.jonas["id"], "incident_id": inc_id, "scheduled_on": TODAY, "scheduled_time": "10:00", "motif": "Entretien suite à l'incident"}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        cid = r.get_json()["id"]
        self.assertTrue(any("Convocation" in t for t in self._titles(self.pj_h)))
        self.assertEqual(self.c.get(f"/api/incidents/{inc_id}", headers=self.dd_h).get_json()["status"], "convocation")
        self.assertEqual(len(self.c.get("/api/convocations?status=planned", headers=self.dd_h).get_json()), 1)
        self.assertEqual(self.c.post(f"/api/convocations/{cid}/status", json={"status": "held", "parent_attended": True, "notes": "Parents reçus"}, headers=self.dd_h).status_code, 200)
        # Décision humaine + clôture ; le parent (communication activée + incident communiqué) reçoit la décision
        self.assertEqual(self.c.post(f"/api/incidents/{inc_id}/status", json={"status": "decided", "action_taken": "Avertissement écrit"}, headers=self.dd_h).status_code, 200)
        self.assertTrue(any("Décision" in t for t in self._titles(self.pj_h)))
        # Droit de réponse du parent → DD notifié ; sur un incident non communiqué : refusé
        self.assertEqual(self.c.post(f"/api/incidents/{inc_id}/replies", json={"body": "Nous avons discuté avec Jonas."}, headers=self.pj_h).status_code, 201)
        self.assertTrue(any("Réponse du parent" in t for t in self._titles(self.dd_h)))
        hidden = self.c.post("/api/incidents", json={"student_id": self.jonas["id"], "title": "Note interne seulement", "points": -1, "notify_parent": False}, headers=self.dd_h).get_json()
        self.assertEqual(self.c.post(f"/api/incidents/{hidden['id']}/replies", json={"body": "?"}, headers=self.pj_h).status_code, 404)
        # Correction de points tracée (jamais un effacement)
        r = self.c.post(f"/api/students/{self.jonas['id']}/points-adjust", json={"points": 10, "reason": "Excuses présentées et travail de réparation"}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["balance"]["remaining"], 74)
        d = self.c.get(f"/api/students/{self.jonas['id']}", headers=self.dir_h).get_json()
        self.assertEqual(len(d["discipline"]["incidents"]), 3)
        self.assertEqual(self.c.post(f"/api/students/{self.jonas['id']}/points-adjust", json={"points": 5, "reason": "x"}, headers=self.prof_b_h).status_code, 403)
        # Seuils configurables par la Direction seulement
        self.assertEqual(self.c.put("/api/discipline/thresholds", json={"thresholds": [{"remaining_points": 60, "label": "Avertissement"}]}, headers=self.dd_h).status_code, 403)
        r = self.c.put("/api/discipline/thresholds", json={"capital": 120, "thresholds": [{"remaining_points": 80, "label": "Avertissement", "action": "Lettre"}, {"remaining_points": 40, "label": "Conseil"}]}, headers=self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        t = self.c.get("/api/discipline/thresholds", headers=self.dd_h).get_json()
        self.assertEqual(t["capital"], 120); self.assertEqual([x["remaining_points"] for x in t["thresholds"]], [80, 40])

    # ---------------- Règlement : analyse → validation ----------------
    def test_05_reglement_analyze_and_confirm(self):
        text = ("REGLEMENT INTERIEUR\nArticle 1. Tout retard non justifié entraîne un avertissement.\n"
                "Article 2. Toute absence injustifiée est sanctionnée.\nArticle 3. Les bagarres et violences sont interdites et passibles d'exclusion.\n"
                "Article 4. Le téléphone portable est interdit en classe.\nArticle 5. La tenue scolaire est obligatoire.\nArticle 6. La bonne conduite est récompensée.\n")
        r = self.c.post("/api/discipline/reglement/analyze", data={"file": (io.BytesIO(text.encode()), "reglement.txt")}, headers=self.dir_h, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        props = r.get_json()["proposals"]
        cats = {p["category"] for p in props}
        self.assertTrue({"retard", "absence", "comportement", "bonus"} <= cats, props)
        self.assertTrue(all(p["points"] < 0 for p in props if p["category"] != "bonus"))
        self.assertEqual(self.c.post("/api/discipline/reglement/analyze", data={"file": (io.BytesIO(text.encode()), "r.txt")}, headers=self.dd_h, content_type="multipart/form-data").status_code, 403)
        before = len(self.c.get("/api/discipline/rules", headers=self.dir_h).get_json())
        r = self.c.post("/api/discipline/reglement/confirm", json={"rules": props[:3]}, headers=self.dir_h)
        self.assertEqual(r.status_code, 201); self.assertEqual(r.get_json()["created"], 3)
        self.assertEqual(len(self.c.get("/api/discipline/rules", headers=self.dir_h).get_json()), before + 3)
        # Le PDF du règlement devient un document consultable par tous
        r = self.c.post("/api/documents", json={"kind": "reglement", "title": "Règlement intérieur 2026", "file_name": "reglement.pdf", "file_data": PDF_DATA}, headers=self.dir_h)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.get("/api/documents", headers=self.pk_h).get_json()[0]["kind"], "reglement")
        self.assertEqual(self.c.post("/api/documents", json={"kind": "autre", "title": "x", "file_data": PDF_DATA}, headers=self.pk_h).status_code, 403)
        staff_doc = self.c.post("/api/documents", json={"kind": "autre", "title": "Interne", "file_data": PDF_DATA, "visible_to": "staff"}, headers=self.dir_h).get_json()
        self.assertEqual(self.c.get(f"/api/documents/{staff_doc['id']}/file", headers=self.pk_h).status_code, 404)
        self.assertEqual(self.c.get(f"/api/documents/{staff_doc['id']}/file", headers=self.prof_a_h).status_code, 200)

    # ---------------- Registres ----------------
    def test_06_registers(self):
        reg = self.c.get(f"/api/registers/attendance?class_id={self.cA['id']}", headers=self.prof_a_h).get_json()
        self.assertEqual(reg["class"]["name"], "5e Primaire A"); self.assertTrue(len(reg["days"]) >= 1)
        kevin = next(s for s in reg["students"] if s["first_name"] == "Kevin")
        self.assertEqual(kevin["marks"][TODAY], "R")
        self.assertEqual(self.c.get(f"/api/registers/attendance?class_id={self.cA['id']}", headers=self.prof_b_h).status_code, 404)
        self.assertEqual(self.c.get(f"/api/registers/attendance?class_id={self.cA['id']}", headers=self.pk_h).status_code, 404)
        disc = self.c.get("/api/registers/discipline", headers=self.dd_h).get_json()
        self.assertTrue(len(disc["rows"]) >= 2)
        self.assertEqual(self.c.get("/api/registers/discipline", headers=self.prof_b_h).status_code, 403)

    # ---------------- Calendrier & communiqués ----------------
    def test_07_calendar_events_and_feed(self):
        r = self.c.post("/api/calendar/events", json={"kind": "reunion", "title": "Réunion des parents", "starts_on": TODAY, "starts_time": "15:00", "target_scope": "all", "audience": "parents"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertTrue(r.get_json()["notified"] >= 3)
        self.assertTrue(any("Réunion" in t for t in self._titles(self.pk_h)))
        # Le DD publie un communiqué pour son cycle uniquement (« toute l'école » est ramené à son périmètre)
        r = self.c.post("/api/calendar/events", json={"kind": "communique", "title": "Contrôle des tenues lundi", "body": "Uniforme complet exigé.", "target_scope": "all"}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertTrue(any("tenues" in t for t in self._titles(self.pj_h)))
        self.assertFalse(any("tenues" in t for t in self._titles(self.pk_h)))
        # Le DD ne cible pas un autre cycle ; un parent ne publie pas
        self.assertEqual(self.c.post("/api/calendar/events", json={"kind": "conge", "title": "x", "starts_on": TODAY, "target_scope": "cycle", "target_value": "primaire"}, headers=self.dd_h).status_code, 403)
        self.assertEqual(self.c.post("/api/calendar/events", json={"kind": "fete", "title": "x", "starts_on": TODAY}, headers=self.pk_h).status_code, 403)
        # Événement réservé au personnel invisible du parent
        self.c.post("/api/calendar/events", json={"kind": "reunion", "title": "Conseil pédagogique", "starts_on": TODAY, "audience": "staff"}, headers=self.dir_h)
        parent_titles = [e["title"] for e in self.c.get("/api/calendar/events", headers=self.pk_h).get_json()]
        self.assertIn("Réunion des parents", parent_titles); self.assertNotIn("Conseil pédagogique", parent_titles); self.assertNotIn("Contrôle des tenues lundi", parent_titles)
        # Flux du mois : événement, examen, devoir, échéance, présence, convocation
        self.c.post(f"/api/classes/{self.cA['id']}/exams", json={"subject": "Mathématiques", "date": TODAY, "start_time": "08:00"}, headers=self.dir_h)
        feed = self.c.get("/api/calendar?month=" + TODAY[:7], headers=self.pk_h).get_json()
        kinds = {i["kind"] for i in feed["items"]}
        self.assertTrue({"reunion", "examen", "echeance", "presence_late"} <= kinds, kinds)
        feed_j = self.c.get("/api/calendar?month=" + TODAY[:7], headers=self.pj_h).get_json()
        self.assertIn("convocation", {i["kind"] for i in feed_j["items"]})
        self.assertEqual(self.c.get("/api/calendar?month=2026-9", headers=self.pk_h).status_code, 400)

    # ---------------- Ressources, contacts, messages ----------------
    def test_08_resources_contacts_messages(self):
        r = self.c.post("/api/resources", json={"class_id": self.cA["id"], "kind": "devoir", "title": "Exercices de fractions", "subject": "Mathématiques", "due_date": TODAY, "file_name": "fractions.pdf", "file_data": PDF_DATA}, headers=self.prof_a_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        rid = r.get_json()["id"]
        self.assertEqual(self.c.post("/api/resources", json={"class_id": self.cA["id"], "kind": "livre", "title": "x"}, headers=self.prof_b_h).status_code, 404)
        self.assertEqual(self.c.post("/api/resources", json={"class_id": self.cA["id"], "kind": "devoir", "title": "sans date"}, headers=self.prof_a_h).status_code, 400)
        self.assertTrue(any("Nouveau devoir" in t for t in self._titles(self.pk_h)))
        self.assertEqual(self.c.get("/api/resources", headers=self.pk_h).get_json()[0]["title"], "Exercices de fractions")
        self.assertEqual(self.c.get("/api/resources", headers=self.pj_h).get_json(), [])
        self.assertEqual(self.c.get(f"/api/resources/{rid}/file", headers=self.pk_h).get_json()["file_name"], "fractions.pdf")
        self.assertEqual(self.c.get(f"/api/resources/{rid}/file", headers=self.pj_h).status_code, 404)
        self.assertIn("devoir", {i["kind"] for i in self.c.get("/api/calendar?month=" + TODAY[:7], headers=self.pk_h).get_json()["items"]})
        # Contacts : téléphone masqué par défaut, visible si l'enseignant le partage
        prof_id = self.c.get("/api/me", headers=self.prof_a_h).get_json()["user_id"]
        self.c.put("/api/me", json={"phone": "0999000111"}, headers=self.prof_a_h)
        ct = self.c.get(f"/api/students/{self.kevin['id']}/contacts", headers=self.pk_h).get_json()
        self.assertEqual(ct["teachers"][0]["name"], "Paul Prof"); self.assertTrue(ct["teachers"][0]["is_titulaire"]); self.assertIsNone(ct["teachers"][0]["phone"])
        self.c.put("/api/me/preferences", json={"share_phone": True}, headers=self.prof_a_h)
        self.assertEqual(self.c.get(f"/api/students/{self.kevin['id']}/contacts", headers=self.pk_h).get_json()["teachers"][0]["phone"], "+243999000111")
        # Cahier de communication : parent → titulaire + DD ; réponse → parent ; périmètre
        r = self.c.post(f"/api/messages/{self.kevin['id']}", json={"body": "Kevin sera absent vendredi."}, headers=self.pk_h)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(any("Nouveau message" in t for t in self._titles(self.prof_a_h)))
        self.assertEqual(self.c.get("/api/messages/unread-count", headers=self.prof_a_h).get_json()["unread"], 1)
        th = self.c.get(f"/api/messages/{self.kevin['id']}", headers=self.prof_a_h).get_json()
        self.assertEqual(th["messages"][0]["sender_role"], "parent")
        self.assertEqual(self.c.get("/api/messages/unread-count", headers=self.prof_a_h).get_json()["unread"], 0)
        self.c.post(f"/api/messages/{self.kevin['id']}", json={"body": "Bien noté, merci."}, headers=self.prof_a_h)
        self.assertTrue(any("Nouveau message" in t for t in self._titles(self.pk_h)))
        self.assertEqual(self.c.get(f"/api/messages/{self.kevin['id']}", headers=self.pj_h).status_code, 404)
        self.assertEqual(self.c.get(f"/api/messages/{self.kevin['id']}", headers=self.prof_b_h).status_code, 404)
        threads = self.c.get("/api/messages/threads", headers=self.pk_h).get_json()
        self.assertEqual(threads[0]["first_name"], "Kevin"); self.assertIn("Bien noté", threads[0]["last_body"])

    # ---------------- Résultats : périodes, proclamation, conduite, décision, maternelle ----------------
    def test_09_periods_publication_conduct_decision_and_maternelle(self):
        r = self.c.post("/api/periods", json={"preset": "standard"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 201); self.assertEqual(r.get_json()["created"], 6)
        periods = self.c.get("/api/periods", headers=self.pk_h).get_json()["periods"]
        p1 = next(p for p in periods if p["label"] == "Période 1")
        self.c.post(f"/api/classes/{self.cA['id']}/grades", json={"subject": "Mathématiques", "period": "Période 1", "max_score": 20, "entries": [{"student_id": self.kevin["id"], "score": 15}, {"student_id": self.sarah["id"], "score": 12}]}, headers=self.prof_a_h)
        self.c.post(f"/api/classes/{self.cA['id']}/grades", json={"subject": "Français", "period": "Période 1", "max_score": 10, "entries": [{"student_id": self.kevin["id"], "score": 7}, {"student_id": self.sarah["id"], "score": 9}]}, headers=self.prof_a_h)
        # Avant proclamation : le parent ne voit rien, le titulaire tout
        d = self.c.get(f"/api/students/{self.kevin['id']}", headers=self.pk_h).get_json()
        self.assertEqual(d["grades"], []); self.assertIsNone(d["bulletin"]["general_average_20"])
        self.assertEqual(len(self.c.get(f"/api/students/{self.kevin['id']}", headers=self.prof_a_h).get_json()["grades"]), 2)
        res = self.c.get(f"/api/classes/{self.cA['id']}/results?period=Période 1", headers=self.prof_a_h).get_json()
        self.assertTrue(res["can_council"]); self.assertEqual(res["students"][0]["rank"] in (1, 2), True)
        # Conseil : cote de conduite fixée par le titulaire ; décision réservée à la Direction
        self.assertEqual(self.c.put(f"/api/students/{self.kevin['id']}/conduct", json={"period": "Période 1", "label": "Bien", "note": "Efforts notés"}, headers=self.prof_a_h).status_code, 200)
        self.assertEqual(self.c.put(f"/api/students/{self.kevin['id']}/conduct", json={"period": "Période 1", "label": "Bien"}, headers=self.prof_b_h).status_code, 403)
        self.assertEqual(self.c.put(f"/api/students/{self.kevin['id']}/decision", json={"decision": "admis", "mention": "Satisfaction"}, headers=self.prof_a_h).status_code, 403)
        # Proclamation
        self.assertEqual(self.c.post(f"/api/periods/{p1['id']}/publish", headers=self.prof_a_h).status_code, 403)
        r = self.c.post(f"/api/periods/{p1['id']}/publish", headers=self.dir_h)
        self.assertEqual(r.status_code, 200); self.assertEqual(r.get_json()["students"], 2)
        self.assertTrue(any("Bulletin disponible" in t for t in self._titles(self.pk_h)))
        d = self.c.get(f"/api/students/{self.kevin['id']}", headers=self.pk_h).get_json()
        self.assertEqual(len(d["grades"]), 2)
        b = d["bulletin"]
        self.assertEqual(b["general_average_20"], 14.5); self.assertEqual(b["percent"], 72.5)
        self.assertEqual(b["conduct"]["label"], "Bien"); self.assertTrue(b["conduct"]["overridden"])
        # Décision de fin d'année → parent notifié
        self.assertEqual(self.c.put(f"/api/students/{self.kevin['id']}/decision", json={"decision": "admis", "mention": "Satisfaction"}, headers=self.dir_h).status_code, 200)
        self.assertTrue(any("Décision de fin d'année" in t for t in self._titles(self.pk_h)))
        self.assertEqual(self.c.get(f"/api/students/{self.kevin['id']}", headers=self.pk_h).get_json()["bulletin"]["decision"]["decision"], "admis")
        # Une période avec des notes ne se supprime pas
        self.assertEqual(self.c.delete(f"/api/periods/{p1['id']}", headers=self.dir_h).status_code, 409)
        # Maternelle : appréciations par domaine, publiées avec la période
        r = self.c.post(f"/api/classes/{self.cM['id']}/appreciations", json={"period": "Période 2", "domain": "Langage", "entries": [{"student_id": self.lea["id"], "level": 3, "comment": "S'exprime bien"}]}, headers=self.prof_m_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.c.post(f"/api/classes/{self.cM['id']}/appreciations", json={"period": "P2", "domain": "Langage", "entries": [{"student_id": self.lea["id"], "level": 9}]}, headers=self.prof_m_h).status_code, 400)
        self.assertEqual(self.c.get(f"/api/students/{self.lea['id']}", headers=self.pl_h).get_json()["appreciations"], [])
        p2 = next(p for p in periods if p["label"] == "Période 2")
        self.c.post(f"/api/periods/{p2['id']}/publish", headers=self.dir_h)
        self.assertEqual(self.c.get(f"/api/students/{self.lea['id']}", headers=self.pl_h).get_json()["appreciations"][0]["level"], 3)
        self.assertEqual(self.c.get("/api/appreciations/domains", headers=self.pl_h).get_json()["levels"]["3"], "Acquis")

    # ---------------- Boutique : variantes, retrait le lendemain ----------------
    def test_10_store_variants_and_pickup(self):
        prod = self.c.post("/api/store/products", json={"name": "Chemise", "category": "uniformes", "price": 12, "stock": 20, "options": ["S", "M", "L"]}, headers=self.dir_h).get_json()
        self.assertEqual(json.loads(self.c.get("/api/store/products", headers=self.pk_h).get_json()[0]["options"]), ["S", "M", "L"])
        self.assertEqual(self.c.post("/api/store/orders", json={"student_id": self.kevin["id"], "items": [{"product_id": prod["id"], "quantity": 1}]}, headers=self.pk_h).status_code, 400)
        r = self.c.post("/api/store/orders", json={"student_id": self.kevin["id"], "items": [{"product_id": prod["id"], "quantity": 2, "variant": "M"}]}, headers=self.pk_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        o = r.get_json()
        self.assertRegex(o["pickup_code"], r"^[A-Z2-9]{6}$"); self.assertTrue(o["pickup_date"] > TODAY)
        # Pas prête tant que non payée
        self.assertEqual(self.c.post(f"/api/store/orders/{o['id']}/status", json={"status": "ready"}, headers=self.dir_h).status_code, 409)
        pay = self.c.post("/api/payments", json={"obligation_id": o["obligation_id"], "amount": 24, "method": "mobile_money", "idempotency_key": "chemise-1"}, headers=self.pk_h).get_json()
        self.c.post(f"/api/payments/{pay['id']}/confirm", json={}, headers=self.dir_h)
        self.assertEqual(self.c.post(f"/api/store/orders/{o['id']}/status", json={"status": "ready"}, headers=self.dir_h).status_code, 200)
        self.assertTrue(any("prête" in t for t in self._titles(self.pk_h)))
        self.assertEqual(self.c.post(f"/api/store/orders/{o['id']}/status", json={"status": "delivered", "pickup_code": "WRONG1"}, headers=self.dir_h).status_code, 400)
        self.assertEqual(self.c.post(f"/api/store/orders/{o['id']}/status", json={"status": "delivered", "pickup_code": o["pickup_code"].lower()}, headers=self.dir_h).status_code, 200)
        self.assertEqual(self.c.get("/api/store/orders", headers=self.pk_h).get_json()[0]["items"][0]["variant"], "M")

    # ---------------- Attestation ----------------
    def test_11_attestation_data(self):
        a = self.c.get(f"/api/students/{self.kevin['id']}/attestation", headers=self.pk_h).get_json()
        self.assertEqual(a["student"]["first_name"], "Kevin"); self.assertEqual(a["school"]["name"], "École des Lots"); self.assertEqual(a["director"], "Marie Dir")
        self.assertEqual(self.c.get(f"/api/students/{self.kevin['id']}/attestation", headers=self.pj_h).status_code, 404)

    # ---------------- Abonnement : essai → facture → paiement → suspension → reprise ----------------
    def test_12_subscription_lifecycle_and_read_only(self):
        s = self.c.get("/api/subscription", headers=self.dir_h).get_json()
        self.assertEqual(s["status"], "trial"); self.assertEqual(s["plan"]["code"], "essentiel"); self.assertEqual(s["estimated_amount"], 49.0)
        self.assertEqual(self.c.get("/api/subscription", headers=self.prof_a_h).status_code, 403)
        self.assertEqual([p["code"] for p in self.c.get("/api/plans").get_json()], ["essentiel", "ecole", "complexe", "reseau"])
        # Fin d'essai simulée → facture émise, statut actif, Direction notifiée
        conn = db.get_connection()
        conn.execute("UPDATE subscriptions SET trial_ends_at=? WHERE tenant_id=?", (str(time.time() - 3600), self.tenant_id)); conn.commit(); conn.close()
        s = self.c.get("/api/subscription", headers=self.dir_h).get_json()
        self.assertEqual(s["status"], "active"); self.assertIsNotNone(s["open_invoice"]); self.assertRegex(s["open_invoice"]["number"], r"^INV-\d{4}-\d{4}$")
        self.assertEqual(s["open_invoice"]["amount"], 49.0)
        # Une facture ouverte est ce qui amène la Direction sur l'écran d'abonnement.
        me = self.c.get("/api/me", headers=self.dir_h).get_json()
        self.assertIn("Facture", me["subscription"]["attention"] or "")
        self.assertIsNone(self.c.get("/api/me", headers=self.prof_a_h).get_json()["subscription"]["attention"])
        self.assertTrue(any("Facture" in t for t in self._titles(self.dir_h)))
        inv_id = s["open_invoice"]["id"]
        # Retard au-delà du délai de grâce → lecture seule : écriture bloquée (402), lecture libre, paiement autorisé
        conn = db.get_connection()
        conn.execute("UPDATE invoices SET due_at=? WHERE id=?", (str(time.time() - 86400 * 20), inv_id)); conn.commit(); conn.close()
        me = self.c.get("/api/me", headers=self.dir_h).get_json()
        self.assertEqual(me["subscription"]["status"], "suspended"); self.assertTrue(me["subscription"]["read_only"])
        r = self.c.post("/api/students", json={"first_name": "Bloqué", "last_name": "X", "academic_year_id": self.year}, headers=self.dir_h)
        self.assertEqual(r.status_code, 402)
        self.assertEqual(self.c.post(f"/api/classes/{self.cA['id']}/attendance", json={"date": TODAY, "records": [{"student_id": self.kevin["id"], "status": "present"}]}, headers=self.prof_a_h).status_code, 402)
        self.assertEqual(self.c.get("/api/students", headers=self.dir_h).status_code, 200)
        r = self.c.post("/api/subscription/pay", json={"invoice_id": inv_id, "method": "mobile_money", "reference": "MP-2026-77"}, headers=self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)); self.assertEqual(r.get_json()["status"], "pending")
        # Plateforme : refus sans droit ; confirmation par l'admin → actif, écriture rétablie
        self.assertEqual(self.c.get("/api/platform/overview", headers=self.dir_h).status_code, 403)
        admin_id = self.c.get("/api/me", headers=self.dir_h).get_json()["user_id"]
        # `INSERT OR IGNORE` est du SQLite pur : ce montage tombait dès qu'on
        # exécutait la suite contre PostgreSQL. `ON CONFLICT DO NOTHING` dit la
        # même chose sur les deux moteurs — c'est déjà la forme utilisée partout
        # dans le backend.
        conn = db.get_connection(); conn.execute("INSERT INTO platform_admins (user_id, created_at) VALUES (?,?) ON CONFLICT DO NOTHING", (admin_id, str(time.time()))); conn.commit(); conn.close()
        ov = self.c.get("/api/platform/overview", headers=self.dir_h).get_json()
        self.assertTrue(any(t["name"] == "École des Lots" for t in ov["tenants"])); self.assertEqual(len(ov["pending_invoices"]), 1)
        self.assertEqual(self.c.post(f"/api/platform/invoices/{inv_id}/confirm", headers=self.dir_h).status_code, 200)
        me = self.c.get("/api/me", headers=self.dir_h).get_json()
        self.assertEqual(me["subscription"]["status"], "active"); self.assertFalse(me["subscription"]["read_only"])
        self.assertEqual(self.c.post("/api/students", json={"first_name": "Libre", "last_name": "X", "academic_year_id": self.year}, headers=self.dir_h).status_code, 201)
        self.assertTrue(any("Paiement confirmé" in t for t in self._titles(self.dir_h)))
        # Palier automatique selon les élèves actifs
        self.assertEqual(self.c.put("/api/platform/plans/ecole", json={"per_student": 0.25}, headers=self.dir_h).status_code, 200)
        conn = db.get_connection(); conn.execute("DELETE FROM platform_admins WHERE user_id=?", (admin_id,)); conn.commit(); conn.close()

    def test_13_school_life_settings_are_validated_and_scoped(self):
        """Réglages de vie scolaire : enregistrés, validés, réservés à la Direction."""
        r = self.c.put("/api/settings", json={
            "pass_threshold": 55, "store_cutoff_time": "18:45",
            "exam_period_starts": "2026-10-12", "exam_period_ends": "2026-10-19",
            "parent_notify_present": True, "teacher_contact_visible": True,
        }, headers=self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        s = r.get_json()
        self.assertEqual(s["pass_threshold"], 55.0)
        self.assertEqual(s["store_cutoff_time"], "18:45")
        self.assertEqual(s["exam_period_starts"], "2026-10-12")
        self.assertEqual(s["parent_notify_present"], 1)
        self.assertEqual(s["teacher_contact_visible"], 1)
        # Validation : heure et pourcentage hors bornes refusés
        self.assertEqual(self.c.put("/api/settings", json={"store_cutoff_time": "25:00"}, headers=self.dir_h).status_code, 400)
        self.assertEqual(self.c.put("/api/settings", json={"pass_threshold": 140}, headers=self.dir_h).status_code, 400)
        self.assertEqual(self.c.put("/api/settings", json={"exam_period_starts": "12/10/2026"}, headers=self.dir_h).status_code, 400)
        # Un professeur ne règle rien pour l'établissement
        self.assertEqual(self.c.put("/api/settings", json={"pass_threshold": 10}, headers=self.prof_a_h).status_code, 403)
        # L'ouverture des coordonnées par l'établissement est répercutée aux parents…
        contacts = self.c.get(f"/api/students/{self.kevin['id']}/contacts", headers=self.pk_h).get_json()
        self.assertTrue(all(t["contact_visible"] for t in contacts["teachers"]))
        # …et refermée, sauf pour l'enseignant qui a choisi de partager son numéro.
        self.c.put("/api/settings", json={"teacher_contact_visible": False}, headers=self.dir_h)
        self.c.put("/api/me/preferences", json={"share_phone": True}, headers=self.prof_a_h)
        contacts = self.c.get(f"/api/students/{self.kevin['id']}/contacts", headers=self.pk_h).get_json()
        self.assertTrue(all(t["contact_visible"] for t in contacts["teachers"]))
        self.c.put("/api/me/preferences", json={"share_phone": False}, headers=self.prof_a_h)
        contacts = self.c.get(f"/api/students/{self.kevin['id']}/contacts", headers=self.pk_h).get_json()
        self.assertFalse(any(t["contact_visible"] for t in contacts["teachers"]))
        self.assertTrue(all(t["phone"] is None and t["email"] is None for t in contacts["teachers"]))
        # Le personnel, lui, garde l'annuaire interne.
        staff_view = self.c.get(f"/api/students/{self.kevin['id']}/contacts", headers=self.dir_h).get_json()
        self.assertTrue(all(t["contact_visible"] for t in staff_view["teachers"]))


if __name__ == "__main__":
    unittest.main()
