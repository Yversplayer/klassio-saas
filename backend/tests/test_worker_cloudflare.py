"""KLASSIO — garde-fous statiques sur le Worker Cloudflare (cloudflare/).

Le Worker ne s'exécute pas dans cette suite (pas de Node dans la pile). Ces
tests vérifient dans le SOURCE les deux règles dont l'oubli ne se verrait
qu'en production :
  1. HTTPS obligatoire, AVANT toute autre décision (constaté le 06/10/2026 :
     http:// répondait 200, page de connexion comprise) ;
  2. seuls les fichiers publics partent en ligne (liste blanche).
Le comportement réel est vérifié en ligne après chaque déploiement (curl).
"""
import os
import re
import unittest

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def lire(*chemin):
    with open(os.path.join(RACINE, *chemin), encoding="utf-8") as f:
        return f.read()


class WorkerCloudflare(unittest.TestCase):
    def test_https_exige_avant_tout_le_reste(self):
        source = lire("cloudflare", "worker.js")
        corps = source[source.index("async fetch(requete, env)"):]
        self.assertIn("exigerHttps(requete, url)", corps)
        self.assertLess(corps.index("exigerHttps(requete, url)"), corps.index("relayerApi("),
                        "l'API serait servie en HTTP avant la règle HTTPS")
        self.assertLess(corps.index("exigerHttps(requete, url)"), corps.index("servirFichier("))
        regle = source[source.index("function exigerHttps"):source.index("export default")]
        self.assertIn('url.protocol !== "http:"', regle)
        self.assertIn("301", regle)
        self.assertIn("403", regle, "une écriture en HTTP doit être refusée, pas redirigée")

    def test_seuls_les_fichiers_publics_partent_en_ligne(self):
        script = lire("cloudflare", "construire.sh")
        copies = " ".join(l for l in script.splitlines() if l.strip().startswith("cp "))
        for interdit in ("backend", ".md", "render.yaml", "wrangler", ".env", "tools"):
            self.assertNotIn(interdit, copies, f"« {interdit} » publié par construire.sh")
        self.assertTrue(re.search(r"cp -R app assets dist/", script))


if __name__ == "__main__":
    unittest.main()
