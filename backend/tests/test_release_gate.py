"""KLASSIO — balayage d'isolation inter-établissements sur TOUTES les routes.

Les tests existants vérifient l'isolation sur les parcours qu'ils exercent.
Ce fichier ne choisit pas : il énumère les 63 routes paramétrées depuis
`app.url_map`, remplace chaque identifiant par celui d'un AUTRE établissement,
et exige que le serveur refuse. Une route ajoutée demain sans contrôle de
périmètre fera échouer ce test sans que personne n'ait à y penser.

Le principe testé est celui de docs/MULTI_TENANT.md : le `tenant_id` vient de
la session serveur, jamais du client. Un identifiant appartenant à
l'établissement A, présenté par un utilisateur de l'établissement B, doit être
traité comme inexistant.
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402

TODAY = date.today().isoformat()

# Routes publiques par conception : elles n'ont pas de session, donc pas de
# périmètre à franchir. Elles sont vérifiées séparément (test_90).
ROUTES_PUBLIQUES = {"/api/portal/<slug>", "/api/<path:_any>"}

# Nom du paramètre d'URL -> table où lire un identifiant réel de l'établissement A.
TABLE_PAR_PARAMETRE = {
    "student_id": "students",
    "class_id": "classes",
    "incident_id": "incidents",
    "resource_id": "resources",
    "doc_id": "school_documents",
    "event_id": "calendar_events",
    "exam_id": "exams",
    "receipt_id": "receipts",
    "payment_id": "payments",
    "order_id": "orders",
    "product_id": "store_products",
    "invoice_id": "invoices",
    "period_id": "academic_periods",
    "import_id": "result_imports",
    "report_id": "incident_reports",
    "rule_id": "discipline_rules",
    "slot_id": "schedule_slots",
    "jid": "attendance_justifications",
    "notification_id": "notifications",
    "invitation_id": "invitations",
    "year_id": "academic_years",
    "conversation_id": "ai_conversations",
    "conv_id": "ai_conversations",
    "tenant_id": "tenants",
    "payment_id": "payments",
    "receipt_id": "receipts",
}


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


def _inviter(c, dir_h, role, email, name, student_ids=None, class_ids=None, titulaire_class_id=None):
    inv = c.post("/api/invitations", json={"role": role, "student_ids": student_ids,
                                           "class_ids": class_ids, "titulaire_class_id": titulaire_class_id},
                 headers=dir_h)
    assert inv.status_code == 201, inv.get_data(as_text=True)
    acc = c.post("/api/invitations/accept", json={"token": inv.get_json()["token"], "name": name,
                                                  "email": email, "password": "Secret123!"})
    assert acc.status_code == 201, acc.get_data(as_text=True)
    return {"Authorization": "Bearer " + acc.get_json()["token"]}


class IsolationInterEtablissementsTests(unittest.TestCase):
    """Établissement A richement peuplé, établissement B minimal.
    Aucun utilisateur de B ne doit jamais atteindre une donnée de A."""

    @classmethod
    def setUpClass(cls):
        cls.client = c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

        # ---------- Établissement A : le plus complet possible ----------
        r = c.post("/api/auth/register-school", json={"email": "dir@alpha.test", "password": "Secret123!",
                                                      "name": "Alice Directrice", "school_name": "École Alpha"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.a_dir = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.a_tenant = r.get_json()["tenant_id"]
        an = c.get("/api/academic-years", headers=cls.a_dir).get_json()[0]["id"]

        klass = c.post("/api/classes", json={"name": "6e A", "level": "6e", "academic_year_id": an},
                       headers=cls.a_dir).get_json()
        eleve = c.post("/api/students", json={"first_name": "Kevin", "last_name": "Mbala",
                                              "academic_year_id": an, "class_id": klass["id"]},
                       headers=cls.a_dir).get_json()
        cls.a_eleve, cls.a_classe = eleve, klass

        cls.a_prof = _inviter(c, cls.a_dir, "professeur", "prof@alpha.test", "Paul Prof",
                              class_ids=[klass["id"]], titulaire_class_id=klass["id"])
        cls.a_dd = _inviter(c, cls.a_dir, "discipline", "dd@alpha.test", "Didier Discipline")
        cls.a_parent = _inviter(c, cls.a_dir, "parent", "parent@alpha.test", "Jean Mbala",
                                student_ids=[eleve["id"]])

        # Finance : obligation, paiement confirmé, reçu
        item = c.post("/api/catalog-items", json={"name": "Frais", "amount": 300, "currency": "USD"},
                      headers=cls.a_dir).get_json()
        obl = c.post("/api/obligations", json={"student_id": eleve["id"], "catalog_item_id": item["id"],
                                               "academic_year_id": an}, headers=cls.a_dir).get_json()
        # Paiement cash : confirmé immédiatement, donc il produit aussi un reçu.
        # (Ce POST échouait silencieusement avant que le montage ne vérifie les
        # codes de retour — la clé d'idempotence est devenue obligatoire.)
        pay = c.post("/api/payments", json={"obligation_id": obl["id"], "amount": 300, "currency": "USD",
                                            "method": "cash", "idempotency_key": "gate-pay-1"},
                     headers=cls.a_dir)
        assert pay.status_code == 201, f"montage paiement : {pay.status_code} {pay.get_data(as_text=True)[:200]}"
        cls.a_obligation = obl["id"]
        # Vie scolaire
        c.post("/api/attendance", json={"class_id": klass["id"], "date": TODAY,
                                        "entries": [{"student_id": eleve["id"], "status": "absent"}]},
               headers=cls.a_prof)
        c.post("/api/incidents", json={"student_id": eleve["id"], "title": "Bagarre",
                                       "category": "violence", "severity": "grave", "points": -20,
                                       "occurred_at": TODAY}, headers=cls.a_dd)
        c.post("/api/calendar/events", json={"title": "Réunion", "starts_on": TODAY}, headers=cls.a_dir)
        c.post(f"/api/messages/{eleve['id']}", json={"body": "Bonjour"}, headers=cls.a_parent)
        c.post("/api/ai/ask", json={"message": "Combien d'élèves ?"}, headers=cls.a_dir)

        # Ressources supplémentaires : plus l'établissement A est peuplé, plus
        # le balayage couvre de routes. Chaque création est vérifiée — une
        # création silencieusement ratée réduirait la couverture sans le dire.
        def creer(nom, methode, chemin, corps, entetes, attendu=201):
            r = c.open(chemin, method=methode, headers=entetes, json=corps)
            assert r.status_code == attendu, f"montage {nom} : {r.status_code} {r.get_data(as_text=True)[:200]}"
            return r.get_json()

        creer("incident", "POST", "/api/incidents",
              {"student_id": eleve["id"], "title": "Bagarre", "category": "comportement",
               "severity": "high", "points": -20, "occurred_at": TODAY}, cls.a_dir)
        creer("periodes", "POST", "/api/periods", {"preset": "standard"}, cls.a_dir)
        creer("produit", "POST", "/api/store/products",
              {"name": "Cahier", "price": 5, "currency": "USD", "category": "fournitures",
               "stock": 10}, cls.a_dir)
        creer("creneau", "POST", f"/api/classes/{klass['id']}/schedule",
              {"weekday": 1, "start_time": "08:00", "end_time": "09:00", "subject": "Maths"}, cls.a_dir)
        creer("examen", "POST", f"/api/classes/{klass['id']}/exams",
              {"subject": "Maths", "date": TODAY, "title": "Interro"}, cls.a_dir)
        creer("regle", "POST", "/api/discipline/rules",
              {"label": "Retard", "category": "retard", "points": -2}, cls.a_dir)
        creer("ressource", "POST", "/api/resources",
              {"class_id": klass["id"], "kind": "lecon", "title": "Chapitre 1"}, cls.a_prof)
        creer("signalement", "POST", "/api/incident-reports",
              {"student_id": eleve["id"], "description": "Comportement à qualifier",
               "occurred_at": TODAY}, cls.a_prof)
        creer("invitation", "POST", "/api/invitations", {"role": "professeur"}, cls.a_dir)
        # Un PDF minimal mais réel, pour couvrir les routes de document/fichier.
        pdf = ("data:application/pdf;base64,JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+"
               "PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDAvS2lkc1tdPj4KZW5kb2JqCnRyYWlsZXIKPDwvUm9vdCAxIDAgUj4+Cg==")
        creer("document", "POST", "/api/documents",
              {"kind": "reglement", "title": "Règlement intérieur", "visible_to": "tous",
               "file_name": "reglement.pdf", "file_data": pdf}, cls.a_dir)
        creer("justification", "POST", f"/api/students/{eleve['id']}/justifications",
              {"date": TODAY, "reason": "Maladie"}, cls.a_parent)
        # Une session d'import de résultats, pour que le balayage d'isolation
        # puisse aussi viser /api/results/imports/<import_id>. Sans elle, ces
        # routes restaient hors du filet automatique.
        periodes = c.get("/api/periods", headers=cls.a_dir).get_json()["periods"]
        if not periodes:
            c.post("/api/periods", json={"label": "Période 1", "sort": 0}, headers=cls.a_dir)
            periodes = c.get("/api/periods", headers=cls.a_dir).get_json()["periods"]
        import io as _io
        csv_resultats = ("Identifiant,Matiere,Periode,Resultat,Bareme\n"
                         f"{eleve['code']},Mathématiques,{periodes[0]['label']},14,20\n")
        c.post("/api/results/imports",
               data={"file": (_io.BytesIO(csv_resultats.encode()), "resultats.csv"),
                     "period_id": periodes[0]["id"]},
               content_type="multipart/form-data", headers=cls.a_dir)

        produits = c.get("/api/store/products", headers=cls.a_parent).get_json()
        creer("commande", "POST", "/api/store/orders",
              {"student_id": eleve["id"],
               "items": [{"product_id": produits[0]["id"], "quantity": 1}]}, cls.a_parent)

        # ---------- Établissement B : minimal, l'attaquant ----------
        r = c.post("/api/auth/register-school", json={"email": "dir@beta.test", "password": "Secret123!",
                                                      "name": "Bruno Directeur", "school_name": "École Beta"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.b_dir = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.b_tenant = r.get_json()["tenant_id"]
        bn = c.get("/api/academic-years", headers=cls.b_dir).get_json()[0]["id"]
        bklass = c.post("/api/classes", json={"name": "1e B", "level": "1e", "academic_year_id": bn},
                        headers=cls.b_dir).get_json()
        beleve = c.post("/api/students", json={"first_name": "Sarah", "last_name": "Beta",
                                               "academic_year_id": bn, "class_id": bklass["id"]},
                        headers=cls.b_dir).get_json()
        cls.b_parent = _inviter(c, cls.b_dir, "parent", "parent@beta.test", "Grace Beta",
                                student_ids=[beleve["id"]])

        cls.identifiants_a = cls._identifiants_de(cls.a_tenant)
        cls.identifiants_a["tenant_id"] = cls.a_tenant

    @classmethod
    def _identifiants_de(cls, tenant_id):
        """Un identifiant réel par table, pour l'établissement donné.

        Lu directement en base : c'est plus complet et plus honnête que de se
        limiter aux objets que les tests savent créer par l'API.
        """
        trouves, conn = {}, db.get_connection()
        try:
            for parametre, table in TABLE_PAR_PARAMETRE.items():
                if table == "tenants":
                    continue
                colonne_tenant = "id" if table == "tenants" else "tenant_id"
                try:
                    ligne = conn.execute(
                        f"SELECT id FROM {table} WHERE {colonne_tenant}=? LIMIT 1", (tenant_id,)
                    ).fetchone()
                except Exception:
                    ligne = None
                if ligne:
                    trouves[parametre] = ligne["id"]
        finally:
            conn.close()
        # user_id : un membre de l'établissement A
        conn = db.get_connection()
        try:
            ligne = conn.execute("SELECT user_id FROM memberships WHERE tenant_id=? AND role='professeur' LIMIT 1",
                                 (tenant_id,)).fetchone()
        finally:
            conn.close()
        if ligne:
            trouves["user_id"] = ligne["user_id"]
        return trouves

    def setUp(self):
        security.reset_rate_limits_for_tests()

    # ------------------------------------------------------------------
    # Le balayage
    # ------------------------------------------------------------------
    def _balayer(self, entetes, nom_role):
        """Appelle chaque route paramétrée avec les identifiants de A.
        Retourne (fuites, non_couvertes, testees)."""
        fuites, non_couvertes, testees = [], [], 0
        for regle in flask_app_module.app.url_map.iter_rules():
            if not regle.arguments or regle.rule in ROUTES_PUBLIQUES:
                continue
            valeurs, manquant = {}, False
            for argument in regle.arguments:
                if argument in self.identifiants_a:
                    valeurs[argument] = self.identifiants_a[argument]
                else:
                    manquant = True
            if manquant:
                non_couvertes.append((regle.rule, sorted(a for a in regle.arguments
                                                         if a not in self.identifiants_a)))
                continue
            chemin = regle.rule
            for cle, valeur in valeurs.items():
                for gabarit in (f"<{cle}>", f"<int:{cle}>", f"<string:{cle}>", f"<path:{cle}>"):
                    chemin = chemin.replace(gabarit, str(valeur))
            for methode in sorted(regle.methods & {"GET", "POST", "PUT", "DELETE", "PATCH"}):
                testees += 1
                reponse = self.client.open(chemin, method=methode, headers=entetes, json={})
                if reponse.status_code < 400:
                    fuites.append(f"{nom_role}: {methode} {regle.rule} -> {reponse.status_code} "
                                  f"{reponse.get_data(as_text=True)[:120]}")
        return fuites, non_couvertes, testees

    def test_01_direction_de_B_ne_touche_aucune_ressource_de_A(self):
        fuites, non_couvertes, testees = self._balayer(self.b_dir, "directeur B")
        parametrees = sum(1 for r in flask_app_module.app.url_map.iter_rules()
                          if r.arguments and r.rule not in ROUTES_PUBLIQUES)
        couvertes = parametrees - len(non_couvertes)
        print(f"\n  [balayage] {couvertes}/{parametrees} routes paramétrées couvertes, "
              f"{testees} appels inter-établissements")
        if non_couvertes:
            # Trace honnête : ce que ce test ne prouve PAS.
            print("  [balayage] NON COUVERTES faute d'identifiant de test :")
            for rule, args in sorted(non_couvertes):
                print(f"      {rule}  (paramètres : {', '.join(args)})")
        self.assertEqual(fuites, [], "\n".join(fuites))
        self.assertGreaterEqual(couvertes / parametrees, 0.75,
                                "couverture du balayage trop faible pour conclure")

    def test_02_parent_de_B_ne_touche_aucune_ressource_de_A(self):
        """Le parent est le rôle le plus étroit : c'est le pire cas d'un accès
        transversal réussi."""
        fuites, _, testees = self._balayer(self.b_parent, "parent B")
        self.assertGreater(testees, 40)
        self.assertEqual(fuites, [], "\n".join(fuites))

    def test_03_un_parent_de_A_ne_voit_que_son_enfant(self):
        """Le périmètre le plus étroit du produit, vérifié sur les listes."""
        eleves = self.client.get("/api/students", headers=self.a_parent).get_json()
        self.assertEqual([e["id"] for e in eleves], [self.a_eleve["id"]])

    def test_04_le_tenant_id_envoye_par_le_client_est_ignore(self):
        """Un client qui envoie le tenant_id d'un autre établissement ne doit
        pas le voir pris en compte — la session seule fait foi."""
        r = self.client.post("/api/students", json={"first_name": "Intrus", "last_name": "Test",
                                                    "tenant_id": self.a_tenant}, headers=self.b_dir)
        if r.status_code == 201:
            cree = r.get_json()
            conn = db.get_connection()
            try:
                ligne = conn.execute("SELECT tenant_id FROM students WHERE id=?", (cree["id"],)).fetchone()
            finally:
                conn.close()
            self.assertEqual(ligne["tenant_id"], self.b_tenant,
                             "le tenant_id du corps de requête a été pris en compte")

    def test_05_un_jeton_falsifie_ou_expire_est_refuse(self):
        for jeton in ("", "n-importe-quoi", "Bearer", self.a_dir["Authorization"][:-4] + "aaaa"):
            r = self.client.get("/api/students", headers={"Authorization": f"Bearer {jeton}"})
            self.assertEqual(r.status_code, 401, f"jeton accepté : {jeton!r}")

    def test_06_apres_logout_le_jeton_ne_vaut_plus_rien(self):
        r = self.client.post("/api/auth/register-school", json={"email": "jetable@gate.test",
                                                                "password": "Secret123!", "name": "Jet Able",
                                                                "school_name": "École Jetable"})
        h = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.assertEqual(self.client.get("/api/students", headers=h).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/students", headers=h).status_code, 401)

    def test_07_une_session_expiree_est_refusee_et_effacee(self):
        r = self.client.post("/api/auth/register-school", json={"email": "expire@gate.test",
                                                                "password": "Secret123!", "name": "Ex Pire",
                                                                "school_name": "École Expirée"})
        jeton = r.get_json()["token"]
        h = {"Authorization": "Bearer " + jeton}
        conn = db.get_connection()
        try:
            conn.execute("UPDATE sessions SET expires_at='0' WHERE token=?",
                         (security.hash_session_token(jeton),))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.client.get("/api/students", headers=h).status_code, 401)
        conn = db.get_connection()
        try:
            reste = conn.execute("SELECT 1 FROM sessions WHERE token=?",
                                 (security.hash_session_token(jeton),)).fetchone()
        finally:
            conn.close()
        self.assertIsNone(reste, "une session expirée doit être supprimée, pas seulement refusée")

    def test_08_un_membership_revoque_invalide_la_session_en_cours(self):
        conn = db.get_connection()
        try:
            conn.execute("UPDATE memberships SET status='revoked' WHERE tenant_id=? AND role='professeur'",
                         (self.a_tenant,))
            conn.commit()
            self.assertEqual(self.client.get("/api/students", headers=self.a_prof).status_code, 401)
        finally:
            conn.execute("UPDATE memberships SET status='active' WHERE tenant_id=? AND role='professeur'",
                         (self.a_tenant,))
            conn.commit()
            conn.close()
        self.assertEqual(self.client.get("/api/students", headers=self.a_prof).status_code, 200)

    def test_20_un_corps_incomplet_ne_produit_jamais_un_500(self):
        """Un champ obligatoire absent est une faute du client : 4xx, avec le
        nom du champ. Un 500 signifie que le serveur a planté sur une entrée
        parfaitement prévisible — et il laisse une trace dans les logs de
        production pour chaque client mal écrit."""
        substituts = {"student_id": self.a_eleve["id"], "class_id": self.a_classe["id"]}
        cinq_cents = []
        for regle in flask_app_module.app.url_map.iter_rules():
            if regle.rule.startswith("/api/auth") or "_test_" in regle.rule:
                continue
            chemin, inconnu = regle.rule, False
            for argument in regle.arguments:
                if argument in substituts:
                    chemin = chemin.replace(f"<{argument}>", substituts[argument])
                else:
                    inconnu = True
            if inconnu:
                continue
            for methode in sorted(regle.methods & {"POST", "PUT", "PATCH"}):
                reponse = self.client.open(chemin, method=methode, headers=self.a_dir, json={})
                if reponse.status_code >= 500:
                    cinq_cents.append(f"{methode} {regle.rule} -> {reponse.status_code}")
        self.assertEqual(cinq_cents, [], "\n".join(cinq_cents))

    def test_21_les_champs_obligatoires_des_routes_de_creation(self):
        """Cas que le corps vide ne révèle pas : un corps partiellement rempli
        qui passe la première validation et casse sur la seconde."""
        cas = [
            ("/api/students", {"first_name": "Sans", "last_name": "Année"}),          # academic_year_id absent
            ("/api/classes", {"name": "Sans année"}),                                  # academic_year_id absent
            ("/api/obligations", {"student_id": self.a_eleve["id"]}),                  # item et année absents
            ("/api/payments", {"obligation_id": "inexistant", "amount": 10}),          # idempotency_key absente
            (f"/api/students/{self.a_eleve['id']}/guardians", {}),                     # guardian_id absent
            ("/api/academic-years", {}),                                               # label absent
        ]
        for chemin, corps in cas:
            reponse = self.client.post(chemin, json=corps, headers=self.a_dir)
            self.assertLess(reponse.status_code, 500,
                            f"{chemin} avec {corps} -> {reponse.status_code} "
                            f"{reponse.get_data(as_text=True)[:120]}")
            self.assertGreaterEqual(reponse.status_code, 400, f"{chemin} aurait dû refuser {corps}")

    def test_22_un_paiement_sans_cle_didempotence_est_refuse(self):
        """Sans clé d'idempotence, deux clics valent deux paiements. Elle ne
        doit donc jamais être facultative."""
        conn = db.get_connection()
        try:
            obl = conn.execute("SELECT id FROM obligations WHERE tenant_id=? LIMIT 1",
                               (self.a_tenant,)).fetchone()["id"]
        finally:
            conn.close()
        r = self.client.post("/api/payments", json={"obligation_id": obl, "amount": 10, "method": "cash"},
                             headers=self.a_dir)
        self.assertEqual(r.status_code, 400)
        self.assertIn("idempotency_key", r.get_json()["error"])

    def test_30_les_routes_plateforme_sont_fermees_a_un_directeur(self):
        """`/api/platform/*` pilote la facturation de TOUS les établissements.
        Un directeur, même du sien, n'y a rien à faire. Ces routes n'ont pas de
        `tenant_id` dans leurs requêtes — c'est justement pour ça qu'elles ne
        doivent jamais s'ouvrir à autre chose qu'un administrateur plateforme."""
        ouvertes = []
        for regle in flask_app_module.app.url_map.iter_rules():
            if not regle.rule.startswith("/api/platform"):
                continue
            chemin = regle.rule
            for argument in regle.arguments:
                chemin = chemin.replace(f"<{argument}>", "peu-importe")
            for methode in sorted(regle.methods & {"GET", "POST", "PUT", "DELETE", "PATCH"}):
                for entetes, qui in ((self.a_dir, "directeur A"), (self.b_dir, "directeur B"),
                                     (self.a_parent, "parent A")):
                    r = self.client.open(chemin, method=methode, headers=entetes, json={})
                    if r.status_code != 403:
                        ouvertes.append(f"{qui}: {methode} {regle.rule} -> {r.status_code}")
        self.assertEqual(ouvertes, [], "\n".join(ouvertes))

    def test_40_une_image_ne_peut_pas_transporter_de_html(self):
        """Trouvé et exploité pendant l'audit. La validation se limitait à
        `startswith("data:image/")` : la chaîne

            data:image/png;base64,AAA" onerror="…" x="

        passait, et le frontend l'insérait telle quelle dans `<img src="…">`.
        Le guillemet refermait l'attribut ; un gestionnaire `onerror` est bien
        arrivé jusque dans le DOM d'un vrai navigateur. Seule la CSP des pages
        a empêché son exécution — une seule page servie sans CSP suffisait."""
        charges = [
            'data:image/png;base64,AAA" onerror="alert(1)" x="',
            "data:image/png;base64,AAA' onerror='alert(1)' x='",
            'data:image/svg+xml;base64,PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+',
            'javascript:alert(1)',
            'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
            'data:image/png;base64,AAA<script>alert(1)</script>',
            '<img src=x onerror=alert(1)>',
        ]
        for charge in charges:
            r = self.client.put(f"/api/students/{self.a_eleve['id']}", json={"photo_data": charge},
                                headers=self.a_dir)
            self.assertEqual(r.status_code, 400, f"photo_data accepté : {charge[:60]!r}")
            r = self.client.put("/api/settings", json={"logo_data": charge}, headers=self.a_dir)
            self.assertEqual(r.status_code, 400, f"logo_data accepté : {charge[:60]!r}")
            r = self.client.put("/api/settings", json={"cover_data": charge}, headers=self.a_dir)
            self.assertEqual(r.status_code, 400, f"cover_data accepté : {charge[:60]!r}")

    def test_41_une_vraie_image_reste_acceptee(self):
        """Le correctif ne doit pas casser l'usage normal."""
        png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
               "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        r = self.client.put(f"/api/students/{self.a_eleve['id']}", json={"photo_data": png},
                            headers=self.a_dir)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        dossier = self.client.get(f"/api/students/{self.a_eleve['id']}", headers=self.a_dir).get_json()
        self.assertEqual(dossier["student"]["photo_data"], png)
        # Et on peut la retirer.
        r = self.client.put(f"/api/students/{self.a_eleve['id']}", json={"photo_data": None},
                            headers=self.a_dir)
        self.assertEqual(r.status_code, 200)

    def test_42_un_nom_deleve_contenant_du_html_reste_du_texte(self):
        """L'autre vecteur évident : le nom, saisi librement et réaffiché
        partout. Le stockage est brut (c'est correct : c'est le rendu qui doit
        échapper), mais il ne doit jamais être interprété côté serveur."""
        r = self.client.post("/api/students",
                             json={"first_name": "<script>alert(1)</script>", "last_name": "Test",
                                   "academic_year_id": self.client.get("/api/academic-years",
                                                                       headers=self.a_dir).get_json()[0]["id"]},
                             headers=self.a_dir)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        cree = r.get_json()
        relu = self.client.get(f"/api/students/{cree['id']}", headers=self.a_dir).get_json()["student"]
        self.assertEqual(relu["first_name"], "<script>alert(1)</script>",
                         "le nom doit être conservé tel quel, ni interprété ni tronqué")
        # Le JSON renvoyé doit encoder le contenu, jamais l'injecter dans du HTML.
        liste = self.client.get("/api/students", headers=self.a_dir)
        self.assertIn("application/json", liste.headers["Content-Type"])

    def test_43_une_piece_jointe_ne_peut_pas_transporter_de_html(self):
        """Même défaut que test_40, sur les documents et pièces jointes : elles
        finissent dans un `<iframe src="…">` côté navigateur."""
        annee = self.client.get("/api/academic-years", headers=self.a_dir).get_json()[0]["id"]
        classe = self.client.post("/api/classes", json={"name": "Classe PJ", "level": "1e",
                                                        "academic_year_id": annee},
                                  headers=self.a_dir).get_json()
        charges = [
            'data:application/pdf;base64,AAA" onload="alert(1)" x="',
            'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
            'data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Pg==',
            'javascript:alert(1)',
        ]
        for charge in charges:
            r = self.client.post("/api/documents", json={"kind": "reglement", "title": "T",
                                                         "visible_to": "tous", "file_name": "x.pdf",
                                                         "file_data": charge}, headers=self.a_dir)
            self.assertEqual(r.status_code, 400, f"document accepté : {charge[:50]!r}")
            r = self.client.post("/api/resources", json={"class_id": classe["id"], "kind": "lecon",
                                                         "title": "T", "file_name": "x.pdf",
                                                         "file_data": charge}, headers=self.a_dir)
            self.assertEqual(r.status_code, 400, f"ressource acceptée : {charge[:50]!r}")

    def test_44_un_vrai_pdf_reste_accepte(self):
        pdf = ("data:application/pdf;base64,JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+"
               "PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDAvS2lkc1tdPj4KZW5kb2JqCnRyYWlsZXIKPDwvUm9vdCAxIDAgUj4+Cg==")
        r = self.client.post("/api/documents", json={"kind": "reglement", "title": "Règlement 2",
                                                     "visible_to": "tous", "file_name": "r.pdf",
                                                     "file_data": pdf}, headers=self.a_dir)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))

    def test_90_le_portail_public_ne_divulgue_que_la_vitrine(self):
        """La seule route publique qui lit des données d'un établissement."""
        conn = db.get_connection()
        try:
            slug = conn.execute("SELECT slug FROM tenants WHERE id=?", (self.a_tenant,)).fetchone()["slug"]
        finally:
            conn.close()
        corps = self.client.get(f"/api/portal/{slug}").get_data(as_text=True)
        for interdit in ("Kevin", "Mbala", self.a_eleve["id"], "parent@alpha.test", "password"):
            self.assertNotIn(interdit, corps, f"le portail public divulgue « {interdit} »")


if __name__ == "__main__":
    unittest.main()
