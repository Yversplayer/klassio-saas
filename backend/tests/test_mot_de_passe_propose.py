"""KLASSIO — le mot de passe proposé à la création d'un compte (assets/js/motdepasse.js).

Le générateur vit dans le navigateur : ces tests gardent ce qui, s'il cassait,
rendrait la proposition dangereuse ou inutilisable — sans navigateur.

- La liste : uniquement a-z (un accent oblige à chercher une touche sur un
  téléphone et paraît mal orthographié), sans doublon, assez longue pour que
  quatre mots et un nombre dépassent 45 bits.
- Le tirage : crypto.getRandomValues, jamais Math.random (prévisible).
- La forme « Mot-Mot-Mot-Mot-123 » doit passer les règles du SERVEUR : une
  proposition refusée à l'enregistrement serait pire que pas de proposition.
- Les quatre champs qui créent un mot de passe sont branchés.
"""
import math
import os
import re
import secrets
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validation import valid_password  # noqa: E402

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOURCE = os.path.join(RACINE, "assets", "js", "motdepasse.js")


def _source():
    with open(SOURCE, encoding="utf-8") as f:
        return f.read()


def _mots():
    bloc = re.search(r"var MOTS = \((.*?)\)\.trim\(\)\.split", _source(), re.S)
    assert bloc, "liste MOTS introuvable dans motdepasse.js"
    return "".join(re.findall(r'"([^"]*)"', bloc.group(1))).split()


class MotDePasseProposeTests(unittest.TestCase):
    def test_liste_sans_accent_sans_doublon(self):
        mots = _mots()
        hors_regle = [m for m in mots if not re.fullmatch(r"[a-z]{3,9}", m)]
        self.assertEqual(hors_regle, [], "uniquement a-z, 3 à 9 lettres")
        doublons = sorted({m for m in mots if mots.count(m) > 1})
        self.assertEqual(doublons, [])
        # Mots qui s'écrivent avec un accent : écrits sans, ils paraîtraient fautifs.
        for fautif in ("foret", "ecole", "cafe", "eventail", "fenetre", "etoile", "riviere"):
            self.assertNotIn(fautif, mots)

    def test_au_moins_45_bits(self):
        n = len(_mots())
        # quatre mots distincts (arrangements) et un nombre de 100 à 999
        bits = math.log2(n * (n - 1) * (n - 2) * (n - 3)) + math.log2(900)
        self.assertGreaterEqual(bits, 45, f"{n} mots : {bits:.1f} bits seulement")

    def test_tirage_cryptographique(self):
        src = _source()
        self.assertIn("crypto.getRandomValues", src)
        self.assertNotRegex(src, r"Math\.random\s*\(", "Math.random est prévisible : jamais pour un mot de passe")

    def test_la_forme_proposee_passe_les_regles_du_serveur(self):
        mots = _mots()
        for _ in range(300):
            choix = []
            while len(choix) < 4:
                m = secrets.choice(mots)
                if m not in choix:
                    choix.append(m)
            phrase = "-".join(m.capitalize() for m in choix) + "-" + str(100 + secrets.randbelow(900))
            valid_password(phrase)  # lève ValidationError si refusée

    def test_les_quatre_champs_sont_branches(self):
        for page, champ in (("inscription", "passwordInput"), ("invitation", "acceptPassword"),
                            ("parametres", "pwNew"), ("portail", "resetPw")):
            with open(os.path.join(RACINE, "app", page + ".html"), encoding="utf-8") as f:
                html = f.read()
            self.assertIn("motdepasse.js", html, page)
            balise = re.search(r'<input[^>]*id="%s"[^>]*>' % champ, html)
            self.assertTrue(balise and "data-kx-suggere" in balise.group(0), f"{page} : champ {champ} non branché")


if __name__ == "__main__":
    unittest.main()
