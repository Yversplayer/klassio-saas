"""KLASSIO — l'adresse du visiteur, derrière un relais.

En production, aucune requête n'arrive directement : le visiteur parle au
Worker Cloudflare, qui relaie /api vers Render, dont le routeur parle enfin à
Gunicorn. `request.remote_addr` y vaut l'adresse du DERNIER proxy — la même
pour tout le monde. Les limites de tentatives, comptées par adresse, devenaient
des plafonds pour la plateforme entière : 120 accès au portail par 5 minutes
pour TOUTES les familles, 5 inscriptions d'école par 5 minutes pour tout le
pays. Un matin de rentrée, des parents recevaient « Trop de tentatives » sans
en avoir fait une seule.

L'inverse est aussi dangereux : croire un en-tête que le navigateur écrit
lui-même (X-Forwarded-For), c'est laisser un robot changer d'adresse à chaque
essai et ne jamais être limité. Le formulaire de contact le faisait.

D'où la règle de `security.client_ip()` : l'adresse transmise n'est crue que
si la requête porte le secret partagé avec le relais. Sinon, `remote_addr`.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402

SECRET = "secret-de-test-du-relais"


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class AdresseDuVisiteur(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        self._avant = os.environ.get("KLASSIO_RELAIS_SECRET")
        os.environ["KLASSIO_RELAIS_SECRET"] = SECRET

    def tearDown(self):
        if self._avant is None:
            os.environ.pop("KLASSIO_RELAIS_SECRET", None)
        else:
            os.environ["KLASSIO_RELAIS_SECRET"] = self._avant

    def contact(self, entetes, i=0):
        return self.c.post("/api/public/contact", headers=entetes, json={
            "name": "Visiteur", "email": "v@example.test", "subject": "Question %d" % i,
            "message": "un message suffisamment long pour être accepté",
        })

    def relais(self, ip, secret=SECRET):
        return {"X-Klassio-Client-IP": ip, "X-Klassio-Relais": secret}

    def test_deux_visiteurs_derriere_le_relais_ont_chacun_leur_limite(self):
        for i in range(5):
            self.assertEqual(self.contact(self.relais("41.243.0.1"), i).status_code, 201)
        self.assertEqual(self.contact(self.relais("41.243.0.1"), 9).status_code, 429,
                         "le visiteur qui a épuisé sa limite n'est plus limité")
        # Un AUTRE parent, derrière le même relais : il n'a rien envoyé.
        autre = self.contact(self.relais("41.243.0.2"))
        self.assertEqual(autre.status_code, 201,
                         "un visiteur paie pour les tentatives d'un autre : tous partagent l'adresse du proxy")

    def test_adresse_transmise_sans_le_bon_secret_est_ignoree(self):
        # Quelqu'un qui appelle Render directement et invente l'en-tête.
        for i in range(5):
            self.contact(self.relais("10.0.0.%d" % i, secret="devine"), i)
        self.assertEqual(self.contact(self.relais("10.0.0.99", secret="devine")).status_code, 429,
                         "un en-tête forgé suffit à échapper à la limite")

    def test_aucun_relais_configure_aucune_adresse_crue(self):
        os.environ.pop("KLASSIO_RELAIS_SECRET")
        # Sans secret configuré, même un en-tête « vide = vide » ne doit pas passer.
        for i in range(5):
            self.contact(self.relais("10.1.0.%d" % i, secret=""), i)
        self.assertEqual(self.contact(self.relais("10.1.0.99", secret="")).status_code, 429)

    def test_x_forwarded_for_ecrit_par_le_client_n_est_pas_cru(self):
        for i in range(5):
            self.contact({"X-Forwarded-For": "203.0.113.%d" % i}, i)
        self.assertEqual(self.contact({"X-Forwarded-For": "203.0.113.200"}).status_code, 429,
                         "X-Forwarded-For forgé : le robot change d'adresse à chaque essai")

    def test_toutes_les_limites_passent_par_client_ip(self):
        """Une limite ajoutée demain avec `request.remote_addr` retomberait
        dans le défaut : plafond global derrière le proxy."""
        backend = os.path.join(os.path.dirname(__file__), "..")
        for nom in ("app.py", "api_school.py"):
            with open(os.path.join(backend, nom), encoding="utf-8") as f:
                source = f.read()
            fautifs = re.findall(r"(?:check_rate_limit|record_attempt|clear_attempts)\([^)]*remote_addr", source)
            self.assertEqual(fautifs, [], "%s compte encore des tentatives sur remote_addr" % nom)
            self.assertNotIn("X-Forwarded-For", source, "%s croit encore X-Forwarded-For" % nom)


if __name__ == "__main__":
    unittest.main()
