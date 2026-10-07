"""KLASSIO — l'adresse de Klassio sur chaque page (demande du propriétaire, 07/10/2026).

Une page ajoutée demain sans elle — ni écrite dans la page, ni apportée par le
pied de page public (public.js) ou la barre de l'application (admin.js) —
ferait échouer ce test. Le jour où l'adresse change (contact@klassio.cd),
ce test et un `grep` indiquent tous les endroits à mettre à jour.
"""
import glob
import os
import unittest

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ADRESSE = "mudeyimusimwa@gmail.com"


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


class ContactPartout(unittest.TestCase):
    def test_les_scripts_partages_portent_l_adresse(self):
        for script in ("public.js", "admin.js"):
            self.assertIn(ADRESSE, lire(os.path.join(RACINE, "assets", "js", script)), script)

    def test_chaque_page_affiche_l_adresse(self):
        pages = glob.glob(os.path.join(RACINE, "*.html")) + glob.glob(os.path.join(RACINE, "app", "*.html"))
        self.assertGreater(len(pages), 40)
        sans = []
        for page in pages:
            source = lire(page)
            if ADRESSE in source or "assets/js/public.js" in source or "assets/js/admin.js" in source:
                continue
            sans.append(os.path.relpath(page, RACINE))
        self.assertEqual(sans, [], "pages sans l'adresse de Klassio")


if __name__ == "__main__":
    unittest.main()
