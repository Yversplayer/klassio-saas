"""KLASSIO — deux garanties qui ne tenaient pas, et qui ne se voyaient qu'au
deuxième millésime ou sous concurrence.

Ces tests ne vérifient pas un parcours, ils vérifient une PROMESSE :

1. « Un parent ne voit jamais un résultat non proclamé. »
   La proclamation se décidait sur le seul libellé de période. Or un
   établissement appelle « Période 1 » la première période de CHAQUE année.
   Proclamer la Période 1 de 2025-2026 rendait donc visibles les notes de la
   Période 1 de 2026-2027, jamais proclamées. Le défaut est invisible la
   première année : il n'existe qu'une seule année, donc aucune collision.

2. « Ce lien est personnel et à usage unique. » (texte affiché à l'utilisateur)
   L'invitation n'était marquée « acceptée » qu'à la toute fin de la route,
   après création du compte et des rattachements. Deux acceptations simultanées
   du même lien lisaient donc toutes les deux « pending » et créaient deux
   comptes. Un lien transféré — par WhatsApp, cas courant — donnait à un tiers
   l'accès au dossier d'un enfant.
"""
import os
import sys
import threading
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import school  # noqa: E402

TEST_DB = os.path.join(os.path.dirname(__file__), "..", "klassio_test.db")
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class MillesimeTests(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def _ecole(self, email, nom):
        r = self.c.post("/api/auth/register-school", json={
            "email": email, "password": "Secret123!", "name": "Directeur", "school_name": nom})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return {"Authorization": f"Bearer {r.get_json()['token']}"}

    # -----------------------------------------------------------------
    # 1. Proclamation bornée à son année
    # -----------------------------------------------------------------
    def test_01_parent_ne_voit_pas_les_notes_dune_annee_non_proclamee(self):
        H = self._ecole("dir.millesime@test.local", "École Millésime")
        an1 = self.c.get("/api/academic-years", headers=H).get_json()[0]["id"]

        classe1 = self.c.post("/api/classes", json={
            "name": "6e A", "academic_year_id": an1, "cycle": "secondaire"}, headers=H).get_json()["id"]
        eleve = self.c.post("/api/students", json={
            "first_name": "Audrey", "last_name": "Mukendi",
            "academic_year_id": an1, "class_id": classe1}, headers=H).get_json()["id"]

        # Année 1 : une note, une période proclamée. C'est l'historique légitime.
        p1 = self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=H).get_json()["id"]
        self.c.post(f"/api/classes/{classe1}/grades", json={
            "subject": "Maths", "period": "Période 1", "max_score": 20,
            "entries": [{"student_id": eleve, "score": 12}]}, headers=H)
        self.assertEqual(self.c.post(f"/api/periods/{p1}/publish", json={}, headers=H).status_code, 200)

        # Année 2 : nouvelle classe, élève promu, MÊME libellé de période,
        # jamais proclamée.
        an2 = self.c.post("/api/academic-years", json={"label": "2026-2027"}, headers=H).get_json()["id"]
        self.c.post(f"/api/academic-years/{an2}/activate", headers=H)
        classe2 = self.c.post("/api/classes", json={
            "name": "7e A", "academic_year_id": an2, "cycle": "secondaire"}, headers=H).get_json()["id"]
        self.c.put(f"/api/students/{eleve}", json={"class_id": classe2}, headers=H)
        self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=H)
        self.c.post(f"/api/classes/{classe2}/grades", json={
            "subject": "Physique", "period": "Période 1", "max_score": 20,
            "entries": [{"student_id": eleve, "score": 3}]}, headers=H)

        # Le serveur confirme qu'une seule des deux périodes est proclamée.
        conn = db.get_connection()
        publiees = conn.execute(
            "SELECT COUNT(*) n FROM academic_periods WHERE published_at IS NOT NULL").fetchone()["n"]
        conn.close()
        self.assertEqual(publiees, 1, "le test doit comparer une période proclamée à une qui ne l'est pas")

        # Le parent est invité puis consulte.
        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [eleve]}, headers=H).get_json()
        security.reset_rate_limits_for_tests()
        r = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent Mukendi",
            "email": "parent.millesime@test.local", "password": "Secret123!"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        PH = {"Authorization": f"Bearer {r.get_json()['token']}"}

        dossier = self.c.get(f"/api/students/{eleve}", headers=PH).get_json()
        matieres = {g["subject"] for g in (dossier.get("grades") or [])}

        self.assertNotIn("Physique", matieres,
                         "note d'une période NON proclamée exposée au parent (fuite inter-années)")
        self.assertIn("Maths", matieres,
                      "la note proclamée de l'année passée doit rester visible : l'historique n'est jamais effacé")

    def test_01b_le_tableau_de_bord_parent_ne_montre_aucune_note_non_proclamee(self):
        """Le dossier de l'élève filtrait déjà les notes non proclamées (test 01).
        Le TABLEAU DE BORD du parent, lui, lisait `grades` en direct :

            SELECT subject, score, ... FROM grades
            WHERE tenant_id=? AND student_id=? ORDER BY created_at DESC LIMIT 1

        Ni proclamation, ni `is_current`. La tuile « dernière note » du parent
        affichait donc la note la plus récemment SAISIE — y compris une note
        d'une période jamais proclamée, et y compris une version corrigée puis
        remplacée. Même faute que le P0 d'origine, sur un autre chemin de code.
        """
        H = self._ecole("dir.bord@test.local", "École Tableau de Bord")
        an = self.c.get("/api/academic-years", headers=H).get_json()[0]["id"]
        classe = self.c.post("/api/classes", json={
            "name": "6e A", "academic_year_id": an, "cycle": "secondaire"}, headers=H).get_json()["id"]
        eleve = self.c.post("/api/students", json={
            "first_name": "Bruno", "last_name": "Kasongo",
            "academic_year_id": an, "class_id": classe}, headers=H).get_json()["id"]

        # Une période proclamée…
        p1 = self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=H).get_json()["id"]
        self.c.post(f"/api/classes/{classe}/grades", json={
            "subject": "Maths", "period": "Période 1", "max_score": 20,
            "entries": [{"student_id": eleve, "score": 14}]}, headers=H)
        self.assertEqual(self.c.post(f"/api/periods/{p1}/publish", json={}, headers=H).status_code, 200)

        # …et une période PLUS RÉCENTE, jamais proclamée.
        self.c.post("/api/periods", json={"label": "Période 2", "sort": 2}, headers=H)
        self.c.post(f"/api/classes/{classe}/grades", json={
            "subject": "Physique", "period": "Période 2", "max_score": 20,
            "entries": [{"student_id": eleve, "score": 5}]}, headers=H)

        inv = self.c.post("/api/invitations", json={"role": "parent", "student_ids": [eleve]}, headers=H).get_json()
        security.reset_rate_limits_for_tests()
        r = self.c.post("/api/invitations/accept", json={
            "token": inv["token"], "name": "Parent Kasongo",
            "email": "parent.bord@test.local", "password": "Secret123!"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        PH = {"Authorization": f"Bearer {r.get_json()['token']}"}

        bord = self.c.get("/api/dashboard", headers=PH).get_json()
        enfants = bord.get("children") or []
        self.assertEqual(len(enfants), 1, "le parent doit voir son enfant")
        derniere = enfants[0].get("last_grade")

        if derniere is not None:
            self.assertNotEqual(
                derniere.get("subject"), "Physique",
                "note d'une période NON proclamée exposée sur le tableau de bord du parent")
            self.assertEqual(
                derniere.get("subject"), "Maths",
                "seule la dernière note PROCLAMÉE doit remonter au parent")

    def test_01c_le_rang_ignore_les_versions_remplacees(self):
        """La moyenne de l'élève se calcule sur `is_current=1` ; son RANG se
        calculait sur toutes les versions de la classe, corrigées comprises.
        Une note remplacée continuait donc de peser dans la moyenne de son
        camarade — et faussait le classement de tout le monde.
        """
        H = self._ecole("dir.rang@test.local", "École du Rang")
        an = self.c.get("/api/academic-years", headers=H).get_json()[0]["id"]
        classe = self.c.post("/api/classes", json={
            "name": "6e A", "academic_year_id": an, "cycle": "secondaire"}, headers=H).get_json()["id"]
        alice = self.c.post("/api/students", json={
            "first_name": "Alice", "last_name": "A", "academic_year_id": an, "class_id": classe}, headers=H).get_json()["id"]
        bruno = self.c.post("/api/students", json={
            "first_name": "Bruno", "last_name": "B", "academic_year_id": an, "class_id": classe}, headers=H).get_json()["id"]
        self.c.post("/api/periods", json={"label": "Période 1", "sort": 1}, headers=H)

        # Alice 14, Bruno 4. Après correction de Bruno à 18, l'ordre attendu est
        # Bruno 1er (18) devant Alice (14). Si la version remplacée compte
        # encore, Bruno est moyenné à (4+18)/2 = 11 et repasse DERRIÈRE Alice :
        # le classement s'inverse. C'est cette inversion que le test cherche.
        self.c.post(f"/api/classes/{classe}/grades", json={
            "subject": "Maths", "period": "Période 1", "max_score": 20,
            "entries": [{"student_id": alice, "score": 14}, {"student_id": bruno, "score": 4}]}, headers=H)

        # La note de Bruno est CORRIGÉE : sa version à 4 passe en `is_current=0`
        # et une version à 18 la remplace. C'est exactement l'état que produit
        # la confirmation d'un import de résultats (api_academics : UPDATE
        # is_current=0 puis INSERT de la nouvelle version). On le pose
        # directement ici parce que c'est la LECTURE qu'on teste, pas l'import.
        conn = db.get_connection()
        ancienne = conn.execute(
            "SELECT * FROM grades WHERE student_id=? AND subject='Maths'", (bruno,)).fetchone()
        conn.execute("UPDATE grades SET is_current=0 WHERE id=?", (ancienne["id"],))
        conn.execute(
            """INSERT INTO grades (id, tenant_id, student_id, class_id, academic_year_id, period_id,
                                   subject, period, score, max_score, recorded_by, created_at,
                                   version, is_current, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,'import')""",
            (uuid.uuid4().hex, ancienne["tenant_id"], bruno, ancienne["class_id"],
             ancienne["academic_year_id"], ancienne["period_id"], "Maths", "Période 1",
             18, 20, ancienne["recorded_by"], ancienne["created_at"], 2))
        conn.commit()
        conn.close()

        conn = db.get_connection()
        versions = conn.execute(
            "SELECT COUNT(*) n FROM grades WHERE student_id=? AND is_current=0", (bruno,)).fetchone()["n"]
        eleve = dict(conn.execute("SELECT * FROM students WHERE id=?", (bruno,)).fetchone())
        tid = eleve["tenant_id"]
        b = school.bulletin(conn, tid, eleve, period="Période 1")
        conn.close()

        self.assertGreaterEqual(versions, 1, "le test suppose une version remplacée : le correctif a-t-il versionné ?")
        self.assertEqual(b["general_average_20"], 18.0, "la moyenne de Bruno doit se lire sur la version courante")
        self.assertEqual(b["rank"], 1,
                         "Bruno (18) doit être 1er ; s'il ne l'est pas, sa version remplacée (4) pèse encore dans le classement")

    def test_02_appreciation_dune_annee_nefface_pas_celle_de_lannee_precedente(self):
        """Le remplacement d'une appréciation était borné au couple
        (élève, période, domaine) sans l'année : saisir « Période 1 / Langage »
        en 2026-2027 supprimait la ligne de 2025-2026."""
        H = self._ecole("dir.apprec@test.local", "École Maternelle")
        an1 = self.c.get("/api/academic-years", headers=H).get_json()[0]["id"]
        c1 = self.c.post("/api/classes", json={
            "name": "MS", "academic_year_id": an1, "cycle": "maternelle"}, headers=H).get_json()["id"]
        eleve = self.c.post("/api/students", json={
            "first_name": "Sarah", "last_name": "Kabila",
            "academic_year_id": an1, "class_id": c1}, headers=H).get_json()["id"]
        self.c.post(f"/api/classes/{c1}/appreciations", json={
            "period": "Période 1", "domain": "Langage",
            "entries": [{"student_id": eleve, "level": 2}]}, headers=H)

        an2 = self.c.post("/api/academic-years", json={"label": "2027-2028"}, headers=H).get_json()["id"]
        self.c.post(f"/api/academic-years/{an2}/activate", headers=H)
        c2 = self.c.post("/api/classes", json={
            "name": "GS", "academic_year_id": an2, "cycle": "maternelle"}, headers=H).get_json()["id"]
        self.c.put(f"/api/students/{eleve}", json={"class_id": c2}, headers=H)
        self.c.post(f"/api/classes/{c2}/appreciations", json={
            "period": "Période 1", "domain": "Langage",
            "entries": [{"student_id": eleve, "level": 4}]}, headers=H)

        conn = db.get_connection()
        lignes = conn.execute(
            "SELECT level, academic_year_id FROM appreciations WHERE student_id=? ORDER BY level",
            (eleve,)).fetchall()
        conn.close()
        niveaux = [r["level"] for r in lignes]
        self.assertEqual(niveaux, [2, 4],
                         "la progression de l'élève doit être conservée : "
                         f"une année a écrasé l'autre (niveaux trouvés : {niveaux})")
        self.assertEqual(len({r["academic_year_id"] for r in lignes}), 2,
                         "les deux appréciations doivent appartenir à deux années distinctes")


class InvitationUsageUniqueTests(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def test_03_deux_acceptations_simultanees_ne_creent_quun_seul_compte(self):
        r = self.c.post("/api/auth/register-school", json={
            "email": "dir.course@test.local", "password": "Secret123!",
            "name": "Directeur", "school_name": "École Course"})
        H = {"Authorization": f"Bearer {r.get_json()['token']}"}
        an = self.c.get("/api/academic-years", headers=H).get_json()[0]["id"]
        cls = self.c.post("/api/classes", json={
            "name": "6e B", "academic_year_id": an, "cycle": "secondaire"}, headers=H).get_json()["id"]
        eleve = self.c.post("/api/students", json={
            "first_name": "Kevin", "last_name": "Mukendi",
            "academic_year_id": an, "class_id": cls}, headers=H).get_json()["id"]
        inv = self.c.post("/api/invitations", json={
            "role": "parent", "student_ids": [eleve]}, headers=H).get_json()
        security.reset_rate_limits_for_tests()

        # Deux identités DIFFÉRENTES : le lien a été transféré. Les contraintes
        # d'unicité e-mail ne protègent donc rien — seule la prise atomique de
        # l'invitation le fait.
        barriere = threading.Barrier(2)
        resultats = {}

        def accepter(n, email):
            client = flask_app_module.app.test_client()
            corps = {"token": inv["token"], "name": f"Parent {n}",
                     "email": email, "password": "Secret123!"}
            barriere.wait()
            resultats[n] = client.post("/api/invitations/accept", json=corps).status_code

        fils = [threading.Thread(target=accepter, args=(1, "course1@test.local")),
                threading.Thread(target=accepter, args=(2, "course2@test.local"))]
        for f in fils:
            f.start()
        for f in fils:
            f.join()

        conn = db.get_connection()
        parents = conn.execute(
            """SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id
               WHERE m.tenant_id = (SELECT tenant_id FROM students WHERE id=?) AND m.role='parent'""",
            (eleve,)).fetchall()
        liens = conn.execute(
            "SELECT COUNT(*) n FROM student_guardians WHERE student_id=?", (eleve,)).fetchone()["n"]
        conn.close()

        self.assertEqual(len(parents), 1,
                         f"une invitation à usage unique a créé {len(parents)} comptes parent")
        self.assertEqual(liens, 1, f"{liens} rattachements parent-enfant pour une seule invitation")
        self.assertEqual(sorted(resultats.values()), [201, 404],
                         f"le perdant doit recevoir un refus net, obtenu : {resultats}")

    def test_04_le_perdant_ne_laisse_aucun_compte_orphelin(self):
        """Le perdant de la course crée son utilisateur AVANT de tenter de
        prendre l'invitation. Si la transaction n'était pas annulée, un compte
        sans établissement resterait en base — et son e-mail deviendrait
        inutilisable pour une future invitation."""
        conn = db.get_connection()
        orphelins = conn.execute(
            """SELECT u.email FROM users u
               LEFT JOIN memberships m ON m.user_id = u.id
               LEFT JOIN platform_admins p ON p.user_id = u.id
               WHERE m.id IS NULL AND p.user_id IS NULL""").fetchall()
        conn.close()
        self.assertEqual([r["email"] for r in orphelins], [],
                         "comptes créés puis abandonnés par une acceptation perdante")


if __name__ == "__main__":
    unittest.main()
