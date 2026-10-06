"""KLASSIO — l'administration de la plateforme : compte à part, second facteur.

Jusqu'au 06/10/2026, l'accès plateforme était un drapeau sur le compte d'un
directeur d'école : une session de directeur volée ouvrait la facturation de
tout le réseau, un mot de passe suffisait, et l'administrateur devait posséder
une école. Ces tests éprouvent le nouveau dispositif (backend/platform_auth.py)
en attaquant chacune de ses protections — en connaissant toutes les routes :
la discrétion de la page de connexion n'est comptée pour rien.
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import platform_auth  # noqa: E402
import security  # noqa: E402
from tests.outils_plateforme import MOT_DE_PASSE, code_actuel, creer_compte_admin, session_admin  # noqa: E402

APP = flask_app_module.app
RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND = os.path.join(RACINE, "backend")
_n = [0]


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


def email_neuf():
    _n[0] += 1
    return f"adm{_n[0]}.{int(time.time() * 1000)}@plateforme.test"


def connexion(client, email, mot_de_passe=MOT_DE_PASSE, code="000000", entetes=None):
    return client.post("/api/admin/login", headers=entetes or {},
                       json={"email": email, "password": mot_de_passe, "code": code})


class Base(unittest.TestCase):
    def setUp(self):
        security.reset_rate_limits_for_tests()

    def ecole(self):
        _n[0] += 1
        r = APP.test_client().post("/api/auth/register-school", json={
            "email": f"dir{_n[0]}@ecole.test", "password": "Secret123!", "name": "Directrice",
            "school_name": f"École {_n[0]}"})
        self.assertEqual(r.status_code, 201)
        return r.get_json()["token"]


class LeSecondFacteur(Base):
    def test_01_vecteurs_officiels_rfc_6238(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # « 12345678901234567890 »
        for instant, attendu in ((59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924")):
            self.assertEqual(platform_auth.code_totp(secret, platform_auth.pas_courant(instant), 8), attendu)

    def test_02_un_code_ne_sert_qu_une_fois_et_vieillit_vite(self):
        secret = platform_auth.nouveau_secret_totp()
        pas = platform_auth.pas_courant()
        code = platform_auth.code_totp(secret, pas)
        self.assertEqual(platform_auth.verifier_totp(secret, code, 0), pas)
        self.assertIsNone(platform_auth.verifier_totp(secret, code, pas), "code rejoué accepté")
        vieux = platform_auth.code_totp(secret, pas - 3)
        self.assertIsNone(platform_auth.verifier_totp(secret, vieux, 0), "code d'il y a 90 s accepté")
        for invalide in ("", "12345", "1234567", "abcdef", None):
            self.assertIsNone(platform_auth.verifier_totp(secret, invalide, 0))


class LaConnexion(Base):
    def test_10_mot_de_passe_et_code_ouvrent_une_session_en_cookie_httponly(self):
        email = email_neuf()
        secret = creer_compte_admin(email)
        c = APP.test_client(use_cookies=True)
        r = connexion(c, email, code=code_actuel(secret))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("token", r.get_json())
        session = [h for h in r.headers.getlist("Set-Cookie") if h.startswith(platform_auth.ADMIN_COOKIE + "=")]
        self.assertEqual(len(session), 1)
        for attendu in ("httponly", "samesite=strict", "path=/"):
            self.assertIn(attendu, session[0].lower())
        self.assertEqual(c.get("/api/admin/session").status_code, 200)
        self.assertEqual(c.get("/api/platform/overview").status_code, 200)

    def test_11_un_seul_message_quel_que_soit_le_facteur_faux(self):
        email = email_neuf()
        secret = creer_compte_admin(email)
        c = APP.test_client(use_cookies=True)
        reponses = [
            connexion(c, email, mot_de_passe="Mauvais!2026xx", code=code_actuel(secret)),  # mot de passe faux
            connexion(c, email, code="000000" if code_actuel(secret) != "000000" else "111111"),  # code faux
            connexion(c, email, code=""),                                                 # code absent
            connexion(c, "inconnu@plateforme.test", code=code_actuel(secret)),            # adresse inconnue
        ]
        for r in reponses:
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.get_json()["error"], platform_auth.MESSAGE_REFUS)
        self.assertIsNone(c.get_cookie(platform_auth.ADMIN_COOKIE))

    def test_12_un_code_intercepte_ne_se_rejoue_pas(self):
        email = email_neuf()
        secret = creer_compte_admin(email)
        code = code_actuel(secret)
        self.assertEqual(connexion(APP.test_client(use_cookies=True), email, code=code).status_code, 200)
        self.assertEqual(connexion(APP.test_client(use_cookies=True), email, code=code).status_code, 401,
                         "le même code a ouvert une seconde session")

    def test_13_cinq_echecs_verrouillent_le_compte_meme_avec_les_bons_identifiants(self):
        email = email_neuf()
        secret = creer_compte_admin(email)
        c = APP.test_client(use_cookies=True)
        for _ in range(platform_auth.ECHECS_PAR_COMPTE):
            self.assertEqual(connexion(c, email, mot_de_passe="Devine!2026xx").status_code, 401)
        self.assertEqual(connexion(c, email, code=code_actuel(secret)).status_code, 429)

    def test_14_un_visiteur_qui_essaie_des_adresses_differentes_est_arrete(self):
        c = APP.test_client(use_cookies=True)
        for i in range(platform_auth.ECHECS_PAR_VISITEUR):
            connexion(c, f"essai{i}@plateforme.test")
        email = email_neuf()
        secret = creer_compte_admin(email)
        self.assertEqual(connexion(c, email, code=code_actuel(secret)).status_code, 429)

    def test_15_compte_desactive_refuse(self):
        email = email_neuf()
        secret = creer_compte_admin(email, statut="disabled")
        self.assertEqual(connexion(APP.test_client(use_cookies=True), email, code=code_actuel(secret)).status_code, 401)

    def test_16_une_page_tierce_ne_peut_pas_ouvrir_de_session(self):
        email = email_neuf()
        secret = creer_compte_admin(email)
        r = connexion(APP.test_client(use_cookies=True), email, code=code_actuel(secret),
                      entetes={"Sec-Fetch-Site": "cross-site", "Origin": "https://pirate.example"})
        self.assertEqual(r.status_code, 403)

    def test_17_chaque_connexion_est_journalisee(self):
        email = email_neuf()
        secret = creer_compte_admin(email)
        c = APP.test_client(use_cookies=True)
        connexion(c, email, mot_de_passe="Faux!Faux2026x")
        connexion(c, email, code=code_actuel(secret))
        conn = db.get_connection()
        try:
            actions = {r["action"] for r in conn.execute(
                "SELECT action FROM audit_logs WHERE resource_id=? OR resource_id IN "
                "(SELECT id FROM platform_accounts WHERE email=?)", (email, email))}
        finally:
            conn.close()
        self.assertIn("platform.login_failed", actions)
        self.assertIn("platform.login_success", actions)


class LeCloisonnement(Base):
    def test_20_une_session_d_ecole_meme_de_directeur_ne_vaut_rien_ici(self):
        jeton = self.ecole()
        bearer = {"Authorization": "Bearer " + jeton}
        self.assertEqual(APP.test_client().get("/api/platform/overview", headers=bearer).status_code, 403)
        c = APP.test_client(use_cookies=True)
        c.set_cookie(security.SESSION_COOKIE, jeton)
        self.assertEqual(c.get("/api/platform/overview").status_code, 403)

    def test_21_l_ancienne_table_platform_admins_n_ouvre_plus_rien(self):
        jeton = self.ecole()
        h = {"Authorization": "Bearer " + jeton}
        uid = APP.test_client().get("/api/me", headers=h).get_json()["user_id"]
        conn = db.get_connection()
        conn.execute("INSERT INTO platform_admins (user_id, created_at) VALUES (?,?) ON CONFLICT DO NOTHING",
                     (uid, str(time.time())))
        conn.commit(); conn.close()
        self.assertEqual(APP.test_client().get("/api/platform/overview", headers=h).status_code, 403)
        self.assertNotIn("is_platform_admin", APP.test_client().get("/api/me", headers=h).get_json())

    def test_22_une_session_d_administration_ne_vaut_rien_chez_les_ecoles(self):
        c, csrf, _ = session_admin(APP)
        for chemin in ("/api/me", "/api/students", "/api/classes"):
            self.assertEqual(c.get(chemin).status_code, 401, chemin)

    def test_23_seul_le_cookie_ouvre_la_plateforme_jamais_un_en_tete(self):
        c, csrf, _ = session_admin(APP)
        jeton = c.get_cookie(platform_auth.ADMIN_COOKIE).value
        r = APP.test_client().get("/api/platform/overview", headers={"Authorization": "Bearer " + jeton})
        self.assertEqual(r.status_code, 403)

    def test_24_ecriture_sans_le_jeton_csrf_d_administration_refusee(self):
        c, csrf, _ = session_admin(APP)
        chemin = "/api/platform/invoices/inconnue/confirm"
        self.assertEqual(c.post(chemin).status_code, 403)
        self.assertEqual(c.post(chemin, headers={security.CSRF_HEADER: "x" * 64}).status_code, 403)
        # Le jeton CSRF d'une session d'ÉCOLE ne vaut rien ici.
        jeton_ecole = self.ecole()
        self.assertEqual(c.post(chemin, headers={security.CSRF_HEADER: security.csrf_pour(jeton_ecole)}).status_code, 403)
        # Avec le bon jeton, la garde est franchie : c'est la route qui répond (facture inconnue).
        self.assertEqual(c.post(chemin, headers=csrf).status_code, 404)

    def test_25_toutes_les_routes_plateforme_passent_par_la_garde(self):
        """Une route /api/platform ajoutée demain sans la garde serait ouverte
        à toute session d'école : on les appelle toutes avec un directeur."""
        h = {"Authorization": "Bearer " + self.ecole()}
        ouvertes = []
        for regle in APP.url_map.iter_rules():
            if not regle.rule.startswith(("/api/platform", "/api/admin")) or regle.rule == "/api/admin/login":
                continue
            chemin = re.sub(r"<[^>]+>", "x", regle.rule)
            for methode in sorted(regle.methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}):
                r = APP.test_client().open(chemin, method=methode, headers=h, json={})
                if r.status_code != 403:
                    ouvertes.append(f"{methode} {regle.rule} -> {r.status_code}")
        self.assertEqual(ouvertes, [])


