#!/usr/bin/env bash
# Klassio — démarre le logiciel en une commande.
#
#   ./demarrer.sh
#
# Deux serveurs sont nécessaires et doivent tourner ensemble :
#   - l'API Flask sur 5001 ;
#   - les pages statiques sur 4173.
#
# Le port 4173 n'est pas un détail de confort : le CORS du backend
# (backend/app.py, ALLOWED_ORIGINS) n'autorise que cette origine en
# développement. Servir les pages depuis un autre port fait échouer tous les
# appels API dans le navigateur, sans message clair.
#
# Ctrl-C arrête les deux.

set -euo pipefail
cd "$(dirname "$0")"

PY="backend_venv/bin/python"
[ -x "$PY" ] || PY="python3"

API_PORT=5001
WEB_PORT=4173

port_occupe() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

for p in "$API_PORT" "$WEB_PORT"; do
  if port_occupe "$p"; then
    echo "✗ Le port $p est déjà utilisé. Arrêtez le processus qui l'occupe :"
    echo "    lsof -nP -iTCP:$p -sTCP:LISTEN"
    exit 1
  fi
done

pids=()
deja_arrete=0

nettoyer() {
  [ "$deja_arrete" = "1" ] && return 0
  deja_arrete=1
  echo ""
  echo "Arrêt…"
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  # Laisser une seconde aux serveurs pour se fermer, puis insister.
  sleep 1
  for pid in "${pids[@]:-}"; do kill -9 "$pid" 2>/dev/null || true; done
  echo "Arrêté."
}

# Deux pièges vérifiés sur cette machine :
#
# 1. Un gestionnaire de signal qui ne sort PAS laisse le script repartir dans
#    son `wait` : Ctrl-C nettoyait puis le script restait vivant, serveurs
#    compris. Le gestionnaire d'interruption doit donc se terminer par `exit`.
# 2. `wait` sans argument n'est pas réveillé de façon fiable par un signal
#    piégé ici. On attend donc par une boucle de veille, que le signal
#    interrompt réellement.
interrompre() { nettoyer; exit 130; }
trap nettoyer EXIT
trap interrompre INT TERM HUP

echo "→ API Flask sur http://localhost:$API_PORT"
"$PY" backend/app.py >/tmp/klassio-api.log 2>&1 &
pids+=($!)

echo "→ Pages sur http://localhost:$WEB_PORT"
python3 -m http.server "$WEB_PORT" >/tmp/klassio-web.log 2>&1 &
pids+=($!)

# On n'annonce « prêt » qu'après une réponse réelle de l'API — jamais sur une
# simple temporisation. Si elle ne répond pas, on le dit et on montre le log.
echo -n "Attente de l'API"
for _ in $(seq 1 40); do
  if curl -fsS "http://localhost:$API_PORT/api/health" >/dev/null 2>&1; then
    echo " — prête."
    echo ""
    echo "  Klassio est lancé :"
    echo "    Site      http://localhost:$WEB_PORT"
    echo "    Connexion http://localhost:$WEB_PORT/app/connexion.html"
    echo "    Démo      http://localhost:$WEB_PORT/demo.html"
    echo ""
    echo "  Journaux : /tmp/klassio-api.log  /tmp/klassio-web.log"
    echo "  Ctrl-C pour arrêter les deux serveurs."
    echo ""
    # Veille interruptible : tant que les deux serveurs vivent, on dort par
    # tranches d'une seconde. Un Ctrl-C tombe pendant un `sleep`, que le
    # signal interrompt pour de bon.
    while :; do
      for pid in "${pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
          echo "✗ Un serveur s'est arrêté de lui-même. Voir /tmp/klassio-api.log."
          exit 1
        fi
      done
      sleep 1
    done
  fi
  sleep 0.5
  echo -n "."
done

echo ""
echo "✗ L'API n'a pas répondu sur http://localhost:$API_PORT/api/health."
echo "  Dernières lignes de /tmp/klassio-api.log :"
tail -20 /tmp/klassio-api.log || true
exit 1
