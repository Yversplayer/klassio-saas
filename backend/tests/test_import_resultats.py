"""KLASSIO — import des résultats officiels, éprouvé.

Ce que ces tests défendent, dans l'ordre d'importance :

1. **Le nom n'est pas un identifiant.** Le rapprochement se fait sur le code
   élève ; un rapprochement par nom seul est signalé, jamais validé d'office ;
   deux homonymes produisent une erreur, pas un choix arbitraire.

2. **Rien d'ambigu n'entre en base.** Une seule ligne en erreur bloque tout
   l'import. Klassio préfère renvoyer le fichier à la Direction plutôt que
   d'écrire un résultat dont il n'est pas sûr.

3. **Un élève absent du fichier n'a pas zéro.** Il n'a pas de résultat — une
   information différente, remontée telle quelle.

4. **L'historique ne s'écrase pas.** Une seconde version ne supprime pas la
   première : elle la remplace comme version courante, et la première reste
   lisible.

5. **Le navigateur ne décide de rien.** Les compteurs, les élèves rapprochés et
   la version sont relus côté serveur à la confirmation.
"""
import io
import json
import os
import sys
import threading
import unittest

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


EN_TETES = "Identifiant,Nom,Classe,Matiere,Periode,Resultat,Bareme\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    # ---- fabrique -------------------------------------------------------
    def ecole(self, suffixe, eleves=None, periode="Période 1"):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@test.local", "password": "Secret123!",
            "name": "Directeur", "school_name": f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        corps = r.get_json()
        e = {"h": {"Authorization": f"Bearer {corps['token']}"}, "tenant": corps["tenant_id"]}
        e["year"] = self.c.get("/api/academic-years", headers=e["h"]).get_json()[0]["id"]
        e["classe"] = self.c.post("/api/classes", json={
            "name": "6e A", "academic_year_id": e["year"], "cycle": "secondaire"},
            headers=e["h"]).get_json()["id"]
        e["eleves"] = {}
        for prenom, nom in (eleves or [("Audrey", "Mukendi"), ("Kevin", "Kalala")]):
            rep = self.c.post("/api/students", json={
                "first_name": prenom, "last_name": nom,
                "academic_year_id": e["year"], "class_id": e["classe"]}, headers=e["h"]).get_json()
            e["eleves"][f"{prenom} {nom}"] = {"id": rep["id"], "code": rep["code"]}
        e["pid"] = self.c.post("/api/periods", json={"label": periode, "sort": 0},
                               headers=e["h"]).get_json()["id"]
        e["periode"] = periode
        return e

    def fichier(self, lignes, entetes=EN_TETES):
        return (io.BytesIO((entetes + "".join(lignes)).encode("utf-8")), "resultats.csv")

    def ligne(self, e, nom_eleve, matiere="Mathématiques", note="14", bareme="20",
              code=None, classe="6e A", periode=None):
        c = code if code is not None else e["eleves"][nom_eleve]["code"]
        return f"{c},{nom_eleve},{classe},{matiere},{periode or e['periode']},{note},{bareme}\n"

    def analyser(self, e, lignes, entetes=EN_TETES, headers=None, period_id=None):
        return self.c.post("/api/results/imports",
                           data={"file": self.fichier(lignes, entetes),
                                 "period_id": period_id or e["pid"]},
                           content_type="multipart/form-data",
                           headers=headers or e["h"])

    def confirmer(self, e, import_id, headers=None):
        return self.c.post(f"/api/results/imports/{import_id}/confirm",
                           json={}, headers=headers or e["h"])

    def notes_en_base(self, tenant, courantes_seulement=True):
        conn = db.get_connection()
        sql = "SELECT * FROM grades WHERE tenant_id=?"
        if courantes_seulement:
            sql += " AND is_current=1"
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY version, subject", (tenant,))]
        conn.close()
        return rows


# =========================================================================
# Lecture du fichier et détection des colonnes
# =========================================================================

