"""KLASSIO — délibérations : réunir les éléments, ne jamais décider à la place.

Ces tests portent d'abord sur ce que le système REFUSE. Une délibération est un
acte institutionnel : la seule façon de la rendre fiable est de vérifier qu'un
avis ne devient jamais une décision, qu'aucun rôle ne dépasse le sien, et que
rien n'est écrasé.
"""
import os
import sys
import unittest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, BACKEND)

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "klassio_delib_test.db")
os.environ["KLASSIO_DB_PATH"] = TEST_DB

import db  # noqa: E402
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402
import deliberations as delib  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class Base(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def ecole(self, suffixe, noms=("Kabeya", "Mbuyi")):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@delib.test", "password": "Secret123!",
            "name": "Directeur", "school_name": f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        d = r.get_json()
        h = {"Authorization": f"Bearer {d['token']}"}
        an = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        cls = self.c.post("/api/classes", json={"academic_year_id": an, "name": "6e A"},
                          headers=h).get_json()
        eleves = [self.c.post("/api/students", json={
            "academic_year_id": an, "class_id": cls["id"],
            "first_name": "Jean", "last_name": n}, headers=h).get_json() for n in noms]
        return {"h": h, "year": an, "class": cls, "students": eleves, "tenant_id": d["tenant_id"]}

    def delib(self, ctx, kind="ANNUAL"):
        r = self.c.post("/api/deliberations", json={
            "class_id": ctx["class"]["id"], "kind": kind}, headers=ctx["h"])
        self.assertIn(r.status_code, (200, 201), r.get_data(as_text=True))
        return r.get_json()["id"]

    def prof(self, ctx, class_ids, mail, titulaire=None):
        payload = {"role": "professeur", "class_ids": class_ids}
        if titulaire:
            payload["titulaire_class_id"] = titulaire
        inv = self.c.post("/api/invitations", json=payload, headers=ctx["h"]).get_json()
        u = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof", "email": mail,
            "password": "Secret123!"}).get_json()
        return {"Authorization": f"Bearer {u['token']}"}


class AvisNEstPasDecision(Base):
    def test_01_un_professeur_ne_peut_pas_decider(self):
        """LE test du module. Un avis est une contribution au débat ; la
        décision est un acte de la Direction. Rien ne transforme l'un en
        l'autre, et c'est vérifié au SERVEUR, pas en masquant un bouton."""
        ctx = self.ecole("avis01")
        did = self.delib(ctx)
        h = self.prof(ctx, [ctx["class"]["id"]], "prof01@delib.test",
                      titulaire=ctx["class"]["id"])
        eleve = ctx["students"][0]["id"]

        avis = self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "AVIS", "student_id": eleve, "value": "PASSAGE"}, headers=h)
        self.assertEqual(avis.status_code, 201, "le titulaire doit pouvoir donner un avis")

        decision = self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": eleve, "value": "PASSAGE"}, headers=h)
        self.assertEqual(decision.status_code, 403,
                         "un professeur a pu enregistrer une décision officielle")

    def test_02_un_avis_ne_cree_aucune_decision(self):
        """Dix avis « passage » ne font pas une décision."""
        ctx = self.ecole("avis02")
        did = self.delib(ctx)
        h = self.prof(ctx, [ctx["class"]["id"]], "prof02@delib.test",
                      titulaire=ctx["class"]["id"])
        eleve = ctx["students"][0]["id"]
        for _ in range(3):
            self.c.post(f"/api/deliberations/{did}/entries", json={
                "kind": "AVIS", "student_id": eleve, "value": "PASSAGE"}, headers=h)

        tableau = self.c.get(f"/api/deliberations/{did}", headers=ctx["h"]).get_json()
        ligne = [r for r in tableau["rows"] if r["student"]["id"] == eleve][0]
        self.assertIsNone(ligne["decision"], "des avis ont produit une décision")

        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM bulletin_decisions WHERE tenant_id=?",
                         (ctx["tenant_id"],)).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 0, "un avis a écrit dans bulletin_decisions")

    def test_03_la_direction_decide_et_la_decision_fait_foi(self):
        ctx = self.ecole("avis03")
        did = self.delib(ctx)
        eleve = ctx["students"][0]["id"]
        r = self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": eleve, "value": "REDOUBLEMENT",
            "comment": "Résultats insuffisants sur l'année."}, headers=ctx["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))

        tableau = self.c.get(f"/api/deliberations/{did}", headers=ctx["h"]).get_json()
        ligne = [x for x in tableau["rows"] if x["student"]["id"] == eleve][0]
        self.assertEqual(ligne["decision"]["value"], "REDOUBLEMENT")

        # Et la décision se retrouve sur le bulletin, qui la lisait déjà.
        b = self.c.get(f"/api/students/{eleve}/bulletin", headers=ctx["h"]).get_json()
        self.assertEqual(b["decision"]["decision"], "doublant")

    def test_04_aucune_decision_automatique(self):
        """Klassio peut signaler une situation. Il ne conclut jamais."""
        ctx = self.ecole("avis04")
        did = self.delib(ctx)
        tableau = self.c.get(f"/api/deliberations/{did}", headers=ctx["h"]).get_json()
        for ligne in tableau["rows"]:
            self.assertIsNone(ligne["decision"],
                              "une décision est apparue sans que personne ne la prenne")
            niveau = ligne["signals"]["ensemble"]["niveau"]
            self.assertIn(niveau, ("ok", "attention", "examiner"))
            self.assertNotIn(niveau, delib.DECISIONS,
                             "un indicateur porte le nom d'une décision")

    def test_05_une_decision_atypique_exige_un_motif(self):
        ctx = self.ecole("avis05")
        did = self.delib(ctx)
        eleve = ctx["students"][0]["id"]
        sans = self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": eleve, "value": "AUTRE"}, headers=ctx["h"])
        self.assertEqual(sans.status_code, 400, "« Autre » sans motif a été accepté")
        avec = self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": eleve, "value": "AUTRE",
            "comment": "Orientation vers une filière technique."}, headers=ctx["h"])
        self.assertEqual(avec.status_code, 201)


