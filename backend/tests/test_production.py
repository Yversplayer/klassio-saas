"""KLASSIO — ce qui ne casse qu'en production.

Ces tests couvrent les défauts trouvés à l'audit de mise en production : ils
portent sur des chemins de code qui, par construction, ne s'exercent jamais
pendant le développement local sur SQLite mono-processus.

Aucun serveur PostgreSQL n'est nécessaire : la réserve de connexions est
vérifiée avec une fausse connexion, ce qui permet de simuler exactement les
états qu'on ne sait pas provoquer à la demande (socket coupée par le pooler,
connexion cassée en plein vol).
"""
import gzip
import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import security  # noqa: E402
import app as flask_app_module  # noqa: E402


# Route enregistrée à l'import : Flask refuse d'ajouter une route après la
# première requête servie, et l'objet `app` est partagé par tous les modules
# de test. Elle n'existe que dans le processus de test.
@flask_app_module.app.route("/api/_test_charge_utile")
def _route_charge_utile():
    """Réponse JSON volumineuse et réaliste, pour exercer la compression sans
    dépendre d'un établissement peuplé. N'existe que dans le processus de test."""
    from flask import jsonify
    return jsonify({"eleves": [
        {"id": f"id{i:06d}", "code": f"STU-{i:04d}-AAAA", "first_name": "Prenom",
         "last_name": "NomDeFamille", "class_name": "6e A", "status": "active",
         "balance": 300.0, "total_due": 300.0, "total_paid": 0.0}
        for i in range(300)]})


@flask_app_module.app.route("/api/_test_erreur_inattendue")
def _route_qui_explose():
    raise RuntimeError("SELECT password_hash FROM users -- détail interne")


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class _FausseConnexionPsycopg:
    """Le strict minimum de l'interface psycopg utilisée par PgConnection."""

    def __init__(self):
        self.closed = False
        self.broken = False
        self.rollbacks = 0
        self.selects = 0
        self.echoue_au_select = False

    def rollback(self):
        if self.broken:
            raise RuntimeError("connexion cassée")
        self.rollbacks += 1

    def execute(self, sql):
        self.selects += 1
        if self.echoue_au_select:
            raise RuntimeError("serveur a fermé la connexion")

    def close(self):
        self.closed = True


def _connexion_de_test():
    """Une PgConnection sans jamais toucher le réseau."""
    conn = db.PgConnection.__new__(db.PgConnection)
    conn._conn = _FausseConnexionPsycopg()
    conn._repos_depuis = None
    return conn


class ReserveDeConnexionsTests(unittest.TestCase):
    """Une requête authentifiée ouvre deux connexions (require_auth, puis la
    route). À 1,9 s d'ouverture depuis Kinshasa, c'est le premier poste de
    latence du produit — d'où la réserve."""

    def setUp(self):
        db.close_pool()

    def tearDown(self):
        db.close_pool()

    def test_01_close_rend_la_connexion_au_lieu_de_la_fermer(self):
        conn = _connexion_de_test()
        conn.close()
        self.assertFalse(conn._conn.closed, "la socket ne doit pas être fermée")
        self.assertEqual(conn._conn.rollbacks, 1, "toute transaction en cours doit être abandonnée")
        self.assertIn(conn, db._PG_POOL)

    def test_02_la_connexion_rendue_est_bien_reservie(self):
        conn = _connexion_de_test()
        conn.close()
        self.assertIs(db._pool_acquire(), conn)
        self.assertEqual(db._PG_POOL, [], "une connexion servie sort de la réserve")

    def test_03_reserve_pleine_la_connexion_est_fermee(self):
        rendues = []
        for _ in range(db.PG_POOL_SIZE):
            c = _connexion_de_test()
            c.close()
            rendues.append(c)
        surnumeraire = _connexion_de_test()
        surnumeraire.close()
        self.assertTrue(surnumeraire._conn.closed, "au-delà de la taille de réserve, on ferme")
        self.assertEqual(len(db._PG_POOL), db.PG_POOL_SIZE)

    def test_04_connexion_cassee_jamais_remise_en_reserve(self):
        conn = _connexion_de_test()
        conn._conn.broken = True
        conn.close()
        self.assertTrue(conn._conn.closed)
        self.assertEqual(db._PG_POOL, [])

    def test_05_connexion_coupee_pendant_le_repos_est_jetee(self):
        """Le pooler Supabase coupe les connexions inactives ; la réserve ne
        doit jamais servir une socket morte à une requête utilisateur."""
        conn = _connexion_de_test()
        conn.close()
        conn._repos_depuis = 0            # repos ancien → vérification déclenchée
        conn._conn.echoue_au_select = True
        self.assertIsNone(db._pool_acquire())
        self.assertTrue(conn._conn.closed)

    def test_06_repos_bref_pas_daller_retour_inutile(self):
        conn = _connexion_de_test()
        conn.close()
        self.assertIs(db._pool_acquire(), conn)
        self.assertEqual(conn._conn.selects, 0, "un SELECT 1 par requête annulerait le gain")

    def test_07_close_pool_ferme_tout(self):
        conns = []
        for _ in range(3):
            c = _connexion_de_test()
            c.close()
            conns.append(c)
        db.close_pool()
        self.assertEqual(db._PG_POOL, [])
        self.assertTrue(all(c._conn.closed for c in conns))


