# La suite de tests est un TESTEUR du code : depuis qu'il n'existe plus de mode
# gratuit (01/10/2026), une école fraîchement créée est fermée jusqu'au choix
# de son offre et à la confirmation de son premier paiement. Les dix-neuf
# modules qui créent une école pour éprouver AUTRE CHOSE (présences, notes,
# isolation…) travaillent donc avec l'abonnement contourné — exactement comme
# un développeur avec KLASSIO_CONTOURNER_ABONNEMENT=1.
#
# La règle elle-même n'échappe pas aux tests : test_abonnement.py et le cycle
# de vie de test_lots.py remettent config.CONTOURNER_ABONNEMENT à False et
# vérifient l'espace fermé, l'offre obligatoire, la confirmation.
import os

os.environ.setdefault("KLASSIO_CONTOURNER_ABONNEMENT", "1")

# Depuis le 06/10/2026, la session du navigateur voyage dans un cookie
# HttpOnly (security.py). Le client de test de Flask GARDE les cookies : après
# une inscription, il les présenterait à chaque requête suivante, et les
# vingt tests « sans session » — écrits pour vérifier qu'une requête SANS
# AUCUN identifiant est refusée — auraient été authentifiés à leur insu.
# Leur intention reste juste ; c'est le client qui a changé. Par défaut, le
# client de test n'envoie donc aucun cookie, et ces suites éprouvent l'API
# telle qu'elles l'ont toujours éprouvée (Authorization: Bearer).
# Le comportement des cookies — HttpOnly, SameSite, CSRF, révocation — est
# éprouvé par test_session_cookie.py, qui les réactive explicitement
# (`test_client(use_cookies=True)`).
import flask  # noqa: E402

_test_client_flask = flask.Flask.test_client


def _test_client_sans_cookies(self, use_cookies=False, **kwargs):
    return _test_client_flask(self, use_cookies=use_cookies, **kwargs)


flask.Flask.test_client = _test_client_sans_cookies
