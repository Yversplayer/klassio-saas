"""KLASSIO — le pont entre le produit et l'appareil de l'utilisateur.

Jusqu'au 21/09, `notifications.py` se terminait sur un INSERT : Klassio savait
qu'un parent devait être informé, jamais si le message lui était parvenu. Ces
tests éprouvent la couche ajoutée — et surtout ses refus.
"""
import os
import sys
import time
import unittest

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, BACKEND)

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "klassio_comm_test.db")
os.environ["KLASSIO_DB_PATH"] = TEST_DB

import db  # noqa: E402
db.DB_PATH = os.path.abspath(TEST_DB)

import app as flask_app_module  # noqa: E402
import security  # noqa: E402
import mailer  # noqa: E402
import deliveries as deliveries_module  # noqa: E402


def setUpModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def tearDownModule():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)


class Base(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()
        mailer.MODE = "capture"

    def ecole(self, suffixe, email=None):
        courriel = email or f"dir.{suffixe}@comm.test"
        r = self.c.post("/api/auth/register-school", json={
            "email": courriel, "password": "Secret123!",
            "name": "Directeur Comm", "school_name": f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        d = r.get_json()
        self.tenant_id = d["tenant_id"]
        return {"Authorization": f"Bearer {d['token']}"}, d, courriel

    def invitation(self, h, role="professeur"):
        return self.c.post("/api/invitations", json={"role": role}, headers=h).get_json()

    def livraisons(self, tenant_id=None):
        """Les livraisons de CET établissement seulement.

        La base est partagée par tout le module : sans ce filtre, un test lit
        les livraisons des tests précédents et échoue pour une raison qui ne
        le concerne pas.
        """
        conn = db.get_connection()
        rows = conn.execute("SELECT * FROM deliveries WHERE tenant_id=? ORDER BY created_at",
                            (tenant_id or self.tenant_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class EnvoiDInvitation(Base):
    def test_01_un_envoi_reussi_est_trace_comme_ACCEPTED_pas_DELIVERED(self):
        """Le fournisseur a pris la demande. Il ne l'a pas encore remise.

        La nuance n'est pas cosmétique : afficher « remis » quand on ne sait
        pas conduit l'école à croire qu'un parent a été prévenu alors que le
        message est peut-être dans les indésirables, ou rejeté silencieusement.
        """
        h, _, _ = self.ecole("envoi01")
        inv = self.invitation(h)
        r = self.c.post("/api/invitations/send", json={
            "token": inv["token"], "email": "prof01@exemple.test", "name": "Prof"}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertEqual(corps["status"], "ACCEPTED")
        self.assertNotEqual(corps["status"], "DELIVERED")

        liv = self.livraisons()
        self.assertEqual(len(liv), 1)
        self.assertEqual(liv[0]["channel"], "EMAIL")
        self.assertEqual(liv[0]["template"], "invitation")
        self.assertEqual(liv[0]["attempts"], 1)
        self.assertTrue(liv[0]["sent_at"])
        self.assertIsNone(liv[0]["failed_at"])

    def test_02_le_double_clic_ne_produit_pas_deux_messages(self):
        """Une Direction pressée clique deux fois. Le parent ne doit pas
        recevoir deux fois la même invitation."""
        h, _, _ = self.ecole("envoi02")
        inv = self.invitation(h)
        envoi = lambda: self.c.post("/api/invitations/send", json={
            "token": inv["token"], "email": "prof02@exemple.test"}, headers=h)
        a, b = envoi(), envoi()
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.get_json()["delivery_id"], b.get_json()["delivery_id"],
                         "deux livraisons distinctes ont été créées pour un double clic")
        self.assertEqual(len(self.livraisons()), 1)
        # LE POINT QUI COMPTE VRAIMENT. Retomber sur la même ligne ne suffit
        # pas : il faut aussi que le fournisseur n'ait pas été rappelé. Sans
        # cette assertion, le test passait alors que le destinataire recevait
        # deux messages — vérifié le 21/09 sur le serveur réel.
        self.assertEqual(self.livraisons()[0]["attempts"], 1,
                         "le message a été réexpédié : le destinataire en reçoit deux")

    def test_03_une_panne_fournisseur_n_affiche_jamais_envoye(self):
        """Le faux succès est le défaut le plus coûteux d'un tel système :
        l'école croit avoir prévenu, personne n'a rien reçu, et rien ne le
        signale."""
        h, _, _ = self.ecole("envoi03")
        inv = self.invitation(h)
        mailer.MODE = "fail"
        try:
            r = self.c.post("/api/invitations/send", json={
                "token": inv["token"], "email": "prof03@exemple.test"}, headers=h)
        finally:
            mailer.MODE = "capture"
        self.assertEqual(r.status_code, 502, "un échec d'envoi ne doit pas répondre 200")
        corps = r.get_json()
        self.assertEqual(corps["status"], "FAILED")
        self.assertTrue(corps["error"])
        self.assertTrue(corps["retryable"], "une panne temporaire doit rester rejouable")

        liv = self.livraisons()[0]
        self.assertEqual(liv["status"], "FAILED")
        self.assertTrue(liv["failed_at"])
        self.assertIsNone(liv["sent_at"])
        self.assertEqual(liv["error_code"], "simulated")

    def test_04_une_adresse_technique_est_refusee_avant_tout_envoi(self):
        """Un compte créé au téléphone seul porte `tel+…@klassio.invalid`.
        Écrire à ce domaine ferait rebondir le message et abîmerait la
        réputation de l'expéditeur — pour rien."""
        h, _, _ = self.ecole("envoi04")
        inv = self.invitation(h)
        r = self.c.post("/api/invitations/send", json={
            "token": inv["token"], "email": "tel+243900000000@klassio.invalid"}, headers=h)
        self.assertIn(r.status_code, (400, 422))
        self.assertEqual(len(self.livraisons()), 0, "une livraison a été créée pour une adresse morte")

    def test_05_le_jeton_d_une_autre_ecole_ne_donne_rien(self):
        """L'isolation ne se déduit pas de la possession du jeton."""
        h_a, _, _ = self.ecole("envoi05a")
        h_b, _, _ = self.ecole("envoi05b")
        inv_a = self.invitation(h_a)
        r = self.c.post("/api/invitations/send", json={
            "token": inv_a["token"], "email": "intrus@exemple.test"}, headers=h_b)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(self.livraisons()), 0)

    def test_06_une_invitation_revoquee_ne_s_envoie_plus(self):
        h, _, _ = self.ecole("envoi06")
        inv = self.invitation(h)
        self.assertEqual(self.c.post(f"/api/invitations/{inv['id']}/revoke",
                                     json={}, headers=h).status_code, 200)
        r = self.c.post("/api/invitations/send", json={
            "token": inv["token"], "email": "prof06@exemple.test"}, headers=h)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(self.livraisons()), 0)


class LienWhatsApp(Base):
    def test_10_le_lien_contient_numero_message_et_invitation(self):
        h, _, _ = self.ecole("wa10")
        inv = self.invitation(h, role="parent") if False else self.invitation(h)
        r = self.c.post("/api/invitations/whatsapp", json={
            "token": inv["token"], "phone": "+243900111222", "name": "Jean"}, headers=h)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        corps = r.get_json()
        self.assertIn("243900111222", corps["whatsapp_url"])
        self.assertIn("Jean", corps["message"])
        self.assertIn(inv["token"], corps["message"])

    def test_11_whatsapp_ne_pretend_jamais_avoir_envoye(self):
        """Klassio ouvre WhatsApp, il n'envoie pas. Le statut doit le dire."""
        h, _, _ = self.ecole("wa11")
        inv = self.invitation(h)
        corps = self.c.post("/api/invitations/whatsapp", json={
            "token": inv["token"], "phone": "+243900111333"}, headers=h).get_json()
        self.assertEqual(corps["status"], "PREPARED")
        self.assertNotIn(corps["status"], ("SENT", "ACCEPTED", "DELIVERED"))
        liv = [l for l in self.livraisons() if l["channel"] == "WHATSAPP_LINK"]
        self.assertEqual(liv[0]["status"], "CREATED")
        self.assertIsNone(liv[0]["sent_at"], "un lien préparé n'a pas de date d'envoi")


class MotDePasseOublie(Base):
    def test_20_la_reponse_est_identique_que_le_compte_existe_ou_non(self):
        """Sinon le formulaire devient un annuaire : on y teste des adresses
        jusqu'à savoir qui est client de l'école."""
        _, _, courriel = self.ecole("oubli20")
        security.reset_rate_limits_for_tests()
        connu = self.c.post("/api/auth/forgot-password", json={"email": courriel})
        security.reset_rate_limits_for_tests()
        inconnu = self.c.post("/api/auth/forgot-password", json={"email": "personne@nulle-part.test"})
        self.assertEqual(connu.status_code, inconnu.status_code)
        self.assertEqual(connu.get_json(), inconnu.get_json(),
                         "la réponse diffère selon que le compte existe — énumération possible")

    def test_21_un_compte_reel_recoit_un_lien_utilisable(self):
        _, _, courriel = self.ecole("oubli21")
        r = self.c.post("/api/auth/forgot-password", json={"email": courriel})
        self.assertEqual(r.status_code, 200)
        liv = [l for l in self.livraisons() if l["template"] == "password_reset"]
        self.assertEqual(len(liv), 1)
        self.assertEqual(liv[0]["status"], "ACCEPTED")
        self.assertEqual(liv[0]["recipient_address"], courriel)

        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM password_resets WHERE used_at IS NULL AND tenant_id=?",
                         (self.tenant_id,)).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 1, "aucun jeton de réinitialisation n'a été créé")

    def test_22_le_jeton_n_est_jamais_stocke_en_clair(self):
        _, _, courriel = self.ecole("oubli22")
        self.c.post("/api/auth/forgot-password", json={"email": courriel})
        conn = db.get_connection()
        row = conn.execute("SELECT token_hash FROM password_resets WHERE tenant_id=? "
                           "ORDER BY created_at DESC LIMIT 1", (self.tenant_id,)).fetchone()
        conn.close()
        self.assertEqual(len(row["token_hash"]), 64, "ce n'est pas une empreinte SHA-256")

    def test_23_cinq_demandes_d_affilee_ne_font_pas_cinq_messages(self):
        """Un utilisateur qui s'impatiente clique plusieurs fois."""
        _, _, courriel = self.ecole("oubli23")
        for _ in range(5):
            self.c.post("/api/auth/forgot-password", json={"email": courriel})
        liv = [l for l in self.livraisons() if l["template"] == "password_reset"]
        self.assertEqual(len(liv), 1, f"{len(liv)} messages pour cinq clics")

    def test_24_un_compte_sans_acces_actif_ne_recoit_rien(self):
        """Un accès révoqué ne se réactive pas par le formulaire d'oubli."""
        _, _, courriel = self.ecole("oubli24")
        conn = db.get_connection()
        conn.execute("UPDATE memberships SET status='revoked'")
        conn.commit(); conn.close()
        r = self.c.post("/api/auth/forgot-password", json={"email": courriel})
        self.assertEqual(r.status_code, 200, "la réponse doit rester identique")
        self.assertEqual([l for l in self.livraisons() if l["template"] == "password_reset"], [])


class ContenuDesMessages(Base):
    def test_30_aucun_resultat_ni_montant_dans_un_message(self):
        """Une boîte mail se consulte sur un téléphone prêté et se transfère.
        L'e-mail annonce, Klassio montre."""
        sujet, html, texte = mailer.gabarit_resultats(
            "Mme Kabeya", "Jean", "École Test", "https://ex.test/app/", "Période 2")
        for interdit in ("14/20", "moyenne", "rang", "$", "USD"):
            self.assertNotIn(interdit.lower(), texte.lower(),
                             f"« {interdit} » ne doit pas voyager par e-mail")
        self.assertNotIn("Jean", sujet, "le sujet s'affiche sur un écran verrouillé")

    def test_31_le_lien_de_secours_est_toujours_en_clair(self):
        """Un client mail qui bloque le HTML rendrait le bouton invisible."""
        sujet, html, texte = mailer.gabarit_invitation(
            "parent", "Jean", "École Test", "https://ex.test/app/invitation.html?token=XYZ")
        self.assertIn("https://ex.test/app/invitation.html?token=XYZ", texte)
        self.assertIn("https://ex.test/app/invitation.html?token=XYZ", html)

    def test_32_aucune_cle_d_api_ne_fuit_dans_une_livraison(self):
        h, _, _ = self.ecole("fuite32")
        inv = self.invitation(h)
        mailer.API_KEY = "cle-secrete-a-ne-jamais-voir"
        mailer.MODE = "fail"
        try:
            self.c.post("/api/invitations/send", json={
                "token": inv["token"], "email": "x@exemple.test"}, headers=h)
        finally:
            mailer.MODE = "capture"; mailer.API_KEY = ""
        for l in self.livraisons():
            self.assertNotIn("cle-secrete", (l["error_message"] or ""))
            self.assertNotIn("cle-secrete", (l["subject"] or ""))


if __name__ == "__main__":
    unittest.main()
