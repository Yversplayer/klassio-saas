"""KLASSIO — contrat entre l'écran Résultats et le backend.

Ce que ces tests peuvent vérifier, et ce qu'ils ne peuvent pas.

Le projet n'a pas d'exécuteur de tests JavaScript. Le parcours complet
— déposer un fichier, lire l'aperçu, confirmer — a donc été exercé À LA MAIN
dans le navigateur, et les preuves figurent au rapport. Ce fichier couvre ce
qui peut l'être de façon automatique et qui casserait silencieusement sinon :

- les routes appelées par la page existent réellement côté serveur ;
- la page ne fabrique aucun succès (pas de `setTimeout` dans le chemin de
  confirmation) et n'envoie aucun compteur au serveur ;
- l'écran est bien branché (script référencé, entrée de menu, CSP) ;
- le correctif du voile de chargement est en place.

Un test qui vérifierait « la page s'affiche » sans rien de tout cela donnerait
une fausse assurance ; on préfère cerner exactement ce qui est garanti.
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

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PAGE_JS = os.path.join(RACINE, "assets", "js", "page-resultats.js")
PAGE_HTML = os.path.join(RACINE, "app", "resultats.html")
APP_JS = os.path.join(RACINE, "assets", "js", "app.js")
LOADER_JS = os.path.join(RACINE, "assets", "js", "loader.js")


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def code_seul(js):
    """Le fichier sans ses commentaires de ligne.

    Nécessaire pour chercher un motif interdit : le commentaire d'en-tête dit
    justement « aucun setTimeout ici », et le test tombait dessus.
    """
    return "\n".join(re.sub(r"(^|\s)//.*$", "", l) for l in js.split("\n"))


def bloc_de_role(menus, role):
    """Extrait le tableau d'un rôle en comptant les crochets.

    Une expression régulière non gourmande s'arrêtait à la première ligne se
    terminant par « ], », c'est-à-dire au milieu du tableau.
    """
    debut = menus.index(role + ": [") + len(role) + ": ".__len__()
    profondeur, i = 0, debut
    while i < len(menus):
        if menus[i] == "[":
            profondeur += 1
        elif menus[i] == "]":
            profondeur -= 1
            if profondeur == 0:
                return menus[debut:i + 1]
        i += 1
    raise AssertionError(f"tableau du rôle {role} introuvable")


class ContratAvecLeBackend(unittest.TestCase):
    def test_01_toutes_les_routes_appelees_existent(self):
        """Une route renommée côté serveur doit casser ici, pas chez le client.

        On extrait les `api.fetch("/…")` de la page et on vérifie que chacune
        correspond à une règle réelle de l'application Flask.
        """
        js = lire(PAGE_JS)
        appels = set(re.findall(r'api\.fetch\(\s*"(/[^"]+)"', js))
        # Les appels construits par concaténation ("/results/imports/" + id)
        prefixes = set(re.findall(r'api\.fetch\(\s*"(/[^"]+/)"\s*\+', js))
        self.assertTrue(appels or prefixes, "aucun appel d'API détecté — le test ne teste rien")

        regles = [str(r) for r in flask_app_module.app.url_map.iter_rules()]
        def existe(chemin):
            cible = "/api" + chemin
            if cible in regles:
                return True
            # Route paramétrée : on compare segment à segment.
            morceaux = cible.strip("/").split("/")
            for r in regles:
                p = r.strip("/").split("/")
                if len(p) != len(morceaux):
                    continue
                if all(a == b or b.startswith("<") for a, b in zip(morceaux, p)):
                    return True
            return False

        manquantes = [c for c in appels if not existe(c)]
        self.assertEqual(manquantes, [],
                         f"la page appelle des routes inexistantes : {manquantes}")

        # Les appels à préfixe : on reconstitue avec un identifiant factice.
        for p in prefixes:
            for suffixe in ("", "/confirm", "/cancel"):
                chemin = p + "un-identifiant" + suffixe
                if existe(chemin):
                    break
            else:
                self.fail(f"aucune route ne correspond au préfixe « {p} »")

    def test_02_la_page_nenvoie_aucun_compteur_au_serveur(self):
        """Le serveur relit sa propre session : la page ne doit rien lui
        souffler. Un corps contenant `matched` ou `errors` serait au mieux
        inutile, au pire une invitation à lui faire confiance un jour."""
        js = lire(PAGE_JS)
        corps = re.findall(r"JSON\.stringify\(\{([^}]*)\}\)", js)
        for c in corps:
            for interdit in ("matched", "errors", "rows_", "version", "student_id", "tenant"):
                self.assertNotIn(interdit, c,
                                 f"la page envoie « {interdit} » au serveur : {c.strip()!r}")

    def test_03_aucun_succes_fabrique(self):
        """Pas de `setTimeout` : la page ne fait jamais semblant qu'une
        opération avance ni qu'elle a réussi."""
        js = code_seul(lire(PAGE_JS))
        self.assertNotIn("setTimeout", js,
                         "un setTimeout dans cette page ne peut servir qu'à simuler une progression")
        # Le succès n'est rendu que depuis la réponse serveur.
        self.assertIn("rendreSucces(res.body)", js)

    def test_04_limport_ne_declenche_aucune_publication(self):
        """L'écran ne doit appeler aucune route de proclamation : importer et
        publier restent deux décisions distinctes."""
        js = lire(PAGE_JS)
        for interdit in ("/publish", "publication-preview", "unpublish"):
            self.assertNotIn('api.fetch("' + interdit, js,
                             f"l'écran d'import appelle « {interdit} »")
        # …et il le dit à l'utilisateur.
        self.assertIn("ne sont pas encore publiés", js)


