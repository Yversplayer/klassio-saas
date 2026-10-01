#!/usr/bin/env bash
# Klassio — démarre le logiciel en une commande.
#
#   ./demarrer.sh              n'écoute que sur cette machine
#   ./demarrer.sh --reseau     écoute aussi sur le réseau local
#   ./demarrer.sh --testeur    abonnement contourné : un espace créé s'ouvre
#                              sans paiement (KLASSIO_CONTOURNER_ABONNEMENT=1).
#                              Pour TESTER le code — refusé sur une base distante.
#   Les deux options se combinent : ./demarrer.sh --reseau --testeur
#
# UN SEUL SERVEUR. Le backend Flask sert désormais lui-même les pages et les
# ressources (backend/app.py, routes `/` et `/<path:chemin>`).
#
# Ce script lançait auparavant un second serveur de fichiers sur le port 4173.
# Ce montage ne marchait qu'en local, et le 29/09 il a fait échouer un testeur
# sur trois murs à la fois, sans message utile :
#   - le CORS du backend n'autorise que localhost:4173 en développement ;
#   - la CSP de chaque page n'autorise `connect-src` que vers localhost:5001 ;
#   - depuis une autre machine, les appels `/api/...` partaient vers le serveur
#     de fichiers, qui n'a pas d'API — d'où le 404, ou le 504 derrière un proxy.
# Une seule origine supprime les trois d'un coup : plus rien à autoriser.
#
# Ctrl-C arrête le serveur.

set -euo pipefail
cd "$(dirname "$0")"

PY="backend_venv/bin/python"
[ -x "$PY" ] || PY="python3"

API_PORT=5001
HOTE="127.0.0.1"
RESEAU=0
TESTEUR=0
for arg in "$@"; do
  case "$arg" in
    --reseau) HOTE="0.0.0.0"; RESEAU=1 ;;
    --testeur) TESTEUR=1 ;;
    *) echo "Option inconnue : $arg (options : --reseau, --testeur)"; exit 1 ;;
  esac
done
if [ "$TESTEUR" = "1" ]; then
  export KLASSIO_CONTOURNER_ABONNEMENT=1
  echo "⚠  Mode testeur : l'abonnement est contourné, les espaces s'ouvrent sans paiement."
fi

port_occupe() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

if port_occupe "$API_PORT"; then
  echo "✗ Le port $API_PORT est déjà utilisé. Arrêtez le processus qui l'occupe :"
  echo "    lsof -nP -iTCP:$API_PORT -sTCP:LISTEN"
  exit 1
fi

pid=""
deja_arrete=0

nettoyer() {
  [ "$deja_arrete" = "1" ] && return 0
  deja_arrete=1
  echo ""
  echo "Arrêt…"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  # Laisser une seconde au serveur pour se fermer, puis insister.
  sleep 1
  [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  echo "Arrêté."
}

# Deux pièges vérifiés sur cette machine :
#
# 1. Un gestionnaire de signal qui ne sort PAS laisse le script repartir dans
#    son attente : Ctrl-C nettoyait puis le script restait vivant, serveur
#    compris. Le gestionnaire d'interruption doit donc se terminer par `exit`.
# 2. `wait` sans argument n'est pas réveillé de façon fiable par un signal
#    piégé ici. On attend donc par une boucle de veille, que le signal
#    interrompt réellement.
interrompre() { nettoyer; exit 130; }
trap nettoyer EXIT
trap interrompre INT TERM HUP

echo "→ Klassio sur http://localhost:$API_PORT"
KLASSIO_HOST="$HOTE" "$PY" backend/app.py >/tmp/klassio.log 2>&1 &
pid=$!

# On n'annonce « prêt » qu'après une réponse réelle de l'API — jamais sur une
# simple temporisation. Si elle ne répond pas, on le dit et on montre le log.
echo -n "Attente du serveur"
for _ in $(seq 1 40); do
  if curl -fsS "http://localhost:$API_PORT/api/health" >/dev/null 2>&1; then
    echo " — prêt."
    echo ""
    echo "  Klassio est lancé :"
    echo "    Site      http://localhost:$API_PORT"
    echo "    Connexion http://localhost:$API_PORT/app/connexion.html"
    echo "    Démo      http://localhost:$API_PORT/demo.html"
    if [ "$RESEAU" = "1" ]; then
      ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
      echo ""
      if [ -n "$ip" ]; then
        echo "  Depuis une autre machine du MÊME réseau Wi-Fi :"
        echo "    http://$ip:$API_PORT"
      else
        echo "  ⚠ Aucune adresse réseau détectée sur en0/en1."
      fi
      echo "  ⚠ Le serveur est joignable par le réseau local. La base servie est"
      echo "    backend/klassio.db, une base de DÉVELOPPEMENT. N'exposez jamais"
      echo "    ainsi une base contenant de vraies données d'établissement."
    fi
    echo ""
    echo "  Journal : /tmp/klassio.log"
    echo "  Ctrl-C pour arrêter."
    echo ""
    # Veille interruptible : tant que le serveur vit, on dort par tranches
    # d'une seconde. Un Ctrl-C tombe pendant un `sleep`, que le signal
    # interrompt pour de bon.
    while :; do
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "✗ Le serveur s'est arrêté de lui-même. Voir /tmp/klassio.log."
        exit 1
      fi
      sleep 1
    done
  fi
  sleep 0.5
  echo -n "."
done

echo ""
echo "✗ Le serveur n'a pas répondu sur http://localhost:$API_PORT/api/health."
echo "  Dernières lignes de /tmp/klassio.log :"
tail -20 /tmp/klassio.log || true
exit 1
