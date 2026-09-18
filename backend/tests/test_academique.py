"""KLASSIO — la fondation académique, éprouvée.

Ce fichier n'existe pas pour faire monter un compteur. Chaque test vérifie un
EFFET, pas un code de retour : ce qui est réellement en base, ce que le parent
voit réellement, ce que le serveur refuse réellement d'écrire.

Les quatre promesses que la fondation doit tenir, et que ces tests attaquent :

1. « Chaque établissement configure sa propre structure. » Deux écoles
   coexistent avec des structures différentes, et une même école donne six
   périodes au primaire là où le secondaire en a quatre. Si un nombre de
   périodes était écrit quelque part dans le code, ces tests tomberaient.

2. « Une période verrouillée ne se modifie pas. » Le refus doit venir du
   SERVEUR, résister à un payload retouché, et ne laisser aucune écriture
   partielle derrière lui.

3. « L'audience d'une proclamation est recalculée par le serveur. » Le
   navigateur envoie des critères ; s'il envoie des identifiants d'élèves
   d'une autre classe, d'un autre établissement, ou inventés, ils ne doivent
   produire aucun destinataire.

4. « Une nouvelle année ne réécrit jamais l'histoire. » Les résultats de
   2024-2025 restent ceux de 2024-2025, quelle que soit la structure adoptée
   ensuite.
"""
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
import school  # noqa: E402
import security  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class Base(unittest.TestCase):
    """Fabrique d'établissements réalistes. Tout passe par l'API publique —
    aucun test ne fabrique un état en écrivant directement en base, sinon il
    testerait ses propres INSERT plutôt que le produit."""

    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def ecole(self, suffixe, nom=None):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@test.local", "password": "Secret123!",
            "name": "Directeur", "school_name": nom or f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        corps = r.get_json()
        h = {"Authorization": f"Bearer {corps['token']}"}
        an = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        return {"h": h, "year": an, "tenant": corps["tenant_id"]}

    def annee(self, e, label, **kw):
        r = self.c.post("/api/academic-years", json={"label": label, **kw}, headers=e["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    def classe(self, e, nom, cycle="secondaire", annee=None, level=None):
        r = self.c.post("/api/classes", json={
            "name": nom, "academic_year_id": annee or e["year"], "cycle": cycle,
            "level": level}, headers=e["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    def eleve(self, e, prenom, nom, classe, annee=None):
        r = self.c.post("/api/students", json={
            "first_name": prenom, "last_name": nom,
            "academic_year_id": annee or e["year"], "class_id": classe}, headers=e["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    def periode(self, e, label, **kw):
        r = self.c.post("/api/periods", json={"label": label, **kw}, headers=e["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    def notes(self, e, classe, periode_label, eleve_id, score=15, subject="Mathématiques"):
        r = self.c.post(f"/api/classes/{classe}/grades", json={
            "subject": subject, "period": periode_label, "max_score": 20,
            "entries": [{"student_id": eleve_id, "score": score}]}, headers=e["h"])
        return r

    def parent(self, e, enfants, suffixe):
        inv = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": enfants}, headers=e["h"]).get_json()
        security.reset_rate_limits_for_tests()
        r = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent", "email": f"p.{suffixe}@test.local",
            "password": "Secret123!"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return {"Authorization": f"Bearer {r.get_json()['token']}"}

    def prof(self, e, classes, suffixe):
        inv = self.c.post("/api/invitations", json={
            "role": "professeur", "class_ids": classes,
            "titulaire_class_id": classes[0]}, headers=e["h"]).get_json()
        security.reset_rate_limits_for_tests()
        r = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Professeur", "email": f"t.{suffixe}@test.local",
            "password": "Secret123!"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return {"Authorization": f"Bearer {r.get_json()['token']}"}

    def calendrier(self, e, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        r = self.c.get(f"/api/academic-calendar{'?' + q if q else ''}", headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()

    def periodes_en_base(self, tenant):
        conn = db.get_connection()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM academic_periods WHERE tenant_id=? ORDER BY sort", (tenant,))]
        conn.close()
        return rows


# =========================================================================
# §2 — Les structures sont pilotées par les DONNÉES, pas par le code
# =========================================================================

class StructuresAcademiques(Base):
    def test_01_une_ecole_deux_divisions_deux_structures(self):
        """Six périodes au primaire, quatre au secondaire, MÊME année.

        C'est le scénario que le produit doit tenir sans modification de code.
        Si un nombre de périodes était supposé quelque part, ce test tombe.
        """
        e = self.ecole("struct1", "Complexe Bilingue")
        self.classe(e, "3e primaire", "primaire")
        self.classe(e, "5e secondaire", "secondaire")
        for i in range(6):
            self.periode(e, f"P{i + 1}", division="primaire", sort=i)
        for i in range(4):
            self.periode(e, f"T{i + 1}", division="secondaire", sort=i)

        cal = self.calendrier(e)
        par_division = {d["division"]: d for d in cal["divisions"]}
        self.assertEqual(par_division["primaire"]["period_count"], 6)
        self.assertEqual(par_division["secondaire"]["period_count"], 4)
        # Les libellés sont ceux de l'école, pas des noms fabriqués.
        self.assertEqual([p["label"] for p in par_division["primaire"]["periods"]],
                         ["P1", "P2", "P3", "P4", "P5", "P6"])
        self.assertEqual([p["label"] for p in par_division["secondaire"]["periods"]],
                         ["T1", "T2", "T3", "T4"])
        # Aucune fuite d'une division vers l'autre.
        self.assertNotIn("P1", [p["label"] for p in par_division["secondaire"]["periods"]])

    def test_02_une_autre_ecole_a_une_structure_totalement_differente(self):
        """Deux écoles coexistent avec des structures sans rapport."""
        a = self.ecole("struct2a", "École A")
        b = self.ecole("struct2b", "École B")
        self.classe(a, "6e A", "secondaire")
        self.classe(b, "6e B", "secondaire")
        for i in range(4):
            self.periode(a, f"Bimestre {i + 1}", sort=i)
        for i in range(3):
            self.periode(b, f"Trimestre {i + 1}", sort=i)

        ca = self.calendrier(a)
        cb = self.calendrier(b)
        self.assertEqual(ca["divisions"][0]["period_count"], 4)
        self.assertEqual(cb["divisions"][0]["period_count"], 3)
        labels_b = [p["label"] for p in cb["divisions"][0]["periods"]]
        self.assertTrue(all(l.startswith("Trimestre") for l in labels_b), labels_b)
        # B ne voit RIEN de A.
        self.assertNotIn("Bimestre 1", labels_b)

    def test_03_une_structure_inhabituelle_passe_aussi(self):
        """Dix périodes aux noms libres — pour prouver qu'aucun nombre ni
        vocabulaire (« trimestre », « semestre ») n'est privilégié."""
        e = self.ecole("struct3", "École Modulaire")
        self.classe(e, "Groupe Alpha", "secondaire")
        noms = ["Module Découverte", "Module Approfondissement", "Cycle Court", "Étape 4",
                "Séquence V", "Bloc 6", "Unité 7", "Palier 8", "Session 9", "Module Final"]
        for i, n in enumerate(noms):
            self.periode(e, n, sort=i)
        cal = self.calendrier(e)
        self.assertEqual(cal["divisions"][0]["period_count"], 10)
        self.assertEqual([p["label"] for p in cal["divisions"][0]["periods"]], noms,
                         "l'ordre déclaré par l'école doit être respecté tel quel")

    def test_04_lordre_suit_le_champ_sort_pas_lordre_de_creation(self):
        e = self.ecole("struct4")
        self.classe(e, "6e A", "secondaire")
        self.periode(e, "Troisième", sort=3)
        self.periode(e, "Première", sort=1)
        self.periode(e, "Deuxième", sort=2)
        cal = self.calendrier(e)
        self.assertEqual([p["label"] for p in cal["divisions"][0]["periods"]],
                         ["Première", "Deuxième", "Troisième"])

    def test_05_une_periode_de_division_remplace_la_periode_commune_homonyme(self):
        """Une école peut poser un socle commun puis le spécialiser."""
        e = self.ecole("struct5")
        self.classe(e, "3e primaire", "primaire")
        self.classe(e, "5e secondaire", "secondaire")
        self.periode(e, "Période 1", sort=0, starts_on="2026-09-01", ends_on="2026-10-31")
        self.periode(e, "Période 2", sort=1)
        # Le primaire a sa propre Période 1, avec d'autres dates.
        self.periode(e, "Période 1", division="primaire", sort=0,
                     starts_on="2026-09-15", ends_on="2026-11-15")

        cal = self.calendrier(e)
        par_division = {d["division"]: d for d in cal["divisions"]}
        prim = {p["label"]: p for p in par_division["primaire"]["periods"]}
        sec = {p["label"]: p for p in par_division["secondaire"]["periods"]}
        self.assertEqual(prim["Période 1"]["starts_on"], "2026-09-15",
                         "le primaire doit recevoir SA période 1, pas la commune")
        self.assertEqual(sec["Période 1"]["starts_on"], "2026-09-01")
        # La période 2 commune reste partagée par les deux.
        self.assertIn("Période 2", prim)
        self.assertIn("Période 2", sec)

    def test_06_modification_avant_verrouillage(self):
        e = self.ecole("struct6")
        self.classe(e, "6e A", "secondaire")
        pid = self.periode(e, "Période 1", sort=0, starts_on="2026-09-01", ends_on="2026-10-31")
        r = self.c.put(f"/api/periods/{pid}", json={
            "label": "Premier trimestre", "ends_on": "2026-11-15", "sort": 5}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        # Vérifié EN BASE, pas seulement dans la réponse.
        ligne = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        self.assertEqual(ligne["label"], "Premier trimestre")
        self.assertEqual(ligne["ends_on"], "2026-11-15")
        self.assertEqual(ligne["sort"], 5)


# =========================================================================
# §3 — Dates : refus, ET aucune écriture partielle
# =========================================================================

class InvariantsDeDates(Base):
    def test_07_un_calendrier_incoherent_est_refuse_et_nentre_pas_en_base(self):
        e = self.ecole("dates1")
        self.classe(e, "6e A", "secondaire")
        avant = len(self.periodes_en_base(e["tenant"]))

        cas = [
            ("fin avant début", {"starts_on": "2026-11-01", "ends_on": "2026-10-01"}),
            ("saisie avant la fin de période", {"ends_on": "2026-11-30", "result_entry_deadline": "2026-11-01"}),
            ("validation avant saisie", {"result_entry_deadline": "2026-12-05", "validation_deadline": "2026-12-01"}),
            ("proclamation avant validation", {"validation_deadline": "2026-12-10", "proclamation_at": "2026-12-01"}),
            ("format non ISO", {"starts_on": "01/09/2026"}),
            ("date non textuelle", {"starts_on": 20260901}),
            ("division inexistante", {"division": "collège"}),
        ]
        for libelle, charge in cas:
            with self.subTest(cas=libelle):
                r = self.c.post("/api/periods", json={"label": f"Refusée {libelle}", **charge},
                                headers=e["h"])
                self.assertEqual(r.status_code, 400,
                                 f"{libelle} → {r.status_code} : {r.get_data(as_text=True)[:140]}")

        apres = self.periodes_en_base(e["tenant"])
        self.assertEqual(len(apres), avant,
                         f"{len(apres) - avant} période(s) créée(s) malgré le refus — "
                         "une requête rejetée ne doit rien laisser derrière elle")

    def test_08_une_modification_refusee_laisse_letat_precedent_intact(self):
        e = self.ecole("dates2")
        self.classe(e, "6e A", "secondaire")
        pid = self.periode(e, "Période 1", sort=0, starts_on="2026-09-01", ends_on="2026-10-31")
        avant = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]

        r = self.c.put(f"/api/periods/{pid}", json={
            "label": "Nouveau nom", "starts_on": "2026-12-01", "ends_on": "2026-11-01"},
            headers=e["h"])
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))

        apres = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        self.assertEqual(apres["label"], avant["label"],
                         "le libellé a été modifié alors que la requête était refusée")
        self.assertEqual(apres["starts_on"], avant["starts_on"])
        self.assertEqual(apres["ends_on"], avant["ends_on"])

    def test_09_une_modification_partielle_est_validee_contre_les_dates_deja_en_base(self):
        """Le piège : n'envoyer qu'UNE date.

        En ne validant que les champs présents dans la requête, une fin de
        période antérieure au début déjà enregistré passait — parce que
        `starts_on` était absent du corps, donc lu comme None, donc comparé à
        rien. Le calendrier devenait incohérent en base sans qu'aucune règle
        n'ait été violée « visiblement ».
        """
        e = self.ecole("dates3")
        self.classe(e, "6e A", "secondaire")
        pid = self.periode(e, "Période 1", sort=0, starts_on="2026-09-01", ends_on="2026-10-31")

        r = self.c.put(f"/api/periods/{pid}", json={"ends_on": "2026-08-01"}, headers=e["h"])
        self.assertEqual(r.status_code, 400,
                         "une fin antérieure au début DÉJÀ ENREGISTRÉ doit être refusée "
                         f"même si le début n'est pas renvoyé — obtenu {r.status_code}")
        ligne = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        self.assertEqual(ligne["ends_on"], "2026-10-31", "la date incohérente a été écrite")

    def test_10_un_libelle_en_double_dans_la_meme_annee_est_refuse(self):
        e = self.ecole("dates4")
        self.classe(e, "6e A", "secondaire")
        self.periode(e, "Période 1", sort=0)
        r = self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=e["h"])
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertEqual(len(self.periodes_en_base(e["tenant"])), 1)


# =========================================================================
# §4 — Période courante : déduite des dates, y compris aux frontières
# =========================================================================

class PeriodeCourante(Base):
    def _ecole_avec_calendrier(self, suffixe):
        e = self.ecole(suffixe)
        self.classe(e, "6e A", "secondaire")
        self.periode(e, "Période 1", sort=0, starts_on="2026-09-01", ends_on="2026-10-31")
        # Trou volontaire du 1er au 15 novembre : des vacances.
        self.periode(e, "Période 2", sort=1, starts_on="2026-11-16", ends_on="2026-12-20")
        self.periode(e, "Période 3", sort=2, starts_on="2027-01-10", ends_on="2027-03-31")
        return e

    def _courante(self, tenant, annee, jour):
        conn = db.get_connection()
        try:
            p = school.current_period(conn, tenant, annee, today=jour)
            return p["label"] if p else None
        finally:
            conn.close()

    def test_11_la_bonne_periode_est_retournee_a_chaque_date(self):
        e = self._ecole_avec_calendrier("courante1")
        cas = [
            ("2026-08-15", "Période 1", "avant toute période → la prochaine à venir"),
            ("2026-09-01", "Période 1", "exactement au premier jour"),
            ("2026-10-05", "Période 1", "en plein milieu"),
            ("2026-10-31", "Période 1", "exactement au dernier jour"),
            ("2026-11-05", "Période 2", "entre deux périodes → la prochaine"),
            ("2026-11-16", "Période 2", "premier jour de la suivante"),
            ("2026-12-20", "Période 2", "dernier jour de la suivante"),
            ("2027-02-01", "Période 3", "dernière période"),
            ("2027-06-01", None, "après la dernière → aucune"),
        ]
        for jour, attendu, pourquoi in cas:
            with self.subTest(jour=jour, pourquoi=pourquoi):
                self.assertEqual(self._courante(e["tenant"], e["year"], jour), attendu,
                                 f"{pourquoi} ({jour})")

    def test_12_les_bornes_sont_inclusives_des_deux_cotes(self):
        """Un élève présent le dernier jour d'une période appartient à cette
        période — pas à la suivante, pas à aucune."""
        e = self._ecole_avec_calendrier("courante2")
        self.assertEqual(self._courante(e["tenant"], e["year"], "2026-08-31"), "Période 1")
        self.assertEqual(self._courante(e["tenant"], e["year"], "2026-09-01"), "Période 1")
        self.assertEqual(self._courante(e["tenant"], e["year"], "2026-10-31"), "Période 1")
        self.assertEqual(self._courante(e["tenant"], e["year"], "2026-11-01"), "Période 2")

    def test_13_la_periode_courante_est_propre_a_la_division(self):
        e = self.ecole("courante3")
        self.classe(e, "3e primaire", "primaire")
        self.classe(e, "5e secondaire", "secondaire")
        self.periode(e, "Trimestre 1", division="secondaire", sort=0,
                     starts_on="2026-09-01", ends_on="2026-12-15")
        self.periode(e, "Bimestre 1", division="primaire", sort=0,
                     starts_on="2026-09-01", ends_on="2026-10-31")
        self.periode(e, "Bimestre 2", division="primaire", sort=1,
                     starts_on="2026-11-01", ends_on="2026-12-15")
        conn = db.get_connection()
        try:
            prim = school.current_period(conn, e["tenant"], e["year"], "primaire", today="2026-11-10")
            sec = school.current_period(conn, e["tenant"], e["year"], "secondaire", today="2026-11-10")
        finally:
            conn.close()
        self.assertEqual(prim["label"], "Bimestre 2")
        self.assertEqual(sec["label"], "Trimestre 1")

    def test_14_letat_se_deduit_des_dates_et_des_echeances(self):
        base = {"starts_on": "2026-09-01", "ends_on": "2026-10-31",
                "result_entry_deadline": "2026-11-10", "admin_state": "READY"}
        self.assertEqual(school.period_state(base, today="2026-08-01"), "UPCOMING")
        self.assertEqual(school.period_state(base, today="2026-09-01"), "OPEN")
        self.assertEqual(school.period_state(base, today="2026-10-31"), "OPEN")
        self.assertEqual(school.period_state(base, today="2026-11-05"), "CLOSING",
                         "période finie mais échéance de saisie en cours")
        self.assertEqual(school.period_state(base, today="2026-11-10"), "CLOSING",
                         "le jour même de l'échéance compte encore")
        self.assertEqual(school.period_state(base, today="2026-11-11"), "CLOSED")

    def test_15_un_etat_administratif_prime_toujours_sur_les_dates(self):
        """Une période verrouillée le reste, même en plein milieu de ses dates."""
        for etat in ("DRAFT", "LOCKED", "ARCHIVED"):
            p = {"starts_on": "2026-09-01", "ends_on": "2026-10-31", "admin_state": etat}
            self.assertEqual(school.period_state(p, today="2026-09-15"), etat)

    def test_16_une_periode_sans_dates_reste_ouverte(self):
        """On n'invente pas de dates à une école qui n'en a pas mis."""
        self.assertEqual(school.period_state({"admin_state": "READY"}, today="2026-09-15"), "OPEN")


# =========================================================================
# §5 — Verrouillage : le refus vient du serveur
# =========================================================================

class Verrouillage(Base):
    def _verrouillee(self, suffixe):
        e = self.ecole(suffixe)
        cls = self.classe(e, "6e A", "secondaire")
        eleve = self.eleve(e, "Audrey", "Mukendi", cls)
        pid = self.periode(e, "Période 1", sort=0)
        r = self.c.post(f"/api/periods/{pid}/lock", json={}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return e, cls, eleve, pid

    def test_17_une_periode_verrouillee_refuse_la_modification(self):
        e, _, _, pid = self._verrouillee("verrou1")
        avant = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        r = self.c.put(f"/api/periods/{pid}", json={"label": "Renommée", "sort": 99},
                       headers=e["h"])
        self.assertEqual(r.status_code, 403, r.get_data(as_text=True))
        apres = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        self.assertEqual(apres["label"], avant["label"])
        self.assertEqual(apres["sort"], avant["sort"], "modification partielle enregistrée")

    def test_18_une_periode_verrouillee_refuse_la_saisie_de_notes(self):
        """Le verrou porte sur les RÉSULTATS, pas seulement sur la fiche."""
        e, cls, eleve, _ = self._verrouillee("verrou2")
        r = self.notes(e, cls, "Période 1", eleve, score=18)
        self.assertEqual(r.status_code, 403, r.get_data(as_text=True))
        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM grades WHERE tenant_id=?", (e["tenant"],)).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 0, "une note a été écrite dans une période verrouillée")

    def test_19_un_payload_retouche_ne_contourne_pas_le_verrou(self):
        """Envoyer admin_state ou locked_at soi-même ne rouvre rien."""
        e, cls, eleve, pid = self._verrouillee("verrou3")
        for charge in ({"admin_state": "READY"}, {"admin_state": "READY", "locked_at": None},
                       {"locked_at": None, "label": "Forcée"}, {"admin_state": "OPEN"}):
            with self.subTest(charge=charge):
                r = self.c.put(f"/api/periods/{pid}", json=charge, headers=e["h"])
                self.assertIn(r.status_code, (400, 403),
                              f"{charge} → {r.status_code} : le verrou a cédé")
        ligne = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        self.assertEqual(ligne["admin_state"], "LOCKED")
        self.assertIsNotNone(ligne["locked_at"])

    def test_20_un_autre_role_ne_verrouille_ni_ne_modifie(self):
        e, cls, eleve, pid = self._verrouillee("verrou4")
        prof_h = self.prof(e, [cls], "verrou4")
        parent_h = self.parent(e, [eleve], "verrou4")
        for nom, h in (("professeur", prof_h), ("parent", parent_h)):
            with self.subTest(role=nom):
                self.assertEqual(self.c.post(f"/api/periods/{pid}/lock", json={}, headers=h).status_code, 403)
                self.assertEqual(self.c.put(f"/api/periods/{pid}", json={"label": "X"}, headers=h).status_code, 403)
                self.assertEqual(self.c.post(f"/api/periods/{pid}/reopen",
                                             json={"reason": "je veux modifier les notes"},
                                             headers=h).status_code, 403)

    def test_21_un_autre_etablissement_ne_verrouille_rien(self):
        e, _, _, pid = self._verrouillee("verrou5")
        autre = self.ecole("verrou5bis")
        for chemin, methode in ((f"/api/periods/{pid}/lock", "post"),
                                (f"/api/periods/{pid}/reopen", "post"),
                                (f"/api/periods/{pid}/reopenings", "get"),
                                (f"/api/periods/{pid}", "put")):
            with self.subTest(route=chemin):
                fn = getattr(self.c, methode)
                r = fn(chemin, json={"reason": "tentative depuis un autre établissement",
                                     "label": "X"}, headers=autre["h"])
                self.assertEqual(r.status_code, 404,
                                 f"{chemin} → {r.status_code} : une autre école apprend "
                                 "l'existence de cette période")

    def test_22_verrouiller_deux_fois_ne_deplace_pas_la_date(self):
        e, _, _, pid = self._verrouillee("verrou6")
        premier = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]["locked_at"]
        self.c.post(f"/api/periods/{pid}/lock", json={}, headers=e["h"])
        second = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]["locked_at"]
        self.assertEqual(premier, second)


# =========================================================================
# §6 — Réouvertures : motivées, tracées, réversibles
# =========================================================================

class Reouvertures(Base):
    def _verrouillee(self, suffixe):
        e = self.ecole(suffixe)
        cls = self.classe(e, "6e A", "secondaire")
        eleve = self.eleve(e, "Audrey", "Mukendi", cls)
        pid = self.periode(e, "Période 1", sort=0)
        self.c.post(f"/api/periods/{pid}/lock", json={}, headers=e["h"])
        return e, cls, eleve, pid

    MOTIF = "Erreur de barème signalée par le titulaire de la 6e A"

    def test_23_une_reouverture_motivee_rend_la_periode_modifiable(self):
        e, cls, eleve, pid = self._verrouillee("reouv1")
        r = self.c.post(f"/api/periods/{pid}/reopen", json={"reason": self.MOTIF}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["state"], "OPEN")
        # Et la saisie redevient réellement possible.
        self.assertEqual(self.notes(e, cls, "Période 1", eleve, score=17).status_code, 200)

    def test_24_une_reouverture_sans_motif_serieux_est_refusee(self):
        e, _, _, pid = self._verrouillee("reouv2")
        for libelle, charge in (("absent", {}), ("vide", {"reason": ""}),
                                ("espaces", {"reason": "   "}), ("trop court", {"reason": "erreur"}),
                                ("non textuel", {"reason": 12345})):
            with self.subTest(motif=libelle):
                r = self.c.post(f"/api/periods/{pid}/reopen", json=charge, headers=e["h"])
                self.assertEqual(r.status_code, 400,
                                 f"motif {libelle} → {r.status_code} : le verrou est contournable")
        ligne = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == pid][0]
        self.assertEqual(ligne["admin_state"], "LOCKED",
                         "la période a été rouverte malgré un motif refusé")

    def test_25_la_reouverture_est_tracee_avec_qui_quand_et_pourquoi(self):
        e, _, _, pid = self._verrouillee("reouv3")
        self.c.post(f"/api/periods/{pid}/reopen", json={"reason": self.MOTIF}, headers=e["h"])
        historique = self.c.get(f"/api/periods/{pid}/reopenings", headers=e["h"]).get_json()
        self.assertEqual(len(historique), 1)
        ligne = historique[0]
        self.assertEqual(ligne["reason"], self.MOTIF)
        self.assertTrue(ligne["reopened_by"], "aucun responsable enregistré")
        self.assertTrue(ligne["reopened_at"], "aucun horodatage")
        self.assertEqual(ligne["reopened_by_name"], "Directeur")

        # …et le journal d'audit en porte trace, avec le motif.
        conn = db.get_connection()
        lignes = [dict(r) for r in conn.execute(
            "SELECT * FROM audit_logs WHERE tenant_id=? AND action='period.reopened'",
            (e["tenant"],))]
        conn.close()
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0]["resource_id"], pid)
        # L'audit stocke du JSON échappé (ensure_ascii) : on le décode plutôt
        # que de comparer des octets, sinon le moindre accent fait échouer.
        self.assertEqual(json.loads(lignes[0]["after_json"])["reason"], self.MOTIF)
        self.assertEqual(lignes[0]["actor_id"], self.c.get("/api/me", headers=e["h"]).get_json()["user_id"])

    def test_26_rouvrir_une_periode_non_verrouillee_est_refuse(self):
        e = self.ecole("reouv4")
        self.classe(e, "6e A", "secondaire")
        pid = self.periode(e, "Période 1", sort=0)
        r = self.c.post(f"/api/periods/{pid}/reopen", json={"reason": self.MOTIF}, headers=e["h"])
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))

    def test_27_refermer_apres_reouverture_clot_la_ligne_douverture(self):
        e, _, _, pid = self._verrouillee("reouv5")
        self.c.post(f"/api/periods/{pid}/reopen", json={"reason": self.MOTIF}, headers=e["h"])
        self.c.post(f"/api/periods/{pid}/lock", json={}, headers=e["h"])
        historique = self.c.get(f"/api/periods/{pid}/reopenings", headers=e["h"]).get_json()
        self.assertTrue(historique[0]["relocked_at"],
                        "la réouverture reste ouverte indéfiniment après refermeture")
        self.assertTrue(historique[0]["relocked_by"])

    def test_28_plusieurs_reouvertures_sempilent_sans_secraser(self):
        e, _, _, pid = self._verrouillee("reouv6")
        for i in range(3):
            self.c.post(f"/api/periods/{pid}/reopen",
                        json={"reason": f"Correction numéro {i} demandée par le conseil"},
                        headers=e["h"])
            self.c.post(f"/api/periods/{pid}/lock", json={}, headers=e["h"])
        historique = self.c.get(f"/api/periods/{pid}/reopenings", headers=e["h"]).get_json()
        self.assertEqual(len(historique), 3, "l'historique des réouvertures a été écrasé")
        self.assertTrue(all(h["relocked_at"] for h in historique))

    def test_29_une_periode_inexistante_repond_404(self):
        e = self.ecole("reouv7")
        for chemin in (f"/api/periods/inexistante/reopen", f"/api/periods/inexistante/lock"):
            r = self.c.post(chemin, json={"reason": self.MOTIF}, headers=e["h"])
            self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()


# =========================================================================
# §7 / §8 — Publication : l'audience est recalculée PAR LE SERVEUR
#
# C'est le point le plus sensible de toute la fondation : cette audience
# décide qui voit les résultats de son enfant. Les tests ci-dessous
# l'attaquent, ils ne se contentent pas de la faire tourner.
# =========================================================================

class MixinPublication:
    """Helpers partagés. Volontairement PAS un TestCase : hériter d'une classe
    de tests ferait rejouer tous ses tests dans chaque sous-classe, avec les
    mêmes e-mails — et donc des collisions de comptes."""

    def _ecole_peuplee(self, suffixe):
        """Deux classes, quatre élèves, des notes partout, une période prête."""
        e = self.ecole(suffixe)
        e["c6"] = self.classe(e, "6e A", "secondaire", level="6")
        e["c5"] = self.classe(e, "5e B", "secondaire", level="5")
        e["audrey"] = self.eleve(e, "Audrey", "Mukendi", e["c6"])
        e["kevin"] = self.eleve(e, "Kevin", "Mukendi", e["c6"])
        e["sarah"] = self.eleve(e, "Sarah", "Kalala", e["c5"])
        e["jonas"] = self.eleve(e, "Jonas", "Ilunga", e["c5"])
        e["pid"] = self.periode(e, "Période 1", sort=0)
        for cls, eleves in ((e["c6"], [e["audrey"], e["kevin"]]), (e["c5"], [e["sarah"], e["jonas"]])):
            for el in eleves:
                self.assertEqual(self.notes(e, cls, "Période 1", el, score=14).status_code, 200)
        return e

    def _apercu(self, e, filtre=None):
        r = self.c.post(f"/api/periods/{e['pid']}/publication-preview",
                        json=filtre or {}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()

    def _publier(self, e, filtre=None):
        return self.c.post(f"/api/periods/{e['pid']}/publish", json=filtre or {}, headers=e["h"])

    def _audience_en_base(self, tenant, pid):
        conn = db.get_connection()
        rows = [r["student_id"] for r in conn.execute(
            """SELECT ps.student_id FROM publication_students ps
               JOIN period_publications pp ON pp.id = ps.publication_id
               WHERE pp.tenant_id=? AND pp.period_id=? AND pp.unpublished_at IS NULL""",
            (tenant, pid))]
        conn.close()
        return set(rows)


class VersionnementDesNotes(MixinPublication, Base):
    """Le versionnement des notes saisies à la main.

    Dans une classe dédiée, et non dans le mixin : celui-ci est consommé par
    quatre classes de test, et ces scénarios s'exécuteraient quatre fois en se
    disputant le même établissement.
    """

    def test_saisie_manuelle_corrigee_cree_une_version(self):
        """Corriger une note à la main crée une VERSION, elle ne s'ajoute pas.

        Trouvé par la campagne k6 du 17/09 : `POST /classes/<id>/grades` faisait
        un INSERT sec. Une note corrigée laissait DEUX lignes `is_current=1`
        pour le même élève, la même matière et la même période. Bulletins,
        moyennes et rangs comptaient les deux — un 17 corrigé en 11 donnait une
        moyenne de 14 sur une note qui n'existe pas.

        Le chemin d'IMPORT versionnait déjà ; la saisie manuelle, la plus
        empruntée, avait été oubliée.
        """
        e = self._ecole_peuplee("versionmanuelle")
        eleve = e["audrey"]

        def lignes():
            conn = db.get_connection()
            r = [dict(x) for x in conn.execute(
                """SELECT score, is_current FROM grades
                   WHERE tenant_id=? AND student_id=? AND subject=?
                   ORDER BY created_at""",
                (e["tenant"], eleve, "Mathématiques"))]
            conn.close()
            return r

        self.assertEqual(self.notes(e, e["c6"], "Période 1", eleve, score=17,
                                    subject="Mathématiques").status_code, 200)
        self.assertEqual(self.notes(e, e["c6"], "Période 1", eleve, score=11,
                                    subject="Mathématiques").status_code, 200)

        toutes = lignes()
        courantes = [x for x in toutes if x["is_current"]]
        self.assertEqual(len(courantes), 1,
                         f"deux notes courantes coexistent pour la même matière : {toutes}")
        self.assertEqual(courantes[0]["score"], 11, "la version courante n'est pas la correction")
        # L'ancienne n'est pas supprimée : elle est datée et conservée.
        anciennes = [x for x in toutes if not x["is_current"]]
        self.assertTrue(any(x["score"] == 17 for x in anciennes),
                        "l'ancienne version a disparu au lieu d'être conservée")

    def test_saisie_d_une_autre_matiere_ne_supplante_pas(self):
        """Versionner ne doit pas écraser une matière voisine."""
        e = self._ecole_peuplee("versionmatiere")
        eleve = e["audrey"]
        self.assertEqual(self.notes(e, e["c6"], "Période 1", eleve, score=15,
                                    subject="Français").status_code, 200)
        self.assertEqual(self.notes(e, e["c6"], "Période 1", eleve, score=9,
                                    subject="Mathématiques").status_code, 200)
        conn = db.get_connection()
        courantes = {x["subject"]: x["score"] for x in conn.execute(
            """SELECT subject, score FROM grades
               WHERE tenant_id=? AND student_id=? AND is_current=1""", (e["tenant"], eleve))}
        conn.close()
        self.assertEqual(courantes.get("Français"), 15, "le français a été supplanté à tort")
        self.assertEqual(courantes.get("Mathématiques"), 9)


class PublicationEtAudience(MixinPublication, Base):
    def test_30_publication_sans_filtre_couvre_tous_les_eleves_actifs(self):
        e = self._ecole_peuplee("pub1")
        apercu = self._apercu(e)
        self.assertEqual(apercu["total"], 4)
        self.assertEqual(apercu["included_count"], 4)
        self.assertEqual(apercu["excluded_count"], 0)

        r = self._publier(e)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["included"], 4)
        self.assertEqual(
            self._audience_en_base(e["tenant"], e["pid"]),
            {e["audrey"], e["kevin"], e["sarah"], e["jonas"]},
            "l'audience enregistrée ne correspond pas aux élèves de l'établissement")

    def test_31_lapercu_annonce_exactement_ce_qui_sera_publie(self):
        """Si l'aperçu et la publication divergeaient, la Direction validerait
        une chose et en publierait une autre."""
        e = self._ecole_peuplee("pub2")
        filtre = {"class_ids": [e["c6"]]}
        apercu = self._apercu(e, filtre)
        r = self._publier(e, filtre)
        self.assertEqual(r.status_code, 200)
        corps = r.get_json()
        self.assertEqual(apercu["included_count"], corps["included"])
        self.assertEqual(apercu["excluded_count"], corps["excluded"])
        self.assertEqual(len(self._audience_en_base(e["tenant"], e["pid"])), apercu["included_count"])

    def test_32_filtre_sur_une_classe(self):
        e = self._ecole_peuplee("pub3")
        self._publier(e, {"class_ids": [e["c6"]]})
        self.assertEqual(self._audience_en_base(e["tenant"], e["pid"]),
                         {e["audrey"], e["kevin"]})

    def test_33_filtre_sur_plusieurs_classes(self):
        e = self._ecole_peuplee("pub4")
        self._publier(e, {"class_ids": [e["c6"], e["c5"]]})
        self.assertEqual(len(self._audience_en_base(e["tenant"], e["pid"])), 4)

    def test_34_filtre_sur_un_niveau(self):
        e = self._ecole_peuplee("pub5")
        apercu = self._apercu(e, {"levels": ["6"]})
        self.assertEqual(apercu["included_count"], 2, "le niveau 6 ne compte que la 6e A")
        self._publier(e, {"levels": ["6"]})
        self.assertEqual(self._audience_en_base(e["tenant"], e["pid"]),
                         {e["audrey"], e["kevin"]})

    def test_35_filtre_sur_des_eleves_nommement_designes(self):
        e = self._ecole_peuplee("pub6")
        self._publier(e, {"student_ids": [e["audrey"], e["sarah"]]})
        self.assertEqual(self._audience_en_base(e["tenant"], e["pid"]),
                         {e["audrey"], e["sarah"]})

    def test_36_les_filtres_se_combinent_en_intersection(self):
        e = self._ecole_peuplee("pub7")
        # Classe 6e A ET élève Sarah (qui est en 5e B) → personne.
        apercu = self._apercu(e, {"class_ids": [e["c6"]], "student_ids": [e["sarah"]]})
        self.assertEqual(apercu["included_count"], 0,
                         "des filtres contradictoires doivent donner une audience vide, "
                         "jamais l'union des deux")
        # Classe 6e A ET élève Audrey → Audrey seule.
        apercu = self._apercu(e, {"class_ids": [e["c6"]], "student_ids": [e["audrey"]]})
        self.assertEqual(apercu["included_count"], 1)

    def test_37_chaque_exclusion_porte_son_motif(self):
        """La Direction doit pouvoir expliquer à un parent pourquoi il est exclu."""
        e = self._ecole_peuplee("pub8")
        apercu = self._apercu(e, {"class_ids": [e["c6"]]})
        self.assertEqual(apercu["excluded_count"], 2)
        motifs = {x["reason"] for x in apercu["excluded_sample"]}
        self.assertTrue(motifs, "aucun motif d'exclusion fourni")
        self.assertTrue(all(m.strip() for m in motifs))


class AudienceAdversariale(MixinPublication, Base):
    """Le navigateur n'est pas une source de vérité.

    Chaque test envoie un filtre retouché comme le ferait quelqu'un qui édite
    la requête, et vérifie que le serveur ne s'y laisse pas prendre.
    """

    def test_38_un_eleve_dun_autre_etablissement_ne_rejoint_jamais_laudience(self):
        a = self._ecole_peuplee("adv1a")
        b = self._ecole_peuplee("adv1b")
        # A publie en désignant explicitement un élève de B.
        r = self._publier(a, {"student_ids": [a["audrey"], b["sarah"]]})
        self.assertEqual(r.status_code, 200)
        audience = self._audience_en_base(a["tenant"], a["pid"])
        self.assertNotIn(b["sarah"], audience,
                         "un élève d'un autre établissement est entré dans l'audience")
        self.assertEqual(audience, {a["audrey"]})

    def test_39_une_classe_dun_autre_etablissement_nelargit_rien(self):
        a = self._ecole_peuplee("adv2a")
        b = self._ecole_peuplee("adv2b")
        apercu = self._apercu(a, {"class_ids": [b["c6"]]})
        self.assertEqual(apercu["included_count"], 0,
                         "une classe étrangère a servi de filtre valide")

    def test_40_des_identifiants_inventes_nelargissent_rien(self):
        e = self._ecole_peuplee("adv3")
        for filtre in ({"student_ids": ["nimporte-quoi", "00000000"]},
                       {"class_ids": ["classe-fantome"]},
                       {"levels": ["niveau-inexistant"]}):
            with self.subTest(filtre=filtre):
                apercu = self._apercu(e, filtre)
                self.assertEqual(apercu["included_count"], 0,
                                 f"{filtre} a produit des destinataires")

    def test_41_un_filtre_malforme_est_refuse_et_ne_publie_rien(self):
        e = self._ecole_peuplee("adv4")
        for filtre in ({"student_ids": "pas-une-liste"}, {"class_ids": [1, 2, 3]},
                       {"levels": {"a": 1}}, {"division": "collège"}):
            with self.subTest(filtre=filtre):
                r = self._publier(e, filtre)
                self.assertEqual(r.status_code, 400,
                                 f"{filtre} → {r.status_code} au lieu d'un refus")
        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM period_publications WHERE tenant_id=?",
                         (e["tenant"],)).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 0, "une publication a été créée malgré un filtre refusé")

    def test_42_un_eleve_archive_nentre_pas_dans_laudience(self):
        """Retirer un élève de l'établissement doit le retirer des destinataires,
        même si la Direction le désigne nommément."""
        e = self._ecole_peuplee("adv5")
        r = self.c.put(f"/api/students/{e['kevin']}", json={"status": "archived"}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        apercu = self._apercu(e, {"student_ids": [e["audrey"], e["kevin"]]})
        self.assertEqual(apercu["included_count"], 1,
                         "un élève archivé est resté destinataire")

    def test_43_un_autre_role_ne_publie_pas_meme_avec_un_filtre_valide(self):
        e = self._ecole_peuplee("adv6")
        prof_h = self.prof(e, [e["c6"]], "adv6")
        parent_h = self.parent(e, [e["audrey"]], "adv6")
        for nom, h in (("professeur", prof_h), ("parent", parent_h)):
            with self.subTest(role=nom):
                for chemin in (f"/api/periods/{e['pid']}/publish",
                               f"/api/periods/{e['pid']}/publication-preview"):
                    r = self.c.post(chemin, json={"class_ids": [e["c6"]]}, headers=h)
                    self.assertEqual(r.status_code, 403, f"{nom} sur {chemin} → {r.status_code}")
        self.assertEqual(self._audience_en_base(e["tenant"], e["pid"]), set())

    def test_44_un_autre_etablissement_ne_publie_pas_notre_periode(self):
        a = self._ecole_peuplee("adv7a")
        b = self.ecole("adv7b")
        for chemin in (f"/api/periods/{a['pid']}/publish",
                       f"/api/periods/{a['pid']}/publication-preview"):
            r = self.c.post(chemin, json={}, headers=b["h"])
            self.assertEqual(r.status_code, 404, f"{chemin} → {r.status_code}")
        self.assertEqual(self._audience_en_base(a["tenant"], a["pid"]), set())


class Idempotence(MixinPublication, Base):
    def test_45_publier_deux_fois_ne_cree_quune_publication(self):
        e = self._ecole_peuplee("idem1")
        premier = self._publier(e)
        self.assertEqual(premier.status_code, 200)
        second = self._publier(e)
        self.assertEqual(second.status_code, 409,
                         "une seconde proclamation a été acceptée sans retrait de la première")
        conn = db.get_connection()
        pubs = conn.execute("SELECT COUNT(*) n FROM period_publications WHERE tenant_id=?",
                            (e["tenant"],)).fetchone()["n"]
        notifs = conn.execute("SELECT COUNT(*) n FROM notifications WHERE tenant_id=?",
                              (e["tenant"],)).fetchone()["n"]
        evts = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE tenant_id=? AND event_type='results.period.published'",
            (e["tenant"],)).fetchone()["n"]
        conn.close()
        self.assertEqual(pubs, 1, f"{pubs} publications")
        self.assertEqual(evts, 1, f"{evts} événements de proclamation")
        self.assertLessEqual(notifs, 4, f"{notifs} notifications pour 4 élèves")

    TOURS = 12

    def test_46_deux_publications_simultanees_nen_produisent_quune(self):
        """Double clic, ou deux onglets. Mesuré en boucle : une course ne
        s'ouvre pas à tous les coups, un tour unique ne prouverait rien."""
        anomalies = []
        for tour in range(self.TOURS):
            # La limite anti-abus sur la création d'établissement (5 / 5 min)
            # est bien réelle et voulue : c'est la boucle de test qui est
            # anormale, pas le produit.
            security.reset_rate_limits_for_tests()
            e = self._ecole_peuplee(f"idem2-{tour}")
            barriere = threading.Barrier(2)
            codes = {}

            def publier(n):
                client = flask_app_module.app.test_client()
                barriere.wait()
                codes[n] = client.post(f"/api/periods/{e['pid']}/publish",
                                       json={}, headers=e["h"]).status_code

            fils = [threading.Thread(target=publier, args=(i,)) for i in (1, 2)]
            for f in fils:
                f.start()
            for f in fils:
                f.join()

            conn = db.get_connection()
            pubs = conn.execute("SELECT COUNT(*) n FROM period_publications WHERE tenant_id=?",
                                (e["tenant"],)).fetchone()["n"]
            lignes = conn.execute(
                "SELECT COUNT(*) n FROM publication_students WHERE tenant_id=?",
                (e["tenant"],)).fetchone()["n"]
            evts = conn.execute(
                "SELECT COUNT(*) n FROM events WHERE tenant_id=? AND event_type='results.period.published'",
                (e["tenant"],)).fetchone()["n"]
            conn.close()
            if (pubs, lignes, evts) != (1, 4, 1):
                anomalies.append(f"tour {tour} : {pubs} publication(s), {lignes} ligne(s) "
                                 f"d'audience (4 attendues), {evts} événement(s) — codes {codes}")
        self.assertEqual(anomalies, [],
                         f"{len(anomalies)}/{self.TOURS} tours ont dupliqué la proclamation :\n  "
                         + "\n  ".join(anomalies))

    def test_47_retirer_puis_republier_repart_dune_audience_propre(self):
        e = self._ecole_peuplee("idem3")
        self._publier(e)
        self.assertEqual(len(self._audience_en_base(e["tenant"], e["pid"])), 4)
        r = self.c.post(f"/api/periods/{e['pid']}/publish", json={"unpublish": True}, headers=e["h"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._audience_en_base(e["tenant"], e["pid"]), set(),
                         "l'audience reste active après retrait de la proclamation")
        # Republication restreinte : l'ancienne audience ne doit pas ressurgir.
        self._publier(e, {"class_ids": [e["c6"]]})
        self.assertEqual(self._audience_en_base(e["tenant"], e["pid"]),
                         {e["audrey"], e["kevin"]})


# =========================================================================
# §9 — Politique de diffusion : configurable, jamais écrite en dur
# =========================================================================

class PolitiqueDeDiffusion(MixinPublication, Base):
    def _endetter(self, e, eleve, montant):
        item = self.c.post("/api/catalog-items", json={
            "name": "Frais scolaires", "category": "scolarite",
            "amount": montant, "currency": "USD"}, headers=e["h"]).get_json()["id"]
        r = self.c.post("/api/obligations", json={
            "student_id": eleve, "catalog_item_id": item,
            "amount": montant, "academic_year_id": e["year"]}, headers=e["h"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))

    def _politique(self, e, politique):
        r = self.c.put("/api/settings", json={"results_policy": politique}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_48_par_defaut_aucune_condition_financiere(self):
        """Une école qui n'a rien configuré ne retient les bulletins de personne."""
        e = self._ecole_peuplee("pol1")
        self._endetter(e, e["audrey"], 500)
        apercu = self._apercu(e)
        self.assertEqual(apercu["policy"]["mode"], "always")
        self.assertEqual(apercu["included_count"], 4,
                         "un élève a été exclu alors qu'aucune politique n'est configurée")

    def test_49_politique_sur_solde_exclut_et_dit_pourquoi(self):
        e = self._ecole_peuplee("pol2")
        self._endetter(e, e["audrey"], 500)
        self._politique(e, {"mode": "balance", "max_balance": 0})
        apercu = self._apercu(e)
        self.assertEqual(apercu["included_count"], 3)
        self.assertEqual(apercu["excluded_count"], 1)
        exclu = apercu["excluded_sample"][0]
        self.assertEqual(exclu["id"], e["audrey"])
        self.assertIn("solde", exclu["reason"].lower())

    def test_50_le_plafond_est_respecte(self):
        """Le même élève passe ou non selon le seuil choisi par l'école."""
        e = self._ecole_peuplee("pol3")
        self._endetter(e, e["audrey"], 100)
        self._politique(e, {"mode": "balance", "max_balance": 50})
        self.assertEqual(self._apercu(e)["included_count"], 3, "100 > 50 : doit être exclu")
        self._politique(e, {"mode": "balance", "max_balance": 150})
        self.assertEqual(self._apercu(e)["included_count"], 4, "100 <= 150 : doit être inclus")

    def test_51_une_classe_peut_etre_exemptee_par_la_direction(self):
        e = self._ecole_peuplee("pol4")
        self._endetter(e, e["audrey"], 500)
        self._politique(e, {"mode": "balance", "max_balance": 0,
                            "exempt_class_ids": [e["c6"]]})
        self.assertEqual(self._apercu(e)["included_count"], 4,
                         "l'exemption de classe n'a pas été appliquée")

    def test_52_la_politique_ne_touche_jamais_au_resultat_officiel(self):
        """Un résultat non diffusé EXISTE : il reste au dossier, et le
        personnel le voit. La politique gouverne la diffusion, pas la donnée."""
        e = self._ecole_peuplee("pol5")
        self._endetter(e, e["audrey"], 500)
        self._politique(e, {"mode": "balance", "max_balance": 0})
        self._publier(e)

        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM grades WHERE tenant_id=? AND student_id=?",
                         (e["tenant"], e["audrey"])).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 1, "le résultat officiel a été supprimé par la politique de diffusion")
        # Et la Direction le lit toujours.
        dossier = self.c.get(f"/api/students/{e['audrey']}", headers=e["h"]).get_json()
        self.assertTrue(dossier.get("grades"), "la Direction ne voit plus le résultat")

    def test_53_une_politique_invalide_est_refusee(self):
        e = self._ecole_peuplee("pol6")
        for politique in ({"mode": "gratuit"}, {"mode": "balance", "max_balance": -5},
                          {"mode": "balance", "max_balance": "beaucoup"},
                          {"mode": "balance", "exempt_class_ids": "toutes"}, "always"):
            with self.subTest(politique=politique):
                r = self.c.put("/api/settings", json={"results_policy": politique}, headers=e["h"])
                self.assertEqual(r.status_code, 400, f"{politique} → {r.status_code}")
        conn = db.get_connection()
        v = conn.execute("SELECT results_policy FROM tenant_settings WHERE tenant_id=?",
                         (e["tenant"],)).fetchone()
        conn.close()
        self.assertTrue(v is None or v["results_policy"] is None,
                        "une politique refusée a tout de même été enregistrée")

    def test_54_la_politique_est_propre_a_chaque_etablissement(self):
        a = self._ecole_peuplee("pol7a")
        b = self._ecole_peuplee("pol7b")
        self._endetter(a, a["audrey"], 500)
        self._endetter(b, b["audrey"], 500)
        self._politique(a, {"mode": "balance", "max_balance": 0})
        self.assertEqual(self._apercu(a)["included_count"], 3)
        self.assertEqual(self._apercu(b)["included_count"], 4,
                         "la politique de A s'est appliquée à B")


