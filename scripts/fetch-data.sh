#!/usr/bin/env sh
# Télécharge une copie locale des parcelles cadastrales (Etalab) dans data/.
# Usage : ./scripts/fetch-data.sh [code_insee]   (défaut : 44047, Couëron)
set -eu
INSEE="${1:-44047}"
DEPT="$(printf '%s' "$INSEE" | cut -c1-2)"
DIR="$(cd "$(dirname "$0")/.." && pwd)/data"
URL="https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes/${DEPT}/${INSEE}/cadastre-${INSEE}-parcelles.json.gz"

mkdir -p "$DIR"
echo "Téléchargement de $URL"
curl -fL --retry 3 -o "$DIR/cadastre-${INSEE}-parcelles.json.gz" "$URL"
echo "OK → $DIR/cadastre-${INSEE}-parcelles.json.gz"