class LectureDuFichier(Base):
    def test_01_un_fichier_valide_est_analyse_sans_rien_ecrire(self):
        e = self.ecole("imp1")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi"), self.ligne(e, "Kevin Kalala")])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertEqual(corps["total_rows"], 2)
        self.assertEqual(corps["matched"], 2)
        self.assertEqual(corps["errors"], 0)
        self.assertFalse(corps["blocking"])
        self.assertEqual(self.notes_en_base(e["tenant"]), [],
                         "l'analyse a écrit des résultats — elle ne doit rien écrire")

    def test_02_les_colonnes_sont_detectees_quel_que_soit_leur_intitule(self):
        """Aucune école ne renommera ses colonnes pour Klassio."""
        e = self.ecole("imp2")
        entetes = "Code Élève,Nom complet,Section,Branche,Trimestre,Cote /20,Divers\n"
        code = e["eleves"]["Audrey Mukendi"]["code"]
        r = self.analyser(e, [f"{code},Audrey Mukendi,6e A,Français,Période 1,15,rien\n"], entetes)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        corps = r.get_json()
        champs = {m["field"] for m in corps["mapping"]}
        for attendu in ("student_code", "subject", "score", "class_name", "period"):
            self.assertIn(attendu, champs, f"{attendu} non détecté dans {corps['mapping']}")
        self.assertEqual(corps["matched"], 1)

    def test_03_le_bareme_peut_venir_de_lentete(self):
        e = self.ecole("imp3")
        entetes = "Identifiant,Nom,Classe,Matiere,Periode,Note sur 100\n"
        code = e["eleves"]["Audrey Mukendi"]["code"]
        r = self.analyser(e, [f"{code},Audrey Mukendi,6e A,Maths,Période 1,87\n"], entetes)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["errors"], 0,
                         "87 doit être valide sur un barème de 100 lu dans l'en-tête")

    def test_04_les_notes_a_la_francaise_sont_lues(self):
        e = self.ecole("imp4")
        # La virgule décimale doit être protégée, sinon le lecteur CSV coupe le champ.
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note='"14,5"')])
        self.assertEqual(r.get_json()["errors"], 0)
        self.assertEqual(r.get_json()["matched"], 1)

    def test_05_un_fichier_inexploitable_est_refuse_clairement(self):
        e = self.ecole("imp5")
        cas = [
            ("vide", [], ""),
            ("en-têtes seuls", [], EN_TETES),
            ("aucune colonne de note", ["x,y\n"], "Couleur,Taille\n"),
            ("aucune colonne d'élève", ["Maths,12\n"], "Matiere,Note\n"),
        ]
        for libelle, lignes, entetes in cas:
            with self.subTest(cas=libelle):
                r = self.analyser(e, lignes, entetes)
                self.assertEqual(r.status_code, 400,
                                 f"{libelle} → {r.status_code} : {r.get_data(as_text=True)[:120]}")
                self.assertNotIn("interne", (r.get_json() or {}).get("error", "").lower())

    def test_06_un_xlsx_abime_est_refuse_sans_erreur_interne(self):
        e = self.ecole("imp6")
        r = self.c.post("/api/results/imports",
                        data={"file": (io.BytesIO(b"pas une archive zip"), "resultats.xlsx"),
                              "period_id": e["pid"]},
                        content_type="multipart/form-data", headers=e["h"])
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))


# =========================================================================
# Rapprochement des élèves
# =========================================================================