class LaVieDeLaSession(Base):
    def _vieillir(self, client, colonne, valeur):
        conn = db.get_connection()
        conn.execute(f"UPDATE platform_sessions SET {colonne}=? WHERE token=?",
                     (valeur, platform_auth._empreinte(client.get_cookie(platform_auth.ADMIN_COOKIE).value)))
        conn.commit(); conn.close()

    def test_30_trente_minutes_d_inactivite_ferment_la_session(self):
        c, _, _ = session_admin(APP)
        self._vieillir(c, "last_seen_at", str(time.time() - platform_auth.INACTIVITE_SECONDES - 5))
        self.assertEqual(c.get("/api/platform/overview").status_code, 403)
        self.assertIsNone(c.get_cookie(platform_auth.ADMIN_COOKIE), "cookie expiré laissé dans le navigateur")

    def test_31_huit_heures_au_plus_meme_en_activite(self):
        c, _, _ = session_admin(APP)
        self._vieillir(c, "expires_at", str(time.time() - 1))
        self.assertEqual(c.get("/api/platform/overview").status_code, 403)

    def test_32_deconnexion_et_jeton_rejoue(self):
        c, csrf, _ = session_admin(APP)
        ancien = c.get_cookie(platform_auth.ADMIN_COOKIE).value
        self.assertEqual(c.post("/api/admin/logout", headers=csrf).status_code, 200)
        self.assertIsNone(c.get_cookie(platform_auth.ADMIN_COOKIE))
        vole = APP.test_client(use_cookies=True)
        vole.set_cookie(platform_auth.ADMIN_COOKIE, ancien)
        self.assertEqual(vole.get("/api/platform/overview").status_code, 403)

    def test_33_cookie_fabrique_refuse(self):
        c = APP.test_client(use_cookies=True)
        c.set_cookie(platform_auth.ADMIN_COOKIE, "fabrique-de-toutes-pieces")
        self.assertEqual(c.get("/api/platform/overview").status_code, 403)


