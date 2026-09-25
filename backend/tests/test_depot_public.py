"""KLASSIO — ce que le dépôt PUBLIC ne doit jamais transporter.

Pourquoi ce fichier existe.

Le dépôt `Yversplayer/klassio-saas` est public, et son lien circule entre
programmeurs. Un secret poussé une seule fois y reste pour toujours : effacé au
commit suivant, il demeure dans l'historique et dans chaque copie déjà clonée.
La seule réparation est de le RÉVOQUER — changer la clé, le mot de passe — pas
de le supprimer.

Le 25/09, une revue de l'historique complet (34 commits) n'a trouvé aucune clé
d'API, aucune base, aucun vrai mot de passe. Elle a trouvé 163 jetons de
session en clair : k6 recopie dans ses exports ce que renvoie `setup()`, donc
les en-têtes `Authorization: Bearer …` des comptes de test. Ils ne valaient rien
— bases jetables, serveur local, produit jamais déployé — mais personne ne
l'avait vu, et le jour où la campagne serait rejouée contre un vrai serveur, ce
seraient des sessions vivantes, lisibles par tous.

Ce test ne suppose rien de ce qu'on POURRAIT oublier. Il relit chaque fichier
suivi par git, à chaque exécution de la suite.

Il ne lit que l'INDEX git (`git ls-files`) : un fichier local ignoré — la base
de développement, un `.env` — est hors de son champ, et c'est voulu. Hors d'un
dépôt git (le miroir du Bureau n'a pas de `.git`), il s'abstient.
"""
import os
import re
import subprocess
import unittest

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# 1. Des NOMS de fichiers qui ne doivent jamais être suivis.
# ---------------------------------------------------------------------------
CHEMINS_INTERDITS = [
    # Bases : `klassio.db` contient des élèves mineurs nommés, leurs
    # responsables, des paiements et des empreintes de mots de passe.
    (re.compile(r"\.(db|sqlite3?)$|\.db-(wal|shm)$|klassio\.db\.avant-"), "base de données"),
    (re.compile(r"(^|/)exports_store/"), "export généré par l'application"),
    # Configuration réelle. Seul le MODÈLE `.env.example` a le droit d'exister.
    (re.compile(r"(^|/)\.env$|(^|/)[^/]*\.env$"), "fichier d'environnement"),
    (re.compile(r"\.(pem|key|p12|pfx)$|(^|/)id_(rsa|ed25519|ecdsa)$"), "clé privée ou certificat"),
]

# ---------------------------------------------------------------------------
# 2. Des CONTENUS qui trahissent un secret.
# ---------------------------------------------------------------------------
SECRETS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "clé Anthropic"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "clé OpenAI"),
    (re.compile(r"xkeysib-[a-f0-9]{20,}"), "clé Brevo (fournisseur d'e-mail de Klassio)"),
    (re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"), "clé SendGrid"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "clé AWS"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"), "jeton GitHub"),
    # Les clés Supabase (anon, service_role) sont des JWT.
    (re.compile(r"\beyJhbGciOi[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."), "JWT — clé Supabase ?"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "clé privée"),
    # Un jeton de session Klassio fait 43 caractères base64url.
    (re.compile(r"Bearer [A-Za-z0-9_-]{24,}"), "jeton de session en clair"),
]

# Une URL PostgreSQL n'est un secret que si son mot de passe en est un. Les
# exemples de la documentation (`MOT_DE_PASSE`, `…`) et les gabarits
# (`{encode}`) sont légitimes : on ne refuse que ce qui ressemble à une vraie
# valeur.
URL_POSTGRES = re.compile(r"postgres(?:ql)?://[^:@/\s]+:([^@/\s]+)@")
MOT_DE_PASSE_FACTICE = re.compile(r"^[A-Z_]+$|[{}<>…*$]")

EXTENSIONS_BINAIRES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".xlsx", ".xls",
    ".woff", ".woff2", ".ttf", ".otf", ".zip", ".gz",
}


