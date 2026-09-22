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


class ApresLaRentree(Base):
    """Ce qui doit continuer de marcher une fois les élèves passés."""

    def test_le_tableau_de_bord_ne_compte_pas_lannee_archivee(self):
        """Deux écrans qui se contredisent font douter des deux.

        Le tableau de bord comptait les classes de toutes les années : après
        une rentrée, il annonçait une classe de plus que l'écran Classes — la
        classe archivée, vidée de ses élèves.
        """
        ctx = self.ecole("bord", eleves=("Alpha",))
        eleve = ctx["students"][0]["id"]
        self.decider(ctx, eleve, "PASSAGE")
        plan = self.plan(ctx)
        cible = self.classe_cible(ctx, plan["id"], "6e A")
        self.c.patch(f"/api/promotion-plans/{plan['id']}/assignments/{eleve}",
                     json={"target_class_id": cible}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{plan['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{plan['id']}/apply",
                    json={"confirm": True}, headers=ctx["h"])

        bord = self.c.get("/api/dashboard", headers=ctx["h"]).get_json()
        listees = self.c.get("/api/classes", headers=ctx["h"]).get_json()
        self.assertEqual(bord["class_count"], len(listees),
                         "le tableau de bord et l'écran Classes ne disent pas la même chose")
        self.assertEqual(bord["attendance_today"]["class_count"], len(listees))
        self.assertNotIn(ctx["class"]["id"], [c["id"] for c in bord["classes_outstanding"]],
                         "la classe archivée figure encore dans le suivi financier")

    def test_proclamer_lannee_terminee_atteint_encore_les_parents(self):
        """Les élèves ont avancé ; les résultats de l'année close restent les
        leurs.

        L'audience d'une proclamation se calculait sur l'année COURANTE de
        l'élève. Après un passage, proclamer une période de l'année terminée ne
        touchait plus personne : les parents n'ont jamais reçu les résultats de
        l'année que leur enfant venait de finir, et rien ne le signalait.
        """
        ctx = self.ecole("proclamation", eleves=("Alpha",))
        eleve = ctx["students"][0]["id"]
        self.c.post("/api/periods", json={"label": "Période 1", "sort": 0}, headers=ctx["h"])
        periodes = self.c.get("/api/periods", headers=ctx["h"]).get_json()["periods"]
        p1 = [p for p in periodes if p["label"] == "Période 1"][0]
        r = self.c.post(f"/api/classes/{ctx['class']['id']}/grades", json={
            "period": "Période 1", "subject": "Mathématiques",
            "entries": [{"student_id": eleve, "score": 14, "max_score": 20}]}, headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        self.decider(ctx, eleve, "PASSAGE")
        plan = self.plan(ctx)
        cible = self.classe_cible(ctx, plan["id"], "6e A")
        self.c.patch(f"/api/promotion-plans/{plan['id']}/assignments/{eleve}",
                     json={"target_class_id": cible}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{plan['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{plan['id']}/apply",
                    json={"confirm": True}, headers=ctx["h"])

        # L'élève est passé. On proclame maintenant la période de l'an dernier.
        pub = self.c.post(f"/api/periods/{p1['id']}/publish", json={}, headers=ctx["h"])
        self.assertEqual(pub.status_code, 200, pub.get_data(as_text=True))
        self.assertEqual(pub.get_json().get("included"), 1,
                         "la proclamation n'a atteint personne")

        inv = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [eleve]}, headers=ctx["h"]).get_json()
        u = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "parent.proc@promo.test",
            "password": "Secret123!"}).get_json()
        hp = {"Authorization": f"Bearer {u['token']}"}
        dossier = self.c.get(f"/api/students/{eleve}", headers=hp).get_json()
        vus = [(x["period"], x["score"]) for x in (dossier.get("grades") or [])]
        self.assertEqual(vus, [("Période 1", 14.0)],
                         f"le parent ne voit pas les résultats de l'année terminée : {vus}")


# ---------------------------------------------------------------------------
# Le cycle : une donnée déclarée, jamais redevinée
# ---------------------------------------------------------------------------# ---------------------------------------------------------------------------
# Le cycle : une donnée déclarée, jamais redevinée
# ---------------------------------------------------------------------------

class CycleExplicite(Base):

    def creer_classe(self, ctx, nom, level=None, cycle=None, annee=None):
        corps = {"academic_year_id": annee or ctx["year"], "name": nom}
        if level:
            corps["level"] = level
        if cycle:
            corps["cycle"] = cycle
        r = self.c.post("/api/classes", json=corps, headers=ctx["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()

    def test_un_cycle_declare_fait_foi(self):
        """LE PRINCIPE. Ce que la Direction déclare ne se redevine jamais."""
        ctx = self.ecole("cycledeclare")
        c = self.creer_classe(ctx, "5e Scientifique A", level="5e", cycle="secondaire")
        self.assertEqual(c["cycle"], "secondaire")
        self.assertEqual(c["cycle_source"], "declare")

    def test_une_classe_a_section_nest_plus_rangee_en_primaire(self):
        """« 5e Scientifique A » tombait en primaire : le chiffre l'emportait
        sur la section. Deux systèmes coexistent en RDC et numérotent
        différemment ; seule la section lève le doute dans les deux."""
        ctx = self.ecole("cyclesection")
        for nom, level in [("5e Scientifique A", "5e"), ("3e Littéraire B", "3e"),
                           ("2e Pédagogique", "2e"), ("6e Commerciale A", "6e")]:
            c = self.creer_classe(ctx, nom, level=level)
            self.assertEqual(c["cycle"], "secondaire", f"{nom} rangée en {c['cycle']}")
            self.assertEqual(c["cycle_source"], "deduit", "une déduction se dit déduite")

    def test_les_classes_primaires_restent_primaires(self):
        ctx = self.ecole("cycleprimaire")
        for nom, level in [("4e année primaire", "4e"), ("6e A", "6e"), ("2e B", "2e")]:
            c = self.creer_classe(ctx, nom, level=level)
            self.assertEqual(c["cycle"], "primaire", f"{nom} rangée en {c['cycle']}")

    def test_un_secondaire_sans_section_est_reconnu(self):
        ctx = self.ecole("cyclesecondaire")
        for nom, level in [("7e A", "7e"), ("8e B", "8e"),
                           ("1re Humanités", "1re"), ("Secondaire 2", None)]:
            c = self.creer_classe(ctx, nom, level=level)
            self.assertEqual(c["cycle"], "secondaire", f"{nom} rangée en {c['cycle']}")

    def test_la_maternelle_reste_reconnue(self):
        ctx = self.ecole("cyclematernelle")
        for nom in ("Maternelle 2", "Jardin d'enfants", "Pré-scolaire A"):
            self.assertEqual(self.creer_classe(ctx, nom)["cycle"], "maternelle")

    def test_corriger_le_cycle_le_rend_declare(self):
        ctx = self.ecole("cyclecorrige")
        c = self.creer_classe(ctx, "5e A", level="5e")
        self.assertEqual(c["cycle_source"], "deduit")
        r = self.c.put(f"/api/classes/{c['id']}", json={"cycle": "secondaire"}, headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        cls = self.c.get(f"/api/classes/{c['id']}", headers=ctx["h"]).get_json()
        self.assertEqual(cls["cycle"], "secondaire")
        self.assertEqual(cls["cycle_source"], "declare")

    def test_la_copie_conserve_le_cycle_au_lieu_de_le_redeviner(self):
        """LE POINT QUI COMPTE POUR LE PASSAGE D'ANNÉE.

        Redéduire le cycle à chaque rentrée rejouerait l'approximation
        d'origine — et effacerait la correction que la Direction aurait faite
        entre-temps. La copie recopie, elle ne recalcule pas.
        """
        ctx = self.ecole("cyclecopie")
        # Une classe dont le cycle DÉCLARÉ contredit ce qu'on devinerait.
        corrigee = self.creer_classe(ctx, "5e A", level="5e", cycle="secondaire")
        self.creer_classe(ctx, "3e Littéraire", level="3e")   # déduit secondaire
        p = self.plan(ctx)
        r = self.c.post(f"/api/promotion-plans/{p['id']}/copy-classes", headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        copies = {c["name"]: c for c in self.c.get(
            f"/api/classes?academic_year_id={p['target_year_id']}", headers=ctx["h"]).get_json()}
        self.assertEqual(copies["5e A"]["cycle"], "secondaire",
                         "le cycle déclaré a été redeviné à la copie")
        self.assertEqual(copies["5e A"]["cycle_source"], "declare",
                         "une classe déclarée est redevenue une déduction")
        self.assertEqual(copies["3e Littéraire"]["cycle"], "secondaire")
        self.assertEqual(copies["3e Littéraire"]["cycle_source"], "deduit")
        # Et la classe d'origine n'a pas bougé.
        self.assertEqual(self.c.get(f"/api/classes/{corrigee['id']}",
                                    headers=ctx["h"]).get_json()["cycle"], "secondaire")


# ---------------------------------------------------------------------------
# Le titulaire consulte, il ne pilote pas
# ---------------------------------------------------------------------------

class VisibiliteTitulaire(Base):

    def enseignant(self, ctx, mail, class_ids, titulaire=None):
        payload = {"role": "professeur", "class_ids": class_ids}
        if titulaire:
            payload["titulaire_class_id"] = titulaire
        inv = self.c.post("/api/invitations", json=payload, headers=ctx["h"]).get_json()
        u = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof", "email": mail,
            "password": "Secret123!"}).get_json()
        return {"Authorization": f"Bearer {u['token']}"}

    def deux_classes(self, suffixe):
        ctx = self.ecole(suffixe)
        autre = self.c.post("/api/classes", json={
            "academic_year_id": ctx["year"], "name": "5e B"}, headers=ctx["h"]).get_json()
        self.c.post("/api/students", json={
            "academic_year_id": ctx["year"], "class_id": autre["id"],
            "first_name": "Eve", "last_name": "Zoulou"}, headers=ctx["h"])
        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        p = self.plan(ctx)
        return ctx, autre, p

    def test_le_titulaire_consulte_le_plan_de_sa_classe(self):
        ctx, autre, p = self.deux_classes("titvoit")
        h = self.enseignant(ctx, "tit1@promo.test", [ctx["class"]["id"]],
                            titulaire=ctx["class"]["id"])
        liste = self.c.get("/api/promotion-plans", headers=h)
        self.assertEqual(liste.status_code, 200, liste.get_data(as_text=True))
        corps = liste.get_json()
        self.assertEqual(len(corps["plans"]), 1)
        self.assertEqual(corps["plans"][0]["student_count"], 3, "effectif hors périmètre")
        self.assertFalse(corps["peut_piloter"])

        detail = self.c.get(f"/api/promotion-plans/{p['id']}", headers=h)
        self.assertEqual(detail.status_code, 200, detail.get_data(as_text=True))
        d = detail.get_json()
        # Il voit ses élèves, leurs décisions et la destination proposée.
        self.assertEqual(len(d["assignments"]), 3)
        self.assertTrue(all(a["source_class_id"] == ctx["class"]["id"] for a in d["assignments"]))
        self.assertTrue(all(a["action"] == "PASSAGE" for a in d["assignments"]))
        self.assertIn("target_class_id", d["assignments"][0])
        # Mais l'écran ne lui propose rien à modifier.
        self.assertFalse(d["modifiable"])
        self.assertFalse(d["peut_piloter"])

    def test_le_titulaire_ne_voit_pas_la_classe_dun_collegue(self):
        ctx, autre, p = self.deux_classes("titcloison")
        h = self.enseignant(ctx, "tit2@promo.test", [ctx["class"]["id"]],
                            titulaire=ctx["class"]["id"])
        d = self.c.get(f"/api/promotion-plans/{p['id']}", headers=h).get_json()
        self.assertEqual([c["id"] for c in d["classes_source"]], [ctx["class"]["id"]])
        noms = [a["last_name"] for a in d["assignments"]]
        self.assertNotIn("Zoulou", noms, "un élève d'une autre classe a fuité")
        # Et le demander explicitement ne donne rien.
        force = self.c.get(f"/api/promotion-plans/{p['id']}?source_class_id={autre['id']}",
                           headers=h)
        self.assertEqual(force.status_code, 404)

    def test_le_titulaire_ne_pilote_rien(self):
        """Le refus est au serveur. Masquer les boutons ne protège personne."""
        ctx, autre, p = self.deux_classes("titrefus")
        h = self.enseignant(ctx, "tit3@promo.test", [ctx["class"]["id"]],
                            titulaire=ctx["class"]["id"])
        eleve = ctx["students"][0]["id"]
        interdits = [
            ("POST", f"/api/promotion-plans/{p['id']}/status", {"status": "VALIDE"}),
            ("POST", f"/api/promotion-plans/{p['id']}/apply", {"confirm": True}),
            ("POST", f"/api/promotion-plans/{p['id']}/distribute",
             {"source_class_id": ctx["class"]["id"], "target_class_ids": [autre["id"]]}),
            ("POST", f"/api/promotion-plans/{p['id']}/copy-classes", {}),
            ("POST", f"/api/promotion-plans/{p['id']}/refresh", {}),
            ("PATCH", f"/api/promotion-plans/{p['id']}/assignments/{eleve}",
             {"action": "REDOUBLEMENT"}),
            ("POST", f"/api/students/{eleve}/class-correction",
             {"class_id": autre["id"], "reason": "Essai."}),
            ("POST", "/api/promotion-plans",
             {"source_year_id": ctx["year"], "target_year_label": "2099-2100"}),
        ]
        for methode, chemin, corps in interdits:
            r = self.c.open(chemin, method=methode, json=corps, headers=h)
            self.assertEqual(r.status_code, 403, f"{methode} {chemin} → {r.status_code}")

    def test_un_professeur_non_titulaire_nentre_pas(self):
        """Enseigner dans une classe n'est pas la préparer."""
        ctx, autre, p = self.deux_classes("nontit")
        h = self.enseignant(ctx, "simple@promo.test", [ctx["class"]["id"]])
        self.assertEqual(self.c.get("/api/promotion-plans", headers=h).status_code, 403)
        self.assertEqual(self.c.get(f"/api/promotion-plans/{p['id']}", headers=h).status_code, 403)

    def test_le_dd_et_le_parent_nentrent_pas(self):
        """Le DD dépose des éléments disciplinaires en délibération ; il ne
        devient pas décideur du passage, ni lecteur du plan."""
        ctx, autre, p = self.deux_classes("ddparent")
        inv = self.c.post("/api/invitations", json={
            "role": "discipline", "scope_cycles": ["secondaire"]}, headers=ctx["h"]).get_json()
        dd = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "DD", "email": "dd@promo.test",
            "password": "Secret123!"}).get_json()
        hdd = {"Authorization": f"Bearer {dd['token']}"}
        self.assertEqual(self.c.get("/api/promotion-plans", headers=hdd).status_code, 403)
        self.assertEqual(self.c.get(f"/api/promotion-plans/{p['id']}", headers=hdd).status_code, 403)

        inv2 = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [ctx["students"][0]["id"]]},
            headers=ctx["h"]).get_json()
        par = self.c.post("/api/invitations/accept", json={
            "token": inv2["token"], "name": "Parent", "email": "par@promo.test",
            "password": "Secret123!"}).get_json()
        hpar = {"Authorization": f"Bearer {par['token']}"}
        self.assertEqual(self.c.get("/api/promotion-plans", headers=hpar).status_code, 403)
        self.assertEqual(self.c.get(f"/api/promotion-plans/{p['id']}", headers=hpar).status_code, 403)

    def test_un_titulaire_dune_autre_ecole_ne_voit_rien(self):
        ctx, autre, p = self.deux_classes("titiso")
        b = self.ecole("titisoB")
        hb = self.enseignant(b, "titb@promo.test", [b["class"]["id"]],
                             titulaire=b["class"]["id"])
        r = self.c.get(f"/api/promotion-plans/{p['id']}", headers=hb)
        self.assertEqual(r.status_code, 404, "un plan a fuité entre établissements")