# =========================================================================
# §10 — Ce que le parent voit réellement
# =========================================================================

class AccesParent(MixinPublication, Base):
    def _resultats_vus(self, headers, eleve):
        r = self.c.get(f"/api/students/{eleve}", headers=headers)
        if r.status_code != 200:
            return r.status_code, []
        corps = r.get_json()
        return 200, [(g["subject"], g["period"]) for g in (corps.get("grades") or [])]

    def test_55_avant_proclamation_le_parent_ne_voit_rien(self):
        e = self._ecole_peuplee("par1")
        h = self.parent(e, [e["audrey"]], "par1")
        code, resultats = self._resultats_vus(h, e["audrey"])
        self.assertEqual(code, 200)
        self.assertEqual(resultats, [],
                         "des résultats non proclamés sont visibles du parent")

    def test_56_apres_proclamation_le_parent_voit_son_enfant(self):
        e = self._ecole_peuplee("par2")
        h = self.parent(e, [e["audrey"]], "par2")
        self._publier(e)
        code, resultats = self._resultats_vus(h, e["audrey"])
        self.assertEqual(code, 200)
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0][1], "Période 1")

    def test_57_le_parent_ne_voit_pas_un_enfant_qui_nest_pas_le_sien(self):
        e = self._ecole_peuplee("par3")
        h = self.parent(e, [e["audrey"]], "par3")
        self._publier(e)
        code, _ = self._resultats_vus(h, e["sarah"])
        self.assertEqual(code, 404,
                         "un parent atteint le dossier d'un élève non autorisé")

    def test_58_un_parent_dun_autre_etablissement_ne_voit_rien(self):
        a = self._ecole_peuplee("par4a")
        b = self._ecole_peuplee("par4b")
        hb = self.parent(b, [b["audrey"]], "par4b")
        self._publier(a)
        code, _ = self._resultats_vus(hb, a["audrey"])
        self.assertEqual(code, 404)

    def test_59_un_parent_hors_audience_ne_voit_rien_meme_apres_proclamation(self):
        """Le cœur de la publication filtrée : la période EST proclamée, mais
        cet élève n'en fait pas partie."""
        e = self._ecole_peuplee("par5")
        h_dans = self.parent(e, [e["audrey"]], "par5in")     # 6e A → inclus
        h_hors = self.parent(e, [e["sarah"]], "par5out")     # 5e B → exclu
        self._publier(e, {"class_ids": [e["c6"]]})

        _, vus_dans = self._resultats_vus(h_dans, e["audrey"])
        _, vus_hors = self._resultats_vus(h_hors, e["sarah"])
        self.assertEqual(len(vus_dans), 1, "le parent inclus ne voit pas les résultats")
        self.assertEqual(vus_hors, [],
                         "un parent EXCLU de l'audience voit tout de même les résultats — "
                         "la proclamation filtrée ne sert alors à rien")

    def test_60_le_bulletin_suit_la_meme_regle_que_les_notes(self):
        """Un bulletin calculé sur des résultats non diffusés serait un
        document officiel que l'établissement n'a pas autorisé."""
        e = self._ecole_peuplee("par6")
        h = self.parent(e, [e["sarah"]], "par6")
        self._publier(e, {"class_ids": [e["c6"]]})   # Sarah est en 5e B : exclue
        r = self.c.get(f"/api/students/{e['sarah']}/bulletin", headers=h)
        self.assertEqual(r.status_code, 200)
        b = r.get_json()
        self.assertEqual(b.get("subjects") or [], [],
                         "le bulletin expose des résultats hors audience")

    def test_61_retirer_la_proclamation_referme_laccès_du_parent(self):
        e = self._ecole_peuplee("par7")
        h = self.parent(e, [e["audrey"]], "par7")
        self._publier(e)
        self.assertEqual(len(self._resultats_vus(h, e["audrey"])[1]), 1)
        self.c.post(f"/api/periods/{e['pid']}/publish", json={"unpublish": True}, headers=e["h"])
        self.assertEqual(self._resultats_vus(h, e["audrey"])[1], [],
                         "le parent voit encore des résultats dépubliés")

    def test_62_le_personnel_voit_les_resultats_avant_toute_proclamation(self):
        """La règle ne s'applique qu'aux parents : l'établissement doit pouvoir
        relire ses résultats avant de les proclamer."""
        e = self._ecole_peuplee("par8")
        prof_h = self.prof(e, [e["c6"]], "par8")
        for nom, h in (("direction", e["h"]), ("professeur", prof_h)):
            with self.subTest(role=nom):
                code, resultats = self._resultats_vus(h, e["audrey"])
                self.assertEqual(code, 200)
                self.assertEqual(len(resultats), 1, f"{nom} ne voit pas les résultats non proclamés")


