#!/usr/bin/env bash
# Klassio — montée en charge progressive, un palier après l'autre.
#
#   tools/k6/paliers.sh [DUREE_PLATEAU_SECONDES]
#
# On ne cherche pas ici à « passer » : on cherche l'endroit où ça casse, et on
# note à quel prix. Chaque palier rejoue EXACTEMENT le même scénario métier
# (charge.js, la matinée d'école) avec de plus en plus d'utilisateurs, et on
# relève les mêmes chiffres : p50, p90, p95, p99, taux d'erreur, débit.
#
# À lancer UNIQUEMENT contre le serveur local sur base jetable (port 5010).
# Jamais contre une base de travail, jamais contre la production.
set -u

K6=${K6:-/Users/macbookpro/.local/bin/k6}
RACINE="$(cd "$(dirname "$0")/../.." && pwd)"
SORTIE="$RACINE/tools/k6/resultats"
DUREE=${1:-45}
PALIERS=${PALIERS:-"1 5 10 25 50 100"}

mkdir -p "$SORTIE"
echo "Montée en charge — paliers : $PALIERS (plateau ${DUREE}s chacun)"
echo

for n in $PALIERS; do
  echo "── palier ${n} VUs ──"
  "$K6" run -e PALIER="$n" -e DUREE="$DUREE" \
    --summary-trend-stats="med,p(90),p(95),p(99),max" \
    --summary-export="$SORTIE/palier-${n}.json" \
    "$RACINE/tools/k6/charge.js" > "$SORTIE/palier-${n}.txt" 2>&1
  code=$?
  # Un seuil dépassé (code 99) n'interrompt PAS le balayage : c'est précisément
  # l'information qu'on vient chercher. On le note et on continue.
  echo "   code de sortie k6 : $code  (0 = tous seuils tenus, 99 = seuil dépassé)"
done

echo
echo "Récapitulatif :"
"$RACINE/backend_venv/bin/python" "$RACINE/tools/k6/paliers_tableau.py" "$SORTIE" $PALIERS
