"""KLASSIO — traduction de dialecte SQL : les cas qui cassent une migration.

Ces tests tournent sans base de données : ils vérifient la seule pièce qui
réécrit les requêtes de tout le backend.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sql_dialect  # noqa: E402


class SqlDialectTests(unittest.TestCase):
    def test_01_marqueurs_traduits(self):
        self.assertEqual(
            sql_dialect.to_pyformat("SELECT * FROM students WHERE tenant_id=? AND id=?"),
            "SELECT * FROM students WHERE tenant_id=%s AND id=%s",
        )

    def test_02_point_interrogation_dans_une_chaine_preserve(self):
        """Un « ? » qui appartient au texte n'est pas un marqueur."""
        self.assertEqual(
            sql_dialect.to_pyformat("SELECT 'Ça va ?' AS t WHERE id=?"),
            "SELECT 'Ça va ?' AS t WHERE id=%s",
        )

    def test_03_pourcent_double_pour_psycopg(self):
        """LIKE '%x%' doit survivre au formatage de psycopg."""
        self.assertEqual(
            sql_dialect.to_pyformat("SELECT 1 WHERE name LIKE '%Kabongo%' AND id=?"),
            "SELECT 1 WHERE name LIKE '%%Kabongo%%' AND id=%%s".replace("%%s", "%s"),
        )

    def test_04_apostrophe_echappee(self):
        """'' à l'intérieur d'une chaîne ne referme pas la chaîne."""
        sql = "SELECT 'aujourd''hui ?' AS t, x FROM y WHERE z=?"
        self.assertEqual(sql_dialect.to_pyformat(sql), "SELECT 'aujourd''hui ?' AS t, x FROM y WHERE z=%s")

    def test_05_requete_reelle_du_backend(self):
        sql = ("SELECT SUM(CASE WHEN status='present' THEN 1 ELSE 0 END) p, COUNT(*) n "
               "FROM attendance WHERE tenant_id=? AND class_id=? AND date=?")
        out = sql_dialect.to_pyformat(sql)
        self.assertEqual(out.count("%s"), 3)
        self.assertIn("WHEN status='present'", out)

    def test_06_schema_traduit_les_types(self):
        ddl = "CREATE TABLE IF NOT EXISTS grades (id TEXT PRIMARY KEY, score REAL NOT NULL, n INTEGER DEFAULT 0);"
        out = sql_dialect.schema_to_postgres(ddl)
        self.assertIn("DOUBLE PRECISION", out)
        self.assertNotIn("REAL", out)
        self.assertIn("INTEGER", out)

    def test_07_schema_refuse_ce_qui_ne_se_traduit_pas_seul(self):
        with self.assertRaises(ValueError):
            sql_dialect.schema_to_postgres("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT);")
        with self.assertRaises(ValueError):
            sql_dialect.schema_to_postgres("CREATE TABLE t (d TEXT DEFAULT (datetime('now')));")

    def test_08_schema_retire_les_pragma(self):
        """PRAGMA n'existe pas en PostgreSQL et ferait échouer tout le script."""
        out = sql_dialect.schema_to_postgres("PRAGMA foreign_keys = ON;\nCREATE TABLE t (id TEXT);")
        self.assertNotIn("PRAGMA", out)
        self.assertIn("CREATE TABLE t", out)

    def test_09_schema_reel_de_klassio_se_traduit(self):
        path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        out = sql_dialect.schema_to_postgres(source)
        self.assertIn("CREATE TABLE IF NOT EXISTS tenants", out)
        self.assertNotIn(" REAL", out)
        self.assertEqual(source.count("CREATE TABLE"), out.count("CREATE TABLE"))


    # -----------------------------------------------------------------
    # Commentaires SQL. Ajoutés après un vrai incident : un commentaire
    # français placé dans une requête (« PostgreSQL n'accepte pas… ») faisait
    # croire au traducteur qu'une chaîne s'ouvrait, et plus aucun « ? » situé
    # après n'était traduit. PostgreSQL recevait alors des « ? » littéraux.
    # -----------------------------------------------------------------

    def test_10_apostrophe_dans_un_commentaire_de_ligne(self):
        sql = "SELECT a FROM t -- n'accepte pas la colonne nue\nWHERE id=? AND x=?"
        self.assertEqual(sql_dialect.to_pyformat(sql).count("%s"), 2)

    def test_11_apostrophe_dans_un_commentaire_encadre(self):
        sql = "SELECT 1 /* l'essentiel */ WHERE id=? AND y=?"
        self.assertEqual(sql_dialect.to_pyformat(sql).count("%s"), 2)

    def test_12_pourcent_double_meme_dans_un_commentaire(self):
        """psycopg lit le pourcentage partout, commentaires compris."""
        self.assertEqual(
            sql_dialect.to_pyformat("SELECT 1 -- 100% fiable\nWHERE id=?"),
            "SELECT 1 -- 100%% fiable\nWHERE id=%s",
        )

    def test_13_un_tiret_tiret_dans_une_chaine_reste_du_texte(self):
        sql = "SELECT '-- pas un commentaire ?' AS t WHERE id=?"
        self.assertEqual(sql_dialect.to_pyformat(sql).count("%s"), 1)

    def test_14_commentaire_non_referme_ne_perd_pas_la_requete(self):
        self.assertEqual(sql_dialect.to_pyformat("SELECT 1 /* jamais refermé"),
                         "SELECT 1 /* jamais refermé")

    def test_15_toutes_les_requetes_du_backend_gardent_leurs_marqueurs(self):
        """Filet global : dans chaque fichier du backend, le nombre de « ? »
        hors chaîne doit survivre à la traduction. Une requête commentée qui
        casserait la traduction serait attrapée ici, pas en production."""
        import glob
        import os
        import re
        racine = os.path.join(os.path.dirname(__file__), "..")
        for chemin in glob.glob(os.path.join(racine, "*.py")):
            with open(chemin, encoding="utf-8") as f:
                source = f.read()
            for requete in re.findall(r'"""(\s*(?:SELECT|INSERT|UPDATE|DELETE)[^"]*?)"""', source, re.IGNORECASE):
                # Les parties `{…}` d'une f-string sont du Python, pas du SQL :
                # elles produisent leurs propres marqueurs à l'exécution.
                statique = re.sub(r"\{[^{}]*\}", "", requete)
                traduite = sql_dialect.to_pyformat(statique)
                self.assertNotIn("?", traduite,
                                 f"marqueur non traduit dans {os.path.basename(chemin)} : {requete[:80]}…")


if __name__ == "__main__":
    unittest.main()
