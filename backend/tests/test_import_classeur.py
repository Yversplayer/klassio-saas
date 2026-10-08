"""KLASSIO — l'import lit le classeur que l'école A DÉJÀ (08/10/2026).

Le propriétaire a déposé le classeur d'une école : plusieurs feuilles, un titre
au-dessus de chaque tableau. Réponse : « Aucune ligne exploitable ». Reproduit
sur des classeurs fictifs de même forme : 0 élève sur chacun. Le moteur
attendait les titres en ligne 1 et ne lisait qu'une feuille.

Chaque test ci-dessous décrit une forme de fichier réellement tenue dans les
écoles. Aucun ne demande à l'école de retoucher son fichier.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import openpyxl  # noqa: E402
import app as flask_app_module  # noqa: E402
import security  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


def classeur(*feuilles):
    """feuilles : (titre, [lignes]) — données fictives."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for titre, lignes in feuilles:
        ws = wb.create_sheet(titre)
        for ligne in lignes:
            ws.append(ligne)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


ENTETE_ECOLE = [["COMPLEXE SCOLAIRE LES ETOILES"], ["LISTE DES ELEVES — 2025-2026"], []]


class ClasseurReelTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def _ecole(self, nom):
        security.reset_rate_limits_for_tests()
        r = self.client.post("/api/auth/register-school", json={
            "email": f"dir@{nom}.classeur.test", "password": "Secret123!",
            "name": "Directrice", "school_name": f"École {nom}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def _analyser(self, h, fichier, nom="ecole.xlsx", attendu=200):
        r = self.client.post("/api/onboarding/analyze-import", data={"file": (fichier, nom)},
                             content_type="multipart/form-data", headers=h)
        self.assertEqual(r.status_code, attendu, r.get_data(as_text=True))
        return r.get_json()

    def test_01_titres_au_dessus_classes_eleves_paiements(self):
        """La forme exacte du fichier signalé : feuille Classes (sans élèves),
        feuille Élèves sous trois lignes de titre, feuille Paiements à
        rattacher. Classe écrite « 6ème A » et « 6 eme a »."""
        h = self._ecole("complet")
        f = classeur(
            ("CLASSES", ENTETE_ECOLE + [["N°", "CLASSE", "TITULAIRE"], [1, "6ème A", "M. Lukusa"]]),
            ("ELEVES", ENTETE_ECOLE + [
                ["N°", "NOMS", "POST-NOMS", "PRENOMS", "SEXE", "CLASSE", "NOM DU PARENT", "TEL. PARENT", "FRAIS ANNUELS"],
                [1, "KABONGO", "MUTOMBO", "Grace", "F", "6ème A", "Jean Kabongo", 812345678, 300],
                [2, "ILUNGA", "KASONGO", "Kevin", "M", "6 eme a", "Marie Ilunga", "0991234567", 300],
                [3, "MBUYI", None, "Sarah", "F", "5ème B", "Paul Mbuyi", "0851112233", 250]]),
            ("PAIEMENTS", [["SUIVI DES PAIEMENTS"], [],
                           ["N°", "NOM DE L'ELEVE", "CLASSE", "DATE", "MONTANT PAYE"],
                           [1, "KABONGO MUTOMBO Grace", "6ème A", "05/09/2025", 100],
                           [2, "Grace KABONGO MUTOMBO", "6ème A", "05/10/2025", 50],
                           [3, "MBUYI Sarah", "5ème B", "06/09/2025", 250]]))
        a = self._analyser(h, f)
        self.assertEqual(a["students_count"], 3, "élèves non trouvés sous les lignes de titre")
        self.assertEqual(a["classes_detected"], ["5e B", "6e A"], "« 6ème A » et « 6 eme a » : une seule classe")
        par_prenom = {e["first_name"]: e for e in a["normalized_records"]}
        self.assertEqual(par_prenom["Grace"]["last_name"], "KABONGO MUTOMBO", "postnom perdu")
        self.assertEqual(par_prenom["Grace"]["guardian_name"], "Jean Kabongo")
        self.assertEqual(par_prenom["Grace"]["guardian_phone"], "0812345678", "zéro du téléphone perdu")
        self.assertEqual(par_prenom["Grace"]["paid_amount"], 150, "deux tranches de la feuille Paiements")
        self.assertEqual(par_prenom["Sarah"]["paid_amount"], 250)
        self.assertEqual(par_prenom["Kevin"]["paid_amount"], 0)
        roles = {s["name"]: s["role"] for s in a["sheets"]}
        self.assertEqual(roles, {"CLASSES": "ignoree", "ELEVES": "eleves", "PAIEMENTS": "paiements"})

        r = self.client.post("/api/onboarding/confirm-import",
                             json={"import_session_id": a["import_session_id"]}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        eleves = {e["first_name"]: e for e in self.client.get("/api/students", headers=h).get_json()}
        self.assertEqual(len(eleves), 3)
        self.assertEqual(eleves["Grace"]["balance"], 150, "300 dus, 150 versés")

    def test_02_une_feuille_par_classe_sans_colonne_classe(self):
        """La classe vient du nom de la feuille ou de « CLASSE : … » au-dessus
        du tableau ; la ligne TOTAL n'est pas un élève."""
        h = self._ecole("parclasse")
        f = classeur(
            ("6e A", [["ECOLE LA SOURCE"], [], ["N°", "NOMS ET POST-NOMS", "PRENOM"],
                      [1, "TSHIBANGU KALALA", "Daniel"], [2, "NKULU BANZA", "Ruth"]]),
            ("Feuil2", [["ECOLE LA SOURCE"], ["CLASSE : 6e B"], [], ["N°", "NOMS ET POST-NOMS", "PRENOM"],
                        [1, "MWAMBA LUBO", "Esther"], ["TOTAL", None, None]]))
        a = self._analyser(h, f)
        self.assertEqual(a["students_count"], 3, [r["last_name"] for r in a["normalized_records"]])
        classes = {e["first_name"]: e["class_name"] for e in a["normalized_records"]}
        self.assertEqual(classes, {"Daniel": "6e A", "Ruth": "6e A", "Esther": "6e B"})

    def test_03_plusieurs_classes_dans_une_feuille_en_blocs(self):
        h = self._ecole("blocs")
        f = classeur(("Listes", [
            ["CLASSE : 1re A"], ["Nom", "Prénom"], ["Lukusa", "Marc"],
            [], ["CLASSE : 1re B"], ["Nom", "Prénom"], ["Kanyinda", "Naomie"], ["Badibanga", "Josué"]]))
        a = self._analyser(h, f)
        classes = {e["first_name"]: e["class_name"] for e in a["normalized_records"]}
        self.assertEqual(classes, {"Marc": "1re A", "Naomie": "1re B", "Josué": "1re B"})

    def test_04_la_colonne_du_parent_n_est_jamais_le_nom_de_l_eleve(self):
        """« Nom du parent » contient « nom » : placée avant la colonne de
        l'élève, elle devenait le nom de l'élève."""
        h = self._ecole("parent")
        csv = "Nom du parent,Nom de l'élève,Classe\nJean Kabongo,Kabongo Grace,6e A\n"
        a = self._analyser(h, io.BytesIO(csv.encode()), "eleves.csv")
        e = a["normalized_records"][0]
        self.assertEqual((e["last_name"], e["first_name"], e["guardian_name"]), ("Kabongo", "Grace", "Jean Kabongo"))

    def test_05_un_paiement_sans_eleve_n_entre_pas(self):
        """Rien n'est rattaché au hasard : un nom absent de la liste, ou porté
        par deux élèves de classes non précisées, est signalé et ignoré."""
        h = self._ecole("orphelin")
        f = classeur(
            ("Élèves", [["Nom", "Prénom", "Classe", "Frais"], ["Kabongo", "Grace", "6e A", 300],
                        ["Mukendi", "Audrey", "6e A", 300], ["Mukendi", "Audrey", "5e B", 250]]),
            ("Versements", [["Élève", "Montant payé"], ["Inconnu Personne", 80], ["Mukendi Audrey", 40]]))
        a = self._analyser(h, f)
        self.assertEqual(a["financial_projection"]["total_payments_sum"], 0)
        problemes = " | ".join(x["issue"] for x in a["anomalies"])
        self.assertIn("élève introuvable", problemes)
        self.assertIn("plusieurs élèves portent ce nom", problemes)

    def test_06_un_ancien_xls_recoit_une_consigne_claire(self):
        h = self._ecole("xls")
        r = self._analyser(h, io.BytesIO(b"\xd0\xcf\x11\xe0 pas un xlsx"), "eleves.xls", attendu=400)
        self.assertIn("Enregistrer sous", r["error"])

    def test_07_sans_liste_d_eleves_le_refus_dit_ce_qui_a_ete_lu(self):
        h = self._ecole("vide")
        f = classeur(("CLASSES", [["Classe", "Titulaire"], ["6e A", "M. Lukusa"]]), ("Lisez-moi", [["Bonjour"]]))
        r = self._analyser(h, f, attendu=400)
        self.assertIn("CLASSES", r["error"])
        self.assertIn("Lisez-moi", r["error"])


if __name__ == "__main__":
    unittest.main()