class RapprochementDesEleves(Base):
    def test_07_le_code_eleve_prime_sur_le_nom(self):
        """Le fichier porte un nom faux mais le bon code : c'est le code qui gagne."""
        e = self.ecole("match1")
        code = e["eleves"]["Audrey Mukendi"]["code"]
        r = self.analyser(e, [f"{code},Nom Totalement Faux,6e A,Maths,Période 1,14,20\n"])
        corps = r.get_json()
        self.assertEqual(corps["matched"], 1)
        self.assertEqual(corps["errors"], 0)
        ligne = corps["rows_sample"][0]
        self.assertEqual(ligne["match_by"], "code")
        self.assertEqual(ligne["matched_name"], "Audrey Mukendi")

    def test_08_un_code_inconnu_est_une_erreur_bloquante(self):
        e = self.ecole("match2")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi"),
                              f"STU-9999-9999,Fantôme Inexistant,6e A,Maths,Période 1,10,20\n"])
        corps = r.get_json()
        self.assertEqual(corps["errors"], 1)
        self.assertTrue(corps["blocking"])
        self.assertIn("introuvable", corps["problems"][0]["issues"][0])

    def test_09_un_rapprochement_par_nom_seul_est_signale_jamais_valide(self):
        e = self.ecole("match3")
        entetes = "Nom,Classe,Matiere,Periode,Resultat,Bareme\n"
        r = self.analyser(e, ["Audrey Mukendi,6e A,Maths,Période 1,14,20\n"], entetes)
        corps = r.get_json()
        self.assertEqual(corps["warnings"], 1, "un rapprochement par nom doit alerter")
        self.assertEqual(corps["matched"], 0)
        self.assertEqual(corps["errors"], 0)
        ligne = corps["problems"][0]
        self.assertEqual(ligne["match_by"], "name")
        self.assertIn("NOM seul", " ".join(ligne["issues"]))

    def test_10_deux_homonymes_sans_code_produisent_une_erreur(self):
        """Klassio ne choisit jamais entre deux élèves du même nom."""
        e = self.ecole("match4", eleves=[("Audrey", "Mukendi"), ("Audrey", "Mukendi")])
        entetes = "Nom,Classe,Matiere,Periode,Resultat,Bareme\n"
        r = self.analyser(e, ["Audrey Mukendi,6e A,Maths,Période 1,14,20\n"], entetes)
        corps = r.get_json()
        self.assertEqual(corps["errors"], 1)
        self.assertIn("identifiant est nécessaire", " ".join(corps["problems"][0]["issues"]))

    def test_11_un_code_dun_autre_etablissement_ne_correspond_a_rien(self):
        a = self.ecole("match5a")
        b = self.ecole("match5b")
        code_b = b["eleves"]["Audrey Mukendi"]["code"]
        r = self.analyser(a, [f"{code_b},Audrey Mukendi,6e A,Maths,Période 1,14,20\n"])
        corps = r.get_json()
        self.assertEqual(corps["errors"], 1,
                         "un code d'un autre établissement a été rapproché")
        self.assertIsNone(corps["problems"][0]["student_id"])

    def test_12_un_doublon_dans_le_fichier_est_bloquant(self):
        e = self.ecole("match6")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="14"),
                              self.ligne(e, "Audrey Mukendi", note="18")])
        corps = r.get_json()
        self.assertEqual(corps["errors"], 1)
        self.assertIn("doublon", " ".join(corps["problems"][0]["issues"]).lower())

    def test_13_deux_matieres_pour_le_meme_eleve_ne_sont_pas_un_doublon(self):
        e = self.ecole("match7")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi", matiere="Maths"),
                              self.ligne(e, "Audrey Mukendi", matiere="Français")])
        self.assertEqual(r.get_json()["errors"], 0)
        self.assertEqual(r.get_json()["matched"], 2)

    def test_14_une_note_hors_bareme_est_bloquante(self):
        e = self.ecole("match8")
        for libelle, note in (("supérieure au barème", "25"), ("négative", "-3"),
                              ("illisible", "très bien"), ("absente", "")):
            with self.subTest(note=libelle):
                r = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note=note)])
                self.assertEqual(r.get_json()["errors"], 1, f"note {libelle} acceptée")

    def test_15_une_periode_differente_de_celle_de_limport_est_bloquante(self):
        """Importer des résultats de Période 2 dans la Période 1 serait une
        erreur silencieuse et irrattrapable."""
        e = self.ecole("match9")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi", periode="Période 2")])
        corps = r.get_json()
        self.assertEqual(corps["errors"], 1)
        self.assertIn("période", " ".join(corps["problems"][0]["issues"]).lower())

    def test_16_une_classe_divergente_alerte_sans_bloquer(self):
        e = self.ecole("match10")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi", classe="5e B")])
        corps = r.get_json()
        self.assertEqual(corps["errors"], 0, "une classe divergente ne doit pas bloquer")
        self.assertEqual(corps["warnings"], 1)

    def test_17_les_eleves_absents_du_fichier_sont_nommes_pas_mis_a_zero(self):
        e = self.ecole("match11")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi")])
        corps = r.get_json()
        self.assertEqual(corps["students_expected"], 2)
        self.assertEqual(corps["students_in_file"], 1)
        absents = corps["students_without_result"]
        self.assertEqual(len(absents), 1)
        self.assertEqual(absents[0]["name"], "Kevin Kalala")

        # …et après confirmation, cet élève n'a AUCUNE note — pas un zéro.
        self.confirmer(e, corps["import_id"])
        notes = self.notes_en_base(e["tenant"])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["student_id"], e["eleves"]["Audrey Mukendi"]["id"])


