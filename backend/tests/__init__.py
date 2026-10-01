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
