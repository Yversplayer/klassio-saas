"""KLASSIO — Row Level Security : la base cloisonne les établissements elle-même.

Le backend filtre chaque requête par établissement, et test_release_gate.py
le vérifie route par route. RLS (07/10/2026, db._activer_rls) est le filet
DESSOUS : ces tests simulent le bug qu'il doit rattraper — une requête qui
oublie son `WHERE tenant_id = ?`, une écriture vers l'école d'à côté — et
vérifient que PostgreSQL lui-même refuse.

PostgreSQL seulement (tools/pg_tests.py) : SQLite n'a pas de RLS.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import flask  # noqa: E402
import app as flask_app_module  # noqa: E402
import security  # noqa: E402

APP = flask_app_module.app
POSTGRES = db.is_postgres()


def setUpModule():
    if not POSTGRES:
        return
    db.init_db()


def ecole(nom):
    c = APP.test_client()
    r = c.post("/api/auth/register-school", json={
        "email": f"dir.{nom}@rls.test", "password": "Secret123!", "name": f"Direction {nom}",
        "school_name": f"École {nom}"})
    assert r.status_code == 201, r.get_data(as_text=True)
    corps = r.get_json()
    h = {"Authorization": "Bearer " + corps["token"]}
    an = c.get("/api/academic-years", headers=h).get_json()[0]["id"]
    cls = c.post("/api/classes", json={"name": f"6e {nom}", "academic_year_id": an, "cycle": "secondaire"},
                 headers=h).get_json()["id"]
    eleve = c.post("/api/students", json={"first_name": f"Élève{nom}", "last_name": "Test",
                                          "academic_year_id": an, "class_id": cls}, headers=h).get_json()["id"]
    uid = c.get("/api/me", headers=h).get_json()["user_id"]
    return {"tenant": corps["tenant_id"], "h": h, "classe": cls, "eleve": eleve, "user": uid,
            "token": corps["token"]}


class SousLaPorteeDe:
    """Une connexion prise PENDANT une requête d'école, comme une route."""

    def __init__(self, tenant_id, user_id="u", globale=False):
        self.ctx = {"tenant_id": tenant_id, "user_id": user_id, "role": "directeur"}
        self.globale = globale

    def __enter__(self):
        self._req = APP.test_request_context()
        self._req.__enter__()
        flask.g.ctx = self.ctx
        self.conn = db.get_connection(globale=self.globale)
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        self._req.__exit__(*exc)


def tables_a_tenant(conn):
    return [r["table_name"] for r in conn.execute(
        """SELECT c.table_name FROM information_schema.columns c
           JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
           WHERE c.table_schema = current_schema() AND c.column_name = 'tenant_id'
             AND t.table_type = 'BASE TABLE' ORDER BY 1""")]