# ---------------------------------------------------------------------------
# Corriger après application — local, motivé, tracé
# ---------------------------------------------------------------------------

class CorrectionApresApplication(Base):

    def _rentree_faite(self, suffixe):
        noms = ["Alpha", "Bravo", "Charlie"]
        ctx = self.ecole(suffixe, eleves=noms)
        for e in ctx["students"]:
            self.decider(ctx, e["id"], "PASSAGE")
        p = self.plan(ctx)
        a = self.classe_cible(ctx, p["id"], "6e A")
        b = self.classe_cible(ctx, p["id"], "6e B")
        for e in ctx["students"]:
            self.c.patch(f"/api/promotion-plans/{p['id']}/assignments/{e['id']}",
                         json={"target_class_id": a}, headers=ctx["h"])
        self.c.post(f"/api/promotion-plans/{p['id']}/status",
                    json={"status": "VALIDE"}, headers=ctx["h"])
        r = self.c.post(f"/api/promotion-plans/{p['id']}/apply",
                        json={"confirm": True}, headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return ctx, p, a, b

    def test_corriger_un_eleve_sans_defaire_la_rentree(self):
        ctx, p, a, b = self._rentree_faite("corrige")
        eleve = ctx["students"][0]["id"]
        r = self.c.post(f"/api/students/{eleve}/class-correction", json={
            "class_id": b, "reason": "Erreur de répartition : devait être en 6e B."},
            headers=ctx["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["ancienne_classe_id"], a)
        self.assertEqual(r.get_json()["nouvelle_classe_id"], b)
        # L'élève a bougé, son identité n'a pas changé.
        dossier = self.c.get(f"/api/students/{eleve}", headers=ctx["h"]).get_json()["student"]
        self.assertEqual(dossier["id"], eleve)
        self.assertEqual(dossier["class"]["id"], b)
        # Les autres n'ont pas bougé : la correction est LOCALE.
        for e in ctx["students"][1:]:
            autre = self.c.get(f"/api/students/{e['id']}", headers=ctx["h"]).get_json()["student"]
            self.assertEqual(autre["class"]["id"], a)

    def test_la_classe_quittee_et_le_motif_sont_conserves(self):
        ctx, p, a, b = self._rentree_faite("trace")
        eleve = ctx["students"][0]["id"]
        self.c.post(f"/api/students/{eleve}/class-correction", json={
            "class_id": b, "reason": "Effectif déséquilibré."}, headers=ctx["h"])
        parcours = self.c.get(f"/api/students/{eleve}/enrollments",
                              headers=ctx["h"]).get_json()["parcours"]
        courante = [x for x in parcours if x["courante"]][0]
        self.assertEqual(courante["class_id"], b)
        self.assertEqual(courante["previous_class_name"], "6e A",
                         "la classe quittée a été effacée par la correction")
        self.assertEqual(courante["corrected_reason"], "Effectif déséquilibré.")
        self.assertTrue(courante["corrected_at"])
        self.assertTrue(courante["corrected_by_name"])

    def test_lhistorique_de_lannee_precedente_nest_pas_touche(self):
        ctx, p, a, b = self._rentree_faite("histoire")
        eleve = ctx["students"][0]["id"]
        avant = [x for x in self.c.get(f"/api/students/{eleve}/enrollments",
                                       headers=ctx["h"]).get_json()["parcours"]
                 if not x["courante"]][0]
        self.c.post(f"/api/students/{eleve}/class-correction", json={
            "class_id": b, "reason": "Correction."}, headers=ctx["h"])
        apres = [x for x in self.c.get(f"/api/students/{eleve}/enrollments",
                                       headers=ctx["h"]).get_json()["parcours"]
                 if not x["courante"]][0]
        self.assertEqual(apres, avant, "l'année passée a été réécrite")

    def test_une_correction_sans_motif_est_refusee(self):
        ctx, p, a, b = self._rentree_faite("motif")
        eleve = ctx["students"][0]["id"]
        for corps in ({"class_id": b}, {"class_id": b, "reason": "  "},
                      {"class_id": b, "reason": "x"}):
            r = self.c.post(f"/api/students/{eleve}/class-correction",
                            json=corps, headers=ctx["h"])
            self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
        dossier = self.c.get(f"/api/students/{eleve}", headers=ctx["h"]).get_json()["student"]
        self.assertEqual(dossier["class"]["id"], a, "l'élève a bougé sans motif")

    def test_on_ne_renvoie_pas_un_eleve_dans_une_annee_archivee(self):
        """Renvoyer un élève dans une classe de l'an dernier n'est pas une
        correction : c'est une corruption de l'historique."""
        ctx, p, a, b = self._rentree_faite("archivee")
        eleve = ctx["students"][0]["id"]
        r = self.c.post(f"/api/students/{eleve}/class-correction", json={
            "class_id": ctx["class"]["id"], "reason": "Retour en arrière."},
            headers=ctx["h"])
        self.assertEqual(r.status_code, 404)
        # Le chemin générique est fermé lui aussi.
        r2 = self.c.put(f"/api/students/{eleve}",
                        json={"class_id": ctx["class"]["id"]}, headers=ctx["h"])
        self.assertEqual(r2.status_code, 404, "l'élève a pu repartir dans l'année archivée")

    def test_la_correction_laisse_une_entree_daudit(self):
        ctx, p, a, b = self._rentree_faite("audit")
        eleve = ctx["students"][0]["id"]
        self.c.post(f"/api/students/{eleve}/class-correction", json={
            "class_id": b, "reason": "Erreur de saisie."}, headers=ctx["h"])
        lignes = self.c.get("/api/audit-logs", headers=ctx["h"]).get_json()
        trace = [x for x in lignes if x.get("action") == "student.class_corrected"]
        self.assertEqual(len(trace), 1, "aucune trace d'audit")
        self.assertEqual(trace[0]["resource_id"], eleve)

    def test_une_correction_dun_autre_etablissement_est_refusee(self):
        ctx, p, a, b = self._rentree_faite("corriso")
        autre = self.ecole("corrisoB")
        r = self.c.post(f"/api/students/{autre['students'][0]['id']}/class-correction",
                        json={"class_id": b, "reason": "Tentative."}, headers=ctx["h"])
        self.assertEqual(r.status_code, 404)
        r2 = self.c.post(f"/api/students/{ctx['students'][0]['id']}/class-correction",
                         json={"class_id": autre["class"]["id"], "reason": "Tentative."},
                         headers=ctx["h"])
        self.assertEqual(r2.status_code, 404)
