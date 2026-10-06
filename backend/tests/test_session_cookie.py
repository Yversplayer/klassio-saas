"""KLASSIO — la session du navigateur : cookie HttpOnly, CSRF, origine.

Jusqu'au 06/10/2026, le frontend gardait le token de session dans
localStorage : une XSS qui passait la CSP pouvait le LIRE et usurper la
session pendant 12 h. Le token voyage désormais dans un cookie que le script
de la page ne voit pas (security.py, « Où vit le token de session »).

Un cookie part tout seul : ces tests vérifient donc aussi, de façon
adversariale, qu'aucune écriture authentifiée par cookie ne passe sans le
jeton CSRF, et qu'aucune écriture venue d'un autre site ne passe du tout.

Ce module RÉACTIVE les cookies du client de test (désactivés par défaut dans
tests/__init__.py pour les suites qui éprouvent l'API en Bearer).
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

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Ce qu'envoie un navigateur depuis une page Klassio.
NAVIGATEUR = {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"}
_compteur = [0]


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


def entetes_cookie(resp, nom):
    return [h for h in resp.headers.getlist("Set-Cookie") if h.startswith(nom + "=")]


class Base(unittest.TestCase):
    def setUp(self):
        security.reset_rate_limits_for_tests()
        self.c = flask_app_module.app.test_client(use_cookies=True)

    def inscrire(self, client=None, entetes=NAVIGATEUR):
        _compteur[0] += 1
        n = _compteur[0]
        r = (client or self.c).post("/api/auth/register-school", headers=entetes, json={
            "email": f"dir{n}@cookie.test", "password": "Secret123!",
            "name": "Directrice", "school_name": f"École Cookie {n}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r, f"dir{n}@cookie.test"

    def jeton(self, client=None):
        cookie = (client or self.c).get_cookie(security.SESSION_COOKIE)
        return cookie.value if cookie else None

    def csrf(self, client=None):
        return {security.CSRF_HEADER: (client or self.c).get_cookie(security.CSRF_COOKIE).value, **NAVIGATEUR}


class LeCookieEstHorsDePorteeDuScript(Base):
    def test_01_le_navigateur_ne_recoit_le_token_que_dans_un_cookie_httponly_strict(self):
        r, _ = self.inscrire()
        self.assertNotIn("token", r.get_json(), "le token est lisible dans le corps de la réponse")
        session = entetes_cookie(r, security.SESSION_COOKIE)
        self.assertEqual(len(session), 1)
        attributs = session[0].lower()
        for attendu in ("httponly", "samesite=strict", "path=/", f"max-age={security.SESSION_TTL_SECONDS}"):
            self.assertIn(attendu, attributs)

    def test_02_le_jeton_csrf_est_lisible_par_la_page_mais_n_est_pas_la_session(self):
        r, _ = self.inscrire()
        csrf = entetes_cookie(r, security.CSRF_COOKIE)[0].lower()
        self.assertNotIn("httponly", csrf)
        self.assertIn("samesite=strict", csrf)
        valeur = self.c.get_cookie(security.CSRF_COOKIE).value
        self.assertNotEqual(valeur, self.jeton())
        # Ni le token, ni son empreinte stockée en base.
        self.assertNotEqual(valeur, security.hash_session_token(self.jeton()))

    def test_03_secure_en_https_jamais_en_clair(self):
        r, _ = self.inscrire(entetes={**NAVIGATEUR, "X-Forwarded-Proto": "https"})
        self.assertIn("secure", entetes_cookie(r, security.SESSION_COOKIE)[0].lower())
        c2 = flask_app_module.app.test_client(use_cookies=True)
        r2, _ = self.inscrire(client=c2)
        self.assertNotIn("; secure", entetes_cookie(r2, security.SESSION_COOKIE)[0].lower())

    def test_04_un_client_qui_n_est_pas_un_navigateur_recoit_encore_le_token(self):
        r, _ = self.inscrire(entetes={})
        self.assertTrue(r.get_json().get("token"))

    def test_05_le_frontend_ne_stocke_ni_n_envoie_plus_le_token(self):
        """Le serveur peut poser un cookie HttpOnly ; si le frontend recopiait
        encore le token dans localStorage, la protection ne vaudrait rien."""
        dossier = os.path.join(RACINE, "assets", "js")
        for nom in sorted(os.listdir(dossier)):
            if not nom.endswith(".js"):
                continue
            with open(os.path.join(dossier, nom), encoding="utf-8") as f:
                source = f.read()
            self.assertIsNone(re.search(r"setItem\(\s*[\"']klassio_token", source), f"{nom} stocke encore le token")
            self.assertFalse("Bearer " in source, f"{nom} envoie encore un en-tête Bearer")
        with open(os.path.join(dossier, "app.js"), encoding="utf-8") as f:
            self.assertIn("X-CSRF-Token", f.read(), "app.js n'envoie pas le jeton CSRF")


class LaSessionParCookie(Base):
    def test_10_le_cookie_seul_authentifie_une_lecture(self):
        self.inscrire()
        self.assertEqual(self.c.get("/api/me", headers=NAVIGATEUR).status_code, 200)

    def test_11_ecriture_sans_jeton_csrf_refusee_pour_chaque_methode(self):
        self.inscrire()
        for methode, chemin in (("post", "/api/periods"),
                                ("put", "/api/me/preferences"),
                                ("patch", "/api/promotion-plans/x/assignments/y"),
                                ("delete", "/api/calendar/events/x")):
            r = getattr(self.c, methode)(chemin, json={"label": "P"}, headers=NAVIGATEUR)
            self.assertEqual(r.status_code, 403, f"{methode.upper()} {chemin} sans CSRF : {r.status_code}")

    def test_12_mauvais_jeton_csrf_refuse(self):
        self.inscrire()
        for faux in ("x", "0" * 64, security.csrf_pour("un-autre-token")):
            r = self.c.post("/api/periods", json={"label": "P"},
                            headers={security.CSRF_HEADER: faux, **NAVIGATEUR})
            self.assertEqual(r.status_code, 403, f"jeton CSRF {faux!r} accepté")

    def test_13_bon_jeton_csrf_accepte(self):
        self.inscrire()
        r = self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=self.csrf())
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(self.c.put("/api/me/preferences", json={}, headers=self.csrf()).status_code, 200)
        # PATCH et DELETE franchissent la garde CSRF : ce qui répond ensuite
        # est la route elle-même (ressource inconnue), plus le 403.
        self.assertNotEqual(self.c.patch("/api/promotion-plans/x/assignments/y", json={},
                                         headers=self.csrf()).status_code, 403)
        self.assertNotEqual(self.c.delete("/api/calendar/events/x", headers=self.csrf()).status_code, 403)

    def test_14_le_jeton_csrf_d_une_autre_session_ne_vaut_rien(self):
        autre = flask_app_module.app.test_client(use_cookies=True)
        self.inscrire(client=autre)
        self.inscrire()
        r = self.c.post("/api/periods", json={"label": "P"},
                        headers={security.CSRF_HEADER: autre.get_cookie(security.CSRF_COOKIE).value, **NAVIGATEUR})
        self.assertEqual(r.status_code, 403)

    def test_15_bearer_explicite_n_est_pas_soumis_au_csrf_et_fait_foi(self):
        r, _ = self.inscrire(entetes={})
        jeton = r.get_json()["token"]
        nu = flask_app_module.app.test_client()
        r = nu.post("/api/periods", json={"label": "P", "sort": 1}, headers={"Authorization": "Bearer " + jeton})
        self.assertEqual(r.status_code, 201)
        # Un en-tête Authorization présent mais vide ne retombe PAS sur le cookie.
        self.inscrire()
        self.assertEqual(self.c.get("/api/me", headers={"Authorization": "Bearer "}).status_code, 401)


class LesEcrituresIntersites(Base):
    def test_20_une_page_tierce_ne_peut_rien_ecrire_meme_avec_le_jeton(self):
        self.inscrire()
        pirate = {security.CSRF_HEADER: self.c.get_cookie(security.CSRF_COOKIE).value,
                  "Sec-Fetch-Site": "cross-site", "Origin": "https://pirate.example"}
        r = self.c.post("/api/periods", json={"label": "P"}, headers=pirate)
        self.assertEqual(r.status_code, 403)

    def test_21_ni_connecter_le_visiteur_au_compte_de_l_attaquant(self):
        _, email = self.inscrire()
        r = flask_app_module.app.test_client(use_cookies=True).post(
            "/api/auth/login", json={"identifier": email, "password": "Secret123!"},
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(entetes_cookie(r, security.SESSION_COOKIE), [])

    def test_22_navigateur_ancien_sans_sec_fetch_site_origin_etrangere_refusee(self):
        self.inscrire()
        r = self.c.post("/api/periods", json={"label": "P"},
                        headers={security.CSRF_HEADER: self.c.get_cookie(security.CSRF_COOKIE).value,
                                 "Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/periods", json={"label": "P", "sort": 2},
                        headers={security.CSRF_HEADER: self.c.get_cookie(security.CSRF_COOKIE).value,
                                 "Origin": "http://localhost"})
        self.assertEqual(r.status_code, 201, "la propre origine du site est refusée")

    def test_23_meme_site_mais_autre_origine_refuse(self):
        self.inscrire()
        r = self.c.post("/api/periods", json={"label": "P"},
                        headers={**self.csrf(), "Sec-Fetch-Site": "same-site",
                                 "Origin": "https://autre.workers.dev"})
        self.assertEqual(r.status_code, 403)


class LaVieDeLaSession(Base):
    def test_30_deconnexion_efface_le_cookie_et_tue_le_token(self):
        self.inscrire()
        ancien = self.jeton()
        r = self.c.post("/api/auth/logout", headers=self.csrf())
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.c.get_cookie(security.SESSION_COOKIE), "le cookie reste dans le navigateur")
        # Un attaquant qui aurait copié le cookie avant la déconnexion :
        self.c.set_cookie(security.SESSION_COOKIE, ancien)
        self.assertEqual(self.c.get("/api/me", headers=NAVIGATEUR).status_code, 401)

    def test_31_changer_de_mot_de_passe_revoque_l_ancien_cookie(self):
        self.inscrire()
        autre_appareil = self.jeton()
        r = self.c.post("/api/me/password", json={"current_password": "Secret123!",
                                                  "new_password": "Nouveau456!"}, headers=self.csrf())
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertNotIn("token", r.get_json())
        nouveau = self.jeton()
        self.assertNotEqual(nouveau, autre_appareil)
        self.assertEqual(self.c.get("/api/me", headers=NAVIGATEUR).status_code, 200)
        vole = flask_app_module.app.test_client(use_cookies=True)
        vole.set_cookie(security.SESSION_COOKIE, autre_appareil)
        self.assertEqual(vole.get("/api/me", headers=NAVIGATEUR).status_code, 401)

    def test_32_cookie_falsifie_ou_expire_refuse_et_efface(self):
        self.c.set_cookie(security.SESSION_COOKIE, "fabrique-de-toutes-pieces")
        r = self.c.get("/api/me", headers=NAVIGATEUR)
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(self.c.get_cookie(security.SESSION_COOKIE))
        self.inscrire()
        conn = db.get_connection()
        try:
            conn.execute("UPDATE sessions SET expires_at='0' WHERE token=?",
                         (security.hash_session_token(self.jeton()),))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.c.get("/api/me", headers=NAVIGATEUR).status_code, 401)

    def test_33_deux_sessions_simultanees_independantes(self):
        _, email = self.inscrire()
        telephone = flask_app_module.app.test_client(use_cookies=True)
        r = telephone.post("/api/auth/login", json={"identifier": email, "password": "Secret123!"},
                           headers=NAVIGATEUR)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(self.jeton(telephone), self.jeton())
        self.assertEqual(self.c.post("/api/auth/logout", headers=self.csrf()).status_code, 200)
        self.assertEqual(telephone.get("/api/me", headers=NAVIGATEUR).status_code, 200,
                         "se déconnecter d'un appareil a fermé l'autre")

    def test_34_pas_de_fixation_de_session(self):
        """Un cookie planté AVANT la connexion n'est jamais adopté : la
        connexion émet un token neuf, tiré au hasard par le serveur."""
        _, email = self.inscrire()
        self.c.post("/api/auth/logout", headers=self.csrf())
        self.c.set_cookie(security.SESSION_COOKIE, "jeton-choisi-par-l-attaquant")
        r = self.c.post("/api/auth/login", json={"identifier": email, "password": "Secret123!"},
                        headers=NAVIGATEUR)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(self.jeton(), "jeton-choisi-par-l-attaquant")
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{40,}", self.jeton()))


if __name__ == "__main__":
    unittest.main()
