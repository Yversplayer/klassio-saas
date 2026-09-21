"""KLASSIO — passage d'année : préparer la rentrée sans jamais la décider.

Ces tests portent d'abord sur ce que le système REFUSE. Un passage d'année
déplace tous les élèves d'un établissement en une opération irréversible : la
seule façon de le rendre fiable est de vérifier qu'il refuse de s'exécuter sur
un plan incomplet, qu'il ne fait passer personne par défaut, et qu'il ne perd
rien de ce qui existait avant.
"""
import os
import sys
import unittest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, BACKEND)

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "klassio_promo_test.db")
os.environ["KLASSIO_DB_PATH"] = TEST_DB

import db  # noqa: E402
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402
import promotions  # noqa: E402


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

    def ecole(self, suffixe, eleves=("Kabeya", "Mbuyi", "Ilunga")):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@promo.test", "password": "Secret123!",
            "name": "Directeur", "school_name": f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        d = r.get_json()
        h = {"Authorization": f"Bearer {d['token']}"}
        an = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        cls = self.c.post("/api/classes", json={"academic_year_id": an, "name": "5e A"},
                          headers=h).get_json()
        rows = [self.c.post("/api/students", json={
            "academic_year_id": an, "class_id": cls["id"],
            "first_name": "Jean", "last_name": n}, headers=h).get_json() for n in eleves]
        return {"h": h, "year": an, "class": cls, "students": rows, "tenant_id": d["tenant_id"]}

    def plan(self, ctx, label="2027-2028"):
        r = self.c.post("/api/promotion-plans", json={
            "source_year_id": ctx["year"], "target_year_label": label}, headers=ctx["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()

    def decider(self, ctx, student_id, valeur, motif=None):
        """Passe par la délibération : c'est le seul chemin officiel."""
        if "delib" not in ctx:
            r = self.c.post("/api/deliberations", json={
                "class_id": ctx["class"]["id"], "kind": "ANNUAL"}, headers=ctx["h"])
            self.assertIn(r.status_code, (200, 201), r.get_data(as_text=True))
            ctx["delib"] = r.get_json()["id"]
        corps = {"kind": "DECISION", "student_id": student_id, "value": valeur}
        if motif:
            corps["comment"] = motif
        r = self.c.post(f"/api/deliberations/{ctx['delib']}/entries", json=corps, headers=ctx["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))

    def classe_cible(self, ctx, plan_id, nom):
        detail = self.c.get(f"/api/promotion-plans/{plan_id}", headers=ctx["h"]).get_json()
        for c in detail["classes_cible"]:
            if c["name"] == nom:
                return c["id"]
        r = self.c.post("/api/classes", json={
            "academic_year_id": detail["plan"]["target_year_id"], "name": nom}, headers=ctx["h"])
        return r.get_json()["id"]


# ---------------------------------------------------------------------------
# Ce que Klassio ne décide pas
# ---------------------------------------------------------------------------

class PasDeDecisionAutomatique(Base):

    def test_eleve_sans_deliberation_est_en_attente_pas_en_passage(self):
        """LE TEST CENTRAL. Un élève dont personne n'a parlé ne passe pas.

        C'est la faute que tout ce module existe pour rendre impossible :
        transformer un oubli administratif en décision pédagogique, pour toute
        une école, sans que personne ne s'en aperçoive.
        """
        ctx = self.ecole("sansdelib")
        p = self.plan(ctx)
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        self.assertEqual(len(detail["assignments"]), 3)
        for a in detail["assignments"]:
            self.assertEqual(a["action"], promotions.EN_ATTENTE, a)
            self.assertIsNone(a["origin"])
        self.assertEqual(detail["etat"]["sans_decision"], 3)
        self.assertFalse(detail["etat"]["applicable"])

    def test_aucune_classe_darrivee_nest_devinee(self):
        """Klassio ne sait pas ce qui vient après la 5e A — et ne le prétend pas."""
        ctx = self.ecole("devine")
        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        p = self.plan(ctx)
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        for a in detail["assignments"]:
            self.assertEqual(a["action"], promotions.PASSAGE)
            self.assertIsNone(a["target_class_id"], "une destination a été inventée")
        self.assertEqual(detail["etat"]["sans_classe"], 3)

    def test_decision_differee_ne_devient_pas_un_passage(self):
        """A_EXAMINER et AUTRE sont des décisions de NE PAS trancher."""
        ctx = self.ecole("differe")
        self.decider(ctx, ctx["students"][0]["id"], "A_EXAMINER", "Dossier incomplet.")
        self.decider(ctx, ctx["students"][1]["id"], "AUTRE", "Transfert en cours d'étude.")
        self.decider(ctx, ctx["students"][2]["id"], "PASSAGE")
        p = self.plan(ctx)
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        par_eleve = {a["student_id"]: a["action"] for a in detail["assignments"]}
        self.assertEqual(par_eleve[ctx["students"][0]["id"]], promotions.EN_ATTENTE)
        self.assertEqual(par_eleve[ctx["students"][1]["id"]], promotions.EN_ATTENTE)
        self.assertEqual(par_eleve[ctx["students"][2]["id"]], promotions.PASSAGE)

    def test_les_decisions_deliberees_sont_reprises_telles_quelles(self):
        ctx = self.ecole("reprise")
        self.decider(ctx, ctx["students"][0]["id"], "PASSAGE")
        self.decider(ctx, ctx["students"][1]["id"], "REDOUBLEMENT")
        self.decider(ctx, ctx["students"][2]["id"], "DEPART", "Déménagement.")
        p = self.plan(ctx)
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        par_eleve = {a["student_id"]: a for a in detail["assignments"]}
        self.assertEqual(par_eleve[ctx["students"][0]["id"]]["action"], promotions.PASSAGE)
        self.assertEqual(par_eleve[ctx["students"][1]["id"]]["action"], promotions.REDOUBLEMENT)
        depart = par_eleve[ctx["students"][2]["id"]]
        self.assertEqual(depart["action"], promotions.DEPART)
        self.assertEqual(depart["origin"], promotions.DELIBERATION)
        self.assertEqual(depart["note"], "Déménagement.")


    def test_une_deliberation_tenue_apres_louverture_du_plan_est_reprise(self):
        """L'ordre réel : on ouvre le plan de la rentrée, PUIS on délibère.

        Un plan qui ne verrait que les décisions antérieures à son ouverture
        obligerait à le refaire après chaque conseil de classe — ou, pire,
        laisserait toute une classe en attente sans que personne ne comprenne
        pourquoi.
        """
        ctx = self.ecole("tardive")
        p = self.plan(ctx)
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        self.assertEqual(detail["etat"]["sans_decision"], 3)

        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        r = self.c.post(f"/api/promotion-plans/{p['id']}/refresh", headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["repris"], 3)
        self.assertEqual(r.get_json()["etat"]["sans_decision"], 0)

    def test_la_reprise_necrase_jamais_un_arbitrage_de_la_direction(self):
        """La contrepartie du test précédent, et la raison pour laquelle la
        reprise ne porte QUE sur les lignes encore vierges."""
        ctx = self.ecole("arbitrage")
        p = self.plan(ctx)
        tranche = ctx["students"][0]["id"]
        self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{tranche}",
                     json={"action": "DEPART", "note": "Famille partie."}, headers=ctx["h"])
        # Le conseil se réunit ensuite et dit « passage » pour tout le monde.
        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        self.c.post(f"/api/promotion-plans/{p['id']}/refresh", headers=ctx["h"])
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        par_eleve = {a["student_id"]: a for a in detail["assignments"]}
        self.assertEqual(par_eleve[tranche]["action"], promotions.DEPART,
                         "l'arbitrage de la Direction a été écrasé")
        self.assertEqual(par_eleve[tranche]["note"], "Famille partie.")
        for e in ctx["students"][1:]:
            self.assertEqual(par_eleve[e["id"]]["action"], promotions.PASSAGE)


# ---------------------------------------------------------------------------
# Ce qui bloque l'application
# ---------------------------------------------------------------------------

class RefusDappliquer(Base):

    def _plan_complet(self, suffixe):
        ctx = self.ecole(suffixe)
        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        p = self.plan(ctx)
        cible = self.classe_cible(ctx, p["id"], "6e A")
        for e in ctx["students"]:
            r = self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{e['id']}",
                             json={"target_class_id": cible}, headers=ctx["h"])
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return ctx, p, cible

    def test_valider_un_plan_incomplet_est_refuse_avec_les_noms(self):
        ctx = self.ecole("incomplet")
        p = self.plan(ctx)
        r = self.c.post(f"/api/promotion-plans/{p['id']}/status",
                        json={"status": "VALIDE"}, headers=ctx["h"])
        self.assertEqual(r.status_code, 409)
        corps = r.get_json()
        self.assertEqual(corps["bloquants_total"], 3)
        self.assertTrue(all(b["manque"] == "décision" for b in corps["bloquants"]))
        # Un compte ne suffit pas : la Direction doit savoir qui aller chercher.
        self.assertTrue(all(b["nom"].strip() for b in corps["bloquants"]))

    def test_appliquer_un_plan_non_valide_est_refuse(self):
        ctx, p, _ = self._plan_complet("nonvalide")
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                        json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r.status_code, 409)
        self.assertIn("validé", r.get_json()["error"])

    def test_appliquer_sans_confirmation_ne_deplace_rien(self):
        ctx, p, _ = self._plan_complet("sansconfirm")
        self.c.post(f"/api/promotion-plans/{p['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply", json={}, headers=ctx["h"])
        self.assertEqual(r.status_code, 400)
        eleve = self.c.get(f"/api/students/{ctx['students'][0]['id']}",
                           headers=ctx["h"]).get_json()["student"]
        self.assertEqual(eleve["academic_year_id"], ctx["year"], "l'élève a bougé sans confirmation")

    def test_un_eleve_inscrit_apres_la_validation_bloque_lapplication(self):
        """Le contrôle est refait à l'application, pas seulement à la validation.

        Entre les deux, une inscription tardive peut arriver : l'appliquer
        quand même laisserait cet élève hors de la nouvelle année.
        """
        ctx, p, _ = self._plan_complet("tardif")
        self.c.post(f"/api/promotion-plans/{p['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        self.c.post("/api/students", json={
            "academic_year_id": ctx["year"], "class_id": ctx["class"]["id"],
            "first_name": "Tardif", "last_name": "Nouveau"}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{p['id']}/refresh", headers=ctx["h"])
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                        json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["bloquants_total"], 1)

    def test_un_plan_applique_ne_se_rejoue_pas(self):
        ctx, p, _ = self._plan_complet("rejeu")
        self.c.post(f"/api/promotion-plans/{p['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                        json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        r2 = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                         json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r2.status_code, 409)
        self.assertIn("déjà été appliqué", r2.get_json()["error"])

    def test_un_plan_applique_nest_plus_modifiable(self):
        ctx, p, cible = self._plan_complet("fige")
        self.c.post(f"/api/promotion-plans/{p['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                    json={"confirm": True}, headers=ctx["h"])
        r = self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{ctx['students'][0]['id']}",
                         json={"action": "REDOUBLEMENT"}, headers=ctx["h"])
        self.assertEqual(r.status_code, 409)


# ---------------------------------------------------------------------------
# L'application elle-même
# ---------------------------------------------------------------------------

class Application(Base):

    def _preparer(self, suffixe, decisions):
        ctx = self.ecole(suffixe)
        for e, d in zip(ctx["students"], decisions):
            self.decider(ctx, e["id"], d, "Motif." if d in ("DEPART", "AUTRE") else None)
        p = self.plan(ctx)
        cible = self.classe_cible(ctx, p["id"], "6e A")
        redouble = self.classe_cible(ctx, p["id"], "5e A")
        for e, d in zip(ctx["students"], decisions):
            if d == "PASSAGE":
                self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{e['id']}",
                             json={"target_class_id": cible}, headers=ctx["h"])
            elif d == "REDOUBLEMENT":
                self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{e['id']}",
                             json={"target_class_id": redouble}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{p['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        return ctx, p, cible, redouble

    def test_lidentite_de_leleve_ne_change_pas(self):
        """Le même `student_id` avance d'une année. Rien n'est recopié.

        Si le passage créait un nouvel élève, ses notes, ses frais, ses
        incidents et ses responsables resteraient accrochés à l'ancien : le
        dossier de l'enfant serait coupé en deux chaque rentrée.
        """
        ctx, p, cible, _ = self._preparer("identite", ["PASSAGE"] * 3)
        avant = ctx["students"][0]["id"]
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                        json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["deplaces"], 3)
        eleve = self.c.get(f"/api/students/{avant}", headers=ctx["h"]).get_json()["student"]
        self.assertEqual(eleve["id"], avant)
        self.assertEqual(eleve["class"]["id"], cible)
        self.assertNotEqual(eleve["academic_year_id"], ctx["year"])

    def test_la_classe_quittee_reste_consultable(self):
        """Ce que l'avancement ferait disparaître est consigné avant de l'être."""
        ctx, p, cible, _ = self._preparer("parcours", ["PASSAGE"] * 3)
        eid = ctx["students"][0]["id"]
        self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                    json={"confirm": True}, headers=ctx["h"])
        parcours = self.c.get(f"/api/students/{eid}/enrollments",
                              headers=ctx["h"]).get_json()["parcours"]
        annees = {x["academic_year_id"]: x for x in parcours}
        self.assertIn(ctx["year"], annees, "l'année quittée a disparu du parcours")
        self.assertEqual(annees[ctx["year"]]["class_name"], "5e A")
        self.assertFalse(annees[ctx["year"]]["courante"])
        courante = [x for x in parcours if x["courante"]]
        self.assertEqual(len(courante), 1)
        self.assertEqual(courante[0]["class_id"], cible)

    def test_un_depart_est_archive_jamais_supprime(self):
        ctx, p, _, _ = self._preparer("depart", ["PASSAGE", "PASSAGE", "DEPART"])
        parti = ctx["students"][2]["id"]
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                        json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r.get_json()["archives"], 1)
        eleve = self.c.get(f"/api/students/{parti}", headers=ctx["h"])
        self.assertEqual(eleve.status_code, 200, "le dossier de l'élève parti a disparu")
        self.assertEqual(eleve.get_json()["student"]["status"], "archived")
        self.assertEqual(eleve.get_json()["student"]["academic_year_id"], ctx["year"])

    def test_appliquer_ouvre_la_nouvelle_annee(self):
        """Élèves déplacés ET année basculée, dans la même opération.

        Entre les deux, l'établissement verrait ses anciennes classes vidées de
        leurs élèves. Cet état intermédiaire ne doit jamais exister.
        """
        ctx, p, _, _ = self._preparer("bascule", ["PASSAGE"] * 3)
        self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                    json={"confirm": True}, headers=ctx["h"])
        annees = {a["id"]: a for a in
                  self.c.get("/api/academic-years", headers=ctx["h"]).get_json()}
        ancienne = annees[ctx["year"]]
        self.assertEqual(ancienne["is_active"], 0)
        self.assertEqual(ancienne["status"], "ARCHIVED")
        nouvelle = [a for a in annees.values() if a["is_active"]]
        self.assertEqual(len(nouvelle), 1, "deux années actives à la fois")
        self.assertEqual(nouvelle[0]["status"], "ACTIVE")
        # Et l'établissement voit bien ses nouvelles classes peuplées.
        classes = {c["name"]: c for c in self.c.get("/api/classes", headers=ctx["h"]).get_json()}
        self.assertEqual(classes["6e A"]["student_count"], 3)

    def test_la_liste_des_classes_ne_melange_pas_les_annees(self):
        """Deux classes homonymes, dont une vidée, ne doivent pas coexister.

        La classe de l'année écoulée porte souvent le MÊME NOM que celle de la
        nouvelle. Les afficher ensemble mettait côte à côte la vraie classe et
        son fantôme, sans rien pour les distinguer — et l'appel du matin se
        faisait dans l'une ou l'autre au hasard.
        """
        ctx, p, cible, _ = self._preparer("melange", ["PASSAGE"] * 3)
        self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                    json={"confirm": True}, headers=ctx["h"])
        listees = self.c.get("/api/classes", headers=ctx["h"]).get_json()
        # La classe d'ORIGINE, identifiée par son id, ne doit plus apparaître —
        # même si une classe homonyme existe dans la nouvelle année.
        self.assertNotIn(ctx["class"]["id"], [c["id"] for c in listees],
                         "la classe de l'an dernier reste affichée")
        self.assertIn("6e A", [c["name"] for c in listees])
        # L'année écoulée reste consultable si on la demande.
        anciennes = self.c.get(f"/api/classes?academic_year_id={ctx['year']}",
                               headers=ctx["h"]).get_json()
        self.assertEqual([c["name"] for c in anciennes], ["5e A"])
        # Et celle d'un autre établissement reste introuvable.
        autre = self.ecole("melangeB")
        r = self.c.get(f"/api/classes?academic_year_id={autre['year']}", headers=ctx["h"])
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# La répartition : équilibrer des effectifs, rien d'autre
# ---------------------------------------------------------------------------