def _fichiers_suivis():
    try:
        sortie = subprocess.run(
            ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [c for c in sortie.decode("utf-8").split("\0") if c]


def secrets_dans(texte):
    """Chaque (nature, extrait) suspect trouvé dans un texte."""
    trouves = [(nature, m.group(0)[:48]) for motif, nature in SECRETS for m in motif.finditer(texte)]
    for m in URL_POSTGRES.finditer(texte):
        if not MOT_DE_PASSE_FACTICE.search(m.group(1)):
            trouves.append(("URL PostgreSQL avec mot de passe", m.group(0)[:48]))
    return trouves


def chemin_interdit(chemin):
    if chemin.endswith(".env.example"):
        return None
    for motif, nature in CHEMINS_INTERDITS:
        if motif.search(chemin):
            return nature
    return None


class DepotPublicTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fichiers = _fichiers_suivis()

    def setUp(self):
        if self.fichiers is None:
            self.skipTest("pas de dépôt git ici (le miroir du Bureau n'en a pas)")

    def test_01_aucun_fichier_interdit_n_est_suivi(self):
        fautifs = [f"  {c}  ({n})" for c in self.fichiers if (n := chemin_interdit(c))]
        self.assertEqual(
            fautifs, [],
            "Des fichiers qui ne doivent JAMAIS être publiés sont suivis par git.\n"
            "Retirez-les de l'index (`git rm --cached`), ajoutez-les au .gitignore, et\n"
            "s'ils ont déjà été poussés, considérez leur contenu comme compromis.\n\n"
            + "\n".join(fautifs),
        )

    def test_02_aucun_secret_dans_un_fichier_suivi(self):
        fautifs = []
        for chemin in self.fichiers:
            if os.path.splitext(chemin)[1].lower() in EXTENSIONS_BINAIRES:
                continue
            complet = os.path.join(RACINE, chemin)
            if not os.path.isfile(complet):
                continue
            with open(complet, encoding="utf-8", errors="ignore") as f:
                texte = f.read()
            for nature, extrait in secrets_dans(texte):
                fautifs.append(f"  {chemin}  —  {nature}  —  {extrait}…")
        self.assertEqual(
            fautifs, [],
            "Un secret est présent dans un fichier suivi par git — donc publié au\n"
            "prochain push, et lisible pour toujours dans l'historique.\n"
            "S'il a déjà été poussé : RÉVOQUEZ-LE d'abord, nettoyez ensuite.\n\n"
            + "\n".join(fautifs),
        )

    def test_03_aucun_export_k6_ne_garde_setup_data(self):
        """`setup_data` porte les jetons des comptes connectés par setup()."""
        fautifs = []
        for chemin in self.fichiers:
            if chemin.startswith("tools/k6/resultats/") and chemin.endswith(".json"):
                with open(os.path.join(RACINE, chemin), encoding="utf-8") as f:
                    if '"setup_data"' in f.read():
                        fautifs.append(f"  {chemin}")
        self.assertEqual(
            fautifs, [],
            "Des exports k6 versionnés gardent `setup_data`, donc des jetons de\n"
            "session. Nettoyez-les : python tools/k6/nettoyer_export.py <fichiers>\n\n"
            + "\n".join(fautifs),
        )

    def test_04_le_modele_de_configuration_ne_contient_aucune_valeur_secrete(self):
        """`.env.example` est public par nature : ses clés sensibles restent vides."""
        chemin = os.path.join(RACINE, "backend", ".env.example")
        if not os.path.exists(chemin):
            self.skipTest("pas de .env.example")
        sensibles = re.compile(r"(KEY|SECRET|PASSWORD|TOKEN|DB_URL)$")
        remplies = []
        with open(chemin, encoding="utf-8") as f:
            for n, ligne in enumerate(f, 1):
                ligne = ligne.strip()
                if not ligne or ligne.startswith("#") or "=" not in ligne:
                    continue
                cle, valeur = ligne.split("=", 1)
                if sensibles.search(cle.strip()) and valeur.strip():
                    remplies.append(f"  ligne {n} : {cle.strip()} n'est pas vide")
        self.assertEqual(remplies, [], "Le modèle de configuration public porte une valeur sensible.\n" + "\n".join(remplies))


class LeGardeFouSaitReconnaitreTests(unittest.TestCase):
    """Un garde-fou qu'on n'a jamais vu se déclencher ne garde rien."""

    def test_10_il_reconnait_chaque_famille_de_secret(self):
        # Assemblés à l'exécution : écrits en clair ici, ces faux secrets feraient
        # échouer test_02 sur ce fichier même.
        echantillons = {
            "clé Anthropic": "sk-" + "ant-" + "a" * 30,
            "clé Brevo (fournisseur d'e-mail de Klassio)": "xkey" + "sib-" + "0" * 32,
            "JWT — clé Supabase ?": "eyJhbG" + "ciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.abc",
            "jeton de session en clair": "Bear" + "er 6fvykQao0xauptnj4hP66AtljLFZjnMIqf",
            "URL PostgreSQL avec mot de passe": "postgresql://postgres" + ":Vr4iM0tDeP4sse@hote:5432/db",
        }
        for nature, texte in echantillons.items():
            self.assertIn(nature, [n for n, _ in secrets_dans(texte)], f"non reconnu : {nature}")

    def test_11_il_laisse_passer_les_exemples_legitimes(self):
        legitimes = [
            "postgresql://postgres.abcdefgh:MOT_DE_PASSE@aws-1-eu-west-1.pooler.supabase.com:5432/postgres",
            'uri = f"postgresql://{parsed.username}:{encode}@{parsed.hostname}"',
            "(postgresql://postgres:…@…pooler.supabase.com:6543/postgres)",
            "headers: { Authorization: `Bearer ${token}` }",
            '"password": "Secret123!"',
        ]
        for texte in legitimes:
            self.assertEqual(secrets_dans(texte), [], f"faux positif sur : {texte}")

    def test_12_il_reconnait_les_chemins_interdits(self):
        for chemin in ("backend/klassio.db", "backend/klassio.db.avant-remise-a-zero-2026",
                       "backend/.env", "prod.env", "backend/exports_store/a.xlsx", "deploy/id_rsa"):
            self.assertIsNotNone(chemin_interdit(chemin), f"chemin non refusé : {chemin}")
        for chemin in ("backend/.env.example", "backend/db.py", "docs/exemples/export.xlsx"):
            self.assertIsNone(chemin_interdit(chemin), f"chemin refusé à tort : {chemin}")


if __name__ == "__main__":
    unittest.main()
