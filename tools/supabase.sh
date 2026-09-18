#!/usr/bin/env bash
# KLASSIO — lance les outils Supabase avec un interpréteur qui a le bon pilote.
#
#   bash tools/supabase.sh mot-de-passe   enregistre le mot de passe de la base
#   bash tools/supabase.sh verifier       teste la connexion Postgres
#   bash tools/supabase.sh etat           état de la configuration Supabase
#
# Fonctionne depuis n'importe quel dossier, y compris la copie du Bureau :
# la configuration et les outils restent ceux du projet principal.
set -u

PROJET_PRINCIPAL="/Users/macbookpro/klassio-saas"
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Interpréteur : le venv du projet principal s'il existe, sinon python3 du système.
PY="$PROJET_PRINCIPAL/backend_venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
if [ -z "${PY:-}" ]; then
  echo "Aucun interpréteur Python trouvé." >&2
  exit 1
fi

# Les outils et le fichier .env vivent dans le projet principal quand il existe :
# un seul endroit pour le mot de passe, pas deux copies qui divergent.
RACINE="$ICI"
[ -f "$PROJET_PRINCIPAL/backend/tools/pg_check.py" ] && RACINE="$PROJET_PRINCIPAL"

case "${1:-verifier}" in
  mot-de-passe|password|mdp) OUTIL="set_db_password.py" ;;
  verifier|check|test)       OUTIL="pg_check.py" ;;
  etat|status|supabase)      OUTIL="supabase_check.py" ;;
  *) echo "Usage : bash tools/supabase.sh [mot-de-passe|verifier|etat]" >&2; exit 2 ;;
esac

echo "Interpréteur : $PY"
echo "Projet       : $RACINE"
echo
exec "$PY" "$RACINE/backend/tools/$OUTIL"