class Repartition(Base):

    def _six(self, suffixe):
        noms = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
        ctx = self.ecole(suffixe, eleves=noms)
        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        p = self.plan(ctx)
        a = self.classe_cible(ctx, p["id"], "6e A")
        b = self.classe_cible(ctx, p["id"], "6e B")
        return ctx, p, a, b

    def test_les_effectifs_sont_equilibres_entre_les_classes_designees(self):
        ctx, p, a, b = self._six("equilibre")
        r = self.c.post(f"/api/promotion-plans/{p['id']}/distribute", json={
            "source_class_id": ctx["class"]["id"], "target_class_ids": [a, b]},
            headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["places"], 6)
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        effectifs = {c["id"]: c["planned"] for c in detail["classes_cible"]}
        self.assertEqual(effectifs[a], 3)
        self.assertEqual(effectifs[b], 3)

    def test_repartir_ne_defait_pas_les_placements_manuels(self):
        """Relancer la répartition après trois corrections à la main ne doit
        pas effacer ces corrections."""
        ctx, p, a, b = self._six("manuel")
        fixe = ctx["students"][0]["id"]
        self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{fixe}",
                     json={"target_class_id": b}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{p['id']}/distribute", json={
            "source_class_id": ctx["class"]["id"], "target_class_ids": [a, b]},
            headers=ctx["h"])
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        par_eleve = {x["student_id"]: x for x in detail["assignments"]}
        self.assertEqual(par_eleve[fixe]["target_class_id"], b)
        self.assertEqual(par_eleve[fixe]["origin"], promotions.MANUEL)
        effectifs = {c["id"]: c["planned"] for c in detail["classes_cible"]}
        self.assertEqual(effectifs[a] + effectifs[b], 6)
        # L'équilibre tient compte de la place déjà prise : 3/3, pas 2/4.
        self.assertEqual(sorted([effectifs[a], effectifs[b]]), [3, 3])

    def test_deux_classes_sources_ne_remplissent_pas_deux_fois_la_meme_cible(self):
        ctx, p, a, b = self._six("deuxsources")
        seconde = self.c.post("/api/classes", json={
            "academic_year_id": ctx["year"], "name": "5e B"}, headers=ctx["h"]).get_json()
        for n in ("Golf", "Hotel"):
            self.c.post("/api/students", json={
                "academic_year_id": ctx["year"], "class_id": seconde["id"],
                "first_name": "Jean", "last_name": n}, headers=ctx["h"])
        d2 = self.c.post("/api/deliberations", json={
            "class_id": seconde["id"], "kind": "ANNUAL"}, headers=ctx["h"]).get_json()["id"]
        nouveaux = self.c.get(f"/api/students?class_id={seconde['id']}",
                              headers=ctx["h"]).get_json()
        for x in (nouveaux["students"] if isinstance(nouveaux, dict) else nouveaux):
            self.c.post(f"/api/deliberations/{d2}/entries", json={
                "kind": "DECISION", "student_id": x["id"], "value": "PASSAGE"},
                headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{p['id']}/refresh", headers=ctx["h"])
        for src in (ctx["class"]["id"], seconde["id"]):
            self.c.post(f"/api/promotion-plans/{p['id']}/distribute", json={
                "source_class_id": src, "target_class_ids": [a, b]}, headers=ctx["h"])
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        effectifs = sorted(c["planned"] for c in detail["classes_cible"])
        self.assertEqual(effectifs, [4, 4], f"répartition déséquilibrée : {effectifs}")

    def test_une_classe_darrivee_dune_autre_annee_est_refusee(self):
        ctx, p, a, _ = self._six("mauvaiseannee")
        r = self.c.post(f"/api/promotion-plans/{p['id']}/distribute", json={
            "source_class_id": ctx["class"]["id"], "target_class_ids": [ctx["class"]["id"]]},
            headers=ctx["h"])
        self.assertEqual(r.status_code, 404)

    def test_changer_pour_depart_libere_la_classe_darrivee(self):
        """Un élève qui ne vient pas ne doit pas occuper une place."""
        ctx, p, a, b = self._six("liberation")
        self.c.post(f"/api/promotion-plans/{p['id']}/distribute", json={
            "source_class_id": ctx["class"]["id"], "target_class_ids": [a]}, headers=ctx["h"])
        cible_eleve = ctx["students"][0]["id"]
        self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{cible_eleve}",
                     json={"action": "DEPART", "note": "Déménagement."}, headers=ctx["h"])
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        par_eleve = {x["student_id"]: x for x in detail["assignments"]}
        self.assertIsNone(par_eleve[cible_eleve]["target_class_id"])
        effectifs = {c["id"]: c["planned"] for c in detail["classes_cible"]}
        self.assertEqual(effectifs[a], 5)