class BranchementDeLEcran(unittest.TestCase):
    def test_05_la_page_charge_ses_scripts(self):
        html = lire(PAGE_HTML)
        for script in ("ui.js", "loader.js", "app.js", "admin.js", "page-resultats.js"):
            self.assertIn(script, html, f"{script} n'est pas chargé par resultats.html")
        self.assertIn('data-page="resultats"', html)

    def test_06_la_csp_autorise_lapi_et_rien_de_plus(self):
        html = lire(PAGE_HTML)
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html)
        self.assertIsNotNone(csp, "aucune CSP sur cette page")
        contenu = csp.group(1)
        self.assertIn("script-src 'self'", contenu, "des scripts externes seraient autorisés")
        self.assertIn("connect-src 'self' http://localhost:5001", contenu)

    def test_07_lentree_de_menu_nexiste_que_pour_la_direction(self):
        js = lire(APP_JS)
        menus = re.search(r"var ROLE_MENUS = \{(.+?)\n  \};", js, re.S).group(1)
        for role in ("directeur", "discipline", "professeur", "parent"):
            present = "resultats.html" in bloc_de_role(menus, role)
            if role == "directeur":
                self.assertTrue(present, "la Direction n'a pas d'entrée Résultats")
            else:
                self.assertFalse(present, f"le rôle {role} se voit proposer l'import des résultats")

    def test_08_lecran_refuse_les_roles_non_autorises(self):
        js = lire(PAGE_JS)
        self.assertIn('c.role !== "directeur"', js,
                      "la page ne filtre pas le rôle (le serveur refuse, mais l'écran ne doit "
                      "pas proposer une action vouée à l'échec)")


class VoileDeChargement(unittest.TestCase):
    def test_09_le_voile_peut_etre_retire_avant_sa_frame(self):
        """Le défaut corrigé : `show()` posait la classe dans un
        requestAnimationFrame, et `hide()` appelé avant cette frame n'avait
        aucun effet — le voile plein écran restait affiché et avalait tous les
        clics. Reproduit sur l'import des résultats, où la réponse arrive en
        moins d'une frame.
        """
        js = lire(LOADER_JS)
        self.assertIn("cancelAnimationFrame", js,
                      "hide() ne peut pas annuler l'affichage différé de show()")
        hide = re.search(r"function hide\(\)\s*\{(.+?)\n  \}", js, re.S)
        self.assertIsNotNone(hide, "hide() introuvable")
        self.assertIn("cancelAnimationFrame", hide.group(1),
                      "hide() n'annule pas la frame en attente")

    def test_10_la_page_utilise_le_loader_commun(self):
        """§16 : réutiliser l'animation existante, ne pas en créer une seconde."""
        js = lire(PAGE_JS)
        self.assertIn("window.KlassioLoader", js)
        self.assertNotIn("@keyframes", js, "une animation propre à cette page a été créée")


if __name__ == "__main__":
    unittest.main()
