"""KLASSIO — trois domaines vérifiés dans leur calcul, pas seulement dans leur flux.

Les tests existants exercent les parcours : un professeur saisit une note, un
parent la voit. Ceux-ci vérifient ce que le produit CALCULE et À QUI il parle —
les endroits où une erreur ne provoque aucune exception et passe donc inaperçue.

- Discipline : les règles et les seuils sont configurables. Un capital ou un
  seuil modifié doit changer le résultat. Sinon la configuration est décorative.
- Notifications : la seule faute impardonnable est le mauvais destinataire.
- Bulletins : les cas limites (aucune note, ex æquo, barèmes mélangés) où une
  moyenne se calcule quand même, mais faux.
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


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class _Etablissement(unittest.TestCase):
    prefixe = "dom"

    @classmethod
    def setUpClass(cls):
        cls.client = c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        p = cls.prefixe
        r = c.post("/api/auth/register-school",
                   json={"email": f"dir@{p}.test", "password": "Secret123!",
                         "name": "Directrice", "school_name": f"École {p}"})
        assert r.status_code == 201, r.get_data(as_text=True)
        cls.dir_h = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.tenant_id = r.get_json()["tenant_id"]
        cls.annee = c.get("/api/academic-years", headers=cls.dir_h).get_json()[0]["id"]
        # Une classe de secondaire : c'est le périmètre du Directeur des disciplines.
        cls.classe = c.post("/api/classes", json={"name": "5e A", "level": "5e",
                                                  "academic_year_id": cls.annee,
                                                  "cycle": "secondaire"},
                            headers=cls.dir_h).get_json()

        def eleve(prenom, nom):
            return c.post("/api/students",
                          json={"first_name": prenom, "last_name": nom,
                                "academic_year_id": cls.annee, "class_id": cls.classe["id"]},
                          headers=cls.dir_h).get_json()

        cls.kevin = eleve("Kevin", "Mbala")
        cls.sarah = eleve("Sarah", "Ilunga")

        cls.prof_h = cls._inviter(c, cls.dir_h, "professeur", f"prof@{p}.test", "Paul Prof",
                                  class_ids=[cls.classe["id"]],
                                  titulaire_class_id=cls.classe["id"])
        cls.dd_h = cls._inviter(c, cls.dir_h, "discipline", f"dd@{p}.test", "Didier DD")
        cls.parent_kevin_h = cls._inviter(c, cls.dir_h, "parent", f"pk@{p}.test", "Jean Mbala",
                                          student_ids=[cls.kevin["id"]])
        cls.parent_sarah_h = cls._inviter(c, cls.dir_h, "parent", f"ps@{p}.test", "Alice Ilunga",
                                          student_ids=[cls.sarah["id"]])

    @staticmethod
    def _inviter(c, dir_h, role, courriel, nom, **extra):
        inv = c.post("/api/invitations", json=dict({"role": role}, **extra), headers=dir_h)
        assert inv.status_code == 201, inv.get_data(as_text=True)
        acc = c.post("/api/invitations/accept",
                     json={"token": inv.get_json()["token"], "name": nom,
                           "email": courriel, "password": "Secret123!"})
        assert acc.status_code == 201, acc.get_data(as_text=True)
        return {"Authorization": "Bearer " + acc.get_json()["token"]}

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def _notifs(self, entetes):
        return self.client.get("/api/notifications", headers=entetes).get_json()

    def _titres(self, entetes):
        return [n["title"] for n in self._notifs(entetes)]


class DisciplineConfigurableTests(_Etablissement):
    """Un réglage qui ne change pas le résultat n'est pas un réglage."""

    prefixe = "disc"

    def _conduite(self, eleve, entetes=None):
        d = self.client.get(f"/api/students/{eleve['id']}", headers=entetes or self.dir_h).get_json()
        return d["student"].get("conduct") or d.get("conduct") or {}

    def test_01_le_capital_de_conduite_est_celui_configure(self):
        r = self.client.put("/api/discipline/thresholds",
                            json={"capital": 60,
                                  "thresholds": [{"remaining_points": 30, "label": "Alerte"}]},
                            headers=self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        reglages = self.client.get("/api/settings", headers=self.dir_h).get_json()
        self.assertEqual(reglages["discipline_capital"], 60)
        apercu = self.client.get("/api/discipline/overview", headers=self.dir_h).get_json()
        self.assertEqual(apercu["capital"], 60,
                         "l'aperçu discipline doit refléter le capital configuré")

    def test_02_un_capital_aberrant_est_refuse(self):
        for valeur in (0, 5, 5000, -10, "beaucoup"):
            r = self.client.put("/api/discipline/thresholds",
                                json={"capital": valeur,
                                      "thresholds": [{"remaining_points": 30, "label": "Alerte"}]},
                                headers=self.dir_h)
            self.assertEqual(r.status_code, 400, f"capital {valeur!r} accepté")
        self.assertEqual(self.client.get("/api/settings", headers=self.dir_h).get_json()
                         ["discipline_capital"], 60, "un refus ne doit rien avoir modifié")

    def test_03_les_points_dun_incident_sont_reellement_deduits(self):
        avant = self.client.get(f"/api/students/{self.kevin['id']}",
                                headers=self.dir_h).get_json()
        r = self.client.post("/api/incidents",
                             json={"student_id": self.kevin["id"], "title": "Bagarre",
                                   "category": "comportement", "severity": "high",
                                   "points": -15, "occurred_at": TODAY}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertEqual(corps["balance"]["delta"], -15)
        self.assertEqual(corps["balance"]["remaining"], 60 - 15,
                         "le restant doit partir du capital configuré, pas d'une valeur en dur")

    def test_04_un_seuil_franchi_est_signale_une_fois_et_ne_sanctionne_rien(self):
        """Le produit DÉTECTE le franchissement d'un seuil. Il ne décide rien.

        Et il le signale au FRANCHISSEMENT, pas à chaque incident suivant :
        `crossed_thresholds(avant, après)` compare une transition. Sans cela,
        un élève déjà sous le seuil déclencherait une alerte à chaque retard,
        et plus personne ne lirait les alertes."""
        r = self.client.put("/api/discipline/thresholds",
                            json={"capital": 60,
                                  "thresholds": [
                                      {"remaining_points": 50, "label": "Avertissement",
                                       "action": "Convocation du responsable"},
                                      {"remaining_points": 20, "label": "Conseil de discipline",
                                       "action": "Réunion du conseil"}]},
                            headers=self.dir_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        # Sarah part de 60, intacte. Un incident à −15 la fait passer sous 50.
        r = self.client.post("/api/incidents",
                             json={"student_id": self.sarah["id"], "title": "Incident",
                                   "category": "comportement", "severity": "high",
                                   "points": -15, "occurred_at": TODAY}, headers=self.dd_h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertEqual(corps["balance"]["remaining"], 45)
        self.assertTrue(corps["threshold_reached"], "60 → 45 franchit le seuil 50")
        self.assertEqual([c["label"] for c in corps["crossed"]], ["Avertissement"],
                         "seul le seuil réellement franchi doit être signalé")

        # Second incident : elle reste au-dessus de 20, aucun NOUVEAU seuil.
        r = self.client.post("/api/incidents",
                             json={"student_id": self.sarah["id"], "title": "Suite",
                                   "category": "comportement", "severity": "medium",
                                   "points": -10, "occurred_at": TODAY}, headers=self.dd_h)
        corps = r.get_json()
        self.assertEqual(corps["balance"]["remaining"], 35)
        self.assertEqual(corps["crossed"], [],
                         "déjà sous le seuil : ne pas ré-alerter à chaque incident")

        # Troisième : elle passe sous 20, nouveau seuil franchi.
        r = self.client.post("/api/incidents",
                             json={"student_id": self.sarah["id"], "title": "Grave",
                                   "category": "comportement", "severity": "high",
                                   "points": -20, "occurred_at": TODAY}, headers=self.dd_h)
        corps = r.get_json()
        self.assertEqual(corps["balance"]["remaining"], 15)
        self.assertEqual([c["label"] for c in corps["crossed"]], ["Conseil de discipline"])

        # Et rien n'a été décidé automatiquement.
        conn = db.get_connection()
        try:
            convocations = conn.execute(
                "SELECT COUNT(*) AS n FROM convocations WHERE tenant_id=? AND student_id=?",
                (self.tenant_id, self.sarah["id"])).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(convocations, 0,
                         "franchir un seuil alerte un humain, ne convoque jamais tout seul")

    def test_05_les_seuils_sont_relus_tels_quils_ont_ete_ecrits(self):
        corps = self.client.get("/api/discipline/thresholds", headers=self.dir_h).get_json()
        self.assertEqual(corps["capital"], 60)
        self.assertEqual([(s["remaining_points"], s["label"]) for s in corps["thresholds"]],
                         [(50, "Avertissement"), (20, "Conseil de discipline")])

    def test_06_un_professeur_ne_configure_pas_la_discipline(self):
        for entetes, qui in ((self.prof_h, "professeur"), (self.parent_kevin_h, "parent")):
            r = self.client.put("/api/discipline/thresholds",
                                json={"capital": 100,
                                      "thresholds": [{"remaining_points": 30, "label": "X"}]},
                                headers=entetes)
            self.assertEqual(r.status_code, 403, f"{qui} a pu changer le capital")
            r = self.client.put("/api/discipline/thresholds",
                                json={"thresholds": [{"remaining_points": 1, "label": "X"}]},
                                headers=entetes)
            self.assertEqual(r.status_code, 403, f"{qui} a pu changer les seuils")
        self.assertEqual(self.client.get("/api/settings", headers=self.dir_h).get_json()
                         ["discipline_capital"], 60)


class NotificationsTests(_Etablissement):
    """La seule faute impardonnable d'un système de notification scolaire :
    parler du mauvais enfant à un parent."""

    prefixe = "notif"

    def test_10_une_absence_ne_notifie_que_le_parent_concerne(self):
        r = self.client.post(f"/api/classes/{self.classe['id']}/attendance",
                             json={"date": TODAY,
                                   "records": [{"student_id": self.kevin["id"], "status": "absent"},
                                               {"student_id": self.sarah["id"], "status": "present"}]},
                             headers=self.prof_h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        pour_kevin = self._notifs(self.parent_kevin_h)
        pour_sarah = self._notifs(self.parent_sarah_h)
        self.assertTrue(any("absence" in n["title"].lower() for n in pour_kevin),
                        "le parent de l'élève absent doit être prévenu")
        for n in pour_sarah:
            self.assertNotIn("Kevin", n["title"] + n["body"],
                             "le parent de Sarah ne doit jamais lire le nom de Kevin")
        for n in pour_kevin:
            self.assertNotIn("Sarah", n["title"] + n["body"])

    def test_11_aucune_notification_ne_traverse_les_etablissements(self):
        conn = db.get_connection()
        try:
            etrangeres = conn.execute(
                """SELECT COUNT(*) AS n FROM notifications nt
                   WHERE nt.recipient_user_id IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM memberships m
                                     WHERE m.user_id = nt.recipient_user_id
                                       AND m.tenant_id = nt.tenant_id)""").fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(etrangeres, 0)

    def test_12_le_compteur_de_non_lues_suit_la_lecture(self):
        avant = self.client.get("/api/notifications/summary",
                                headers=self.parent_kevin_h).get_json()["unread_count"]
        self.assertGreater(avant, 0, "il doit rester des notifications non lues à ce stade")
        notifs = self._notifs(self.parent_kevin_h)
        non_lue = next(n for n in notifs if n["status"] == "unread")
        r = self.client.post(f"/api/notifications/{non_lue['id']}/read", headers=self.parent_kevin_h)
        self.assertEqual(r.status_code, 200)
        apres = self.client.get("/api/notifications/summary",
                                headers=self.parent_kevin_h).get_json()["unread_count"]
        self.assertEqual(apres, avant - 1)

    def test_13_un_parent_ne_peut_pas_lire_la_notification_dun_autre(self):
        notifs = self._notifs(self.parent_kevin_h)
        self.assertTrue(notifs)
        r = self.client.post(f"/api/notifications/{notifs[0]['id']}/read",
                             headers=self.parent_sarah_h)
        self.assertEqual(r.status_code, 404,
                         "marquer lue la notification d'autrui doit être refusé, pas silencieux")

    def test_14_tout_marquer_lu_ne_touche_que_ses_propres_notifications(self):
        avant_sarah = self.client.get("/api/notifications/summary",
                                      headers=self.parent_sarah_h).get_json()["unread_count"]
        self.client.post("/api/notifications/read-all", headers=self.parent_kevin_h)
        self.assertEqual(self.client.get("/api/notifications/summary",
                                         headers=self.parent_kevin_h).get_json()["unread_count"], 0)
        self.assertEqual(self.client.get("/api/notifications/summary",
                                         headers=self.parent_sarah_h).get_json()["unread_count"],
                         avant_sarah, "les notifications d'un autre parent ont été touchées")


class BulletinCasLimitesTests(_Etablissement):
    """Les cas où une moyenne se calcule quand même — et faux."""

    prefixe = "bull"

    def test_20_un_eleve_sans_note_na_pas_de_moyenne_inventee(self):
        b = self.client.get(f"/api/students/{self.kevin['id']}/bulletin",
                            headers=self.dir_h)
        self.assertEqual(b.status_code, 200, b.get_data(as_text=True))
        corps = b.get_json()
        self.assertEqual(corps["subjects"], [])
        self.assertIsNone(corps["general_average_20"],
                          "aucune note ne doit jamais donner 0 — c'est une note, pas une absence de note")

    def test_21_des_baremes_differents_sont_ramenes_sur_vingt(self):
        """Une interro sur 10 et un devoir sur 50 ne se moyennent pas bruts."""
        self.client.post(f"/api/classes/{self.classe['id']}/grades",
                         json={"subject": "Maths", "period": "Période 1", "max_score": 10,
                               "entries": [{"student_id": self.kevin["id"], "score": 8}]},
                         headers=self.prof_h)
        self.client.post(f"/api/classes/{self.classe['id']}/grades",
                         json={"subject": "Histoire", "period": "Période 1", "max_score": 50,
                               "entries": [{"student_id": self.kevin["id"], "score": 25}]},
                         headers=self.prof_h)
        b = self.client.get(f"/api/students/{self.kevin['id']}/bulletin",
                            headers=self.dir_h).get_json()
        par_matiere = {s["subject"]: s["average_20"] for s in b["subjects"]}
        self.assertEqual(par_matiere["Maths"], 16.0, "8/10 vaut 16/20")
        self.assertEqual(par_matiere["Histoire"], 10.0, "25/50 vaut 10/20")
        self.assertEqual(b["general_average_20"], 13.0, "(16 + 10) / 2")

    def test_22_un_score_hors_bareme_est_refuse(self):
        for score, bareme in ((25, 20), (-3, 20), (11, 10)):
            r = self.client.post(f"/api/classes/{self.classe['id']}/grades",
                                 json={"subject": "Test", "period": "Période 1",
                                       "max_score": bareme,
                                       "entries": [{"student_id": self.kevin["id"], "score": score}]},
                                 headers=self.prof_h)
            self.assertEqual(r.status_code, 400, f"score {score}/{bareme} accepté")

    def test_24_le_rang_correspond_a_la_moyenne_affichee(self):
        """Trouvé et reproduit à l'audit. Le rang se calculait sur
        `AVG(score / max_score)` à plat — pondéré par le NOMBRE de notes —
        alors que la moyenne imprimée juste au-dessus est la moyenne des
        moyennes par matière. Deux bulletins affichaient 12,0 et portaient des
        rangs différents."""
        # Alice : cinq notes de maths à 18, une de français à 6 → (18+6)/2 = 12
        for _ in range(5):
            self.client.post(f"/api/classes/{self.classe['id']}/grades",
                             json={"subject": "Maths", "period": "Période 3", "max_score": 20,
                                   "entries": [{"student_id": self.kevin["id"], "score": 18}]},
                             headers=self.prof_h)
        self.client.post(f"/api/classes/{self.classe['id']}/grades",
                         json={"subject": "Histoire", "period": "Période 3", "max_score": 20,
                               "entries": [{"student_id": self.kevin["id"], "score": 6}]},
                         headers=self.prof_h)
        # Sarah : 12 et 12 → 12 également
        for matiere in ("Maths", "Histoire"):
            self.client.post(f"/api/classes/{self.classe['id']}/grades",
                             json={"subject": matiere, "period": "Période 3", "max_score": 20,
                                   "entries": [{"student_id": self.sarah["id"], "score": 12}]},
                             headers=self.prof_h)
        bk = self.client.get(f"/api/students/{self.kevin['id']}/bulletin?period=Période 3",
                             headers=self.dir_h).get_json()
        bs = self.client.get(f"/api/students/{self.sarah['id']}/bulletin?period=Période 3",
                             headers=self.dir_h).get_json()
        self.assertEqual(bk["general_average_20"], 12.0)
        self.assertEqual(bs["general_average_20"], 12.0)
        self.assertEqual(bk["rank"], bs["rank"],
                         "même moyenne affichée, le rang ne peut pas différer")

    def test_23_le_rang_compte_les_ex_aequo_sans_perdre_personne(self):
        for eleve in (self.kevin, self.sarah):
            self.client.post(f"/api/classes/{self.classe['id']}/grades",
                             json={"subject": "Égalité", "period": "Période 2", "max_score": 20,
                                   "entries": [{"student_id": eleve["id"], "score": 12}]},
                             headers=self.prof_h)
        bk = self.client.get(f"/api/students/{self.kevin['id']}/bulletin?period=Période 2",
                             headers=self.dir_h).get_json()
        bs = self.client.get(f"/api/students/{self.sarah['id']}/bulletin?period=Période 2",
                             headers=self.dir_h).get_json()
        self.assertEqual(bk["general_average_20"], bs["general_average_20"])
        self.assertEqual(bk["class_size"], 2)
        self.assertEqual(bs["class_size"], 2)
        self.assertEqual(bk["rank"], bs["rank"],
                         "deux moyennes égales doivent donner le même rang")
        self.assertEqual(bk["rank"], 1, "à égalité au sommet, les deux sont premiers")


if __name__ == "__main__":
    unittest.main()