class ErreursPortablesTests(unittest.TestCase):
    def test_08_integrity_errors_couvre_les_deux_moteurs(self):
        classes = db.integrity_errors()
        self.assertIn(sqlite3.IntegrityError, classes)
        try:
            import psycopg
        except ImportError:
            self.skipTest("psycopg absent de cet environnement")
        self.assertIn(psycopg.errors.IntegrityError, classes)

    def test_09_chaque_moteur_a_son_gestionnaire_409(self):
        """Le décorateur ne visait que SQLite : en Postgres, une contrainte
        d'unicité violée repartait en 500 au lieu de 409."""
        enregistres = flask_app_module.app.error_handler_spec[None][None]
        for classe in db.integrity_errors():
            self.assertIn(classe, enregistres, f"{classe.__name__} sans gestionnaire")


class LimitationDeDebitPartageeTests(unittest.TestCase):
    """Les compteurs anti-force-brute vivaient en mémoire de processus : avec
    plusieurs workers Gunicorn, chacun tenait les siens et un attaquant
    obtenait autant de fois la limite qu'il y avait de workers. Ils sont
    maintenant en base — ces tests vérifient que la limite tient, qu'elle est
    bien partagée, et qu'elle finit par se relâcher."""

    def setUp(self):
        security.reset_rate_limits_for_tests()

    def tearDown(self):
        security.reset_rate_limits_for_tests()

    def test_16_la_limite_se_declenche_au_bon_rang(self):
        for i in range(3):
            autorise, _ = security.check_rate_limit("essai", "1.2.3.4", 3, 300)
            self.assertTrue(autorise, f"la tentative {i + 1} sur 3 doit passer")
            security.record_attempt("essai", "1.2.3.4")
        autorise, retry = security.check_rate_limit("essai", "1.2.3.4", 3, 300)
        self.assertFalse(autorise)
        self.assertGreater(retry, 0)

    def test_17_la_limite_ne_deborde_pas_sur_un_autre_sujet(self):
        for _ in range(3):
            security.record_attempt("essai", "1.2.3.4")
        autorise, _ = security.check_rate_limit("essai", "9.9.9.9", 3, 300)
        self.assertTrue(autorise, "une autre IP ne doit pas payer pour la première")
        autorise, _ = security.check_rate_limit("autre_seau", "1.2.3.4", 3, 300)
        self.assertTrue(autorise, "un autre seau ne doit pas payer pour le premier")

    def test_18_les_compteurs_sont_partages_hors_du_processus(self):
        """Le vrai point : un second worker doit voir les tentatives du premier.
        On lit la base directement, comme le ferait un autre processus."""
        for _ in range(4):
            security.record_attempt("login", "cible@example.test")
        conn = db.get_connection()
        try:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM rate_limit_attempts WHERE bucket=? AND subject=?",
                ("login", "cible@example.test"),
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(n, 4, "les tentatives doivent être visibles hors du processus qui les a comptées")

    def test_19_une_tentative_sortie_de_la_fenetre_ne_compte_plus(self):
        for _ in range(5):
            security.record_attempt("essai", "1.2.3.4")
        self.assertFalse(security.check_rate_limit("essai", "1.2.3.4", 5, 300)[0])
        # Fenêtre d'une seconde : les mêmes tentatives sont désormais trop vieilles.
        self.assertTrue(security.check_rate_limit("essai", "1.2.3.4", 5, 0)[0])

    def test_20_une_connexion_reussie_efface_lardoise(self):
        for _ in range(5):
            security.record_login_failure("kabongo@example.test")
        self.assertFalse(security.check_login_rate_limit("kabongo@example.test")[0])
        security.clear_login_attempts("kabongo@example.test")
        self.assertTrue(security.check_login_rate_limit("kabongo@example.test")[0])

    def test_21_le_login_est_bloque_apres_cinq_echecs(self):
        """Bout en bout, par la route réelle."""
        client = flask_app_module.app.test_client()
        for _ in range(security.LOGIN_MAX_ATTEMPTS):
            r = client.post("/api/auth/login", json={"email": "inconnu@example.test", "password": "faux"})
            self.assertEqual(r.status_code, 401)
        r = client.post("/api/auth/login", json={"email": "inconnu@example.test", "password": "faux"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("Trop de tentatives", r.get_json()["error"])


class CompressionTests(unittest.TestCase):
    """Ni Flask ni le routeur Heroku ne compressent. Sur un établissement de
    2 340 élèves, la liste pèse 892 Ko de JSON ; mesuré, gzip la ramène à
    126 Ko. Coût : 15,7 ms de processeur pour 6,1 s de transfert économisé sur
    un lien à 1 Mbit/s — le rapport qui justifie le niveau 6."""

    def setUp(self):
        self.client = flask_app_module.app.test_client()

    def _corps_volumineux(self):
        """Une réponse JSON dépassant le seuil de compression."""
        return self.client.get("/api/_test_charge_utile",
                               headers={"Accept-Encoding": "gzip"})

    def test_28_une_grosse_reponse_est_compressee(self):
        r = self.client.get("/api/_test_charge_utile", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", r.headers.get("Vary", ""))

    def test_29_le_contenu_decompresse_est_identique(self):
        """Une compression qui altère un octet corromprait chaque réponse."""
        brut = self.client.get("/api/_test_charge_utile",
                               headers={"Accept-Encoding": "identity"})
        comp = self.client.get("/api/_test_charge_utile", headers={"Accept-Encoding": "gzip"})
        self.assertIsNone(brut.headers.get("Content-Encoding"))
        self.assertEqual(json.loads(brut.get_data()),
                         json.loads(gzip.decompress(comp.get_data())))
        self.assertLess(len(comp.get_data()), len(brut.get_data()) // 2,
                        "du JSON doit se compresser d'au moins un facteur 2")

    def test_30_un_client_sans_gzip_recoit_du_brut(self):
        r = self.client.get("/api/_test_charge_utile", headers={"Accept-Encoding": "identity"})
        self.assertIsNone(r.headers.get("Content-Encoding"))
        self.assertIsInstance(json.loads(r.get_data()), dict)

    def test_31_une_petite_reponse_nest_pas_compressee(self):
        """En dessous du seuil, l'en-tête coûterait plus que le gain."""
        r = self.client.get("/api/health", headers={"Accept-Encoding": "gzip"})
        self.assertIsNone(r.headers.get("Content-Encoding"))
        self.assertEqual(r.get_json()["status"], "ok")

    def test_32_une_erreur_nest_pas_compressee(self):
        """Les réponses d'erreur restent lisibles telles quelles dans les
        journaux et les outils de diagnostic."""
        r = self.client.get("/api/students", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(r.headers.get("Content-Encoding"))


class PurgeDesSessionsTests(unittest.TestCase):
    """Une session expirée n'était effacée que si quelqu'un présentait son
    jeton — ce qui n'arrive jamais. La table grossissait indéfiniment et
    conservait des secrets périmés. Relevé sur la base de développement :
    16 jetons d'avant le passage au hachage y dormaient encore, en clair."""

    def test_33_seules_les_sessions_expirees_sont_purgees(self):
        import time as _t
        import security as sec
        client = flask_app_module.app.test_client()
        sec.reset_rate_limits_for_tests()
        # Un vrai établissement : les sessions portent des clés étrangères
        # vers users et tenants, et c'est très bien ainsi.
        r = client.post("/api/auth/register-school",
                        json={"email": "purge@prod.test", "password": "Secret123!",
                              "name": "Pur Ge", "school_name": "École Purge"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        jeton_vif = r.get_json()["token"]
        entetes = {"Authorization": "Bearer " + jeton_vif}
        # Une seconde session pour le même compte, que l'on fera expirer.
        r2 = client.post("/api/auth/login",
                         json={"email": "purge@prod.test", "password": "Secret123!"})
        self.assertEqual(r2.status_code, 200)
        jeton_mort = r2.get_json()["token"]

        conn = db.get_connection()
        try:
            conn.execute("UPDATE sessions SET expires_at='0' WHERE token=?",
                         (sec.hash_session_token(jeton_mort),))
            conn.commit()
            supprimees = sec.purger_sessions_expirees(conn)
            self.assertGreaterEqual(supprimees, 1)
            reste_vif = conn.execute("SELECT 1 FROM sessions WHERE token=?",
                                     (sec.hash_session_token(jeton_vif),)).fetchone()
            reste_mort = conn.execute("SELECT 1 FROM sessions WHERE token=?",
                                      (sec.hash_session_token(jeton_mort),)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(reste_vif, "une session VALIDE a été supprimée")
        self.assertIsNone(reste_mort, "une session expirée a survécu à la purge")
        # Et la session valide fonctionne toujours après la purge.
        self.assertEqual(client.get("/api/students", headers=entetes).status_code, 200)
        self.assertEqual(_t and 1, 1)

    def test_34_la_purge_ne_laisse_aucun_jeton_expire(self):
        """Invariant global : après purge, plus une seule session périmée."""
        import security as sec
        import time as _t
        conn = db.get_connection()
        try:
            sec.purger_sessions_expirees(conn)
            restantes = conn.execute(
                "SELECT COUNT(*) AS n FROM sessions WHERE CAST(expires_at AS REAL) < ?",
                (_t.time(),)).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(restantes, 0)


class ReponsesDeServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()

    def test_22_health_repond_sans_authentification(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")

    def test_23_entetes_de_securite_presents(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")

    def test_24_cors_refuse_une_origine_inconnue(self):
        r = self.client.get("/api/health", headers={"Origin": "https://attaquant.example"})
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)

    def test_25_cors_accepte_une_origine_declaree(self):
        r = self.client.get("/api/health", headers={"Origin": "http://localhost:4173"})
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "http://localhost:4173")

    def test_26_le_joker_cors_reste_impossible(self):
        self.assertNotIn("*", flask_app_module.ALLOWED_ORIGINS)

    def test_27_une_erreur_inattendue_ne_fuit_pas_la_trace(self):
        """Un 500 ne doit jamais renvoyer chemins de fichiers ni requête SQL."""
        r = self.client.get("/api/_test_erreur_inattendue")
        self.assertEqual(r.status_code, 500)
        corps = r.get_data(as_text=True)
        self.assertNotIn("password_hash", corps)
        self.assertNotIn("Traceback", corps)
        self.assertEqual(r.get_json()["error"], "Erreur interne du serveur.")


if __name__ == "__main__":
    unittest.main()
