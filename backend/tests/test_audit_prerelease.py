"""KLASSIO — trois défauts trouvés par l'audit pré-release, figés ici.

Chacun est reproduit avant d'être corrigé, et chacun échouait sans son
correctif. Ils n'ont rien en commun sinon leur mode de découverte : aucun ne
se voit en lisant le code, seulement en le faisant tourner dans les conditions
qui comptent — concurrence, fichier abîmé, panne de base.

1. CONCURRENCE. `confirm_payment` lisait le statut puis écrivait sans
   condition. Deux confirmations simultanées du même paiement — double clic
   de la caissière, ou webhook rejoué par l'opérateur Mobile Money, ce que
   tout fournisseur fait en cas de doute — produisaient DEUX écritures au
   grand livre et DEUX notifications au parent. Mesuré avant correctif :
   8 tours anormaux sur 40.

2. FICHIER ABÎMÉ. Un CSV renommé en .xlsx (réflexe courant) ou un
   téléchargement interrompu faisaient remonter une BadZipFile jusqu'au
   gestionnaire générique : « Erreur interne du serveur » (500) pour une
   entrée simplement invalide.

3. SONDE DE SANTÉ. `/api/health` répondait « ok » sans rien interroger. Avec
   la base injoignable, elle aurait continué à dire que tout va bien.
"""
import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

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