# =========================================================================
# Confirmation, versionnage, historique
# =========================================================================

class ConfirmationEtVersions(Base):
    def test_18_la_confirmation_ecrit_les_resultats_en_version_1(self):
        e = self.ecole("conf1")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="14"),
                                  self.ligne(e, "Kevin Kalala", note="16")]).get_json()
        r = self.confirmer(e, corps["import_id"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        rep = r.get_json()
        self.assertEqual(rep["results_written"], 2)
        self.assertEqual(rep["version"], 1)
        self.assertFalse(rep["published"], "l'import ne doit jamais publier")

        notes = self.notes_en_base(e["tenant"])
        self.assertEqual(len(notes), 2)
        self.assertTrue(all(n["source"] == "import" for n in notes))
        self.assertTrue(all(n["period_id"] == e["pid"] for n in notes))
        self.assertTrue(all(n["result_import_id"] == corps["import_id"] for n in notes))

    def test_19_une_erreur_bloque_la_confirmation(self):
        e = self.ecole("conf2")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi"),
                                  "STU-0000-0000,Inconnu,6e A,Maths,Période 1,10,20\n"]).get_json()
        r = self.confirmer(e, corps["import_id"])
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertEqual(self.notes_en_base(e["tenant"]), [],
                         "des résultats ont été écrits malgré une ligne en erreur")

    def test_20_une_seconde_version_remplace_sans_effacer(self):
        e = self.ecole("conf3")
        c1 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="8")]).get_json()
        self.confirmer(e, c1["import_id"])
        c2 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="17")]).get_json()
        self.assertEqual(c2["next_version"], 2)
        r = self.confirmer(e, c2["import_id"])
        self.assertEqual(r.get_json()["version"], 2)

        courantes = self.notes_en_base(e["tenant"])
        self.assertEqual(len(courantes), 1)
        self.assertEqual(courantes[0]["score"], 17.0)
        self.assertEqual(courantes[0]["version"], 2)

        toutes = self.notes_en_base(e["tenant"], courantes_seulement=False)
        self.assertEqual(len(toutes), 2, "la version 1 a été supprimée")
        ancienne = [n for n in toutes if n["version"] == 1][0]
        self.assertEqual(ancienne["score"], 8.0)
        self.assertEqual(ancienne["is_current"], 0)
        self.assertTrue(ancienne["superseded_at"], "la version remplacée n'est pas datée")
        self.assertEqual(ancienne["superseded_by"], c2["import_id"])

    def test_21_lhistorique_expose_les_deux_versions(self):
        e = self.ecole("conf4")
        c1 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="8")]).get_json()
        self.confirmer(e, c1["import_id"])
        c2 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="17")]).get_json()
        self.confirmer(e, c2["import_id"])
        eleve = e["eleves"]["Audrey Mukendi"]["id"]
        r = self.c.get(f"/api/results/history?student_id={eleve}", headers=e["h"])
        self.assertEqual(r.status_code, 200)
        versions = r.get_json()
        self.assertEqual([v["version"] for v in versions], [2, 1])
        self.assertEqual([v["is_current"] for v in versions], [1, 0])

    def test_22_une_autre_periode_nest_pas_touchee_par_une_nouvelle_version(self):
        e = self.ecole("conf5")
        p2 = self.c.post("/api/periods", json={"label": "Période 2", "sort": 1},
                         headers=e["h"]).get_json()["id"]
        c1 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="8")]).get_json()
        self.confirmer(e, c1["import_id"])
        c2 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="12", periode="Période 2")],
                           period_id=p2).get_json()
        self.confirmer(e, c2["import_id"])
        # Réimport de la période 1 : la période 2 ne bouge pas.
        c3 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="19")]).get_json()
        self.confirmer(e, c3["import_id"])

        courantes = self.notes_en_base(e["tenant"])
        par_periode = {n["period_id"]: n for n in courantes}
        self.assertEqual(par_periode[e["pid"]]["score"], 19.0)
        self.assertEqual(par_periode[p2]["score"], 12.0,
                         "la période 2 a été affectée par un réimport de la période 1")
        self.assertEqual(par_periode[p2]["version"], 1)

    def test_23_confirmer_deux_fois_ne_produit_quune_version(self):
        e = self.ecole("conf6")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).get_json()
        self.assertEqual(self.confirmer(e, corps["import_id"]).status_code, 200)
        second = self.confirmer(e, corps["import_id"])
        self.assertEqual(second.status_code, 409)
        self.assertEqual(len(self.notes_en_base(e["tenant"], courantes_seulement=False)), 1)

    TOURS = 10

    def test_24_deux_confirmations_simultanees_nen_produisent_quune(self):
        anomalies = []
        for tour in range(self.TOURS):
            security.reset_rate_limits_for_tests()
            e = self.ecole(f"conf7-{tour}")
            corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi"),
                                      self.ligne(e, "Kevin Kalala")]).get_json()
            barriere = threading.Barrier(2)
            codes = {}

            def confirmer(n):
                client = flask_app_module.app.test_client()
                barriere.wait()
                codes[n] = client.post(f"/api/results/imports/{corps['import_id']}/confirm",
                                       json={}, headers=e["h"]).status_code

            fils = [threading.Thread(target=confirmer, args=(i,)) for i in (1, 2)]
            for f in fils:
                f.start()
            for f in fils:
                f.join()

            toutes = self.notes_en_base(e["tenant"], courantes_seulement=False)
            if len(toutes) != 2:
                anomalies.append(f"tour {tour} : {len(toutes)} notes écrites (2 attendues), codes {codes}")
        self.assertEqual(anomalies, [],
                         f"{len(anomalies)}/{self.TOURS} tours ont dupliqué l'import :\n  "
                         + "\n  ".join(anomalies))

    def test_25_un_import_annule_nest_plus_confirmable(self):
        e = self.ecole("conf8")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).get_json()
        self.assertEqual(self.c.post(f"/api/results/imports/{corps['import_id']}/cancel",
                                     json={}, headers=e["h"]).status_code, 200)
        self.assertEqual(self.confirmer(e, corps["import_id"]).status_code, 409)
        self.assertEqual(self.notes_en_base(e["tenant"]), [])

    def test_26_letat_se_retrouve_apres_un_rafraichissement(self):
        """L'interface ne garde rien en mémoire : elle redemande au serveur."""
        e = self.ecole("conf9")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi"),
                                  "STU-0000-0000,Inconnu,6e A,Maths,Période 1,10,20\n"]).get_json()
        r = self.c.get(f"/api/results/imports/{corps['import_id']}", headers=e["h"])
        self.assertEqual(r.status_code, 200)
        relu = r.get_json()
        self.assertEqual(relu["total_rows"], corps["total_rows"])
        self.assertEqual(relu["errors"], corps["errors"])
        self.assertEqual(relu["state"], "PREVIEW_READY")
        self.assertEqual(len(relu["problems"]), 1)

        self.confirmer(e, corps["import_id"])   # refusée (erreur bloquante)
        self.assertEqual(self.c.get(f"/api/results/imports/{corps['import_id']}",
                                    headers=e["h"]).get_json()["state"], "PREVIEW_READY")

    def test_27_une_periode_verrouillee_refuse_lanalyse_et_la_confirmation(self):
        e = self.ecole("conf10")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).get_json()
        self.c.post(f"/api/periods/{e['pid']}/lock", json={}, headers=e["h"])
        self.assertEqual(self.confirmer(e, corps["import_id"]).status_code, 403)
        self.assertEqual(self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).status_code, 403)
        self.assertEqual(self.notes_en_base(e["tenant"]), [])