class RienNEstEcrase(Base):
    def test_10_changer_d_avis_conserve_le_precedent(self):
        """§25 : si une décision change avant clôture, l'historique reste."""
        ctx = self.ecole("hist10")
        did = self.delib(ctx)
        eleve = ctx["students"][0]["id"]
        self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": eleve, "value": "REDOUBLEMENT",
            "comment": "Première position du conseil."}, headers=ctx["h"])
        self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": eleve, "value": "PASSAGE",
            "comment": "Après examen du dossier complet."}, headers=ctx["h"])

        dossier = self.c.get(f"/api/deliberations/{did}/students/{eleve}",
                             headers=ctx["h"]).get_json()
        decisions = [e for e in dossier["entries"] if e["kind"] == "DECISION"]
        self.assertEqual(len(decisions), 2, "l'ancienne décision a été effacée")
        courante = [e for e in decisions if e["superseded_at"] is None]
        self.assertEqual(len(courante), 1)
        self.assertEqual(courante[0]["value"], "PASSAGE")
        ancienne = [e for e in decisions if e["superseded_at"] is not None][0]
        self.assertEqual(ancienne["value"], "REDOUBLEMENT")

    def test_11_les_observations_s_ajoutent_sans_se_remplacer(self):
        ctx = self.ecole("hist11")
        did = self.delib(ctx)
        eleve = ctx["students"][0]["id"]
        for texte in ("Progrès net au second trimestre.", "Absences justifiées."):
            self.c.post(f"/api/deliberations/{did}/entries", json={
                "kind": "OBSERVATION", "student_id": eleve, "comment": texte},
                headers=ctx["h"])
        dossier = self.c.get(f"/api/deliberations/{did}/students/{eleve}",
                             headers=ctx["h"]).get_json()
        obs = [e for e in dossier["entries"] if e["kind"] == "OBSERVATION"]
        self.assertEqual(len(obs), 2)
        self.assertTrue(all(o["superseded_at"] is None for o in obs),
                        "une observation en a remplacé une autre")


