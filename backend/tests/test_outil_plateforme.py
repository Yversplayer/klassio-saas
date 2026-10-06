"""KLASSIO — l'outil qui crée les comptes d'administration de la plateforme.

backend/tools/platform_admin.py est le SEUL moyen de créer un administrateur
(aucune route HTTP n'écrit platform_accounts). Sur une base neuve, sans lui,
personne ne confirme le premier paiement et aucune école ne s'ouvre.

Trouvé au premier déploiement (06/10/2026) : l'ancienne version écrivait
`INSERT OR IGNORE`, du SQLite pur — sous PostgreSQL, le moteur de production,
elle tombait en erreur de syntaxe. Ce module tourne donc sous les deux moteurs
(tools/pg_tests.py). Le même jour, l'outil a été refondu : comptes à part,
mot de passe en saisie masquée, second facteur enrôlé avant toute écriture.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import platform_admin  # noqa: E402
import platform_auth  # noqa: E402
import security  # noqa: E402

MOT_DE_PASSE = "Fondateur!Klassio26"


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class Terminal:
    """Simule la personne devant son terminal : elle recopie la clé affichée
    dans son application, puis tape le code que l'application lui montre."""

    def __init__(self, nom="Fondateur", mots_de_passe=(MOT_DE_PASSE, MOT_DE_PASSE), code_faux=False):
        self.sorties = []
        self.nom = nom
        self.mots_de_passe = list(mots_de_passe)
        self.code_faux = code_faux

    def ecrire(self, texte=""):
        self.sorties.append(str(texte))

    def cle(self):
        for ligne in reversed(self.sorties):
            m = re.search(r"Clé\s*:\s*([A-Z2-7 ]+)$", ligne)
            if m:
                return m.group(1).replace(" ", "")
        return None

    def lire(self, invite=""):
        if "Nom" in invite:
            return self.nom
        if "Code" in invite:
            if self.code_faux:
                return "000000" if platform_auth.code_totp(self.cle(), platform_auth.pas_courant()) != "000000" else "111111"
            return platform_auth.code_totp(self.cle(), platform_auth.pas_courant())
        return ""

    def lire_secret(self, invite=""):
        return self.mots_de_passe.pop(0) if self.mots_de_passe else ""

    def lancer(self, *args):
        return platform_admin.main(["platform_admin.py", *args], lire=self.lire,
                                   lire_secret=self.lire_secret, ecrire=self.ecrire)


def compte(email):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM platform_accounts WHERE email=?", (email,)).fetchone()
    finally:
        conn.close()


class OutilPlateforme(unittest.TestCase):
    def setUp(self):
        security.reset_rate_limits_for_tests()

    def test_01_creer_puis_se_connecter_avec_mot_de_passe_et_code(self):
        t = Terminal()
        self.assertEqual(t.lancer("create", "fondateur@outil.test"), 0, "\n".join(t.sorties))
        row = compte("fondateur@outil.test")
        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], MOT_DE_PASSE)
        # Le code de l'enrôlement est consommé : il ne rouvre pas une session.
        c = flask_app_module.app.test_client(use_cookies=True)
        code_enrolement = platform_auth.code_totp(t.cle(), row["totp_last_step"])
        r = c.post("/api/admin/login", json={"email": "fondateur@outil.test",
                                                     "password": MOT_DE_PASSE, "code": code_enrolement})
        self.assertEqual(r.status_code, 401, "le code d'enrôlement a servi deux fois")

    def test_02_mot_de_passe_faible_ou_mal_retape_aucun_compte(self):
        for essais in (["Court1!", "Court1!"] * 3, [MOT_DE_PASSE, "Autre!Chose2026"] * 3,
                       ["sansmajuscule!2026"] * 6):
            t = Terminal(mots_de_passe=essais)
            self.assertEqual(t.lancer("create", "faible@outil.test"), 1)
            self.assertIsNone(compte("faible@outil.test"))

    def test_03_cle_mal_recopiee_aucun_compte(self):
        t = Terminal(code_faux=True)
        self.assertEqual(t.lancer("create", "clefausse@outil.test"), 1)
        self.assertIsNone(compte("clefausse@outil.test"))

    def test_04_doublon_refuse(self):
        self.assertEqual(Terminal().lancer("create", "double@outil.test"), 0)
        self.assertEqual(Terminal().lancer("create", "double@outil.test"), 1)

    def test_05_desactiver_ferme_les_sessions_et_bloque_la_connexion(self):
        t = Terminal()
        t.lancer("create", "desactive@outil.test")
        conn = db.get_connection()
        jeton = platform_auth.ouvrir_session(conn, compte("desactive@outil.test")["id"])
        conn.close()
        self.assertEqual(Terminal().lancer("disable", "desactive@outil.test"), 0)
        c = flask_app_module.app.test_client(use_cookies=True)
        c.set_cookie(platform_auth.ADMIN_COOKIE, jeton)
        self.assertEqual(c.get("/api/platform/overview").status_code, 403)

    def test_06_reset_2fa_remplace_la_cle(self):
        t = Terminal()
        t.lancer("create", "telephone@outil.test")
        ancienne = compte("telephone@outil.test")["totp_secret"]
        self.assertEqual(Terminal().lancer("reset-2fa", "telephone@outil.test"), 0)
        self.assertNotEqual(compte("telephone@outil.test")["totp_secret"], ancienne)

    def test_07_la_liste_ne_montre_ni_cle_ni_empreinte(self):
        t = Terminal()
        t.lancer("create", "liste@outil.test")
        row = compte("liste@outil.test")
        l = Terminal()
        self.assertEqual(l.lancer("list"), 0)
        sortie = "\n".join(l.sorties)
        self.assertIn("liste@outil.test", sortie)
        self.assertNotIn(row["totp_secret"], sortie)
        self.assertNotIn(row["password_hash"], sortie)


if __name__ == "__main__":
    unittest.main()