# =========================================================================
# Le navigateur ne décide de rien
# =========================================================================

class Adversarial(Base):
    def test_28_les_compteurs_envoyes_par_le_client_sont_ignores(self):
        """Transformer « 58 rapprochés, 2 erreurs » en « 60, 0 » ne doit rien
        changer : le serveur relit sa propre session."""
        e = self.ecole("adv1")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi"),
                                  "STU-0000-0000,Inconnu,6e A,Maths,Période 1,10,20\n"]).get_json()
        r = self.c.post(f"/api/results/imports/{corps['import_id']}/confirm",
                        json={"matched": 60, "errors": 0, "rows_unmatched": 0,
                              "force": True, "version": 99}, headers=e["h"])
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertEqual(self.notes_en_base(e["tenant"]), [])

    def test_29_une_session_dun_autre_etablissement_est_invisible(self):
        a = self.ecole("adv2a")
        b = self.ecole("adv2b")
        corps = self.analyser(a, [self.ligne(a, "Audrey Mukendi")]).get_json()
        for methode, chemin in (("get", f"/api/results/imports/{corps['import_id']}"),
                                ("post", f"/api/results/imports/{corps['import_id']}/confirm"),
                                ("post", f"/api/results/imports/{corps['import_id']}/cancel")):
            with self.subTest(route=chemin):
                r = getattr(self.c, methode)(chemin, json={}, headers=b["h"])
                self.assertEqual(r.status_code, 404, f"{chemin} → {r.status_code}")
        self.assertEqual(self.notes_en_base(a["tenant"]), [])

    def test_30_une_periode_dun_autre_etablissement_est_refusee(self):
        a = self.ecole("adv3a")
        b = self.ecole("adv3b")
        r = self.analyser(a, [self.ligne(a, "Audrey Mukendi")], period_id=b["pid"])
        self.assertEqual(r.status_code, 404, r.get_data(as_text=True))

    def test_31_une_periode_inexistante_est_refusee(self):
        e = self.ecole("adv4")
        r = self.analyser(e, [self.ligne(e, "Audrey Mukendi")], period_id="periode-fantome")
        self.assertEqual(r.status_code, 404)
        r = self.c.post("/api/results/imports",
                        data={"file": self.fichier([self.ligne(e, "Audrey Mukendi")])},
                        content_type="multipart/form-data", headers=e["h"])
        self.assertEqual(r.status_code, 404, "une période est obligatoire")

    def test_32_seule_la_direction_importe(self):
        e = self.ecole("adv5")
        inv = self.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": [e["classe"]],
            "titulaire_class_id": e["classe"]}, headers=e["h"]).get_json()
        security.reset_rate_limits_for_tests()
        prof = {"Authorization": "Bearer " + self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Prof", "email": "prof.adv5@test.local",
            "password": "Secret123!"}).get_json()["token"]}
        inv2 = self.c.post("/api/invitations", json={
            "role": "parent",
            "student_ids": [e["eleves"]["Audrey Mukendi"]["id"]]}, headers=e["h"]).get_json()
        security.reset_rate_limits_for_tests()
        parent = {"Authorization": "Bearer " + self.c.post("/api/invitations/accept", json={
            "token": inv2["token"], "name": "Parent", "email": "par.adv5@test.local",
            "password": "Secret123!"}).get_json()["token"]}

        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).get_json()
        for nom, h in (("professeur", prof), ("parent", parent)):
            with self.subTest(role=nom):
                self.assertEqual(self.analyser(e, [self.ligne(e, "Audrey Mukendi")],
                                               headers=h).status_code, 403)
                self.assertEqual(self.confirmer(e, corps["import_id"], headers=h).status_code, 403)
                self.assertEqual(self.c.get(f"/api/results/imports/{corps['import_id']}",
                                            headers=h).status_code, 403)
                self.assertEqual(self.c.get("/api/results/imports", headers=h).status_code, 403)
        self.assertEqual(self.notes_en_base(e["tenant"]), [])

    def test_33_aucune_route_dimport_nest_accessible_sans_session(self):
        e = self.ecole("adv6")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).get_json()
        for methode, chemin in (("get", "/api/results/imports"),
                                ("get", f"/api/results/imports/{corps['import_id']}"),
                                ("post", f"/api/results/imports/{corps['import_id']}/confirm"),
                                ("post", f"/api/results/imports/{corps['import_id']}/cancel"),
                                ("get", "/api/results/history")):
            with self.subTest(route=chemin):
                self.assertEqual(getattr(self.c, methode)(chemin, json={}).status_code, 401)

    def test_34_limport_ne_publie_jamais(self):
        """Import et proclamation restent deux décisions distinctes."""
        e = self.ecole("adv7")
        corps = self.analyser(e, [self.ligne(e, "Audrey Mukendi")]).get_json()
        self.confirmer(e, corps["import_id"])

        conn = db.get_connection()
        periode = conn.execute("SELECT published_at FROM academic_periods WHERE id=?",
                               (e["pid"],)).fetchone()
        publications = conn.execute("SELECT COUNT(*) n FROM period_publications WHERE tenant_id=?",
                                    (e["tenant"],)).fetchone()["n"]
        conn.close()
        self.assertIsNone(periode["published_at"], "l'import a proclamé la période")
        self.assertEqual(publications, 0)

        # Et le parent ne voit donc rien.
        inv = self.c.post("/api/invitations", json={
            "role": "parent",
            "student_ids": [e["eleves"]["Audrey Mukendi"]["id"]]}, headers=e["h"]).get_json()
        security.reset_rate_limits_for_tests()
        parent = {"Authorization": "Bearer " + self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "par.adv7@test.local",
            "password": "Secret123!"}).get_json()["token"]}
        dossier = self.c.get(f"/api/students/{e['eleves']['Audrey Mukendi']['id']}",
                             headers=parent).get_json()
        self.assertEqual(dossier.get("grades") or [], [],
                         "des résultats importés mais non proclamés sont visibles du parent")

    def test_35_apres_proclamation_le_parent_voit_la_version_courante(self):
        """Bout en bout : import v1, import v2, proclamation, lecture parent."""
        e = self.ecole("adv8")
        c1 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="8")]).get_json()
        self.confirmer(e, c1["import_id"])
        c2 = self.analyser(e, [self.ligne(e, "Audrey Mukendi", note="17")]).get_json()
        self.confirmer(e, c2["import_id"])
        self.assertEqual(self.c.post(f"/api/periods/{e['pid']}/publish", json={},
                                     headers=e["h"]).status_code, 200)

        inv = self.c.post("/api/invitations", json={
            "role": "parent",
            "student_ids": [e["eleves"]["Audrey Mukendi"]["id"]]}, headers=e["h"]).get_json()
        security.reset_rate_limits_for_tests()
        parent = {"Authorization": "Bearer " + self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": "par.adv8@test.local",
            "password": "Secret123!"}).get_json()["token"]}
        dossier = self.c.get(f"/api/students/{e['eleves']['Audrey Mukendi']['id']}",
                             headers=parent).get_json()
        notes = dossier.get("grades") or []
        self.assertEqual(len(notes), 1, f"le parent doit voir UNE note (la courante), pas {len(notes)}")
        self.assertEqual(notes[0]["score"], 17.0,
                         "le parent voit une version périmée du résultat")


if __name__ == "__main__":
    unittest.main()