# =========================================================================
# §12 — L'histoire ne se réécrit pas
# =========================================================================

class HistoriqueInterAnnees(Base):
    def _trois_annees(self, suffixe):
        """Un élève qui progresse : 4e A, puis 5e B, puis 6e A.

        Chaque année a SA structure — l'école change de découpage en cours de
        route, ce qui est le cas réel qui casse les systèmes naïfs.
        """
        e = self.ecole(suffixe)
        e["annees"] = {}
        e["classes"] = {}
        plan = [("2024-2025", "4e A", ["Trimestre 1", "Trimestre 2", "Trimestre 3"]),
                ("2025-2026", "5e B", ["Période 1", "Période 2", "Période 3", "Période 4"]),
                ("2026-2027", "6e A", ["Semestre 1", "Semestre 2"])]
        eleve = None
        for i, (label, classe_nom, periodes) in enumerate(plan):
            # Les trois millésimes sont créés explicitement : l'année par défaut
            # de l'inscription s'appelle « Année en cours » et reste inutilisée,
            # exactement comme pour une école qui arrive en cours de route.
            an = self.annee(e, label)
            self.c.post(f"/api/academic-years/{an}/activate", headers=e["h"])
            e["annees"][label] = an
            cls = self.classe(e, classe_nom, "secondaire", annee=an)
            e["classes"][label] = cls
            if eleve is None:
                eleve = self.eleve(e, "Audrey", "Mukendi", cls, annee=an)
            else:
                self.c.put(f"/api/students/{eleve}", json={"class_id": cls}, headers=e["h"])
            for j, p in enumerate(periodes):
                self.periode(e, p, sort=j)
            # Une note dans la PREMIÈRE période de chaque année.
            r = self.notes(e, cls, periodes[0], eleve, score=10 + i * 2)
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        e["eleve"] = eleve
        return e

    def _notes_par_annee(self, tenant, eleve):
        conn = db.get_connection()
        rows = [dict(r) for r in conn.execute(
            """SELECT g.score, g.period, g.academic_year_id, y.label AS annee, g.period_id
               FROM grades g JOIN academic_years y ON y.id = g.academic_year_id
               WHERE g.tenant_id=? AND g.student_id=? ORDER BY y.label""", (tenant, eleve))]
        conn.close()
        return rows

    def test_63_chaque_annee_garde_sa_structure_et_ses_resultats(self):
        e = self._trois_annees("hist1")
        notes = self._notes_par_annee(e["tenant"], e["eleve"])
        self.assertEqual(len(notes), 3, "une note par année attendue")
        self.assertEqual([n["annee"] for n in notes], ["2024-2025", "2025-2026", "2026-2027"])
        self.assertEqual([n["period"] for n in notes],
                         ["Trimestre 1", "Période 1", "Semestre 1"],
                         "les libellés de période ont été mélangés entre années")
        self.assertEqual([n["score"] for n in notes], [10.0, 12.0, 14.0])
        # Chaque note est rattachée à une période RÉELLE, et à une seule.
        self.assertTrue(all(n["period_id"] for n in notes),
                        "une note n'est rattachée à aucune période")
        self.assertEqual(len({n["period_id"] for n in notes}), 3)

    def test_64_les_structures_des_annees_passees_restent_intactes(self):
        e = self._trois_annees("hist2")
        conn = db.get_connection()
        par_annee = {}
        for r in conn.execute(
                """SELECT y.label AS annee, p.label FROM academic_periods p
                   JOIN academic_years y ON y.id = p.academic_year_id
                   WHERE p.tenant_id=? ORDER BY y.label, p.sort""", (e["tenant"],)):
            par_annee.setdefault(r["annee"], []).append(r["label"])
        conn.close()
        self.assertEqual(len(par_annee["2024-2025"]), 3)
        self.assertEqual(len(par_annee["2025-2026"]), 4)
        self.assertEqual(len(par_annee["2026-2027"]), 2,
                         "l'année en cours n'a pas sa propre structure")

    def test_65_modifier_lannee_en_cours_ne_touche_pas_les_precedentes(self):
        e = self._trois_annees("hist3")
        avant = self._notes_par_annee(e["tenant"], e["eleve"])

        # On remanie 2026-2027 : renommage, nouvelle période, suppression.
        cal = self.calendrier(e, academic_year_id=e["annees"]["2026-2027"])
        periodes = cal["divisions"][0]["periods"]
        self.c.put(f"/api/periods/{periodes[0]['id']}", json={"label": "Semestre A"}, headers=e["h"])
        self.periode(e, "Semestre C", sort=9)
        self.c.delete(f"/api/periods/{periodes[1]['id']}", headers=e["h"])

        apres = self._notes_par_annee(e["tenant"], e["eleve"])
        anciennes_avant = [n for n in avant if n["annee"] != "2026-2027"]
        anciennes_apres = [n for n in apres if n["annee"] != "2026-2027"]
        self.assertEqual(anciennes_avant, anciennes_apres,
                         "les résultats des années passées ont été modifiés")

        # Et les structures passées n'ont pas bougé non plus.
        cal_2024 = self.calendrier(e, academic_year_id=e["annees"]["2024-2025"])
        self.assertEqual([p["label"] for p in cal_2024["divisions"][0]["periods"]],
                         ["Trimestre 1", "Trimestre 2", "Trimestre 3"])

    def test_66_proclamer_une_annee_ne_proclame_pas_les_autres(self):
        """Le défaut historique : la proclamation se décidait sur le libellé,
        toutes années confondues."""
        e = self._trois_annees("hist4")
        h = self.parent(e, [e["eleve"]], "hist4")
        cal = self.calendrier(e, academic_year_id=e["annees"]["2024-2025"])
        p_2024 = [p for p in cal["divisions"][0]["periods"] if p["label"] == "Trimestre 1"][0]
        r = self.c.post(f"/api/periods/{p_2024['id']}/publish", json={}, headers=e["h"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        dossier = self.c.get(f"/api/students/{e['eleve']}", headers=h).get_json()
        vus = [(g["period"], g["score"]) for g in (dossier.get("grades") or [])]
        self.assertEqual(vus, [("Trimestre 1", 10.0)],
                         f"le parent voit des résultats d'autres années : {vus}")

    def test_67_un_libelle_identique_dans_deux_annees_reste_distinct(self):
        e = self.ecole("hist5")
        an1 = e["year"]
        c1 = self.classe(e, "6e A", "secondaire", annee=an1)
        eleve = self.eleve(e, "Audrey", "Mukendi", c1, annee=an1)
        self.periode(e, "Période 1", sort=0)
        self.notes(e, c1, "Période 1", eleve, score=8)

        an2 = self.annee(e, "2027-2028")
        self.c.post(f"/api/academic-years/{an2}/activate", headers=e["h"])
        c2 = self.classe(e, "7e A", "secondaire", annee=an2)
        self.c.put(f"/api/students/{eleve}", json={"class_id": c2}, headers=e["h"])
        self.periode(e, "Période 1", sort=0)   # même libellé, autre année
        self.notes(e, c2, "Période 1", eleve, score=19)

        notes = self._notes_par_annee(e["tenant"], eleve)
        self.assertEqual(len(notes), 2)
        self.assertNotEqual(notes[0]["period_id"], notes[1]["period_id"],
                            "deux années partagent la même période")
        self.assertNotEqual(notes[0]["academic_year_id"], notes[1]["academic_year_id"])


# =========================================================================
# §14 — Permissions, rôle par rôle
# =========================================================================

class PermissionsAcademiques(MixinPublication, Base):
    def setUp(self):
        super().setUp()
        # Un suffixe par test : setUp s'exécute pour CHAQUE méthode, et
        # réutiliser le même e-mail ferait échouer la création dès la seconde.
        suffixe = "perm-" + self.id().rsplit(".", 1)[-1][:12]
        self.e = self._ecole_peuplee(suffixe)
        self.roles = {
            "directeur": self.e["h"],
            "professeur": self.prof(self.e, [self.e["c6"]], suffixe),
            "parent": self.parent(self.e, [self.e["audrey"]], suffixe),
        }

    def _appel(self, methode, chemin, h, corps=None):
        return getattr(self.c, methode)(chemin, json=corps if corps is not None else {}, headers=h)

    def test_68_seule_la_direction_configure_le_calendrier(self):
        pid = self.e["pid"]
        actions = [
            ("post", "/api/periods", {"label": "Ajoutée par un tiers", "sort": 9}),
            ("put", f"/api/periods/{pid}", {"label": "Renommée par un tiers"}),
            ("delete", f"/api/periods/{pid}", None),
            ("post", f"/api/periods/{pid}/lock", {}),
            ("post", f"/api/periods/{pid}/reopen", {"reason": "je veux modifier les notes"}),
            ("get", f"/api/periods/{pid}/reopenings", None),
            ("post", f"/api/periods/{pid}/publish", {}),
            ("post", f"/api/periods/{pid}/publication-preview", {}),
        ]
        for methode, chemin, corps in actions:
            for role in ("professeur", "parent"):
                with self.subTest(route=f"{methode.upper()} {chemin}", role=role):
                    r = self._appel(methode, chemin, self.roles[role], corps)
                    self.assertEqual(r.status_code, 403,
                                     f"{role} obtient {r.status_code} sur {methode.upper()} {chemin}")

    def test_69_la_lecture_du_calendrier_est_ouverte_a_tous_les_roles(self):
        """Un parent doit pouvoir savoir quand tombe la proclamation ; c'est
        une information de calendrier, pas un résultat."""
        for role, h in self.roles.items():
            with self.subTest(role=role):
                r = self.c.get("/api/academic-calendar", headers=h)
                self.assertEqual(r.status_code, 200, f"{role} → {r.status_code}")

    def test_70_le_parent_ne_recoit_pas_les_champs_internes_des_periodes(self):
        r = self.c.get("/api/periods", headers=self.roles["parent"])
        self.assertEqual(r.status_code, 200)
        for p in r.get_json()["periods"]:
            self.assertNotIn("published_by", p, "l'identité du proclamateur fuit vers le parent")
            self.assertNotIn("locked_by", p)

    def test_71_aucune_route_academique_nest_accessible_sans_session(self):
        pid = self.e["pid"]
        for methode, chemin in (("get", "/api/academic-calendar"), ("get", "/api/periods"),
                                ("post", "/api/periods"), ("put", f"/api/periods/{pid}"),
                                ("delete", f"/api/periods/{pid}"),
                                ("post", f"/api/periods/{pid}/lock"),
                                ("post", f"/api/periods/{pid}/reopen"),
                                ("get", f"/api/periods/{pid}/reopenings"),
                                ("post", f"/api/periods/{pid}/publish"),
                                ("post", f"/api/periods/{pid}/publication-preview")):
            with self.subTest(route=f"{methode.upper()} {chemin}"):
                r = getattr(self.c, methode)(chemin, json={})
                self.assertEqual(r.status_code, 401, f"{chemin} → {r.status_code} sans session")


# =========================================================================
# §15 — Rien de partiel ne survit à un refus
# =========================================================================

class TransactionsEtRollback(MixinPublication, Base):
    def _compter(self, tenant):
        conn = db.get_connection()
        n = {}
        for t in ("academic_periods", "period_publications", "publication_students",
                  "period_reopenings", "grades", "events", "notifications"):
            col = "tenant_id"
            n[t] = conn.execute(f"SELECT COUNT(*) n FROM {t} WHERE {col}=?", (tenant,)).fetchone()["n"]
        conn.close()
        return n

    def test_72_une_publication_refusee_ne_laisse_ni_audience_ni_notification(self):
        e = self._ecole_peuplee("roll1")
        avant = self._compter(e["tenant"])
        r = self._publier(e, {"student_ids": "pas-une-liste"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._compter(e["tenant"]), avant,
                         "une publication refusée a laissé des écritures derrière elle")

    def test_73_une_seconde_publication_refusee_ne_double_pas_laudience(self):
        e = self._ecole_peuplee("roll2")
        self._publier(e)
        apres_premiere = self._compter(e["tenant"])
        r = self._publier(e)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self._compter(e["tenant"]), apres_premiere,
                         "la seconde publication refusée a tout de même écrit")

    def test_74_une_creation_de_periode_refusee_ne_cree_rien(self):
        e = self._ecole_peuplee("roll3")
        avant = self._compter(e["tenant"])
        self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=e["h"])  # doublon
        self.c.post("/api/periods", json={"label": "Bancale", "starts_on": "2026-11-01",
                                          "ends_on": "2026-01-01"}, headers=e["h"])
        self.c.post("/api/periods", json={"label": "Sans division valide",
                                          "division": "collège"}, headers=e["h"])
        self.assertEqual(self._compter(e["tenant"])["academic_periods"],
                         avant["academic_periods"])

    def test_75_une_reouverture_refusee_ne_touche_ni_la_periode_ni_lhistorique(self):
        e = self._ecole_peuplee("roll4")
        self.c.post(f"/api/periods/{e['pid']}/lock", json={}, headers=e["h"])
        avant = self._compter(e["tenant"])
        etat_avant = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == e["pid"]][0]

        r = self.c.post(f"/api/periods/{e['pid']}/reopen", json={"reason": "non"}, headers=e["h"])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._compter(e["tenant"])["period_reopenings"],
                         avant["period_reopenings"])
        etat_apres = [p for p in self.periodes_en_base(e["tenant"]) if p["id"] == e["pid"]][0]
        self.assertEqual(etat_apres["admin_state"], etat_avant["admin_state"])
        self.assertEqual(etat_apres["locked_at"], etat_avant["locked_at"])

    def test_76_une_saisie_refusee_par_le_verrou_necrit_aucune_note(self):
        e = self._ecole_peuplee("roll5")
        self.c.post(f"/api/periods/{e['pid']}/lock", json={}, headers=e["h"])
        avant = self._compter(e["tenant"])["grades"]
        r = self.c.post(f"/api/classes/{e['c6']}/grades", json={
            "subject": "Physique", "period": "Période 1", "max_score": 20,
            "entries": [{"student_id": e["audrey"], "score": 20},
                        {"student_id": e["kevin"], "score": 19}]}, headers=e["h"])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._compter(e["tenant"])["grades"], avant,
                         "des notes ont été écrites malgré le verrou")