# ---------------------------------------------------------------------------
# Périmètre et isolation
# ---------------------------------------------------------------------------

class Perimetre(Base):

    def _professeur(self, ctx, suffixe):
        r = self.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": [ctx["class"]["id"]]}, headers=ctx["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        a = self.c.post("/api/invitations/accept", json={
            "token": r.get_json()["token"], "name": "Professeur",
            "email": f"prof.{suffixe}@promo.test", "password": "Secret123!"})
        self.assertEqual(a.status_code, 201, a.get_data(as_text=True))
        return {"Authorization": f"Bearer {a.get_json()['token']}"}

    def test_un_professeur_ne_voit_pas_les_plans(self):
        ctx = self.ecole("profplan")
        self.plan(ctx)
        hp = self._professeur(ctx, "profplan")
        self.assertEqual(self.c.get("/api/promotion-plans", headers=hp).status_code, 403)

    def test_un_professeur_ne_peut_pas_appliquer_un_plan(self):
        """Le contrôle est au serveur, pas dans le masquage d'un bouton."""
        ctx = self.ecole("profapply")
        p = self.plan(ctx)
        hp = self._professeur(ctx, "profapply")
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply", json={"confirm": True}, headers=hp)
        self.assertEqual(r.status_code, 403)
        r2 = self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/"
                          f"{ctx['students'][0]['id']}", json={"action": "PASSAGE"}, headers=hp)
        self.assertEqual(r2.status_code, 403)

    def test_le_plan_dune_autre_ecole_est_introuvable(self):
        a = self.ecole("isoA")
        b = self.ecole("isoB")
        p = self.plan(a)
        r = self.c.get(f"/api/promotion-plans/{p['id']}", headers=b["h"])
        self.assertEqual(r.status_code, 404, "un plan a fuité entre établissements")

    def test_un_eleve_dune_autre_ecole_nentre_pas_dans_le_plan(self):
        a = self.ecole("fuiteA")
        b = self.ecole("fuiteB")
        p = self.plan(a)
        r = self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{b['students'][0]['id']}",
                         json={"action": "PASSAGE"}, headers=a["h"])
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# La préparation de l'année d'arrivée
# ---------------------------------------------------------------------------

