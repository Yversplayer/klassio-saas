"""KLASSIO — un poste de développement ne doit jamais pouvoir abîmer la production.

Pourquoi ce fichier existe.

Le 25/09, un audit préparant le partage du dépôt a trouvé deux chemins par
lesquels une machine de développement pouvait toucher une vraie base, sans que
personne ne l'ait voulu :

  1. `seed_echelle.py` et `seed_charge.py` ne protégeaient que la base SQLite de
     travail. Avec KLASSIO_DB_BACKEND=postgres — et la chaîne de connexion était
     déjà dans backend/.env — ils peuplaient la base distante, en y créant des
     comptes Direction dont le mot de passe est publié dans le README.

  2. `pg_migrate.py tout`, présenté dans sa propre documentation comme « les
     deux » (schéma et données), commence par DROP SCHEMA public CASCADE sur la
     base visée, sans rien demander.

Aucun des deux n'était exploitable par un développeur externe : il n'a pas la
chaîne de connexion. Mais le propriétaire l'a, et une commande recopiée
suffisait.

Les garde-fous se fondent sur l'HÔTE de la base, jamais sur une étiquette
d'environnement qu'on peut oublier de poser. Aucun de ces tests n'ouvre de
connexion réelle : les bases distantes y sont fictives, et toute tentative de
s'y connecter fait échouer le test.
"""
import importlib.util
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config  # noqa: E402
import db  # noqa: E402

OUTILS = os.path.join(os.path.dirname(__file__), "..", "tools")

# Fictives. Le mot de passe est volontairement présent : on vérifie qu'il ne
# ressort jamais.
DISTANTE = "postgresql://postgres.abcdefgh:NE_DOIT_JAMAIS_SORTIR@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
DISTANTE_RENDER = "postgres://klassio:NE_DOIT_JAMAIS_SORTIR@dpg-xyz.frankfurt-postgres.render.com/klassio"
LOCALE = "postgresql://postgres:MDP_LOCAL@localhost:5432/klassio"


