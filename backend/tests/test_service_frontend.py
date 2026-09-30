"""KLASSIO — Service des fichiers du frontend par le serveur Flask.

Le 29/09, pour qu'un testeur puisse atteindre Klassio depuis une autre machine,
le backend s'est mis à servir lui-même les pages et les ressources : une seule
origine, donc plus de CORS à accorder ni de `connect-src` à élargir dans la CSP
de 32 pages. Le montage à deux serveurs (4173 pour les fichiers, 5001 pour
l'API) ne marchait qu'en local.

Servir des fichiers depuis la racine du dépôt ouvre deux risques, et ce module
existe pour les tenir fermés :

  1. **La racine du dépôt n'est pas un dossier public.** Elle contient
     `AGENTS.md`, `DEPLOIEMENT.md`, `render.yaml`, `.mcp.json`,
     `requirements.txt`, `demarrer.sh`. La première version de la route servait
     « tout fichier existant à la racine » : les six répondaient 200 dès que le
     serveur écoutait sur le réseau. Seules les pages `.html` et les trois
     fichiers publics attendus à la racine d'un site sortent désormais.
  2. **`backend/` ne doit jamais sortir.** La base de développement, le code
     serveur et un éventuel `.env` sont dans l'arborescence servie.

Et une garantie de forme : cette route attrape `/<path:...>`, donc elle passe
après les routes `/api/...`. Si elle les masquait, toute l'API répondrait du
HTML — d'où le test 05.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class ServiceFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app_module.app.config["TESTING"] = True
        cls.client = flask_app_module.app.test_client()

    # ------------------------------------------------------------------
    # Ce qui doit sortir
    # ------------------------------------------------------------------
    def test_01_les_pages_et_ressources_du_site_sont_servies(self):
        for chemin in ("/", "/index.html", "/demo.html", "/cgu.html",
                       "/app/connexion.html", "/app/inscription.html",
                       "/assets/js/ui.js", "/assets/css/style.css",
                       "/robots.txt", "/sitemap.xml", "/favicon.ico"):
            with self.subTest(chemin=chemin):
                self.assertEqual(self.client.get(chemin).status_code, 200,
                                 f"{chemin} devrait être servi")

    # ------------------------------------------------------------------
    # Ce qui ne doit PAS sortir
    # ------------------------------------------------------------------
    def test_02_les_fichiers_internes_de_la_racine_ne_sortent_pas(self):
        """Le défaut réel du 29/09 : `curl http://<ip>:5001/AGENTS.md` → 200.

        Ces fichiers existent bel et bien sur le disque ; c'est précisément ce
        qui rend le test utile — il ne constate pas une absence, il constate un
        refus de servir.
        """
        racine = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        for nom in ("AGENTS.md", "DEPLOIEMENT.md", "REPRISE.md", "README.md",
                    "render.yaml", "vercel.json", "Procfile", "runtime.txt",
                    "requirements.txt", "requirements-dev.txt",
                    "demarrer.sh", ".mcp.json", ".gitignore"):
            with self.subTest(fichier=nom):
                if not os.path.isfile(os.path.join(racine, nom)):
                    self.skipTest(f"{nom} absent du dépôt")
                self.assertEqual(self.client.get("/" + nom).status_code, 404,
                                 f"/{nom} ne doit pas être téléchargeable")

    def test_03_le_dossier_backend_ne_sort_pas(self):
        for chemin in ("/backend/app.py", "/backend/klassio.db", "/backend/.env",
                       "/backend/config.py", "/backend/tests/test_api.py",
                       "/docs/README.md", "/tools/k6/env-pg.json",
                       "/.git/config", "/backend_venv/pyvenv.cfg"):
            with self.subTest(chemin=chemin):
                self.assertEqual(self.client.get(chemin).status_code, 404,
                                 f"{chemin} ne doit pas être servi")

    def test_04_la_traversee_de_chemin_ne_remonte_pas(self):
        """`send_from_directory` refuse déjà de sortir du dossier ; on le
        vérifie plutôt que de le supposer, y compris encodé."""
        for chemin in ("/app/../backend/app.py",
                       "/assets/../backend/klassio.db",
                       "/app/%2e%2e/backend/app.py",
                       "/app/..%2fbackend%2fapp.py",
                       "/../AGENTS.md"):
            with self.subTest(chemin=chemin):
                reponse = self.client.get(chemin)
                self.assertNotEqual(reponse.status_code, 200,
                                    f"{chemin} a été servi")

    # ------------------------------------------------------------------
    # Ce que la route ne doit pas casser
    # ------------------------------------------------------------------
    def test_05_la_route_attrape_tout_ne_masque_pas_l_api(self):
        """Une route `/<path:...>` déclarée trop largement transformerait
        chaque appel d'API en page HTML. `/api/health` doit rester du JSON, et
        une route d'API inexistante doit répondre 404 en JSON — pas la page
        d'accueil, qu'un client `fetch` interpréterait comme un succès."""
        sante = self.client.get("/api/health")
        self.assertEqual(sante.status_code, 200)
        self.assertIn("application/json", sante.headers.get("Content-Type", ""))

        inconnue = self.client.get("/api/route-qui-nexiste-pas")
        self.assertEqual(inconnue.status_code, 404)
        self.assertIn("application/json", inconnue.headers.get("Content-Type", ""))

    def test_06_une_page_inexistante_repond_404(self):
        for chemin in ("/page-inexistante.html", "/app/inexistante.html",
                       "/assets/js/inexistant.js"):
            with self.subTest(chemin=chemin):
                self.assertEqual(self.client.get(chemin).status_code, 404)


if __name__ == "__main__":
    unittest.main()
