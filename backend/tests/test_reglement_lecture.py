"""KLASSIO — lecture d'un règlement intérieur réel (08/10/2026).

Le modèle : le règlement d'une école de Kinshasa — un tableau « Article |
Faute | Sanction » (« Dérangement → 10 points en conduite + travail
manuel »), des fautes à « renvoi définitif immédiat », et une échelle « De
80 à 100 points : Excellente conduite (E) ». Rien n'est enregistré sans la
Direction ; une photo n'est jamais « devinée ».
"""
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import reglement  # noqa: E402
import security  # noqa: E402


def docx(lignes):
    """Un .docx minimal : un tableau, une cellule = des paragraphes."""
    def p(t):
        return f"<w:p><w:r><w:t xml:space=\"preserve\">{t}</w:t></w:r></w:p>"
    rows = "".join("<w:tr>" + "".join("<w:tc>" + "".join(p(x) for x in cell.split("\n")) + "</w:tc>" for cell in row) + "</w:tr>" for row in lignes)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{p('TITRE 6 : SANCTIONS NEGATIVES')}<w:tbl>{rows}</w:tbl></w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


BAREME = docx([
    ["ARTICLE", "FAUTE OU MANQUEMENT", "SANCTION"],
    ["Article 2", "- Dérangement\n- Dérangement 3 fois par semaine", "- 10 points en conduite + travail manuel\n- Exclusion d'un jour + convocation des parents"],
    ["Article 3", "- Sortie non autorisée de la classe", "- 20 points en conduite"],
])

FIN = """Les fautes qui nécessitent un renvoi définitif immédiat :
- Usage des faux documents
- Le vol

APPRECIATION DE LA CONDUITE
De 80 à 100 points : Excellente conduite (E)
De 65 à 79 points : Très bonne (TB)
De 54 à 40 points : Assez bonne (AB)
A partir de 28 points : Mauvaise conduite (Ma)
"""


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class LectureReglementTests(unittest.TestCase):

    def test_01_le_bareme_word_donne_faute_points_et_sanction(self):
        lu = reglement.analyser(reglement.extraire("reglement.docx", BAREME))
        par = {p["label"]: p for p in lu["proposals"]}
        self.assertEqual(par["Dérangement"]["points"], -10)
        self.assertEqual(par["Dérangement"]["measure"], "10 points en conduite + travail manuel")
        self.assertEqual(par["Sortie non autorisée de la classe"]["points"], -20)
        self.assertIn("Exclusion d'un jour", par["Dérangement 3 fois par semaine"]["measure"])
        self.assertNotIn("FAUTE OU MANQUEMENT", par, "la ligne d'en-tête est devenue une règle")

    def test_02_renvois_et_echelle_de_conduite(self):
        lu = reglement.analyser(FIN)
        par = {p["label"]: p for p in lu["proposals"]}
        self.assertEqual(par["Le vol"]["points"], -100)
        self.assertEqual(par["Le vol"]["severity"], "high")
        self.assertEqual(lu["capital"], 100)
        self.assertEqual(lu["conduct_scale"][0], [80, "Excellente conduite (E)"])
        self.assertEqual(lu["conduct_scale"][-1], [0, "Mauvaise conduite (Ma)"])
        self.assertIn([40, "Assez bonne (AB)"], lu["conduct_scale"])

    def test_03_une_photo_n_est_pas_devinee(self):
        with self.assertRaises(reglement.Illisible):
            reglement.extraire("reglement.jpg", b"\xff\xd8\xff")


class RouteReglementTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        r = cls.c.post("/api/auth/register-school", json={"email": "dir@regl.test", "password": "Secret123!",
                                                          "name": "Direction", "school_name": "École Règlement"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["token"]}

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def test_10_analyse_puis_confirmation_avec_mesure_et_echelle(self):
        r = self.c.post("/api/discipline/reglement/analyze", data={"file": (io.BytesIO(BAREME + b""), "reglement.docx")},
                        headers=self.h, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        props = r.get_json()["proposals"]
        derangement = next(p for p in props if p["label"] == "Dérangement")
        c = self.c.post("/api/discipline/reglement/confirm", json={"rules": [derangement],
                        "capital": 100, "conduct_scale": [[80, "Excellente conduite (E)"], [0, "Mauvaise conduite (Ma)"]]}, headers=self.h)
        self.assertEqual(c.status_code, 201, c.get_data(as_text=True))
        regle = next(x for x in self.c.get("/api/discipline/rules", headers=self.h).get_json() if x["label"] == "Dérangement")
        self.assertEqual(regle["measure"], "10 points en conduite + travail manuel")
        th = self.c.get("/api/discipline/thresholds", headers=self.h).get_json()
        self.assertEqual(th["conduct_scale"][0], [80, "Excellente conduite (E)"])

    def test_11_une_photo_est_refusee_avec_une_explication(self):
        r = self.c.post("/api/discipline/reglement/analyze", data={"file": (io.BytesIO(b"\xff\xd8\xff"), "page.jpg")},
                        headers=self.h, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("photo", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
