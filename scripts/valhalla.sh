#!/usr/bin/env bash
# Genera valhalla-mallorca.tar (teselas de enrutado Valhalla) a partir del PBF recortado de Mallorca.
#
# Uso: VALHALLA_IMAGE=ghcr.io/valhalla/valhalla:3.9.1@sha256:<digest> bash scripts/valhalla.sh <mallorca.osm.pbf> <carpeta-salida>
#
# - Solo ejecuta la imagen oficial de Valhalla en Docker (sin `pip install` ni nada en el runner).
# - Version: debe coincidir con la que lleva valhalla-mobile (0.6.4 -> submodulo Valhalla 3.9.1).
# - Pasos: valhalla_build_config -> valhalla_build_admins -> valhalla_build_tiles -> valhalla_build_extract.
# - Sin base de zonas horarias (valhalla_build_timezones descarga datos de internet y solo sirve para el
#   enrutado dependiente del tiempo, que la app no usa).
# - La base de administraciones (admin.sqlite) se construye con el mismo PBF. Si fallara, se avisa y se
#   generan las teselas sin ella (Valhalla lo tolera: "Admin db not found. Not saving admin information").
# - Solo coche: sin redes de bici ni peaton (la app solo enruta en coche; teselas mas pequenas).
# - La app construye su propia configuracion (ValhallaConfigFactory.usingTileExtract); no se publica JSON.
set -euo pipefail

pbf="${1:?Uso: valhalla.sh <mallorca.osm.pbf> <carpeta-salida>}"
salida="${2:?Uso: valhalla.sh <mallorca.osm.pbf> <carpeta-salida>}"
: "${VALHALLA_IMAGE:?Falta VALHALLA_IMAGE}"
trabajo="${VALHALLA_TRABAJO:-trabajo/valhalla}"
nombre_pbf="$(basename "$pbf")"
nombre_tar="valhalla-mallorca.tar"

[ -f "$pbf" ] || { echo "::error::No existe $pbf"; exit 1; }

# Carpeta de trabajo limpia (los ficheros los crea el usuario del runner, no root).
rm -rf "$trabajo"
mkdir -p "$trabajo" "$salida"
entrada_abs="$(cd "$(dirname "$pbf")" && pwd)"
trabajo_abs="$(cd "$trabajo" && pwd)"
salida_abs="$(cd "$salida" && pwd)"

vh() {
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$entrada_abs:/in:ro" -v "$trabajo_abs:/work" \
    "$VALHALLA_IMAGE" "$@"
}

echo "Imagen: $VALHALLA_IMAGE"
vh valhalla_build_config \
  --mjolnir-tile-dir /work/tiles \
  --mjolnir-tile-extract "/work/$nombre_tar" \
  --mjolnir-admin /work/admin.sqlite \
  --mjolnir-timezone /work/tz_world.sqlite \
  --output /work/valhalla.json

if vh valhalla_build_admins -c /work/valhalla.json "/in/$nombre_pbf" && [ -s "$trabajo_abs/admin.sqlite" ]; then
  echo "Base de administraciones: $(stat -c %s "$trabajo_abs/admin.sqlite") bytes"
else
  rm -f "$trabajo_abs/admin.sqlite"
  echo "::warning::valhalla_build_admins no genero admin.sqlite: teselas sin informacion de administraciones"
fi

vh valhalla_build_tiles -c /work/valhalla.json "/in/$nombre_pbf"
vh valhalla_build_extract -c /work/valhalla.json --overwrite -v

tar_generado="$trabajo_abs/$nombre_tar"
[ -s "$tar_generado" ] || { echo "::error::valhalla_build_extract no genero $nombre_tar"; exit 1; }

# Comprobaciones: el tar de extraccion debe llevar index.bin y al menos una tesela .gph.
tar -tf "$tar_generado" > "$trabajo_abs/contenido.txt"
grep -qx 'index.bin' "$trabajo_abs/contenido.txt" || { echo "::error::$nombre_tar no contiene index.bin"; exit 1; }
teselas="$(grep -c '\.gph$' "$trabajo_abs/contenido.txt" || true)"
[ "$teselas" -gt 0 ] || { echo "::error::$nombre_tar no contiene teselas .gph"; exit 1; }

cp "$tar_generado" "$salida_abs/$nombre_tar"
echo "$nombre_tar: $teselas teselas, $(stat -c %s "$salida_abs/$nombre_tar") bytes"