class Perimetres(Base):
    def test_20_un_parent_n_approche_pas_d_une_deliberation(self):
        ctx = self.ecole("per20")
        did = self.delib(ctx)
        inv = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [ctx["students"][0]["id"]]},
            headers=ctx["h"]).get_json()
        u = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "parent20@delib.test",
            "password": "Secret123!"}).get_json()
        h = {"Authorization": f"Bearer {u['token']}"}
        self.assertEqual(self.c.get("/api/deliberations", headers=h).status_code, 403)
        self.assertEqual(self.c.get(f"/api/deliberations/{did}", headers=h).status_code, 403)
        self.assertEqual(self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "OBSERVATION", "student_id": ctx["students"][0]["id"],
            "comment": "x"}, headers=h).status_code, 403)

    def test_21_un_professeur_n_entre_pas_dans_la_classe_d_un_collegue(self):
        ctx = self.ecole("per21")
        autre = self.c.post("/api/classes", json={
            "academic_year_id": ctx["year"], "name": "5e B"}, headers=ctx["h"]).get_json()
        autre_delib = self.c.post("/api/deliberations", json={
            "class_id": autre["id"], "kind": "ANNUAL"}, headers=ctx["h"]).get_json()["id"]
        sienne = self.delib(ctx)
        h = self.prof(ctx, [ctx["class"]["id"]], "prof21@delib.test")

        self.assertEqual(self.c.get(f"/api/deliberations/{sienne}", headers=h).status_code, 200)
        self.assertEqual(self.c.get(f"/api/deliberations/{autre_delib}", headers=h).status_code, 403,
                         "un professeur a ouvert la délibération d'une autre classe")

    def test_22_une_deliberation_d_une_autre_ecole_est_introuvable(self):
        a = self.ecole("per22a")
        b = self.ecole("per22b")
        did = self.delib(b)
        self.assertEqual(self.c.get(f"/api/deliberations/{did}", headers=a["h"]).status_code, 404)
        self.assertEqual(self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "OBSERVATION", "student_id": b["students"][0]["id"],
            "comment": "x"}, headers=a["h"]).status_code, 404)

    def test_23_un_eleve_d_une_autre_classe_ne_se_glisse_pas_dans_la_seance(self):
        """IDOR : l'identifiant d'élève vient du client, il est revérifié."""
        ctx = self.ecole("per23")
        autre = self.c.post("/api/classes", json={
            "academic_year_id": ctx["year"], "name": "5e B"}, headers=ctx["h"]).get_json()
        etranger = self.c.post("/api/students", json={
            "academic_year_id": ctx["year"], "class_id": autre["id"],
            "first_name": "Paul", "last_name": "Etranger"}, headers=ctx["h"]).get_json()
        did = self.delib(ctx)
        r = self.c.post(f"/api/deliberations/{did}/entries", json={
            "kind": "DECISION", "student_id": etranger["id"], "value": "PASSAGE"},
            headers=ctx["h"])
        self.assertEqual(r.status_code, 404,
                         "un élève hors de la classe a reçu une décision dans cette séance")

    def test_24_seule_la_direction_ouvre_une_seance(self):
        ctx = self.ecole("per24")
        h = self.prof(ctx, [ctx["class"]["id"]], "prof24@delib.test",
                      titulaire=ctx["class"]["id"])
        r = self.c.post("/api/deliberations", json={
            "class_id": ctx["class"]["id"], "kind": "ANNUAL"}, headers=h)
        self.assertEqual(r.status_code, 403)

    def test_25_sans_session_rien(self):
        ctx = self.ecole("per25")
        did = self.delib(ctx)
        self.assertEqual(self.c.get("/api/deliberations").status_code, 401)
        self.assertEqual(self.c.get(f"/api/deliberations/{did}").status_code, 401)


class DonneesReelles(Base):
    def test_30_le_tableau_lit_les_vraies_notes(self):
        """Aucune statistique inventée : les chiffres viennent des tables."""
        ctx = self.ecole("reel30")
        self.c.post(f"/api/classes/{ctx['class']['id']}/grades", json={
            "subject": "Mathématiques", "period": "Période 1", "max_score": 20,
            "entries": [{"student_id": ctx["students"][0]["id"], "score": 16}],
        }, headers=ctx["h"])
        did = self.delib(ctx)
        tableau = self.c.get(f"/api/deliberations/{did}", headers=ctx["h"]).get_json()
        ligne = [r for r in tableau["rows"] if r["student"]["id"] == ctx["students"][0]["id"]][0]
        self.assertEqual(ligne["results"]["average_20"], 16)
        self.assertEqual(ligne["results"]["percent"], 80.0)
        vide = [r for r in tableau["rows"] if r["student"]["id"] == ctx["students"][1]["id"]][0]
        self.assertIsNone(vide["results"]["average_20"],
                          "un élève sans note a reçu une moyenne inventée")

    def test_31_aucun_signal_sans_regle_configuree(self):
        """Klassio ne signale rien que l'établissement n'ait demandé."""
        ctx = self.ecole("reel31")
        did = self.delib(ctx)
        tableau = self.c.get(f"/api/deliberations/{did}", headers=ctx["h"]).get_json()
        for ligne in tableau["rows"]:
            self.assertEqual(ligne["signals"]["presence"]["niveau"], "ok",
                             "une absence a été signalée alors qu'aucun maximum n'est fixé")


if __name__ == "__main__":
    unittest.main()