class PersonneNeDevientAdministrateurParLeWeb(Base):
    def test_40_aucun_code_du_serveur_web_ne_cree_ni_ne_modifie_un_compte(self):
        fautifs = []
        for nom in sorted(os.listdir(BACKEND)):
            if not nom.endswith(".py"):
                continue
            with open(os.path.join(BACKEND, nom), encoding="utf-8") as f:
                source = f.read()
            if re.search(r"INSERT\s+INTO\s+platform_accounts", source, re.I):
                fautifs.append(f"{nom} : INSERT")
            for m in re.finditer(r"UPDATE\s+platform_accounts\s+SET\s+([^\"']+)", source, re.I):
                if not m.group(1).strip().startswith("totp_last_step"):
                    fautifs.append(f"{nom} : UPDATE {m.group(1)[:40]}")
        self.assertEqual(fautifs, [], "seul backend/tools/platform_admin.py peut écrire les comptes")

    def test_41_aucune_route_d_inscription_d_administrateur(self):
        routes = sorted(r.rule for r in APP.url_map.iter_rules() if r.rule.startswith("/api/admin"))
        self.assertEqual(routes, ["/api/admin/login", "/api/admin/logout", "/api/admin/session"])

    def test_42_la_page_de_connexion_n_est_ni_indexee_ni_scriptee_en_ligne(self):
        with open(os.path.join(RACINE, "app", "admin.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('name="robots" content="noindex, nofollow"', page)
        self.assertIn("Content-Security-Policy", page)
        self.assertIsNone(re.search(r"<script>(?!\s*</script>)", page), "script en ligne")
        self.assertNotIn("inscription", page.lower())


if __name__ == "__main__":
    unittest.main()
