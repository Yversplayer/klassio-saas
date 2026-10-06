"""KLASSIO — l'outil qui crée le premier administrateur de la plateforme.

L'accès « plateforme » (confirmer un paiement, ouvrir ou refermer un espace)
ne s'accorde jamais depuis l'application : seulement par
`backend/tools/platform_admin.py grant`, sur le serveur. Sur une base neuve,
c'est donc le SEUL moyen d'avoir quelqu'un pour confirmer le premier paiement
— sans lui, aucune école ne s'ouvre au-delà de ses 72 h provisoires.

Trouvé au premier déploiement (06/10/2026) : l'outil écrivait
`INSERT OR IGNORE`, du SQLite pur. Sous PostgreSQL, le moteur de production,
`grant` tombait en erreur de syntaxe. La suite ne l'avait jamais vu : aucun
test n'appelait l'outil. Celui-ci tourne sous les deux moteurs
(tools/pg_tests.py).
"""
import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import platform_admin  # noqa: E402
import security  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class OutilPlateforme(unittest.TestCase):
    def setUp(self):
        security.reset_rate_limits_for_tests()
        c = flask_app_module.app.test_client()
        r = c.post("/api/auth/register-school", json={
            "email": "fondateur@outil.test", "password": "Secret123!",
            "name": "Fondateur", "school_name": "École de l'outil"})
        self.assertIn(r.status_code, (201, 409), r.get_data(as_text=True))

    def outil(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return platform_admin.main(["platform_admin.py", *args])

    def admins(self):
        conn = db.get_connection()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM platform_admins p JOIN users u ON u.id = p.user_id "
                "WHERE lower(u.email)=?", ("fondateur@outil.test",)).fetchone()["n"]
        finally:
            conn.close()

    def test_accorder_puis_reaccorder_puis_retirer(self):
        self.assertEqual(self.outil("grant", "fondateur@outil.test"), 0)
        self.assertEqual(self.admins(), 1)
        # Rejouer la commande ne doit ni échouer ni dupliquer.
        self.assertEqual(self.outil("grant", "fondateur@outil.test"), 0)
        self.assertEqual(self.admins(), 1)
        self.assertEqual(self.outil("revoke", "fondateur@outil.test"), 0)
        self.assertEqual(self.admins(), 0)

    def test_identifiant_inconnu(self):
        self.assertEqual(self.outil("grant", "personne@outil.test"), 1)


if __name__ == "__main__":
    unittest.main()
