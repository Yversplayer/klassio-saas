"""KLASSIO backend — validation d'entrée.

Trouvé par pentest (session sécurité) : le backend acceptait des montants
négatifs, des chaînes non numériques comme montant, des mots de passe d'un
caractère. Ce module centralise les règles pour ne pas les ré-oublier route
par route.
"""
import re

MAX_TEXT_LENGTH = 200
MIN_PASSWORD_LENGTH = 8


class ValidationError(ValueError):
    pass


def json_object(value):
    """Garantit que le corps de requête est bien un OBJET JSON.

    `request.get_json(force=True)` renvoie ce que le client a envoyé : sur un
    corps `"bonjour"` ou `[1,2]`, c'est une chaîne ou une liste, et le
    `data.get(...)` qui suit lève AttributeError — soit une 500 pour une
    entrée simplement malformée. Vu en conditions réelles sur
    POST /api/invitations pendant l'audit du 14 septembre.

    `or {}` ne suffit pas : une chaîne JSON non vide est vraie.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("Le corps de la requête doit être un objet JSON.")
    return value


def positive_amount(value, field_name="amount"):
    """Refuse tout montant négatif, nul, ou qui n'est pas un nombre réel.
    Trouvé exploitable par pentest : amount=-500 était accepté et confirmé,
    amount="abc" était stocké tel quel et corrompait les agrégats SQL.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} doit être un nombre.")
    if value != value or value in (float("inf"), float("-inf")):  # NaN / infini
        raise ValidationError(f"{field_name} n'est pas un nombre valide.")
    if value <= 0:
        raise ValidationError(f"{field_name} doit être strictement positif.")
    if value > 1_000_000:
        raise ValidationError(f"{field_name} dépasse la limite autorisée (1 000 000).")
    return value


def required_text(value, field_name, max_length=MAX_TEXT_LENGTH):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} est requis.")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"{field_name} dépasse {max_length} caractères.")
    return value


def valid_email(value):
    value = required_text(value, "email", max_length=254).lower()
    if "@" not in value or " " in value or value.startswith("@") or value.endswith("@"):
        raise ValidationError("Adresse email invalide.")
    return value


def valid_password(value):
    """Règles réelles, vérifiées côté serveur — jamais seulement côté client
    (docs/SECURITE.md) : 8 caractères minimum, une majuscule, une minuscule,
    un chiffre, un caractère spécial."""
    if not isinstance(value, str):
        raise ValidationError("Mot de passe invalide.")
    missing = []
    if len(value) < MIN_PASSWORD_LENGTH:
        missing.append(f"{MIN_PASSWORD_LENGTH} caractères minimum")
    if not re.search(r"[A-Z]", value):
        missing.append("une majuscule")
    if not re.search(r"[a-z]", value):
        missing.append("une minuscule")
    if not re.search(r"[0-9]", value):
        missing.append("un chiffre")
    if not re.search(r"[^A-Za-z0-9]", value):
        missing.append("un caractère spécial")
    if missing:
        raise ValidationError("Le mot de passe doit contenir : " + ", ".join(missing) + ".")
    return value


PAYMENT_METHODS = {"cash", "bank", "mobile_money", "card"}


def valid_payment_method(value):
    if value not in PAYMENT_METHODS:
        raise ValidationError(f"Méthode de paiement inconnue : {value}")
    return value


def valid_phone(value):
    """Numéro de téléphone normalisé en E.164. Accepte les saisies courantes
    en RDC (« 0971 83 92 37 », « +243 971 839 237 », « 243971839237 ») et
    tout numéro international commençant par +. Retourne None si vide."""
    if value is None:
        return None
    digits = re.sub(r"[^\d+]", "", str(value))
    if not digits:
        return None
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "+243" + digits[1:]
    elif digits.startswith("243") and len(digits) == 12:
        digits = "+" + digits
    elif not digits.startswith("+") and 9 <= len(digits) <= 10:
        digits = "+243" + digits.lstrip("0")
    if not re.match(r"^\+\d{9,15}$", digits):
        raise ValidationError("Numéro de téléphone invalide — format attendu : +243xxxxxxxxx.")
    return digits


def valid_hex_color(value):
    if value in (None, ""):
        return None
    value = str(value).strip()
    if not re.match(r"^#[0-9A-Fa-f]{6}$", value):
        raise ValidationError("Couleur invalide — format attendu : #RRGGBB.")
    return value.upper()


# ---------------------------------------------------------------------------
# Images transmises en « data URI »
# ---------------------------------------------------------------------------

# Trouvé et exploité pendant l'audit de production : la validation se limitait à
# `valeur.startswith("data:image/")` et à une longueur maximale. La chaîne
#
#     data:image/png;base64,PAS_UNE_IMAGE" onerror="…" x="
#
# passait donc sans obstacle. Le frontend l'insérait ensuite telle quelle dans
# `<img src="…">` : le guillemet refermait l'attribut et le reste devenait de
# vrais attributs HTML — un gestionnaire `onerror` a bien été injecté dans le
# DOM, vérifié dans un navigateur. Seule la Content-Security-Policy des pages
# a empêché son exécution. Une seule page servie sans CSP, ou un navigateur qui
# ne l'applique pas, et c'était un XSS stocké complet.
#
# La forme d'une image en data URI est parfaitement connue : on l'impose, au
# lieu de vérifier seulement son début. Aucun guillemet, aucune espace, aucun
# chevron ne peut plus survivre à cette expression.
DATA_URI_IMAGE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$")

# Le SVG est volontairement absent : un SVG peut contenir du script, et il
# s'exécute quand le navigateur l'affiche depuis une même origine.


def image_data_uri(value, field_name="image", max_length=400_000):
    """Valide une image en data URI, ou lève. Renvoie None pour une valeur vide."""
    if value in (None, "", False):
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} doit être une image.")
    if len(value) > max_length:
        raise ValidationError(f"{field_name} dépasse la taille autorisée.")
    if not DATA_URI_IMAGE.match(value):
        raise ValidationError(
            f"{field_name} doit être une image PNG, JPEG, GIF ou WebP encodée en base64.")
    return value


# Documents et pièces jointes : PDF en plus des images. Même raison d'être que
# DATA_URI_IMAGE — ces valeurs finissent dans un `<iframe src="…">` ou un
# `<embed src="…">` côté navigateur, donc aucun guillemet ne doit pouvoir y
# survivre.
DATA_URI_FICHIER = re.compile(
    r"^data:(image/(png|jpeg|jpg|gif|webp)|application/pdf);base64,[A-Za-z0-9+/]+={0,2}$")


def file_data_uri(value, field_name="fichier", max_length=3_000_000):
    """Valide un PDF ou une image en data URI, ou lève. None si vide."""
    if value in (None, "", False):
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} doit être un fichier PDF ou une image.")
    if len(value) > max_length:
        raise ValidationError(
            f"{field_name} dépasse la taille autorisée ({max_length // 1_000_000} Mo).")
    if not DATA_URI_FICHIER.match(value):
        raise ValidationError(
            f"{field_name} doit être un PDF ou une image (PNG, JPEG, GIF, WebP) encodé en base64.")
    return value
