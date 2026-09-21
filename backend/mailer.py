"""KLASSIO — le canal e-mail : un fournisseur, des gabarits, et un mode capture.

Ce module répond à UNE question : comment un message quitte le serveur.
Il ne décide ni QUI doit être prévenu (c'est `notifications.py`, qui résout les
destinataires côté serveur depuis les liens réels parent↔élève), ni QUAND
réessayer (c'est `deliveries.py`). Il ne connaît qu'une adresse et un texte.

TROIS MODES, parce qu'on ne teste pas un envoi comme on l'exploite :

  EMAIL_MODE=capture     (défaut)  rien ne part. Le message est rendu en entier
                                   et rendu à l'appelant, qui l'enregistre.
                                   C'est le mode du développement et des tests :
                                   impossible d'expédier 400 vrais e-mails par
                                   accident en rejouant un script.
  EMAIL_MODE=production            le fournisseur configuré est réellement appelé.
  EMAIL_MODE=fail                  simule une panne fournisseur. Sert aux tests
                                   d'échec et de retry, sans débrancher le vrai.

AUCUN SECRET N'EST ÉCRIT ICI. La clé vient de l'environnement, n'est jamais
journalisée, jamais renvoyée dans une réponse d'API, jamais stockée en base.
"""
import json
import os
import re
import urllib.error
import urllib.request

import config

TIMEOUT = 15

MODE = (config.get("EMAIL_MODE", "capture") or "capture").strip().lower()
PROVIDER = (config.get("EMAIL_PROVIDER", "brevo") or "brevo").strip().lower()
API_KEY = config.get("EMAIL_API_KEY", "") or ""
FROM_ADDRESS = config.get("EMAIL_FROM", "") or "no-reply@klassio.local"
FROM_NAME = config.get("EMAIL_FROM_NAME", "") or "Klassio"

# Adresse publique du frontend, pour fabriquer les liens des messages. En
# développement le site statique tourne sur 4173 ; en production c'est le
# domaine réel. Sans cette valeur les liens pointeraient vers localhost dans
# un e-mail reçu sur un téléphone — c'est-à-dire nulle part.
APP_BASE_URL = (config.get("KLASSIO_APP_URL", "") or "http://localhost:4173").rstrip("/")