class Base(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()
        security.reset_rate_limits_for_tests()

    def ecole(self, suffixe):
        r = self.c.post("/api/auth/register-school", json={
            "email": f"dir.{suffixe}@test.local", "password": "Secret123!",
            "name": "Directeur", "school_name": f"École {suffixe}"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        h = {"Authorization": f"Bearer {r.get_json()['token']}"}
        an = self.c.get("/api/academic-years", headers=h).get_json()[0]["id"]
        return h, an


class DoubleConfirmationDePaiement(Base):
    def _paiement_en_attente(self, h, an, cle):
        cls = self.c.post("/api/classes", json={
            "name": "6e A", "academic_year_id": an, "cycle": "secondaire"}, headers=h).get_json()["id"]
        eleve = self.c.post("/api/students", json={
            "first_name": "Audrey", "last_name": "Mukendi",
            "academic_year_id": an, "class_id": cls}, headers=h).get_json()["id"]
        article = self.c.post("/api/catalog-items", json={
            "name": "Frais", "category": "scolarite", "amount": 100, "currency": "USD"},
            headers=h).get_json()["id"]
        obligation = self.c.post("/api/obligations", json={
            "student_id": eleve, "catalog_item_id": article,
            "amount": 100, "academic_year_id": an}, headers=h).get_json()["id"]
        # mobile_money reste CREATED : c'est le cas où la confirmation compte
        # vraiment. Un paiement cash est confirmé dès son enregistrement.
        return self.c.post("/api/payments", json={
            "obligation_id": obligation, "amount": 100, "method": "mobile_money",
            "idempotency_key": cle}, headers=h).get_json()["id"]

    # Une course ne se déclenche pas à tous les coups. Mesurée avant correctif,
    # la fenêtre s'ouvrait 8 fois sur 40 : un test à UN seul tour laissait donc
    # passer le défaut quatre fois sur cinq — vérifié, il passait au vert avec
    # le correctif neutralisé.
    #
    # 20 tours portent la détection à environ 99 %. Le test ne peut pas échouer
    # à tort : avec le correctif, le résultat est déterministe (jamais de
    # doublon), donc aucune exécution ne devient intermittente.
    TOURS = 20

    def test_01_un_seul_credit_une_seule_notification(self):
        h, an = self.ecole("paiement")
        anomalies = []

        for tour in range(self.TOURS):
            paiement = self._paiement_en_attente(h, an, f"course-{tour}")
            barriere = threading.Barrier(2)
            codes = {}

            def confirmer(n):
                client = flask_app_module.app.test_client()
                barriere.wait()
                codes[n] = client.post(f"/api/payments/{paiement}/confirm",
                                       json={"provider_reference": f"ref-{n}"}, headers=h).status_code

            fils = [threading.Thread(target=confirmer, args=(i,)) for i in (1, 2)]
            for f in fils:
                f.start()
            for f in fils:
                f.join()

            conn = db.get_connection()
            ecritures = conn.execute(
                "SELECT COUNT(*) n FROM ledger_entries WHERE reference_id=?", (paiement,)).fetchone()["n"]
            evenements = conn.execute(
                "SELECT COUNT(*) n FROM events WHERE entity_id=? AND event_type='payment.confirmed'",
                (paiement,)).fetchone()["n"]
            recus = conn.execute(
                "SELECT COUNT(*) n FROM receipts WHERE payment_id=?", (paiement,)).fetchone()["n"]
            conn.close()

            if (ecritures, evenements, recus) != (1, 1, 1):
                anomalies.append(
                    f"tour {tour} : {ecritures} écriture(s) au grand livre, "
                    f"{evenements} événement(s) — le parent serait notifié {evenements} fois, "
                    f"{recus} reçu(s)")
            self.assertEqual(sorted(codes.values()), [200, 200],
                             f"les deux appels doivent aboutir (idempotence), obtenu : {codes}")

        self.assertEqual(
            anomalies, [],
            f"{len(anomalies)} double(s) confirmation(s) sur {self.TOURS} ont crédité deux fois "
            f"le même paiement :\n  " + "\n  ".join(anomalies))

    def test_02_confirmer_dix_fois_de_suite_ne_credite_quune_fois(self):
        """Le rejeu séquentiel — un webhook réémis toutes les minutes."""
        h, an = self.ecole("rejeu")
        paiement = self._paiement_en_attente(h, an, "rejeu-1")
        for _ in range(10):
            r = self.c.post(f"/api/payments/{paiement}/confirm", json={}, headers=h)
            self.assertEqual(r.status_code, 200)
        conn = db.get_connection()
        n = conn.execute("SELECT COUNT(*) n FROM ledger_entries WHERE reference_id=?", (paiement,)).fetchone()["n"]
        conn.close()
        self.assertEqual(n, 1, f"10 confirmations ont produit {n} écritures")


class FichiersDImportAbimes(Base):
    def _envoyer(self, h, nom, contenu):
        return self.c.post("/api/onboarding/analyze-import",
                           data={"file": (io.BytesIO(contenu), nom)},
                           content_type="multipart/form-data", headers=h)

    def test_03_un_fichier_abime_est_refuse_proprement_jamais_en_500(self):
        h, _ = self.ecole("import")
        cas = [
            ("CSV renommé en .xlsx", "eleves.xlsx", b"Nom,Prenom,Classe\nMukendi,Audrey,6e A\n"),
            ("xlsx tronqué", "abime.xlsx", b"PK\x03\x04ceci-nest-pas-une-archive"),
            ("xlsx vide", "vide.xlsx", b""),
        ]
        for libelle, nom, contenu in cas:
            with self.subTest(cas=libelle):
                r = self._envoyer(h, nom, contenu)
                self.assertEqual(r.status_code, 400,
                                 f"{libelle} → {r.status_code} (attendu 400) : {r.get_data(as_text=True)[:120]}")
                message = (r.get_json() or {}).get("error", "")
                self.assertNotIn("interne", message.lower(),
                                 "le message doit désigner le fichier, pas une panne du serveur")

    def test_04_un_csv_valide_passe_toujours(self):
        """Un garde-fou qui refuse tout ne garde rien : le chemin normal doit
        rester ouvert."""
        h, _ = self.ecole("importok")
        r = self._envoyer(h, "eleves.csv", b"Nom,Prenom,Classe\nMukendi,Audrey,6e A\nKalala,Kevin,6e B\n")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.assertEqual(r.get_json()["students_count"], 2)


class SondeDeSante(unittest.TestCase):
    def setUp(self):
        self.c = flask_app_module.app.test_client()

    def test_05_la_sonde_interroge_vraiment_la_base(self):
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        corps = r.get_json()
        self.assertEqual(corps["status"], "ok")
        self.assertEqual(corps["database"], "ok")
        self.assertIn("database_latency_ms", corps,
                      "sans mesure, rien ne prouve que la base a été interrogée")

    def test_06_la_sonde_sait_echouer(self):
        """Une sonde qui ne peut pas échouer ne surveille rien."""
        vrai = db.get_connection
        flask_app_module.app.logger.disabled = True
        try:
            db.get_connection = lambda: (_ for _ in ()).throw(RuntimeError("base injoignable"))
            r = self.c.get("/api/health")
        finally:
            db.get_connection = vrai
            flask_app_module.app.logger.disabled = False
        self.assertEqual(r.status_code, 503,
                         "base injoignable : la sonde doit répondre 503, pas 200")
        self.assertEqual(r.get_json()["status"], "degraded")
        # Une sonde est publique : elle ne raconte pas la panne.
        self.assertNotIn("injoignable", r.get_data(as_text=True).replace("unreachable", ""))


if __name__ == "__main__":
    unittest.main()