class AnneeDarrivee(Base):

    def test_la_nouvelle_annee_nait_en_preparation(self):
        """Préparer la rentrée ne doit rien changer à l'année en cours."""
        ctx = self.ecole("preparation")
        p = self.plan(ctx)
        annees = {a["id"]: a for a in
                  self.c.get("/api/academic-years", headers=ctx["h"]).get_json()}
        self.assertEqual(annees[p["target_year_id"]]["status"], "PREPARATION")
        self.assertEqual(annees[p["target_year_id"]]["is_active"], 0)
        self.assertEqual(annees[ctx["year"]]["is_active"], 1)
        # Et les classes affichées restent celles de l'année en cours.
        classes = self.c.get("/api/classes", headers=ctx["h"]).get_json()
        self.assertEqual([c["name"] for c in classes], ["5e A"])

    def test_creer_une_annee_a_la_main_ne_vole_pas_lannee_en_cours(self):
        ctx = self.ecole("volannee")
        r = self.c.post("/api/academic-years", json={"label": "2030-2031"}, headers=ctx["h"])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["status"], "PREPARATION")
        annees = self.c.get("/api/academic-years", headers=ctx["h"]).get_json()
        actives = [a for a in annees if a["is_active"]]
        self.assertEqual(len(actives), 1)
        self.assertEqual(actives[0]["id"], ctx["year"])

    def test_copier_les_classes_est_idempotent(self):
        ctx = self.ecole("copie")
        self.c.post("/api/classes", json={"academic_year_id": ctx["year"], "name": "6e A"},
                    headers=ctx["h"])
        p = self.plan(ctx)
        r1 = self.c.post(f"/api/promotion-plans/{p['id']}/copy-classes", headers=ctx["h"])
        self.assertEqual(r1.get_json()["creees"], 2)
        r2 = self.c.post(f"/api/promotion-plans/{p['id']}/copy-classes", headers=ctx["h"])
        self.assertEqual(r2.get_json()["creees"], 0, "la copie a créé des doublons")
        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=ctx["h"]).get_json()
        self.assertEqual(sorted(c["name"] for c in detail["classes_cible"]), ["5e A", "6e A"])

    def test_rouvrir_un_plan_existant_ne_le_duplique_pas(self):
        ctx = self.ecole("doublon")
        p1 = self.plan(ctx)
        r = self.c.post("/api/promotion-plans", json={
            "source_year_id": ctx["year"], "target_year_id": p1["target_year_id"]},
            headers=ctx["h"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["id"], p1["id"])


if __name__ == "__main__":
    unittest.main()