class EmailError(Exception):
    """Échec d'envoi. `code` distingue le temporaire du définitif : seul le
    premier justifie un nouvel essai."""

    def __init__(self, message, code="provider_error", retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# ---------------------------------------------------------------------------
# Adresses
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def adresse_utilisable(email):
    """Peut-on réellement écrire à cette adresse ?

    Deux cas mènent à un envoi perdu d'avance :

    1. une adresse mal formée ;
    2. une adresse TECHNIQUE. Klassio autorise la création d'un compte avec un
       numéro de téléphone seul ; la colonne `email` étant NOT NULL, il reçoit
       alors `tel+243…@klassio.invalid`. Ce domaine n'existe pas — le message
       rebondirait, et le fournisseur pénalise la réputation de l'expéditeur
       pour chaque rebond. On refuse donc AVANT d'appeler qui que ce soit.
    """
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if not _EMAIL_RE.match(email):
        return False
    if email.endswith("@klassio.invalid"):
        return False
    return True


# ---------------------------------------------------------------------------
# Fournisseur
# ---------------------------------------------------------------------------

def _envoyer_brevo(destinataire, sujet, html, texte):
    """Brevo (ex-Sendinblue), en HTTP direct.

    Choisi après inspection du projet : `requirements.txt` est volontairement
    court (« seuls les paquets réellement importés »), et `supabase_client.py`
    montre que la maison écrit ses clients HTTP à la main plutôt que d'ajouter
    un SDK. Brevo s'appelle en un POST JSON — aucune dépendance nouvelle. Son
    palier gratuit est le plus large des fournisseurs comparables, ce qui
    compte quand une école inscrit 400 familles en quelques jours.

    Changer de fournisseur, c'est écrire une seconde fonction comme celle-ci.
    """
    if not API_KEY:
        raise EmailError("EMAIL_API_KEY absente.", code="config_missing", retryable=False)
    corps = json.dumps({
        "sender": {"email": FROM_ADDRESS, "name": FROM_NAME},
        "to": [{"email": destinataire}],
        "subject": sujet,
        "htmlContent": html,
        "textContent": texte,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email", data=corps,
        headers={"Content-Type": "application/json", "accept": "application/json",
                 "api-key": API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            reponse = json.loads(r.read().decode("utf-8") or "{}")
            return reponse.get("messageId") or ""
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        # 4xx = la demande est fautive, la rejouer donnerait le même résultat.
        # 429 et 5xx = le fournisseur est débordé ou en panne : on réessaiera.
        rejouable = e.code == 429 or e.code >= 500
        raise EmailError(f"HTTP {e.code} — {detail}", code=f"http_{e.code}", retryable=rejouable)
    except urllib.error.URLError as e:
        raise EmailError(f"Réseau : {e.reason}", code="network", retryable=True)


FOURNISSEURS = {"brevo": _envoyer_brevo}


def envoyer(destinataire, sujet, html, texte):
    """Tente un envoi. Retourne (identifiant_fournisseur, nom_du_fournisseur).

    Lève EmailError sinon. Ne journalise jamais la clé d'API ni le contenu du
    message : un journal de production se lit à plusieurs, les messages
    contiennent des noms d'élèves.
    """
    if not adresse_utilisable(destinataire):
        raise EmailError("Adresse inutilisable.", code="invalid_address", retryable=False)

    if MODE == "fail":
        raise EmailError("Panne simulée (EMAIL_MODE=fail).", code="simulated", retryable=True)
    if MODE != "production":
        # Mode capture : on ne contacte personne. L'appelant enregistre quand
        # même une livraison, avec son statut et son contenu — ce qui rend le
        # parcours entier testable sans compte fournisseur.
        return ("capture-" + str(abs(hash((destinataire, sujet))))[:16], "capture")

    fonction = FOURNISSEURS.get(PROVIDER)
    if fonction is None:
        raise EmailError(f"EMAIL_PROVIDER « {PROVIDER} » inconnu.",
                         code="config_unknown_provider", retryable=False)
    return (fonction(destinataire, sujet, html, texte) or "", PROVIDER)


# ---------------------------------------------------------------------------
# Gabarits
# ---------------------------------------------------------------------------
#
# RÈGLE QUI GOUVERNE TOUS LES MESSAGES : l'e-mail informe et ramène vers
# Klassio. Il ne transporte pas la donnée.
#
# Une boîte mail se consulte sur un téléphone prêté, se transfère, se laisse
# ouverte. Les notes d'un élève, sa situation disciplinaire et le détail de ce
# que sa famille doit à l'école n'y ont pas leur place : dans Klassio, ces
# informations sont derrière une authentification et un périmètre de rôle ;
# dans un e-mail, elles ne sont derrière rien. Le message dit donc « c'est
# disponible », jamais « voici ».
#
# Le sujet est encore plus exposé que le corps : il s'affiche sur l'écran
# verrouillé. Aucun montant, aucune note, aucun nom d'élève n'y figure.

_STYLES = {
    "corps": "margin:0;padding:24px 12px;background:#f4f4f1;"
             "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;",
    "carte": "max-width:520px;margin:0 auto;background:#ffffff;border-radius:14px;"
             "padding:32px 28px;border:1px solid #e6e6e0;",
    "titre": "margin:0 0 16px;font-size:20px;line-height:1.3;color:#1a1a17;font-weight:700;",
    "texte": "margin:0 0 16px;font-size:15px;line-height:1.6;color:#3d3d38;",
    "bouton": "display:inline-block;background:#1a1a17;color:#ffffff;text-decoration:none;"
              "padding:13px 26px;border-radius:9px;font-size:15px;font-weight:600;",
    "secours": "margin:20px 0 0;font-size:12.5px;line-height:1.5;color:#6b6b63;word-break:break-all;",
    "pied": "margin:24px 0 0;padding-top:18px;border-top:1px solid #ecece7;"
            "font-size:12px;line-height:1.5;color:#8a8a80;",
}


def _echapper(v):
    return (str(v or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _page(titre, paragraphes, bouton_libelle, bouton_url, note_securite, etablissement):
    """Rend un message complet. Toujours un bouton ET le lien en clair : sur un
    téléphone d'entrée de gamme ou dans un client mail qui bloque le HTML, un
    bouton qui ne s'affiche pas rend le message inutilisable."""
    corps_html = "".join(
        f'<p style="{_STYLES["texte"]}">{p}</p>' for p in paragraphes)
    ecole = _echapper(etablissement) if etablissement else ""
    entete = f'<p style="{_STYLES["texte"]}font-weight:600;color:#1a1a17;">{ecole}</p>' if ecole else ""
    secu = f'<p style="{_STYLES["secours"]}">{note_securite}</p>' if note_securite else ""
    html = f"""<!doctype html><html lang="fr"><body style="{_STYLES['corps']}">
<div style="{_STYLES['carte']}">
{entete}<h1 style="{_STYLES['titre']}">{_echapper(titre)}</h1>
{corps_html}
<p style="margin:24px 0 0;"><a href="{_echapper(bouton_url)}" style="{_STYLES['bouton']}">{_echapper(bouton_libelle)}</a></p>
<p style="{_STYLES['secours']}">Si le bouton ne fonctionne pas, copiez ce lien&nbsp;:<br>{_echapper(bouton_url)}</p>
{secu}
<p style="{_STYLES['pied']}">Klassio — la clarté derrière chaque établissement.<br>
Ce message est automatique, il est inutile d'y répondre.</p>
</div></body></html>"""
    lignes = [titre, ""]
    if ecole:
        lignes = [etablissement, "", titre, ""]
    lignes += [re.sub(r"<[^>]+>", "", p) for p in paragraphes]
    lignes += ["", bouton_libelle + " : " + bouton_url]
    if note_securite:
        lignes += ["", re.sub(r"<[^>]+>", "", note_securite)]
    lignes += ["", "Klassio — ce message est automatique."]
    return html, "\n".join(lignes)


ROLE_LIBELLE = {"parent": "parent", "professeur": "enseignant", "discipline": "directeur des disciplines"}


def gabarit_invitation(role, nom_destinataire, etablissement, lien):
    """Invitation. Le sujet ne nomme ni l'élève ni le rôle : il s'affiche sur
    un écran verrouillé, potentiellement devant quelqu'un d'autre."""
    qualite = ROLE_LIBELLE.get(role, "membre")
    bonjour = f"Bonjour {_echapper(nom_destinataire)}," if nom_destinataire else "Bonjour,"
    titre = ("Votre espace enseignant Klassio" if role == "professeur"
             else "Votre invitation à rejoindre Klassio")
    html, texte = _page(
        titre,
        [bonjour,
         f"<strong>{_echapper(etablissement)}</strong> vous invite à rejoindre son espace "
         f"Klassio en tant que <strong>{qualite}</strong>.",
         "Ce lien vous permet de créer votre compte. Il est personnel et ne peut servir qu'une fois."],
        "Créer mon compte", lien,
        "Vous n'attendiez pas cette invitation&nbsp;? Ignorez ce message : sans action de votre part, "
        "aucun compte n'est créé.",
        etablissement)
    return titre, html, texte


def gabarit_reinitialisation(nom_destinataire, etablissement, lien, duree_heures):
    bonjour = f"Bonjour {_echapper(nom_destinataire)}," if nom_destinataire else "Bonjour,"
    titre = "Réinitialisation de votre mot de passe Klassio"
    html, texte = _page(
        titre,
        [bonjour,
         "Vous avez demandé à choisir un nouveau mot de passe pour votre espace Klassio.",
         f"Ce lien est valable {duree_heures} heure(s) et ne peut servir qu'une fois."],
        "Choisir un nouveau mot de passe", lien,
        "Vous n'avez rien demandé&nbsp;? Ignorez ce message : votre mot de passe actuel reste valable "
        "et personne n'a accès à votre compte.",
        etablissement)
    return titre, html, texte


def gabarit_resultats(nom_destinataire, prenom_eleve, etablissement, lien, periode=None):
    """Résultats disponibles. AUCUNE note dans le message — ni moyenne, ni
    rang, ni appréciation. L'e-mail annonce la disponibilité, Klassio montre
    le contenu à qui a le droit de le voir."""
    bonjour = f"Bonjour {_echapper(nom_destinataire)}," if nom_destinataire else "Bonjour,"
    quand = f" pour la {_echapper(periode)}" if periode else ""
    titre = "Les résultats sont disponibles"
    html, texte = _page(
        titre,
        [bonjour,
         f"Les résultats scolaires de <strong>{_echapper(prenom_eleve)}</strong>{quand} sont "
         "maintenant disponibles dans votre espace Klassio.",
         "Connectez-vous pour les consulter."],
        "Consulter les résultats", lien, None, etablissement)
    return titre, html, texte


GABARITS = {
    "invitation": gabarit_invitation,
    "password_reset": gabarit_reinitialisation,
    "results_published": gabarit_resultats,
}