@unittest.skipUnless(POSTGRES, "RLS : PostgreSQL seulement")
class LaBaseCloisonne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        security.reset_rate_limits_for_tests()
        cls.A = ecole("A")
        cls.B = ecole("B")

    def test_01_chaque_table_a_tenant_a_sa_politique(self):
        conn = db.get_connection()
        try:
            tables = tables_a_tenant(conn)
            self.assertGreater(len(tables), 40)
            sans = [t for t in tables if not conn.execute(
                """SELECT 1 FROM pg_class k JOIN pg_namespace n ON n.oid = k.relnamespace
                   WHERE n.nspname = current_schema() AND k.relname = ? AND k.relrowsecurity""", (t,)).fetchone()
                    or not conn.execute(
                """SELECT 1 FROM pg_policies WHERE schemaname = current_schema() AND tablename = ?
                   AND policyname = 'klassio_isolation'""", (t,)).fetchone()]
        finally:
            conn.close()
        self.assertEqual(sans, [], "tables à tenant_id sans RLS")

    def test_02_une_requete_qui_oublie_son_filtre_ne_voit_que_son_ecole(self):
        with SousLaPorteeDe(self.A["tenant"]) as conn:
            tenants = {r["tenant_id"] for r in conn.execute("SELECT tenant_id FROM students")}
            classes = {r["tenant_id"] for r in conn.execute("SELECT tenant_id FROM classes")}
        self.assertEqual(tenants, {self.A["tenant"]})
        self.assertEqual(classes, {self.A["tenant"]})

    def test_03_aucune_table_ne_laisse_voir_l_ecole_d_a_cote(self):
        """Toutes les tables à tenant_id, une par une : élèves, classes,
        paiements, reçus, documents, invitations, notifications, présences,
        discipline, résultats, délibérations, plans de passage, années…"""
        with SousLaPorteeDe(self.A["tenant"]) as conn:
            fuites = []
            for t in tables_a_tenant(conn):
                n = conn.execute(f'SELECT COUNT(*) AS n FROM "{t}" WHERE tenant_id = ?',
                                 (self.B["tenant"],)).fetchone()["n"]
                if n:
                    fuites.append(f"{t}: {n}")
        self.assertEqual(fuites, [])

    def test_04_modifier_ou_supprimer_chez_le_voisin_ne_touche_rien(self):
        with SousLaPorteeDe(self.A["tenant"]) as conn:
            maj = conn.execute("UPDATE students SET first_name = 'Pirate' WHERE id = ?", (self.B["eleve"],)).rowcount
            sup = conn.execute("DELETE FROM classes WHERE id = ?", (self.B["classe"],)).rowcount
            conn.commit()
        self.assertEqual((maj, sup), (0, 0))
        conn = db.get_connection()
        try:
            self.assertNotEqual(conn.execute("SELECT first_name FROM students WHERE id = ?",
                                             (self.B["eleve"],)).fetchone()["first_name"], "Pirate")
            self.assertIsNotNone(conn.execute("SELECT 1 FROM classes WHERE id = ?", (self.B["classe"],)).fetchone())
        finally:
            conn.close()

    def test_05_ecrire_une_ligne_au_nom_du_voisin_est_refuse(self):
        import psycopg
        with SousLaPorteeDe(self.A["tenant"]) as conn:
            an = conn.execute("SELECT id FROM academic_years LIMIT 1").fetchone()["id"]
            with self.assertRaises(psycopg.Error):
                conn.execute("INSERT INTO classes (id, tenant_id, academic_year_id, name, created_at) "
                             "VALUES (?,?,?,?,?)", (security.new_id(), self.B["tenant"], an, "Intruse", "0"))
            conn.rollback()

    def test_06_ferme_par_defaut_sans_reglage_aucune_ligne(self):
        with SousLaPorteeDe(self.A["tenant"]) as conn:
            conn.execute("SELECT set_config('klassio.mode', '', false), set_config('klassio.tenant', '', false)")
            n = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
            conn.rollback()
        self.assertEqual(n, 0, "un réglage manquant laisse voir des lignes")

    def test_07_la_reserve_ne_transmet_pas_l_ecole_d_une_requete_a_l_autre(self):
        """Piège de la réserve de connexions : la requête d'A valide, sa
        connexion retourne à la réserve ; celle de B la reprend et annule
        (rollback) au milieu. Les réglages ne doivent pas revenir à ceux d'A."""
        with SousLaPorteeDe(self.A["tenant"]) as conn:
            conn.execute("SELECT 1")
            conn.commit()
        with SousLaPorteeDe(self.B["tenant"]) as conn:
            conn.rollback()
            vus = {r["tenant_id"] for r in conn.execute("SELECT tenant_id FROM students")}
        self.assertEqual(vus, {self.B["tenant"]})

    def test_08_hors_requete_le_proprietaire_voit_tout(self):
        """Migrations et outils d'exploitation : hors requête HTTP, RLS ne
        s'applique pas (documenté dans db.py)."""
        conn = db.get_connection()
        try:
            vus = {r["tenant_id"] for r in conn.execute("SELECT tenant_id FROM students")}
        finally:
            conn.close()
        self.assertTrue({self.A["tenant"], self.B["tenant"]} <= vus)

    def test_09_changer_son_mot_de_passe_ferme_ses_sessions_dans_toutes_ses_ecoles(self):
        """Usage GLOBAL volontaire (app.change_password) : sans lui, RLS aurait
        laissé vivre la session de l'autre école."""
        u = ecole("Multi")
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO memberships (id, user_id, tenant_id, role, created_at) VALUES (?,?,?,?,?)",
                         (security.new_id(), u["user"], self.B["tenant"], "professeur", "0"))
            conn.commit()
            jeton_b = security.create_session(conn, u["user"], self.B["tenant"])
        finally:
            conn.close()
        c = APP.test_client()
        self.assertEqual(c.get("/api/me", headers={"Authorization": "Bearer " + jeton_b}).status_code, 200)
        r = c.post("/api/me/password", headers=u["h"],
                   json={"current_password": "Secret123!", "new_password": "Nouveau456!"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(c.get("/api/me", headers={"Authorization": "Bearer " + jeton_b}).status_code, 401,
                         "la session de l'autre école a survécu au changement de mot de passe")

    def test_11_comme_chez_supabase_rls_d_office_sur_toutes_les_tables(self):
        """Supabase active RLS sur toute nouvelle table quand « Enable automatic
        RLS » est coché (c'est le cas en production). Une table sous RLS sans
        politique ne renvoie rien à `klassio_app` : sans les politiques
        d'accès des tables sans établissement, la connexion elle-même tombait."""
        conn = db.get_connection()
        try:
            avec_tenant = set(tables_a_tenant(conn))
            for t in [r["table_name"] for r in conn.execute(
                    """SELECT table_name FROM information_schema.tables
                       WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'""")]:
                if t not in avec_tenant:
                    conn.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
            conn.commit()
            db._activer_rls(conn)  # ce que rejoue chaque déploiement
        finally:
            conn.close()
        c = APP.test_client()
        r = c.post("/api/auth/login", json={"identifier": "dir.a@rls.test", "password": "Secret123!"})
        self.assertEqual(r.status_code, 200, "connexion impossible sous RLS d'office : " + r.get_data(as_text=True))
        self.assertEqual(c.get("/api/me", headers={"Authorization": "Bearer " + r.get_json()["token"]}).status_code, 200)
        self.assertTrue(c.get("/api/plans").get_json(), "paliers invisibles sous RLS d'office")

    def test_12_l_administration_voit_l_etat_reel_de_rls(self):
        from tests.outils_plateforme import session_admin
        admin, _, _ = session_admin(APP)
        etat = admin.get("/api/platform/overview").get_json()["security"]
        self.assertEqual(etat["unprotected"], [])
        self.assertEqual(etat["protected"], etat["tenant_tables"])
        self.assertEqual(etat["role"], db.ROLE_APP, "les requêtes ne passent pas par le rôle applicatif")

    def test_10_par_l_api_rien_ne_change_pour_l_ecole_elle_meme(self):
        c = APP.test_client()
        eleves = c.get("/api/students", headers=self.A["h"]).get_json()
        self.assertTrue(any(e["id"] == self.A["eleve"] for e in eleves))
        self.assertFalse(any(e["id"] == self.B["eleve"] for e in eleves))
        self.assertEqual(c.get(f"/api/students/{self.B['eleve']}", headers=self.A["h"]).status_code, 404)


if __name__ == "__main__":
    unittest.main()