def _charger(nom):
    spec = importlib.util.spec_from_file_location(f"outil_{nom}", os.path.join(OUTILS, f"{nom}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aucune_connexion(*_a, **_k):
    raise AssertionError("une connexion à la base a été tentée : le garde-fou arrive trop tard")


class HoteDeLaBaseTests(unittest.TestCase):

    def test_01_les_bases_de_cette_machine_sont_locales(self):
        for url in (LOCALE, "postgresql://U:MDP@127.0.0.1/db", "postgresql://U:MDP@[::1]:5432/db",
                    "postgresql:///klassio?host=/tmp/pg", "host=/var/run/postgresql dbname=k",
                    "host=localhost dbname=k user=u"):
            self.assertTrue(config.postgres_est_local(url), url)

    def test_02_les_hebergeurs_sont_distants(self):
        for url in (DISTANTE, DISTANTE_RENDER, "host=db.example.org dbname=k"):
            self.assertFalse(config.postgres_est_local(url), url)

    def test_03_aucune_base_configuree_ne_vise_rien_de_distant(self):
        self.assertIsNone(config.hote_postgres(""))
        self.assertTrue(config.postgres_est_local(""))

    def test_04_le_mot_de_passe_ne_sort_jamais(self):
        for url in (DISTANTE, DISTANTE_RENDER):
            self.assertNotIn("NE_DOIT_JAMAIS_SORTIR", config.hote_postgres(url))


class BaseJetableTests(unittest.TestCase):
    """db.exiger_base_jetable : le garde-fou partagé des outils de peuplement."""

    def _sous(self, url, postgres=True, etablissements=0):
        compteur = mock.Mock(return_value=etablissements)
        return compteur, [
            mock.patch.object(config, "SUPABASE_DB_URL", url),
            mock.patch.object(db, "is_postgres", return_value=postgres),
            mock.patch.object(db, "_nombre_d_etablissements", compteur),
        ]

    def _executer(self, url, drapeau=False, postgres=True, etablissements=0):
        compteur, patches = self._sous(url, postgres, etablissements)
        for p in patches:
            p.start()
        try:
            db.exiger_base_jetable("outil-de-test", drapeau)
        finally:
            for p in patches:
                p.stop()
        return compteur

    def test_10_base_distante_refusee_par_defaut_sans_meme_s_y_connecter(self):
        compteur, patches = self._sous(DISTANTE)
        for p in patches:
            p.start()
        try:
            with self.assertRaises(SystemExit) as refus:
                db.exiger_base_jetable("outil-de-test")
        finally:
            for p in patches:
                p.stop()
        self.assertIn("DISTANTE", str(refus.exception))
        self.assertNotIn("NE_DOIT_JAMAIS_SORTIR", str(refus.exception))
        compteur.assert_not_called()

    def test_11_meme_avec_le_drapeau_une_base_qui_contient_des_ecoles_est_refusee(self):
        with self.assertRaises(SystemExit) as refus:
            self._executer(DISTANTE, drapeau=True, etablissements=4)
        self.assertIn("4 établissement", str(refus.exception))

    def test_12_une_base_de_recette_vide_passe_avec_le_drapeau(self):
        compteur = self._executer(DISTANTE_RENDER, drapeau=True, etablissements=0)
        compteur.assert_called_once()

    def test_13_postgresql_local_et_sqlite_passent_sans_rien_demander(self):
        self._executer(LOCALE).assert_not_called()
        self._executer(DISTANTE, postgres=False).assert_not_called()   # SQLite : l'URL n'est pas utilisée


class OutilsDePeuplementTests(unittest.TestCase):
    """Les deux outils refusent une base distante AVANT la moindre connexion."""

    def _refus(self, nom, argv):
        outil = _charger(nom)
        with mock.patch.object(config, "SUPABASE_DB_URL", DISTANTE), \
             mock.patch.object(db, "is_postgres", return_value=True), \
             mock.patch.object(db, "get_connection", side_effect=_aucune_connexion), \
             mock.patch.object(db, "init_db", side_effect=_aucune_connexion):
            with self.assertRaises(SystemExit) as refus:
                outil.main(argv)
        return str(refus.exception)

    def test_20_seed_echelle_refuse_une_base_distante(self):
        self.assertIn("seed_echelle.py", self._refus("seed_echelle", ["--ecoles", "1", "--eleves", "5"]))

    def test_21_seed_charge_refuse_une_base_distante(self):
        self.assertIn("seed_charge.py", self._refus("seed_charge", ["--eleves", "5"]))


class _FausseBase:
    """Connexion PostgreSQL simulée : compte les établissements, note tout ce
    qu'on lui fait exécuter, et s'arrête juste après l'effacement."""

    class Arret(Exception):
        pass

    def __init__(self, etablissements):
        self.etablissements = etablissements
        self.executees = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, *_):
        self.executees.append(sql)
        if "COUNT(*) FROM tenants" in sql:
            return mock.Mock(fetchone=mock.Mock(return_value=(self.etablissements,)))
        if sql.startswith("CREATE SCHEMA"):
            raise self.Arret()
        return mock.Mock()

    def commit(self):
        pass

    def rollback(self):
        pass


class MigrationTests(unittest.TestCase):
    """pg_migrate.py reinit / tout : l'effacement n'atteint jamais une base d'école."""

    def _reinit(self, etablissements, argv):
        pgm = _charger("pg_migrate")
        base = _FausseBase(etablissements)
        with mock.patch.object(pgm, "connect_pg", return_value=base), \
             mock.patch.object(config, "SUPABASE_DB_URL", DISTANTE), \
             mock.patch.object(sys, "argv", argv):
            try:
                code = pgm.reinitialiser()
            except _FausseBase.Arret:
                code = "effacement exécuté"
        return code, base.executees

    def test_30_une_base_qui_contient_des_ecoles_n_est_pas_effacee(self):
        code, executees = self._reinit(12, ["pg_migrate.py", "tout"])
        self.assertEqual(code, 3)
        self.assertFalse([s for s in executees if "DROP" in s], "DROP SCHEMA exécuté sur une base d'école")

    def test_31_une_base_vide_est_toujours_reinitialisable(self):
        code, executees = self._reinit(0, ["pg_migrate.py", "reinit"])
        self.assertEqual(code, "effacement exécuté")
        self.assertIn("DROP SCHEMA public CASCADE", executees)

    def test_32_l_effacement_voulu_reste_possible_en_toutes_lettres(self):
        code, executees = self._reinit(12, ["pg_migrate.py", "reinit", "--effacer-la-base-cible"])
        self.assertEqual(code, "effacement exécuté")
        self.assertIn("DROP SCHEMA public CASCADE", executees)


class DemonstrationTests(unittest.TestCase):
    """tools/demo.py : la commande qu'un développeur inconnu lance en premier."""

    def setUp(self):
        import tempfile
        self.dossier = tempfile.mkdtemp(prefix="klassio_demo_test_")
        self.base = os.path.join(self.dossier, "klassio_demo.db")
        # La démonstration est SQLite par conception. Sous tools/pg_tests.py,
        # le moteur ambiant est PostgreSQL : ces tests fixent donc le leur, au
        # lieu d'hériter d'un réglage qui n'est pas celui qu'ils éprouvent.
        self.patches = [mock.patch.object(db, "DB_PATH", self.base),
                        mock.patch.object(config, "DB_BACKEND", "sqlite")]
        for p in self.patches:
            p.start()
        self.demo = _charger("demo")

    def tearDown(self):
        import shutil
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.dossier, ignore_errors=True)

    def _sql(self, requete, *params):
        import sqlite3
        conn = sqlite3.connect(self.base)
        try:
            return conn.execute(requete, params).fetchall()
        finally:
            conn.close()

    def test_40_sans_modele_copie_elle_refuse_la_base_de_travail(self):
        travail = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "klassio.db"))
        with mock.patch.object(db, "DB_PATH", travail):
            with self.assertRaises(SystemExit) as refus:
                self.demo.main([])
        self.assertIn(".env.example", str(refus.exception))

    def test_41_elle_cree_une_ecole_fictive_et_annoncee_comme_telle(self):
        self.assertEqual(self.demo.main([]), 0)
        self.assertEqual(self._sql("SELECT COUNT(*) FROM students")[0][0], 300)
        (nom,), = self._sql("SELECT name FROM tenants")
        self.assertTrue(nom.endswith("DÉMONSTRATION"), nom)
        adresses = [r[0] for r in self._sql("SELECT email FROM users")]
        self.assertTrue(adresses)
        self.assertTrue(all(a.endswith(".charge.test") for a in adresses), adresses[:3])

    def test_42_la_reconstruction_est_reproductible_et_ne_double_rien(self):
        self.demo.main([])
        avant = self._sql("SELECT code, first_name, last_name FROM students ORDER BY code")
        self.assertEqual(self.demo.main([]), 0)            # déjà là : rien ne bouge
        self.demo.main(["--recreer"])
        apres = self._sql("SELECT code, first_name, last_name FROM students ORDER BY code")
        self.assertEqual(len(apres), 300)
        self.assertEqual(avant, apres, "deux constructions doivent donner exactement les mêmes élèves")

    def test_44_elle_ne_se_construit_jamais_sur_postgresql(self):
        with mock.patch.object(config, "DB_BACKEND", "postgres"), \
             mock.patch.object(db, "get_connection", side_effect=_aucune_connexion):
            with self.assertRaises(SystemExit) as refus:
                self.demo.main([])
        self.assertIn("SQLite", str(refus.exception))

    def test_43_une_base_avec_un_seul_compte_reel_n_est_jamais_effacee(self):
        self.demo.main([])
        import sqlite3
        conn = sqlite3.connect(self.base)
        conn.execute("INSERT INTO users (id, email, password_hash, name, created_at) "
                     "VALUES ('reel2', 'parent@gmail.com', 'x$y', 'Parent', '2026-09-25')")
        conn.commit(); conn.close()
        with self.assertRaises(SystemExit) as refus:
            self.demo.main(["--recreer"])
        self.assertIn("ne sera pas effacée", str(refus.exception))
        self.assertTrue(os.path.exists(self.base))
        self.assertEqual(self._sql("SELECT COUNT(*) FROM users WHERE id='reel2'")[0][0], 1)


if __name__ == "__main__":
    unittest.main()
