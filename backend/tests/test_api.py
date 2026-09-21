"""KLASSIO backend — tests d'intégration.

Exécution : depuis backend/, avec le venv activé :
    python3 -m unittest tests.test_api -v

Ces tests utilisent une base SQLite dédiée (klassio_test.db), jamais la base de
développement — voir setUpModule.
"""
import unittest
import sys
import os
import json
import io

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


class KlassioApiTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()
        # Chaque test client de test partage la même IP simulée
        # (127.0.0.1) ; sans ce reset, la limite anti-abus (Conclusion #6 de
        # l'audit) — bien réelle et voulue en production — se déclencherait
        # entre les tests eux-mêmes plutôt que de tester un vrai abus.
        security.reset_rate_limits_for_tests()

    def _register_school(self, email, school_name):
        resp = self.client.post("/api/auth/register-school", json={
            "email": email, "password": "Secret123!", "name": "Directeur Test", "school_name": school_name,
        })
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
        return resp.get_json()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_01_register_and_login(self):
        data = self._register_school("dir1@ecolea.test", "École A")
        self.assertEqual(data["role"], "directeur")
        login = self.client.post("/api/auth/login", json={"email": "dir1@ecolea.test", "password": "Secret123!"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.get_json()["tenant_id"], data["tenant_id"])

    def test_02_wrong_password_rejected(self):
        self._register_school("dir2@ecolea.test", "École A2")
        login = self.client.post("/api/auth/login", json={"email": "dir2@ecolea.test", "password": "WRONG"})
        self.assertEqual(login.status_code, 401)

    def test_03_full_financial_flow_and_balance_never_a_bare_number(self):
        director = self._register_school("dir3@ecolea.test", "École Kinshasa")
        h = self._auth(director["token"])

        years = self.client.get("/api/academic-years", headers=h).get_json()
        year_id = years[0]["id"]

        cls = self.client.post("/api/classes", json={"academic_year_id": year_id, "name": "6e A"}, headers=h).get_json()
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "class_id": cls["id"], "first_name": "Jean", "last_name": "Dupont",
        }, headers=h).get_json()

        item = self.client.post("/api/catalog-items", json={
            "name": "Frais scolaires", "category": "frais", "amount": 250, "currency": "USD",
        }, headers=h).get_json()

        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()
        self.assertEqual(obligation["amount"], 250)

        # Avant tout paiement : solde = obligation entière, jamais un chiffre inventé
        summary = self.client.get(f"/api/students/{student['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(summary["balance"], 250)
        self.assertEqual(summary["total_paid"], 0)

        # Paiement partiel par Mobile Money : reste en attente d'une confirmation
        # séparée (contrairement au cash, voir test_08) — docs/FINANCE.md §7.2.
        payment = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 150, "method": "mobile_money", "idempotency_key": "pay-jean-1",
        }, headers=h).get_json()
        self.assertEqual(payment["status"], "CREATED")

        # Tant que non confirmé, ne compte pas dans le solde (docs/FINANCE.md §7.3)
        summary = self.client.get(f"/api/students/{student['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(summary["balance"], 250)

        confirmed = self.client.post(f"/api/payments/{payment['id']}/confirm",
                                      json={"provider_reference": "REF-1"}, headers=h).get_json()
        self.assertEqual(confirmed["status"], "CONFIRMED")

        summary = self.client.get(f"/api/students/{student['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(summary["total_paid"], 150)
        self.assertEqual(summary["balance"], 100)
        line = summary["obligations"][0]
        self.assertEqual(line["status"], "PARTIALLY_PAID")
        self.assertEqual(len(line["payments"]), 1)

    def test_04_payment_idempotency_no_double_credit(self):
        director = self._register_school("dir4@ecolea.test", "École Idempotence")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Marie", "last_name": "Kabeya",
        }, headers=h).get_json()
        item = self.client.post("/api/catalog-items", json={"name": "Uniforme", "amount": 80, "currency": "USD"}, headers=h).get_json()
        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()

        p1 = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 80, "method": "mobile_money", "idempotency_key": "same-key",
        }, headers=h).get_json()
        # Même clé d'idempotence rejouée : ne doit JAMAIS créer un second paiement
        p2 = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 80, "method": "mobile_money", "idempotency_key": "same-key",
        }, headers=h).get_json()
        self.assertEqual(p1["id"], p2["id"])

        self.client.post(f"/api/payments/{p1['id']}/confirm", json={}, headers=h)
        # Confirmer deux fois le même paiement ne double jamais le crédit
        self.client.post(f"/api/payments/{p1['id']}/confirm", json={}, headers=h)

        summary = self.client.get(f"/api/students/{student['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(summary["total_paid"], 80)
        self.assertEqual(summary["balance"], 0)

    def test_05_cross_tenant_isolation_denied(self):
        """Le test le plus important de ce fichier : école A ne peut jamais voir école B."""
        director_a = self._register_school("dirA@iso.test", "École A")
        director_b = self._register_school("dirB@iso.test", "École B")
        h_a, h_b = self._auth(director_a["token"]), self._auth(director_b["token"])

        year_b = self.client.get("/api/academic-years", headers=h_b).get_json()[0]["id"]
        student_b = self.client.post("/api/students", json={
            "academic_year_id": year_b, "first_name": "Paul", "last_name": "Ilunga",
        }, headers=h_b).get_json()

        # A ne doit jamais accéder au dossier financier d'un élève de B
        resp = self.client.get(f"/api/students/{student_b['id']}/financial-summary", headers=h_a)
        self.assertEqual(resp.status_code, 404)

        # A ne doit jamais voir B dans sa propre liste d'élèves
        students_a = self.client.get("/api/students", headers=h_a).get_json()
        self.assertNotIn(student_b["id"], [s["id"] for s in students_a])

        # A ne peut pas créer une obligation pour un élève de B, même en le ciblant explicitement
        item_a = self.client.post("/api/catalog-items", json={"name": "Frais", "amount": 100, "currency": "USD"}, headers=h_a).get_json()
        resp = self.client.post("/api/obligations", json={
            "student_id": student_b["id"], "academic_year_id": year_b, "catalog_item_id": item_a["id"],
        }, headers=h_a)
        self.assertEqual(resp.status_code, 404)

        # A ne voit jamais les événements/audit de B
        events_a = self.client.get("/api/events", headers=h_a).get_json()
        self.assertEqual(events_a, [])  # rien créé côté A dans ce test

    def _invite_and_accept_parent(self, h, student_id, email, name="Parent Test"):
        """Crée un parent via le VRAI flux (invitation → acceptation) — plus
        de création directe via /api/users, retirée par l'audit de sécurité
        (route morte contournant le modèle d'invitation obligatoire)."""
        inv = self.client.post("/api/invitations", json={
            "role": "parent", "student_ids": [student_id],
        }, headers=h).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": name, "email": email, "password": "Secret123!",
        })
        return accept.get_json()

    def test_06_permission_denied_for_wrong_role(self):
        director = self._register_school("dir6@perm.test", "École Perm")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "X", "last_name": "Y",
        }, headers=h).get_json()
        parent_account = self._invite_and_accept_parent(h, student["id"], "parent6@perm.test")
        h_parent = self._auth(parent_account["token"])

        # Un parent ne peut pas créer d'élève — vérifié côté backend, pas seulement caché côté frontend
        resp = self.client.post("/api/students", json={
            "academic_year_id": "whatever", "first_name": "X", "last_name": "Y",
        }, headers=h_parent)
        self.assertEqual(resp.status_code, 403)

    def test_07_parent_sees_only_own_child_notification(self):
        director = self._register_school("dir7@notif.test", "École Notif")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Grace", "last_name": "Ilunga",
        }, headers=h).get_json()

        # L'acceptation de l'invitation crée elle-même le guardian et le lien
        # student_guardians — plus besoin de POST /api/guardians manuel ici.
        parent_account = self._invite_and_accept_parent(h, student["id"], "parent7@notif.test", "Parent Grace")

        item = self.client.post("/api/catalog-items", json={"name": "Cantine", "amount": 50, "currency": "USD"}, headers=h).get_json()
        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()
        payment = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 50, "method": "cash", "idempotency_key": "notif-test-1",
        }, headers=h).get_json()
        self.client.post(f"/api/payments/{payment['id']}/confirm", json={}, headers=h)

        h_parent = self._auth(parent_account["token"])
        notifs = self.client.get("/api/notifications", headers=h_parent).get_json()
        self.assertEqual(len(notifs), 1)
        self.assertIn("Grace Ilunga", notifs[0]["body"])

        director_notifs = self.client.get("/api/notifications", headers=h).get_json()
        self.assertTrue(any(n["title"] == "Nouveaux paiements reçus" for n in director_notifs))

    def test_10_director_payment_notifications_are_grouped(self):
        """Trouvé par la simulation grandeur nature (docs/RAPPORT_SIMULATION.md) :
        2530 notifications individuelles pour un seul directeur après une vague de
        paiements. Elles doivent maintenant se regrouper en une seule qui s'incrémente."""
        director = self._register_school("dir10@group.test", "École Groupe")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        item = self.client.post("/api/catalog-items", json={"name": "Frais", "amount": 50, "currency": "USD"}, headers=h).get_json()

        for i in range(5):
            student = self.client.post("/api/students", json={
                "academic_year_id": year_id, "first_name": f"E{i}", "last_name": "Group",
            }, headers=h).get_json()
            ob = self.client.post("/api/obligations", json={
                "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
            }, headers=h).get_json()
            self.client.post("/api/payments", json={
                "obligation_id": ob["id"], "amount": 50, "method": "cash", "idempotency_key": f"group-pay-{i}",
            }, headers=h)

        notifs = self.client.get("/api/notifications", headers=h).get_json()
        payment_notifs = [n for n in notifs if n["title"] == "Nouveaux paiements reçus"]
        self.assertEqual(len(payment_notifs), 1, "5 paiements doivent produire UNE seule notification agrégée")
        self.assertEqual(payment_notifs[0]["count"], 5)
        self.assertAlmostEqual(payment_notifs[0]["amount_total"], 250.0)
        self.assertIn("5 paiements", payment_notifs[0]["body"])


    def test_08_cash_payment_auto_confirms_mobile_money_does_not(self):
        """Un paiement cash enregistré par le personnel EST la preuve — confirmé
        immédiatement. Un paiement Mobile Money attend une vérification séparée
        (docs/FINANCE.md §7.1-7.2)."""
        director = self._register_school("dir8@cash.test", "École Cash")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Eric", "last_name": "Mbuyi",
        }, headers=h).get_json()
        item = self.client.post("/api/catalog-items", json={"name": "Transport", "amount": 40, "currency": "USD"}, headers=h).get_json()
        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()

        cash_payment = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 40, "method": "cash", "idempotency_key": "cash-1",
        }, headers=h).get_json()
        self.assertEqual(cash_payment["status"], "CONFIRMED")

        # Le Mobile Money porte sur une SECONDE obligation : la première vient
        # d'être soldée par le paiement cash, et depuis l'audit du 17/09 un
        # paiement sur une obligation déjà payée est refusé. L'assertion, elle,
        # ne change pas : c'est bien « mobile_money ne s'auto-confirme pas »
        # qu'on vérifie, pas la capacité à payer une dette inexistante.
        seconde = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()
        mm_payment = self.client.post("/api/payments", json={
            "obligation_id": seconde["id"], "amount": 1, "method": "mobile_money", "idempotency_key": "mm-1",
        }, headers=h).get_json()
        self.assertEqual(mm_payment["status"], "CREATED")

    def test_09_security_hardening_after_pentest(self):
        """Ajouté après l'exercice de pentest : chaque faille trouvée doit rester bloquée."""
        director = self._register_school("dir9@secu.test", "École Sécu")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Test", "last_name": "Secu",
        }, headers=h).get_json()
        item = self.client.post("/api/catalog-items", json={"name": "Frais", "amount": 100, "currency": "USD"}, headers=h).get_json()
        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()

        # Montant négatif refusé
        resp = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": -500, "method": "cash", "idempotency_key": "sec-neg",
        }, headers=h)
        self.assertEqual(resp.status_code, 400)

        # Montant non numérique refusé
        resp = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": "abc", "method": "cash", "idempotency_key": "sec-str",
        }, headers=h)
        self.assertEqual(resp.status_code, 400)

        # Obligation à montant négatif refusée
        resp = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"], "amount": -1,
        }, headers=h)
        self.assertEqual(resp.status_code, 400)

        # Mot de passe trop court refusé à l'inscription
        resp = self.client.post("/api/auth/register-school", json={
            "email": "weak9@secu.test", "password": "123", "name": "X", "school_name": "Y",
        })
        self.assertEqual(resp.status_code, 400)

        # Email invalide refusé
        resp = self.client.post("/api/auth/register-school", json={
            "email": "not-an-email", "password": "longenough123", "name": "X", "school_name": "Y",
        })
        self.assertEqual(resp.status_code, 400)

        # Collision de clé d'idempotence entre DEUX tenants différents : ne doit plus jamais planter (500)
        other = self._register_school("dir9b@secu.test", "École Sécu B")
        h2 = self._auth(other["token"])
        year2 = self.client.get("/api/academic-years", headers=h2).get_json()[0]["id"]
        student2 = self.client.post("/api/students", json={
            "academic_year_id": year2, "first_name": "Autre", "last_name": "Ecole",
        }, headers=h2).get_json()
        item2 = self.client.post("/api/catalog-items", json={"name": "Frais", "amount": 50, "currency": "USD"}, headers=h2).get_json()
        obligation2 = self.client.post("/api/obligations", json={
            "student_id": student2["id"], "academic_year_id": year2, "catalog_item_id": item2["id"],
        }, headers=h2).get_json()

        self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 10, "method": "cash", "idempotency_key": "SAME-KEY",
        }, headers=h)
        resp = self.client.post("/api/payments", json={
            "obligation_id": obligation2["id"], "amount": 10, "method": "cash", "idempotency_key": "SAME-KEY",
        }, headers=h2)
        self.assertIn(resp.status_code, (200, 201))  # jamais un 500 : chaque tenant a son propre espace de clés

        # Brute force : la 6e tentative de mot de passe erroné doit être bloquée (429)
        for _ in range(5):
            self.client.post("/api/auth/login", json={"email": "dir9@secu.test", "password": "wrong"})
        resp = self.client.post("/api/auth/login", json={"email": "dir9@secu.test", "password": "wrong"})
        self.assertEqual(resp.status_code, 429)


    def test_11_invitation_parent_flow_grants_scoped_access_only(self):
        """Refonte onboarding : le parent ne s'inscrit jamais librement — il accepte
        une invitation créée par le directeur, et n'obtient accès qu'aux enfants
        que le directeur a explicitement associés à cette invitation."""
        director = self._register_school("dir11@invite.test", "École Invitations")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        child1 = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Jean", "last_name": "Kabeya",
        }, headers=h).get_json()
        other_child = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Autre", "last_name": "Eleve",
        }, headers=h).get_json()

        inv = self.client.post("/api/invitations", json={
            "role": "parent", "student_ids": [child1["id"]], "label": "Parent de Jean",
        }, headers=h)
        self.assertEqual(inv.status_code, 201)
        token = inv.get_json()["token"]

        # Un visiteur non authentifié peut consulter ce que l'invitation autorise —
        # jamais plus (pas de recherche libre dans tout l'établissement).
        lookup = self.client.get(f"/api/invitations/lookup?token={token}")
        self.assertEqual(lookup.status_code, 200)
        body = lookup.get_json()
        self.assertEqual(body["role"], "parent")
        self.assertEqual([s["id"] for s in body["students"]], [child1["id"]])

        accept = self.client.post("/api/invitations/accept", json={
            "token": token, "name": "Parent Kabeya", "email": "parent.kabeya@test.test", "password": "Secret123!",
        })
        self.assertEqual(accept.status_code, 201)
        self.assertEqual(accept.get_json()["role"], "parent")
        h_parent = self._auth(accept.get_json()["token"])

        students = self.client.get("/api/students", headers=h_parent).get_json()
        self.assertEqual([s["id"] for s in students], [child1["id"]])  # jamais other_child

        # Le token a été consommé : impossible de le réutiliser (usage unique)
        replay = self.client.post("/api/invitations/accept", json={
            "token": token, "name": "Quelqu'un d'autre", "email": "autre@test.test", "password": "Secret123!",
        })
        self.assertEqual(replay.status_code, 404)

    def test_12_invitation_role_cannot_be_chosen_by_client(self):
        """Le rôle vient toujours de l'invitation créée par le directeur — jamais
        d'un champ envoyé par la personne qui accepte (docs point 14)."""
        director = self._register_school("dir12@invite.test", "École Rôles")
        h = self._auth(director["token"])
        inv = self.client.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()

        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Faux Directeur", "email": "prof12@invite.test",
            "password": "Secret123!", "role": "directeur",  # tentative d'injection de rôle, doit être ignorée
        })
        self.assertEqual(accept.get_json()["role"], "professeur")

    def test_13_excel_import_engine_creates_real_students_and_payments(self):
        """Le moteur d'import (backend/ingestion.py) doit détecter les colonnes,
        signaler une anomalie financière réelle, puis créer des données réelles
        seulement après confirmation explicite — rien n'est écrit à l'analyse."""
        director = self._register_school("dir13@import.test", "École Import")
        h = self._auth(director["token"])

        csv_content = (
            "Nom complet,Classe,Téléphone parent,Parent,Frais,Payé\n"
            "Kabeya Jean,6e A,+243812345678,Marie Kabeya,250,150\n"
            "Ilunga Sarah,6e A,+243898765432,Paul Ilunga,250,400\n"  # anomalie : payé > dû
        )
        data = {"file": (io.BytesIO(csv_content.encode("utf-8")), "eleves.csv")}
        analyze = self.client.post("/api/onboarding/analyze-import", data=data,
                                    content_type="multipart/form-data", headers=h)
        self.assertEqual(analyze.status_code, 200, analyze.get_data(as_text=True))
        analysis = analyze.get_json()
        self.assertEqual(analysis["students_count"], 2)
        self.assertTrue(any(a["field"] == "finance" for a in analysis["anomalies"]))

        # Rien n'a encore été écrit en base à ce stade
        self.assertEqual(self.client.get("/api/students", headers=h).get_json(), [])

        # La confirmation rejoue l'analyse côté serveur : on transmet son
        # identifiant, plus la liste d'enregistrements (voir DEPLOIEMENT.md).
        confirm = self.client.post("/api/onboarding/confirm-import", json={
            "import_session_id": analysis["import_session_id"], "school_name": "École Import",
        }, headers=h)
        self.assertEqual(confirm.status_code, 200, confirm.get_data(as_text=True))
        result = confirm.get_json()
        self.assertEqual(result["students_count"], 2)

        students = self.client.get("/api/students", headers=h).get_json()
        self.assertEqual(len(students), 2)
        jean = next(s for s in students if s["first_name"] == "Jean")
        self.assertEqual(jean["balance"], 100)  # 250 dû - 150 payé, jamais un chiffre brut

    def test_14_xlsx_import_ignores_non_data_sheet_even_if_active(self):
        """Bug réel signalé : un classeur .xlsx avec une feuille 'Lisez-moi' (texte
        libre) enregistrée comme feuille active devant la feuille de données
        faisait analyser 0 élève, puis échouer 'aucun renseignement importé' à
        la confirmation — alors que l'analyse avait pourtant 'réussi'. La cause
        était `wb.active` : ce flag reflète la feuille affichée à l'enregistrement,
        pas celle qui contient des données exploitables."""
        import openpyxl
        director = self._register_school("dir14@import.test", "École Feuilles")
        h = self._auth(director["token"])

        wb = openpyxl.Workbook()
        readme = wb.active
        readme.title = "Lisez-moi"
        readme["A1"] = "Ceci est un export réel, avec quelques imperfections volontaires."
        readme["A2"] = "Rien de tout cela n'a été corrigé avant l'export."
        data_sheet = wb.create_sheet("Élèves")
        data_sheet.append(["Nom complet", "Classe", "Téléphone parent", "Parent", "Frais", "Payé"])
        data_sheet.append(["Kabeya Jean", "6e A", "+243812345678", "Marie Kabeya", 250, 250])
        # `wb.active` reste la première feuille créée ("Lisez-moi") — c'est
        # exactement le cas réel signalé, on ne le force pas artificiellement.
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        data = {"file": (buf, "export_ecole.xlsx")}
        analyze = self.client.post("/api/onboarding/analyze-import", data=data,
                                    content_type="multipart/form-data", headers=h)
        self.assertEqual(analyze.status_code, 200, analyze.get_data(as_text=True))
        analysis = analyze.get_json()
        self.assertEqual(analysis["students_count"], 1)  # pas 0 : la bonne feuille a été choisie

        confirm = self.client.post("/api/onboarding/confirm-import", json={
            "import_session_id": analysis["import_session_id"], "school_name": "École Feuilles",
        }, headers=h)
        self.assertEqual(confirm.status_code, 200, confirm.get_data(as_text=True))
        self.assertEqual(confirm.get_json()["students_count"], 1)

    def test_15_import_analysis_rejects_file_with_no_exploitable_rows(self):
        """Un fichier sans colonne élève reconnaissable doit échouer clairement
        à l'ANALYSE, pas silencieusement réussir puis échouer à la confirmation
        sans explication (le bug exact signalé par l'utilisateur)."""
        director = self._register_school("dir15@import.test", "École Fichier Invalide")
        h = self._auth(director["token"])
        csv_content = "Une colonne quelconque,Une autre\nvaleur,valeur\n"
        data = {"file": (io.BytesIO(csv_content.encode("utf-8")), "invalide.csv")}
        analyze = self.client.post("/api/onboarding/analyze-import", data=data,
                                    content_type="multipart/form-data", headers=h)
        self.assertEqual(analyze.status_code, 400)
        self.assertIn("error", analyze.get_json())

    def _setup_ai_school(self, prefix):
        """École avec 2 classes, 3 élèves, un impayé et un paiement confirmé ce
        mois-ci — assez de données réelles pour tester l'assistant IA."""
        director = self._register_school(f"dir-{prefix}@ai.test", f"École IA {prefix}")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        cls_a = self.client.post("/api/classes", json={"academic_year_id": year_id, "name": "6e A"}, headers=h).get_json()
        item = self.client.post("/api/catalog-items", json={"name": "Frais scolaires", "amount": 250, "currency": "USD"}, headers=h).get_json()

        jean = self.client.post("/api/students", json={
            "academic_year_id": year_id, "class_id": cls_a["id"], "first_name": "Jean", "last_name": "Kabeya",
        }, headers=h).get_json()
        sarah = self.client.post("/api/students", json={
            "academic_year_id": year_id, "class_id": cls_a["id"], "first_name": "Sarah", "last_name": "Mbuyi",
        }, headers=h).get_json()

        ob_jean = self.client.post("/api/obligations", json={
            "student_id": jean["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()
        ob_sarah = self.client.post("/api/obligations", json={
            "student_id": sarah["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()
        # Jean paie intégralement (cash = confirmé immédiatement) ; Sarah ne paie rien.
        self.client.post("/api/payments", json={
            "obligation_id": ob_jean["id"], "amount": 250, "method": "cash", "idempotency_key": f"{prefix}-pay-1",
        }, headers=h)
        return {"h": h, "director": director, "jean": jean, "sarah": sarah, "class": cls_a}

    def test_16_ai_answers_real_read_questions(self):
        """L'assistant IA doit répondre avec de VRAIES données calculées, pas des
        valeurs inventées — mêmes chiffres que les endpoints classiques."""
        ctx = self._setup_ai_school("ai16")
        h = ctx["h"]

        r = self.client.post("/api/ai/ask", json={"message": "Combien d'élèves sont actuellement enregistrés ?"}, headers=h)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("2", body["text"])
        self.assertEqual(body["intent"], "count_students")
        self.assertIsNotNone(body["conversation_id"])

        r = self.client.post("/api/ai/ask", json={"message": "Combien avons-nous encaissé ce mois-ci ?"}, headers=h)
        self.assertEqual(r.get_json()["intent"], "collected_this_month")
        self.assertIn("250", r.get_json()["text"])

        r = self.client.post("/api/ai/ask", json={"message": "Quels sont les plus gros impayés ?"}, headers=h)
        body = r.get_json()
        self.assertEqual(body["intent"], "biggest_unpaid")
        self.assertTrue(any("Mbuyi" in row[0] for row in body["rich"]["rows"]))
        self.assertFalse(any("Kabeya" in row[0] for row in body["rich"]["rows"]))  # Jean a tout payé

        r = self.client.post("/api/ai/ask", json={"message": "Montre-moi les élèves de 6e A."}, headers=h)
        body = r.get_json()
        self.assertEqual(body["intent"], "students_by_class")
        self.assertEqual(len(body["rich"]["rows"]), 2)

    def test_17_ai_never_executes_write_operations(self):
        """Garde-fou architectural : toute intention d'écriture doit être refusée,
        jamais exécutée — et le refus doit être journalisé dans l'audit."""
        ctx = self._setup_ai_school("ai17")
        h = ctx["h"]
        before_count = len(self.client.get("/api/students", headers=h).get_json())

        refusals = [
            "Crée un nouvel élève.",
            "Supprime cet élève.",
            "Enregistre ce paiement.",
            "Envoie un rappel de paiement à tous les parents.",
            "Modifie les frais de cet élève.",
            # L'abonnement Klassio est lui aussi hors de portée de l'assistant :
            # c'est le circuit commercial de l'établissement, pas une donnée
            # scolaire — et surtout pas les frais payés par les familles.
            "Passe l'abonnement en payé.",
        ]
        for message in refusals:
            r = self.client.post("/api/ai/ask", json={"message": message}, headers=h)
            body = r.get_json()
            self.assertTrue(body["refused"], f"'{message}' aurait dû être refusé, intent={body['intent']}")

        after_count = len(self.client.get("/api/students", headers=h).get_json())
        self.assertEqual(before_count, after_count)  # rien n'a été créé ni supprimé

        # Symétrie : refuser une écriture ne doit pas rendre le mot lui-même
        # tabou. Une question de lecture sur l'abonnement reste une question.
        lecture = self.client.post("/api/ai/ask", json={
            "message": "Quel est mon abonnement Klassio ?"}, headers=h).get_json()
        self.assertFalse(lecture["refused"], "une question de lecture ne doit pas être refusée")

        logs = self.client.get("/api/audit-logs", headers=h).get_json()
        self.assertTrue(any(l["action"] == "ai.ask" and l["status"] == "denied" for l in logs))

    def test_17bis_la_recherche_de_l_ia_reste_dans_le_perimetre_du_role(self):
        """« Trouve X » ne doit renvoyer que des élèves que le rôle voit déjà.

        Trouvé le 20/09. Toutes les lectures de ai_assistant.py passent par
        `school.students_where_clause()` — SAUF `search_students()`, qui ne
        filtrait que sur `tenant_id`. C'était justement celle qui prend un nom
        en entrée.

        Mesuré sur la base de charge : un professeur dont le périmètre comptait
        67 élèves sur 400 demandait « trouve Esther » et recevait dix résultats,
        dont SEPT hors de ses classes, avec leur nom et leur classe. Pas une
        fuite entre établissements — le tenant tenait — mais une fuite entre
        RÔLES dans la même école, c'est-à-dire la promesse centrale du produit.

        Le test vérifie les deux sens : le professeur ne voit que sa classe, et
        la Direction continue de tout voir. Un filtre qui casserait la Direction
        serait une régression, pas un correctif.
        """
        ctx = self._setup_ai_school("ai17b")
        h = ctx["h"]
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]

        # Une seconde classe, avec une élève au prénom identique à celle de la
        # première : c'est le cas qui piège une recherche par nom.
        autre = self.client.post("/api/classes", json={
            "academic_year_id": year_id, "name": "5e B"}, headers=h).get_json()
        cachee = self.client.post("/api/students", json={
            "academic_year_id": year_id, "class_id": autre["id"],
            "first_name": "Sarah", "last_name": "Ilunga"}, headers=h).get_json()

        # Un professeur titulaire de la PREMIÈRE classe uniquement.
        inv = self.client.post("/api/invitations", json={
            "role": "professeur", "class_ids": [ctx["class"]["id"]]}, headers=h).get_json()
        prof = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof Titulaire",
            "email": "prof17b@ai.test", "password": "Secret123!"}).get_json()
        h_prof = self._auth(prof["token"])

        visibles = {s["id"] for s in self.client.get("/api/students", headers=h_prof).get_json()}
        self.assertNotIn(cachee["id"], visibles,
                         "le décor est faux : ce professeur voit déjà l'autre classe")

        r = self.client.post("/api/ai/ask", json={"message": "trouve Sarah"}, headers=h_prof).get_json()
        lignes = (r.get("rich") or {}).get("rows") or []
        noms = [l[0] for l in lignes]
        self.assertNotIn("Sarah Ilunga", noms,
                         "l'IA a livré au professeur une élève hors de son périmètre")
        self.assertIn("Sarah Mbuyi", noms, "l'IA ne trouve plus sa propre élève")

        # Contre-épreuve : la Direction voit bien les deux.
        rd = self.client.post("/api/ai/ask", json={"message": "trouve Sarah"}, headers=h).get_json()
        noms_dir = [l[0] for l in ((rd.get("rich") or {}).get("rows") or [])]
        self.assertIn("Sarah Ilunga", noms_dir, "le filtre a aussi aveuglé la Direction")
        self.assertIn("Sarah Mbuyi", noms_dir)

    def test_18_ai_respects_role_permissions_no_cross_role_leak(self):
        """Un parent ne doit jamais obtenir par l'IA une donnée globale qu'il ne
        pourrait pas consulter en naviguant lui-même dans Klassio — et il doit
        obtenir la situation réelle de son propre enfant."""
        ctx = self._setup_ai_school("ai18")
        h = ctx["h"]

        inv = self.client.post("/api/invitations", json={
            "role": "parent", "student_ids": [ctx["jean"]["id"]],
        }, headers=h).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent Kabeya", "email": "parent18@ai.test", "password": "Secret123!",
        })
        h_parent = self._auth(accept.get_json()["token"])

        # Refusé : donnée financière globale de l'établissement.
        r = self.client.post("/api/ai/ask", json={"message": "Combien avons-nous encaissé ce mois-ci ?"}, headers=h_parent)
        body = r.get_json()
        self.assertIn("pas accès", body["text"])
        self.assertNotIn("250", body["text"])

        # Autorisé : solde de son propre enfant, avec la vraie valeur (0, déjà payé).
        r = self.client.post("/api/ai/ask", json={"message": "Que reste-t-il à payer pour Jean ?"}, headers=h_parent)
        body = r.get_json()
        self.assertEqual(body["intent"], "child_balance")
        self.assertIn("0,00", body["text"])

        # Un professeur n'a pas non plus accès aux données financières.
        inv_prof = self.client.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()
        accept_prof = self.client.post("/api/invitations/accept", json={
            "token": inv_prof["token"], "name": "Prof Test", "email": "prof18@ai.test", "password": "Secret123!",
        })
        h_prof = self._auth(accept_prof.get_json()["token"])
        r = self.client.post("/api/ai/ask", json={"message": "Quelle est la situation financière de l'établissement ?"}, headers=h_prof)
        self.assertIn("pas accès", r.get_json()["text"])

    def test_19_ai_conversation_history_isolated_per_user_and_tenant(self):
        """L'historique de conversation doit être strictement isolé — un autre
        utilisateur (même un autre directeur) ne doit jamais y accéder."""
        ctx1 = self._setup_ai_school("ai19a")
        ctx2 = self._setup_ai_school("ai19b")

        r = self.client.post("/api/ai/ask", json={"message": "Combien avons-nous de classes ?"}, headers=ctx1["h"])
        conv_id = r.get_json()["conversation_id"]

        listing = self.client.get("/api/ai/conversations", headers=ctx1["h"]).get_json()
        self.assertTrue(any(c["id"] == conv_id for c in listing))

        # Le directeur de l'autre établissement ne voit ni la conversation, ni ses messages.
        other_listing = self.client.get("/api/ai/conversations", headers=ctx2["h"]).get_json()
        self.assertFalse(any(c["id"] == conv_id for c in other_listing))
        denied = self.client.get(f"/api/ai/conversations/{conv_id}/messages", headers=ctx2["h"])
        self.assertEqual(denied.status_code, 404)

        messages = self.client.get(f"/api/ai/conversations/{conv_id}/messages", headers=ctx1["h"]).get_json()
        self.assertEqual(len(messages), 2)  # question + réponse
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")

    def test_20_ai_fallback_never_invents_an_answer(self):
        """Une question hors périmètre doit obtenir un aveu honnête, jamais une
        réponse fabriquée (docs point 17 — pas d'hallucination)."""
        ctx = self._setup_ai_school("ai20")
        r = self.client.post("/api/ai/ask", json={"message": "Quelle est la météo à Kinshasa aujourd'hui ?"}, headers=ctx["h"])
        body = r.get_json()
        self.assertEqual(body["intent"], "fallback")
        self.assertIn("pas suffisamment d'informations", body["text"])

    def test_21_reports_summary_matches_real_data(self):
        """/api/reports/summary doit renvoyer les mêmes chiffres réels que
        l'assistant IA et le reste de l'API — pas une vue indépendante inventée."""
        ctx = self._setup_ai_school("rep21")
        r = self.client.get("/api/reports/summary", headers=ctx["h"])
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["financial"]["total_paid"], 250)
        self.assertEqual(body["financial"]["total_due"], 500)
        self.assertEqual(body["collection_rate"], 50)
        self.assertEqual(body["students_without_payment_count"], 1)
        self.assertTrue(any(row["last_name"] == "Mbuyi" for row in body["biggest_unpaid"]))

        # Un professeur n'a pas accès aux rapports (pas de obligations.read/payments.read).
        inv = self.client.post("/api/invitations", json={"role": "professeur"}, headers=ctx["h"]).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof Rapports", "email": "prof21@ai.test", "password": "Secret123!",
        })
        h_prof = self._auth(accept.get_json()["token"])
        denied = self.client.get("/api/reports/summary", headers=h_prof)
        self.assertEqual(denied.status_code, 403)

    # ------------------------------------------------------------------
    # Le MONTANT se décide côté serveur (audit du 17/09)
    # ------------------------------------------------------------------

    def _ecole_avec_frais(self, email, nom_ecole, montant=150):
        """Une école, un élève, un frais et son obligation — socle des tests
        de montant ci-dessous."""
        director = self._register_school(email, nom_ecole)
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        cls = self.client.post("/api/classes", json={"academic_year_id": year_id, "name": "6e A"}, headers=h).get_json()
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "class_id": cls["id"], "first_name": "Grâce", "last_name": "Kabila",
        }, headers=h).get_json()
        item = self.client.post("/api/catalog-items", json={
            "name": "Frais scolaires", "category": "frais", "amount": montant, "currency": "USD",
        }, headers=h).get_json()
        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()
        return {"h": h, "year_id": year_id, "student": student, "item": item,
                "obligation": obligation, "director": director}

    def test_20bis_le_wifi_de_l_ecole_ne_bloque_pas_les_parents(self):
        """Vingt parents s'inscrivent depuis la MÊME adresse IP, et passent.

        Trouvé le 18/09 pendant la campagne k6. L'acceptation d'une invitation
        est plafonnée à 10 tentatives par 5 minutes et par adresse IP — une
        protection juste : un jeton d'invitation est un secret, et sans plafond
        on l'énumère. Mais le plafond comptait TOUTES les tentatives, réussies
        comprises. Or les parents d'une école congolaise acceptent leur
        invitation depuis le wifi de l'établissement : ils partagent une seule
        adresse. Le jour de la rentrée, le onzième parent était refusé parce
        que dix voisins avaient réussi avant lui. La protection frappait
        exactement les gens qu'elle devait servir.

        La règle est désormais celle de la connexion : seul un ÉCHEC SUR LE
        SECRET consomme le budget, une réussite efface l'ardoise. Le plafond
        n'a pas bougé d'un cran.
        """
        security.reset_rate_limits_for_tests()
        director = self._register_school("dir20b@rentree.test", "École Rentrée")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        cls = self.client.post("/api/classes", json={
            "academic_year_id": year_id, "name": "6e A"}, headers=h).get_json()

        # Deux fois le plafond : si les réussites comptaient, ça casserait à 11.
        for i in range(20):
            eleve = self.client.post("/api/students", json={
                "academic_year_id": year_id, "class_id": cls["id"],
                "first_name": "Élève", "last_name": f"Rentree{i}",
            }, headers=h).get_json()
            inv = self.client.post("/api/invitations", json={
                "role": "parent", "student_ids": [eleve["id"]],
            }, headers=h).get_json()
            # Le parent ouvre d'abord son lien, puis crée son compte : les deux
            # routes sont plafonnées, les deux doivent le laisser passer.
            vu = self.client.get(f"/api/invitations/lookup?token={inv['token']}")
            self.assertEqual(vu.status_code, 200, f"parent {i} : lien illisible ({vu.get_json()})")
            r = self.client.post("/api/invitations/accept", json={
                "token": inv["token"], "name": f"Parent {i}",
                "email": f"parent{i}@rentree.test", "password": "Secret123!",
            })
            self.assertEqual(r.status_code, 201,
                             f"le parent {i} a été refusé depuis le wifi de l'école : {r.get_json()}")

    def test_20ter_l_enumeration_de_jetons_reste_coupee(self):
        """L'autre moitié de la règle : deviner des jetons coûte toujours.

        Sans ce test, « ne plus compter les réussites » pourrait se dégrader en
        « ne plus rien compter ». Ici personne ne réussit : chaque tentative
        porte un jeton inventé, et la protection doit mordre au onzième.
        """
        security.reset_rate_limits_for_tests()
        refuse = None
        for i in range(15):
            r = self.client.post("/api/invitations/accept", json={
                "token": f"jeton-invente-{i}" + "0" * 40, "name": "Intrus",
                "email": f"intrus{i}@attaque.test", "password": "Secret123!",
            })
            if r.status_code == 429:
                refuse = i
                break
            self.assertEqual(r.status_code, 404, f"tentative {i} : {r.get_json()}")
        self.assertIsNotNone(refuse, "15 jetons inventés d'affilée n'ont jamais été bloqués")
        self.assertLessEqual(refuse, 11,
                             f"la coupure est arrivée trop tard (tentative {refuse})")

        # Et un jeton RÉEL présenté deux fois ne compte pas comme une
        # énumération : son porteur l'a bien reçu.
        security.reset_rate_limits_for_tests()
        director = self._register_school("dir20t@enum.test", "École Énumération")
        h = self._auth(director["token"])
        inv = self.client.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()
        self.assertEqual(self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof", "email": "prof20t@enum.test",
            "password": "Secret123!"}).status_code, 201)
        for _ in range(14):
            r = self.client.post("/api/invitations/accept", json={
                "token": inv["token"], "name": "Prof", "email": "autre20t@enum.test",
                "password": "Secret123!"})
            self.assertEqual(r.status_code, 404,
                             "un lien déjà utilisé ne doit pas consommer le budget anti-énumération")

    def test_20quater_quelques_liens_cassés_ne_bloquent_pas_toute_l_ecole(self):
        """Le cas mixte, celui qui arrive vraiment le jour de la rentrée.

        Sur le wifi de l'école, quelques liens sont réellement invalides — un
        lien tronqué par WhatsApp, un copier-coller incomplet. Ces tentatives-là
        DOIVENT compter : de l'extérieur, elles ressemblent à une énumération.
        Mais si elles s'accumulent sans jamais s'effacer, une poignée de liens
        cassés finit par bloquer tous les parents suivants.

        D'où la seconde moitié de la règle : une activation réussie efface
        l'ardoise de l'adresse. Une inscription qui aboutit prouve que cette
        adresse n'énumère pas.
        """
        security.reset_rate_limits_for_tests()
        director = self._register_school("dir20q@mixte.test", "École Mixte")
        h = self._auth(director["token"])

        def parent_reel(n):
            inv = self.client.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()
            return self.client.post("/api/invitations/accept", json={
                "token": inv["token"], "name": f"Prof {n}",
                "email": f"prof20q{n}@mixte.test", "password": "Secret123!"})

        def lien_casse(n):
            return self.client.post("/api/invitations/accept", json={
                "token": f"lien-tronque-{n}" + "0" * 40, "name": "Parent",
                "email": f"casse20q{n}@mixte.test", "password": "Secret123!"})

        for i in range(8):
            self.assertEqual(lien_casse(i).status_code, 404)
        self.assertEqual(parent_reel(1).status_code, 201, "le 9e arrivant est bloqué par 8 liens cassés")

        # Huit de plus : sans effacement, on serait à 16 et la coupure aurait eu lieu.
        for i in range(8, 16):
            self.assertEqual(lien_casse(i).status_code, 404,
                             "l'ardoise n'a pas été effacée par l'inscription réussie")
        self.assertEqual(parent_reel(2).status_code, 201,
                         "une poignée de liens cassés a bloqué toute l'école")

    def test_21ter_montant_superieur_au_reste_du_refuse(self):
        """Un montant supérieur à la dette réelle est refusé PAR LE SERVEUR.

        Le formulaire portait un `max` HTML, et rien d'autre. En modifiant le
        JSON, on envoyait 999 999 $ sur une obligation qui en devait 150 ; le
        serveur l'acceptait. Une fois la demande confirmée par l'établissement,
        le solde devenait négatif, un REÇU OFFICIEL de 999 999 $ était émis et
        le grand livre enregistrait la somme : un document faux et une
        comptabilité fausse, à partir d'un champ de formulaire.
        """
        ctx = self._ecole_avec_frais("dir21t@montant.test", "École Montant")
        ob = ctx["obligation"]

        excessif = self.client.post("/api/payments", json={
            "obligation_id": ob["id"], "amount": 999999, "method": "cash", "idempotency_key": "excessif-1",
        }, headers=ctx["h"])
        self.assertEqual(excessif.status_code, 400, "un montant hors dette a été accepté")
        self.assertIn("dépasse", excessif.get_json()["error"])

        # Rien n'a été écrit : ni paiement, ni solde entamé, ni reçu.
        resume = self.client.get(f"/api/students/{ctx['student']['id']}/financial-summary", headers=ctx["h"]).get_json()
        self.assertEqual(resume["total_paid"], 0)
        self.assertEqual(resume["balance"], 150)
        self.assertEqual(self.client.get("/api/receipts", headers=ctx["h"]).get_json(), [])

    def test_21quater_paiement_partiel_reste_possible(self):
        """Le contrôle porte sur le RESTE DÛ, pas sur le montant de l'obligation.

        Deux paiements partiels doivent passer ; un troisième qui ferait
        dépasser la dette doit être refusé. Sans cette nuance, la correction du
        montant aurait interdit les paiements échelonnés — c'est-à-dire la
        manière dont les familles paient réellement.
        """
        ctx = self._ecole_avec_frais("dir21q@partiel.test", "École Partiel")
        ob, h = ctx["obligation"], ctx["h"]

        for i, montant in enumerate((60, 50), start=1):
            r = self.client.post("/api/payments", json={
                "obligation_id": ob["id"], "amount": montant, "method": "cash", "idempotency_key": f"partiel-{i}",
            }, headers=h)
            self.assertEqual(r.status_code, 201, f"le paiement partiel de {montant} a été refusé")

        resume = self.client.get(f"/api/students/{ctx['student']['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(resume["total_paid"], 110)
        self.assertEqual(resume["balance"], 40)

        trop = self.client.post("/api/payments", json={
            "obligation_id": ob["id"], "amount": 41, "method": "cash", "idempotency_key": "partiel-3",
        }, headers=h)
        self.assertEqual(trop.status_code, 400, "un dépassement cumulé a été accepté")

        # Le solde exact passe, au centime près.
        exact = self.client.post("/api/payments", json={
            "obligation_id": ob["id"], "amount": 40, "method": "cash", "idempotency_key": "partiel-4",
        }, headers=h)
        self.assertEqual(exact.status_code, 201)
        resume = self.client.get(f"/api/students/{ctx['student']['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(resume["balance"], 0)

        # Une obligation soldée n'accepte plus rien.
        apres = self.client.post("/api/payments", json={
            "obligation_id": ob["id"], "amount": 1, "method": "cash", "idempotency_key": "partiel-5",
        }, headers=h)
        self.assertEqual(apres.status_code, 400)
        self.assertIn("déjà entièrement payée", apres.get_json()["error"])

    def test_21sexies_deux_guichets_ne_peuvent_pas_encaisser_deux_fois_le_solde(self):
        """La course entre deux guichets, rendue déterministe.

        Trouvée le 18/09 par tools/k6/concurrence.js : six guichets soldant
        ensemble le même frais avaient encaissé 1 046 $ sur une dette de 350 $,
        en sept paiements tous CONFIRMED et tous pourvus d'un reçu officiel.

        Le contrôle de montant existait déjà — mais uniquement à la CRÉATION du
        paiement, et il ne compare qu'aux paiements CONFIRMÉS. Deux intentions
        créées avant toute confirmation passent donc toutes les deux. Rejouer la
        course ici ne demande aucun parallélisme : il suffit de créer les deux
        intentions d'abord, puis de les confirmer l'une après l'autre.

        La seconde confirmation doit être REFUSÉE, et l'établissement ne doit
        jamais avoir encaissé plus que ce qui était dû.
        """
        ctx = self._ecole_avec_frais("dir21s@course.test", "École Course")
        ob, h, eleve = ctx["obligation"], ctx["h"], ctx["student"]

        resume = self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()
        reste = resume["balance"]
        self.assertGreater(reste, 0, "le décor du test ne laisse rien à devoir")

        # Deux intentions Mobile Money pour LA TOTALITÉ du reste. Les deux sont
        # légitimes à cet instant : aucune n'est encore confirmée.
        intentions = []
        for i in (1, 2):
            r = self.client.post("/api/payments", json={
                "obligation_id": ob["id"], "amount": reste, "method": "mobile_money",
                "idempotency_key": f"course-guichet-{i}",
            }, headers=h)
            self.assertEqual(r.status_code, 201, f"l'intention {i} a été refusée à la création")
            intentions.append(r.get_json()["id"])

        premier = self.client.post(f"/api/payments/{intentions[0]}/confirm",
                                   json={"provider_reference": "MM-1"}, headers=h)
        self.assertEqual(premier.status_code, 200)
        self.assertTrue(premier.get_json()["receipt_number"], "le premier paiement doit produire un reçu")

        second = self.client.post(f"/api/payments/{intentions[1]}/confirm",
                                  json={"provider_reference": "MM-2"}, headers=h)
        self.assertEqual(second.status_code, 400,
                         "le second guichet a encaissé un solde déjà payé")
        self.assertIn("entièrement payé", second.get_json()["error"])

        # La preuve par l'argent, pas par le code HTTP.
        final = self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(final["balance"], 0, "le frais doit être soldé, ni plus ni moins")
        self.assertEqual(final["total_paid"], resume["total_paid"] + reste,
                         "l'établissement a encaissé plus que ce qui était dû")

        # Et le refus n'a pas fabriqué de reçu : un seul reçu pour ce frais.
        recus = self.client.get("/api/receipts", headers=h).get_json()
        pour_cet_eleve = [r for r in recus if r.get("student_id") == eleve["id"]]
        self.assertEqual(len(pour_cet_eleve), 1,
                         "un second reçu a été émis pour de l'argent jamais encaissé")

    def test_21quinquies_parent_ne_paie_que_ses_enfants(self):
        """Un parent ne peut ni payer, ni lire le reçu d'un élève qui n'est pas
        le sien — y compris dans son propre établissement.

        Le lien parent → enfant est résolu par le serveur
        (`school.resolve_student_access`) ; `student_id` et `obligation_id`
        envoyés par le navigateur ne sont que des prétentions.
        """
        ctx = self._ecole_avec_frais("dir21p@perimetre.test", "École Périmètre")
        h = ctx["h"]

        # Un second élève, étranger au parent.
        autre = self.client.post("/api/students", json={
            "academic_year_id": ctx["year_id"], "first_name": "Josué", "last_name": "Mwamba",
        }, headers=h).get_json()
        ob_autre = self.client.post("/api/obligations", json={
            "student_id": autre["id"], "academic_year_id": ctx["year_id"], "catalog_item_id": ctx["item"]["id"],
        }, headers=h).get_json()
        paiement_autre = self.client.post("/api/payments", json={
            "obligation_id": ob_autre["id"], "amount": 10, "method": "cash", "idempotency_key": "autre-1",
        }, headers=h).get_json()

        # Un parent rattaché au PREMIER élève seulement.
        inv = self.client.post("/api/invitations", json={
            "role": "parent", "student_ids": [ctx["student"]["id"]],
        }, headers=h).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent Périmètre", "email": "parent21p@perimetre.test",
            "password": "Secret123!",
        })
        h_parent = self._auth(accept.get_json()["token"])

        # Payer l'obligation de l'autre élève : introuvable.
        refus = self.client.post("/api/payments", json={
            "obligation_id": ob_autre["id"], "amount": 10, "method": "mobile_money",
            "idempotency_key": "idor-1",
        }, headers=h_parent)
        self.assertEqual(refus.status_code, 404)

        # Lire son reçu : introuvable aussi.
        recu = self.client.get("/api/receipts", headers=h).get_json()
        recu_autre = [r for r in recu if r["student_id"] == autre["id"]]
        self.assertTrue(recu_autre, "le paiement cash de l'autre élève aurait dû produire un reçu")
        self.assertEqual(
            self.client.get(f"/api/receipts/{recu_autre[0]['id']}", headers=h_parent).status_code, 404)

        # Et sa propre liste ne contient que son enfant.
        siens = self.client.get("/api/receipts", headers=h_parent).get_json()
        self.assertTrue(all(r["student_id"] == ctx["student"]["id"] for r in siens))
        self.assertNotIn(paiement_autre["id"], [r.get("payment_id") for r in siens])

    def test_21sexies_echeancier_la_somme_est_verifiee_par_le_serveur(self):
        """Un frais réparti en tranches : la somme est contrôlée côté SERVEUR,
        et l'écriture est tout ou rien.

        L'écran vérifiait la somme, et lui seul. Un client modifié créait trois
        tranches de 100 pour un frais de 1 000 : la dette de l'élève devenait
        300 sans que rien ne proteste. Et en N appels séparés, la troisième
        tranche pouvait échouer après l'écriture des deux premières, laissant un
        échéancier incomplet en base.
        """
        ctx = self._ecole_avec_frais("dir21s@echeancier.test", "École Échéancier", montant=1000)
        h, eleve = ctx["h"], ctx["student"]

        # Somme fausse : refusée, et RIEN n'est écrit.
        avant = len(self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()["obligations"])
        faux = self.client.post("/api/obligations/schedule", json={
            "student_id": eleve["id"], "catalog_item_id": ctx["item"]["id"],
            "academic_year_id": ctx["year_id"], "total": 1000,
            "installments": [{"amount": 100}, {"amount": 100}, {"amount": 100}],
        }, headers=h)
        self.assertEqual(faux.status_code, 400, "une somme de tranches fausse a été acceptée")
        self.assertIn("somme des tranches", faux.get_json()["error"].lower())
        apres = len(self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()["obligations"])
        self.assertEqual(apres, avant, "des tranches ont été écrites malgré le refus")

        # Une tranche invalide au milieu : rien n'est écrit non plus.
        partiel = self.client.post("/api/obligations/schedule", json={
            "student_id": eleve["id"], "catalog_item_id": ctx["item"]["id"],
            "academic_year_id": ctx["year_id"], "total": 1000,
            "installments": [{"amount": 500}, {"amount": -500}, {"amount": 1000}],
        }, headers=h)
        self.assertEqual(partiel.status_code, 400)
        apres = len(self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()["obligations"])
        self.assertEqual(apres, avant, "une tranche a survécu à un échéancier refusé")

        # Répartition correcte, y compris le centime qui ne tombe pas juste.
        bon = self.client.post("/api/obligations/schedule", json={
            "student_id": eleve["id"], "catalog_item_id": ctx["item"]["id"],
            "academic_year_id": ctx["year_id"], "total": 1000,
            "installments": [
                {"amount": 333.33, "due_date": "2026-10-05"},
                {"amount": 333.33, "due_date": "2026-12-05"},
                {"amount": 333.34, "due_date": "2027-02-05"},
            ],
        }, headers=h)
        self.assertEqual(bon.status_code, 201, bon.get_data(as_text=True))
        self.assertEqual(bon.get_json()["count"], 3)

        resume = self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()
        # 1000 de l'obligation du socle + 1000 d'échéancier.
        self.assertEqual(resume["total_due"], 2000)
        tranches = [o for o in resume["obligations"] if o["due_date"]]
        self.assertEqual(len(tranches), 3)
        self.assertEqual(round(sum(o["amount"] for o in tranches), 2), 1000)
        # Les tranches partagent la clé du frais : c'est elle qui les regroupe.
        self.assertEqual(len({o["catalog_item_id"] for o in tranches}), 1)

    def test_21septies_echeancier_reserve_a_la_direction(self):
        """Créer un échéancier est un acte de Direction — pas de parent."""
        ctx = self._ecole_avec_frais("dir21x@echperm.test", "École Échéancier Perm")
        h = ctx["h"]
        inv = self.client.post("/api/invitations", json={
            "role": "parent", "student_ids": [ctx["student"]["id"]],
        }, headers=h).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent Éch", "email": "parent21x@echperm.test",
            "password": "Secret123!",
        })
        h_parent = self._auth(accept.get_json()["token"])
        refus = self.client.post("/api/obligations/schedule", json={
            "student_id": ctx["student"]["id"], "catalog_item_id": ctx["item"]["id"],
            "academic_year_id": ctx["year_id"], "installments": [{"amount": 1}],
        }, headers=h_parent)
        self.assertEqual(refus.status_code, 403)

    # ------------------------------------------------------------------
    # Révocation d'accès (prompt du 17/09)
    # ------------------------------------------------------------------

    def _ecole_avec_parent_accepte(self, email_dir, nom_ecole, email_parent):
        """Une école, un élève, un parent QUI A ACCEPTÉ son invitation et
        dispose d'une session ouverte."""
        director = self._register_school(email_dir, nom_ecole)
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        eleve = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Grâce", "last_name": "Kabila",
        }, headers=h).get_json()
        inv = self.client.post("/api/invitations", json={
            "role": "parent", "student_ids": [eleve["id"]],
        }, headers=h).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent Révoc", "email": email_parent, "password": "Secret123!",
        })
        self.assertEqual(accept.status_code, 201, accept.get_data(as_text=True))
        h_parent = self._auth(accept.get_json()["token"])
        # L'accès fonctionne AVANT toute révocation — sinon le test ne prouve rien.
        self.assertEqual(self.client.get("/api/me", headers=h_parent).status_code, 200)
        return {"h": h, "h_parent": h_parent, "inv": inv, "eleve": eleve,
                "director": director, "year_id": year_id}

    def test_23_revocation_invitation_en_attente(self):
        """Une invitation en attente révoquée : son lien devient inutilisable."""
        director = self._register_school("dir23@revoc.test", "École Révoc A")
        h = self._auth(director["token"])
        inv = self.client.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()

        r = self.client.post(f"/api/invitations/{inv['id']}/revoke", json={}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["previous_status"], "pending")

        # Le lien ne crée plus aucun compte.
        refus = self.client.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Trop Tard", "email": "troptard@revoc.test", "password": "Secret123!",
        })
        self.assertNotEqual(refus.status_code, 201, "un lien révoqué a encore créé un compte")

        # L'invitation reste en base, marquée — jamais supprimée.
        liste = self.client.get("/api/invitations", headers=h).get_json()
        ligne = [i for i in liste if i["id"] == inv["id"]]
        self.assertTrue(ligne, "l'invitation a disparu de l'historique")
        self.assertEqual(ligne[0]["status"], "revoked")
        self.assertIsNotNone(ligne[0]["revoked_at"])

    def test_24_revocation_invitation_acceptee_coupe_vraiment_l_acces(self):
        """LE point essentiel : révoquer une invitation DÉJÀ ACCEPTÉE doit
        couper l'accès pour de vrai, pas seulement changer un texte.

        Avant correctif, la route se contentait de réécrire le statut : le
        parent gardait son compte, sa session et l'accès au dossier de l'enfant.
        """
        ctx = self._ecole_avec_parent_accepte("dir24@revoc.test", "École Révoc B", "parent24@revoc.test")

        r = self.client.post(f"/api/invitations/{ctx['inv']['id']}/revoke",
                             json={"reason": "Invitation envoyée au mauvais parent."}, headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertEqual(corps["previous_status"], "accepted")
        self.assertTrue(corps["access_revoked"], "le membership n'a pas été révoqué")

        # La session ouverte ne vaut plus rien, immédiatement.
        self.assertEqual(self.client.get("/api/me", headers=ctx["h_parent"]).status_code, 401)
        self.assertEqual(self.client.get("/api/students", headers=ctx["h_parent"]).status_code, 401)
        self.assertEqual(self.client.get("/api/dashboard", headers=ctx["h_parent"]).status_code, 401)

        # Et il ne peut pas se reconnecter : le membership n'est plus actif.
        relogin = self.client.post("/api/auth/login", json={
            "identifier": "parent24@revoc.test", "password": "Secret123!",
        })
        self.assertNotEqual(relogin.status_code, 200, "un accès révoqué se rouvre par simple reconnexion")

    def test_25_revocation_ne_detruit_aucune_donnee_metier(self):
        """Révoquer coupe un accès ; cela ne supprime ni l'élève, ni son
        dossier, ni ce qui lui est rattaché."""
        ctx = self._ecole_avec_parent_accepte("dir25@revoc.test", "École Révoc C", "parent25@revoc.test")
        h, eleve = ctx["h"], ctx["eleve"]

        item = self.client.post("/api/catalog-items", json={
            "name": "Frais", "category": "frais", "amount": 100, "currency": "USD"}, headers=h).get_json()
        ob = self.client.post("/api/obligations", json={
            "student_id": eleve["id"], "academic_year_id": ctx["year_id"], "catalog_item_id": item["id"],
        }, headers=h).get_json()
        self.client.post("/api/payments", json={
            "obligation_id": ob["id"], "amount": 40, "method": "cash", "idempotency_key": "revoc-1",
        }, headers=h)

        self.client.post(f"/api/invitations/{ctx['inv']['id']}/revoke", json={}, headers=ctx["h"])

        # L'élève, sa dette, son paiement et son reçu sont intacts côté école.
        self.assertEqual(self.client.get(f"/api/students/{eleve['id']}", headers=h).status_code, 200)
        resume = self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(resume["total_due"], 100)
        self.assertEqual(resume["total_paid"], 40)
        self.assertEqual(len(self.client.get("/api/receipts", headers=h).get_json()), 1)

    def test_26_revocation_securite_et_isolation(self):
        """Qui peut révoquer, et sur quoi."""
        a = self._ecole_avec_parent_accepte("dir26a@revoc.test", "École Révoc D", "parent26a@revoc.test")
        b = self._register_school("dir26b@revoc.test", "École Révoc E")
        h_b = self._auth(b["token"])

        # Une autre école ne voit pas cette invitation : 404, jamais 403 nuancé.
        self.assertEqual(
            self.client.post(f"/api/invitations/{a['inv']['id']}/revoke", json={}, headers=h_b).status_code, 404)

        # Un professeur de la MÊME école n'a pas la permission.
        inv_prof = self.client.post("/api/invitations", json={"role": "professeur"}, headers=a["h"]).get_json()
        accept = self.client.post("/api/invitations/accept", json={
            "token": inv_prof["token"], "name": "Prof 26", "email": "prof26@revoc.test", "password": "Secret123!",
        })
        h_prof = self._auth(accept.get_json()["token"])
        self.assertEqual(
            self.client.post(f"/api/invitations/{a['inv']['id']}/revoke", json={}, headers=h_prof).status_code, 403)

        # Le parent lui-même encore moins.
        self.assertEqual(
            self.client.post(f"/api/invitations/{a['inv']['id']}/revoke", json={}, headers=a["h_parent"]).status_code, 403)

        # Révoquer deux fois est idempotent et ne réécrit pas la date.
        r1 = self.client.post(f"/api/invitations/{a['inv']['id']}/revoke", json={}, headers=a["h"]).get_json()
        date1 = [i for i in self.client.get("/api/invitations", headers=a["h"]).get_json()
                 if i["id"] == a["inv"]["id"]][0]["revoked_at"]
        r2 = self.client.post(f"/api/invitations/{a['inv']['id']}/revoke", json={}, headers=a["h"]).get_json()
        date2 = [i for i in self.client.get("/api/invitations", headers=a["h"]).get_json()
                 if i["id"] == a["inv"]["id"]][0]["revoked_at"]
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertTrue(r2.get("already"))
        self.assertEqual(date1, date2, "la seconde révocation a réécrit la date d'origine")

    def test_27_la_direction_ne_se_revoque_pas_par_ce_chemin(self):
        """Une école qui perd son dernier accès Direction devient
        inadministrable : personne ne peut plus rien y rouvrir."""
        director = self._register_school("dir27@revoc.test", "École Révoc F")
        h = self._auth(director["token"])
        # On fabrique une invitation acceptée par un directeur en la rattachant
        # à la main : le produit n'offre pas ce chemin, la garde doit tenir
        # quand même.
        inv = self.client.post("/api/invitations", json={"role": "professeur"}, headers=h).get_json()
        conn = db.get_connection()
        conn.execute("UPDATE invitations SET status='accepted', accepted_user_id=? WHERE id=?",
                     (director["user_id"] if "user_id" in director else
                      conn.execute("SELECT user_id FROM memberships WHERE tenant_id=? AND role='directeur'",
                                   (director["tenant_id"],)).fetchone()["user_id"], inv["id"]))
        conn.commit()
        conn.close()

        r = self.client.post(f"/api/invitations/{inv['id']}/revoke", json={}, headers=h)
        self.assertEqual(r.status_code, 409)
        # Et la Direction garde son accès.
        self.assertEqual(self.client.get("/api/me", headers=h).status_code, 200)

    # ------------------------------------------------------------------
    # Contact public et suppression de compte (prompt du 17/09)
    # ------------------------------------------------------------------

    def test_28_contact_public_valide_et_limite(self):
        """La seule route d'écriture sans compte : validée et limitée."""
        bon = self.client.post("/api/public/contact", json={
            "name": "Jean Kabila", "email": "jean@example.test",
            "subject": "Question sur les invitations",
            "message": "Bonjour, comment inviter un professeur dans mon établissement ?",
        })
        self.assertEqual(bon.status_code, 201, bon.get_data(as_text=True))
        # La réponse ne dit RIEN sur l'existence d'un compte derrière l'adresse.
        self.assertNotIn("compte", bon.get_json().get("message", "").lower())

        for corps, raison in (
            ({"name": "", "email": "a@b.test", "subject": "S", "message": "assez long pour passer"}, "nom vide"),
            ({"name": "A", "email": "pasunemail", "subject": "S", "message": "assez long pour passer"}, "email invalide"),
            ({"name": "A", "email": "a@b.test", "subject": "S", "message": "court"}, "message trop court"),
        ):
            r = self.client.post("/api/public/contact", json=corps)
            self.assertEqual(r.status_code, 400, f"{raison} : accepté à tort")

        # Limite de débit : 5 par heure, le 6e est refusé.
        for i in range(5):
            self.client.post("/api/public/contact", json={
                "name": "Spam", "email": "s@b.test", "subject": "S" + str(i),
                "message": "message suffisamment long pour être accepté",
            })
        trop = self.client.post("/api/public/contact", json={
            "name": "Spam", "email": "s@b.test", "subject": "encore",
            "message": "message suffisamment long pour être accepté",
        })
        self.assertEqual(trop.status_code, 429, "le formulaire public n'est pas limité")

        # Et la lecture est réservée à l'administration Klassio.
        director = self._register_school("dir28@contact.test", "École Contact")
        self.assertEqual(
            self.client.get("/api/platform/contact-requests", headers=self._auth(director["token"])).status_code, 403)

    def test_29_suppression_de_compte_conserve_les_donnees_de_l_ecole(self):
        """Supprimer SON compte n'efface ni l'élève, ni le reçu, ni l'audit."""
        ctx = self._ecole_avec_parent_accepte("dir29@suppr.test", "École Suppr", "parent29@suppr.test")
        h, h_parent, eleve = ctx["h"], ctx["h_parent"], ctx["eleve"]

        item = self.client.post("/api/catalog-items", json={
            "name": "Frais", "category": "frais", "amount": 100, "currency": "USD"}, headers=h).get_json()
        ob = self.client.post("/api/obligations", json={
            "student_id": eleve["id"], "academic_year_id": ctx["year_id"], "catalog_item_id": item["id"],
        }, headers=h).get_json()
        self.client.post("/api/payments", json={
            "obligation_id": ob["id"], "amount": 30, "method": "cash", "idempotency_key": "suppr-1",
        }, headers=h)

        # Mauvais mot de passe : refusé.
        self.assertEqual(self.client.post("/api/me/delete", json={"password": "FAUX"}, headers=h_parent).status_code, 401)
        # Sans mot de passe non plus.
        self.assertEqual(self.client.post("/api/me/delete", json={}, headers=h_parent).status_code, 400)

        r = self.client.post("/api/me/delete", json={"password": "Secret123!"}, headers=h_parent)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        # Le compte ne vaut plus rien.
        self.assertEqual(self.client.get("/api/me", headers=h_parent).status_code, 401)
        self.assertNotEqual(self.client.post("/api/auth/login", json={
            "identifier": "parent29@suppr.test", "password": "Secret123!"}).status_code, 200)

        # L'école, elle, a tout gardé.
        self.assertEqual(self.client.get(f"/api/students/{eleve['id']}", headers=h).status_code, 200)
        resume = self.client.get(f"/api/students/{eleve['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(resume["total_paid"], 30)
        self.assertEqual(len(self.client.get("/api/receipts", headers=h).get_json()), 1)

    def test_30_derniere_direction_ne_peut_pas_se_supprimer(self):
        """Une école sans Direction deviendrait inadministrable."""
        director = self._register_school("dir30@suppr.test", "École Dernière Direction")
        h = self._auth(director["token"])
        r = self.client.post("/api/me/delete", json={"password": "Secret123!"}, headers=h)
        self.assertEqual(r.status_code, 409)
        self.assertIn("seule Direction", r.get_json()["error"])
        # Et l'accès est intact.
        self.assertEqual(self.client.get("/api/me", headers=h).status_code, 200)

    def test_21bis_catalogue_ferme_au_professeur_et_au_dd(self):
        """Le catalogue des frais est de l'argent : il suit `store.read`.

        La Direction et les parents le lisent — les parents en ont besoin pour
        la Boutique. Le professeur et le Directeur des disciplines, non : leur
        accès financier est fermé, et une grille tarifaire complète n'est pas
        une exception à cette règle.
        """
        director = self._register_school("dir21b@catalogue.test", "École Catalogue")
        h = self._auth(director["token"])
        self.client.post("/api/catalog-items", json={
            "name": "Frais de scolarité", "category": "scolarité", "amount": 150, "currency": "USD",
        }, headers=h)

        # La Direction lit son catalogue.
        self.assertEqual(self.client.get("/api/catalog-items", headers=h).status_code, 200)

        for role, email in (("professeur", "prof21b@catalogue.test"), ("discipline", "dd21b@catalogue.test")):
            inv = self.client.post("/api/invitations", json={"role": role}, headers=h).get_json()
            accept = self.client.post("/api/invitations/accept", json={
                "token": inv["token"], "name": "Membre " + role, "email": email, "password": "Secret123!",
            })
            h_membre = self._auth(accept.get_json()["token"])
            refus = self.client.get("/api/catalog-items", headers=h_membre)
            self.assertEqual(refus.status_code, 403,
                             f"le rôle {role} lit encore la grille tarifaire de l'établissement")

    def test_22_password_change_requires_correct_current_password(self):
        """Changer de mot de passe doit vérifier l'ancien mot de passe et exiger
        que le nouveau respecte les mêmes règles de sécurité réelles."""
        director = self._register_school("dir22@pwd.test", "École Mot de Passe")
        h = self._auth(director["token"])

        wrong = self.client.post("/api/me/password", json={
            "current_password": "MauvaisMotDePasse1!", "new_password": "Nouveau123!",
        }, headers=h)
        self.assertEqual(wrong.status_code, 401)

        weak = self.client.post("/api/me/password", json={
            "current_password": "Secret123!", "new_password": "faible",
        }, headers=h)
        self.assertEqual(weak.status_code, 400)

        ok = self.client.post("/api/me/password", json={
            "current_password": "Secret123!", "new_password": "Nouveau123!",
        }, headers=h)
        self.assertEqual(ok.status_code, 200)

        # L'ancien mot de passe ne fonctionne plus, le nouveau fonctionne.
        old_login = self.client.post("/api/auth/login", json={"email": "dir22@pwd.test", "password": "Secret123!"})
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post("/api/auth/login", json={"email": "dir22@pwd.test", "password": "Nouveau123!"})
        self.assertEqual(new_login.status_code, 200)

        # Audit de sécurité — Conclusion #2 : le token émis AVANT le
        # changement de mot de passe doit être révoqué, pas seulement le mot
        # de passe changé. Un nouveau token doit être fourni pour l'onglet courant.
        self.assertIn("token", ok.get_json())
        self.assertNotEqual(ok.get_json()["token"], director["token"])
        stale = self.client.get("/api/me", headers=h)
        self.assertEqual(stale.status_code, 401)
        fresh = self.client.get("/api/me", headers=self._auth(ok.get_json()["token"]))
        self.assertEqual(fresh.status_code, 200)

    def test_23_session_token_never_stored_in_cleartext(self):
        """Audit de sécurité — Conclusion #3 : seul le hash SHA-256 du token de
        session doit exister en base, jamais le token brut renvoyé au client."""
        director = self._register_school("dir23@sec.test", "École Sécurité Session")
        conn = db.get_connection()
        row = conn.execute("SELECT token FROM sessions WHERE token = ?", (director["token"],)).fetchone()
        conn.close()
        self.assertIsNone(row, "le token brut ne doit jamais se retrouver tel quel dans sessions.token")
        # Le token reste bien utilisable via l'API normale (le hash est vérifié côté serveur).
        self.assertEqual(self.client.get("/api/me", headers=self._auth(director["token"])).status_code, 200)

    def test_24_dead_users_route_removed(self):
        """Audit de sécurité — Conclusion #4 : la route qui permettait de créer
        un compte (y compris rôle 'eleve', interdit par le produit) en
        contournant le modèle d'invitation obligatoire a été retirée."""
        director = self._register_school("dir24@sec.test", "École Route Morte")
        h = self._auth(director["token"])
        resp = self.client.post("/api/users", json={
            "email": "fantome24@sec.test", "password": "Secret123!", "name": "Fantôme", "role": "eleve",
        }, headers=h)
        # 405 (pas 404) : le chemin /api/<path> reste reconnu par le
        # catch-all CORS (OPTIONS uniquement) — POST n'y est plus autorisé.
        self.assertEqual(resp.status_code, 405)
        conn = db.get_connection()
        ghost = conn.execute("SELECT id FROM users WHERE email='fantome24@sec.test'").fetchone()
        conn.close()
        self.assertIsNone(ghost)

    def test_25_import_rejects_negative_or_invalid_amounts(self):
        """Audit de sécurité — Conclusion #1 : un montant négatif ou non
        numérique ne doit jamais fabriquer une dette.

        Ce test visait à l'origine un envoi DIRECT à confirm-import, sans
        fichier. Ce vecteur n'existe plus : la route ne lit que les
        enregistrements issus de l'analyse (session d'import). L'invariant, lui,
        est inchangé — il est donc vérifié aux deux endroits où il peut encore
        être mis en défaut : par un vrai fichier passant par l'analyse, et
        directement sur le moteur d'ingestion.
        """
        director = self._register_school("dir25@sec.test", "École Montants")
        h = self._auth(director["token"])

        def importer(csv_content):
            data = {"file": (io.BytesIO(csv_content.encode("utf-8")), "montants.csv")}
            a = self.client.post("/api/onboarding/analyze-import", data=data,
                                 content_type="multipart/form-data", headers=h)
            if a.status_code != 200:
                return a
            return self.client.post("/api/onboarding/confirm-import", json={
                "import_session_id": a.get_json()["import_session_id"],
                "school_name": "École Montants"}, headers=h)

        # 1. Par le fichier : un montant négatif ne crée aucun élève.
        negative = importer("Nom,Prenom,Classe,Frais,Paye\nIntentionne,Mal,6e A,-999999,0\n")
        self.assertNotEqual(negative.status_code, 200, negative.get_data(as_text=True))
        self.assertFalse(any(s["last_name"] == "Intentionne"
                             for s in self.client.get("/api/students", headers=h).get_json()))

        # 2. Directement sur le moteur, là où la validation vit réellement.
        import ingestion
        conn = db.get_connection()
        try:
            for mauvais in (-999999, "PAS_UN_NOMBRE", float("inf")):
                with self.assertRaises(Exception, msg=f"fee_amount={mauvais!r} accepté"):
                    ingestion.bootstrap_school(conn, director["tenant_id"], None, {
                        "school_name": "École Montants", "academic_year": "2026",
                        "records": [{"first_name": "Encore", "last_name": "Invalide",
                                     "class_name": "6e A", "fee_amount": mauvais, "paid_amount": 0}]})
        finally:
            conn.close()
        self.assertFalse(any(s["last_name"] == "Invalide"
                             for s in self.client.get("/api/students", headers=h).get_json()))

        # 3. Un import légitime continue de fonctionner normalement.
        valid = importer("Nom,Prenom,Classe,Frais,Paye\nEleve,Bon,6e A,250,100\n")
        self.assertEqual(valid.status_code, 200, valid.get_data(as_text=True))
        self.assertEqual(valid.get_json()["students_count"], 1)

    def test_27_idempotency_replay_cannot_auto_confirm_mobile_money(self):
        """Un paiement mobile_money CREATED ne doit jamais passer à CONFIRMED
        parce qu'un second POST réutilise la même clé avec method=cash.
        La confirmation auto cash/banque doit suivre la méthode stockée, pas
        celle du JSON rejoué — sinon le solde est crédité sans preuve."""
        director = self._register_school("dir27@idem.test", "École Idempotence Méthode")
        h = self._auth(director["token"])
        year_id = self.client.get("/api/academic-years", headers=h).get_json()[0]["id"]
        student = self.client.post("/api/students", json={
            "academic_year_id": year_id, "first_name": "Lina", "last_name": "Mwamba",
        }, headers=h).get_json()
        item = self.client.post("/api/catalog-items", json={
            "name": "Frais", "amount": 100, "currency": "USD",
        }, headers=h).get_json()
        obligation = self.client.post("/api/obligations", json={
            "student_id": student["id"], "academic_year_id": year_id, "catalog_item_id": item["id"],
        }, headers=h).get_json()

        first = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 100, "method": "mobile_money",
            "idempotency_key": "mm-then-cash",
        }, headers=h)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.get_json()["status"], "CREATED")

        replay = self.client.post("/api/payments", json={
            "obligation_id": obligation["id"], "amount": 100, "method": "cash",
            "idempotency_key": "mm-then-cash",
        }, headers=h)
        self.assertEqual(replay.status_code, 400)

        summary = self.client.get(f"/api/students/{student['id']}/financial-summary", headers=h).get_json()
        self.assertEqual(summary["total_paid"], 0)
        self.assertEqual(summary["balance"], 100)
        self.assertEqual(summary["obligations"][0]["payments"], [])
        self.assertEqual(summary["obligations"][0]["status"], "ISSUED")

    def test_26_public_endpoints_rate_limited(self):
        """Audit de sécurité — Conclusion #6 : register-school et les routes
        d'invitation publiques doivent ralentir un abus, pas uniquement le login."""
        for i in range(5):
            self.client.post("/api/auth/register-school", json={
                "email": f"flood{i}@sec.test", "password": "Secret123!", "name": "X", "school_name": "Y",
            })
        blocked = self.client.post("/api/auth/register-school", json={
            "email": "flood-extra@sec.test", "password": "Secret123!", "name": "X", "school_name": "Y",
        })
        self.assertEqual(blocked.status_code, 429)


if __name__ == "__main__":
    unittest.main()
