#!/usr/bin/env bash
# Klassio — installe tout ce qu'il faut pour TESTER, en une commande.
#
#   ./installer.sh             environnement Python, dépendances, configuration,
#                              base de démonstration (école fictive, 300 élèves)
#   ./installer.sh --recreer   idem, en reconstruisant la base de démonstration
#
# Ensuite :  ./demarrer.sh --testeur   puis   http://localhost:5001
#
# Rien ne demande une clé, un compte ou un accès à la production. Les outils de
# démonstration refusent toute base PostgreSQL distante : ce script ne peut
# toucher que des données fictives, sur cette machine.
set -euo pipefail
cd "$(dirname "$0")"

RECREER=""
for arg in "$@"; do
  case "$arg" in
    --recreer) RECREER="--recreer" ;;
    *) echo "Option inconnue : $arg (option : --recreer)"; exit 1 ;;
  esac
done

etape() { echo ""; echo "▸ $1"; }

etape "Python"
PY=""
for candidat in python3 python; do
  if command -v "$candidat" >/dev/null 2>&1 && "$candidat" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$candidat"; break
  fi
done
if [ -z "$PY" ]; then
  echo "✗ Python 3.9 ou plus récent est nécessaire. Installez-le depuis https://www.python.org/downloads/ puis relancez."
  exit 1
fi
echo "  $("$PY" --version)"

etape "Environnement isolé (backend_venv)"
if [ ! -x backend_venv/bin/python ]; then
  "$PY" -m venv backend_venv
  echo "  créé"
else
  echo "  déjà présent"
fi
VPY="backend_venv/bin/python"

etape "Dépendances (application + outils de test)"
"$VPY" -m pip install -q --disable-pip-version-check -r requirements-dev.txt
echo "  installées"

etape "Configuration"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "  backend/.env créé depuis le modèle — il n'y a rien à remplir"
else
  echo "  backend/.env déjà présent — conservé"
fi

etape "Base de démonstration"
if [ -n "$RECREER" ] || [ ! -f backend/klassio_demo.db ]; then
  "$VPY" backend/tools/demo.py $RECREER
else
  echo "  backend/klassio_demo.db existe déjà — conservée (./installer.sh --recreer pour la reconstruire)"
fi

echo ""
echo "✓ Klassio est installé."
echo ""
echo "  Lancer :   ./demarrer.sh --testeur"
echo "  Ouvrir :   http://localhost:5001          (le site)"
echo "             http://localhost:5001/app/connexion.html"
echo "  Tests :    $VPY -m unittest discover -s backend/tests -t backend"
echo "             $VPY backend/tools/pg_tests.py"
echo ""
echo "  Comptes et parcours de test : README.md, « Tester Klassio de fond en comble »."
