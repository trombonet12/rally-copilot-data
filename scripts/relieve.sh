#!/usr/bin/env bash
# Genera relieve-mallorca.pmtiles (Terrarium) y curvas-mallorca.pmtiles (curvas de nivel) a partir del MDT05 del IGN.
#
# Uso: BBOX=2.30,39.26,3.50,39.97 bash scripts/relieve.sh <carpeta-salida>
#
# Requiere (apt en ubuntu-24.04): gdal-bin, python3-gdal, python3-numpy, tippecanoe; y `pmtiles` en el PATH.
#
# Pasos:
#   1. Descarga el MDT05 (cobertura WCS 2.0.1 `Elevacion25830_5`, 5 m, EPSG:25830) en bloques cuadrados de
#      BLOQUE_M metros y los junta en un VRT. Si el WCS no responde, falla (no hay otra fuente).
#   2. Python con GDAL: remuestrea el VRT a EPSG:3857 en la rejilla de teselas de 512 px de z13 (media), sanea los
#      valores invalidos (mar = 0 m) y escribe teselas Terrarium PNG de ZMIN a ZMAX (alturas redondeadas a 0,25 m;
#      las teselas sin tierra no se escriben) en un MBTiles -> `pmtiles convert` -> relieve-mallorca.pmtiles.
#      El remuestreo de cada zoom se hace sobre la altura en coma flotante ANTES de codificar (promediar los bytes
#      RGB de un Terrarium ya codificado daria alturas falsas).
#   3. `gdal_contour -i 10` sobre ese mismo DEM (atributos `ele` entero e `indice` = 1 si es multiplo de 50), sin la
#      curva 0 (duplicaria la costa). Dos teselados con tippecanoe (capa `curvas`): las de 50 m desde z11 y las
#      demas desde z12; `tile-join` los une -> `pmtiles convert` -> curvas-mallorca.pmtiles.
#
# El zoom del relieve (7-13) y las curvas (11-14) deben coincidir con las fuentes de scripts/estilo.mjs.
# Atribucion: MDT05 CC-BY 4.0 scne.es (IGN).
set -euo pipefail

salida="${1:?Uso: relieve.sh <carpeta-salida>}"
: "${BBOX:?Falta BBOX (oeste,sur,este,norte)}"

trabajo="${RELIEVE_TRABAJO:-trabajo/relieve}"
wcs="${WCS_URL:-https://servicios.idee.es/wcs-inspire/mdt}"
cobertura="${WCS_COBERTURA:-Elevacion25830_5}"
bloque_m="${BLOQUE_M:-20000}"
solape_m=25
zmin_relieve=7
zmax_relieve=13
zmin_curvas=11
zmax_curvas=14
zmin_curvas_finas=12
atribucion="MDT05 CC-BY 4.0 scne.es"
# El Python de setup-python no ve python3-gdal: se usa el del sistema.
python_gdal="${PYTHON_GDAL:-/usr/bin/python3}"

fallo() {
  echo "::error::$*"
  exit 1
}

for herramienta in curl awk gdalinfo gdalbuildvrt gdaltransform gdal_contour ogr2ogr tippecanoe tile-join pmtiles; do
  command -v "$herramienta" > /dev/null || fallo "Falta la herramienta $herramienta"
done
"$python_gdal" -I -c 'from osgeo import gdal; import numpy' 2> /dev/null \
  || fallo "$python_gdal no tiene python3-gdal y python3-numpy"

IFS=, read -r oeste sur este norte <<< "$BBOX"
rm -rf "$trabajo"
mkdir -p "$trabajo/bloques" "$salida"
salida_abs="$(cd "$salida" && pwd)"

# --- 1. MDT05 por WCS ---------------------------------------------------------------------------------------------
echo "WCS: $wcs ($cobertura)"
describe="$trabajo/describe.xml"
curl -fsS --retry 3 --retry-delay 5 --connect-timeout 30 --max-time 120 -G "$wcs" \
  --data-urlencode "service=WCS" --data-urlencode "version=2.0.1" --data-urlencode "request=DescribeCoverage" \
  --data-urlencode "coverageId=$cobertura" -o "$describe" \
  || fallo "El WCS del IGN no responde ($wcs). Reintenta mas tarde: no hay otra fuente de elevacion configurada"
grep -q "$cobertura" "$describe" || fallo "El WCS del IGN no describe la cobertura $cobertura: $(head -c 300 "$describe")"

# Etiquetas de los ejes del subconjunto (x/y o E/N segun el servidor). VERIFICAR: si no aparecen, se prueba x y.
etiquetas="$(grep -o 'axisLabels="[^"]*"' "$describe" | head -n 1 | sed 's/^axisLabels="//; s/"$//' || true)"
read -r eje_x eje_y _ <<< "${etiquetas:-x y}"
echo "Ejes del subconjunto: $eje_x $eje_y"

# BBOX (lon/lat) -> recuadro en EPSG:25830 (UTM 30 extendido), con 500 m de margen.
bbox_utm="$(printf '%s %s\n' "$oeste" "$sur" "$este" "$sur" "$oeste" "$norte" "$este" "$norte" \
  | gdaltransform -s_srs '+proj=longlat +datum=WGS84 +no_defs' -t_srs EPSG:25830 -output_xy \
  | awk 'NR == 1 { x0 = x1 = $1; y0 = y1 = $2 }
         { if ($1 < x0) x0 = $1; if ($1 > x1) x1 = $1; if ($2 < y0) y0 = $2; if ($2 > y1) y1 = $2 }
         END { printf "%d %d %d %d\n", x0 - 500, y0 - 500, x1 + 500, y1 + 500 }')"
read -r xmin ymin xmax ymax <<< "$bbox_utm"
echo "Recuadro EPSG:25830: $xmin $ymin $xmax $ymax"
[ "$xmax" -gt "$xmin" ] && [ "$ymax" -gt "$ymin" ] || fallo "Recuadro UTM invalido: $bbox_utm"

n=0
for ((y = ymin; y < ymax; y += bloque_m)); do
  for ((x = xmin; x < xmax; x += bloque_m)); do
    x2=$((x + bloque_m < xmax ? x + bloque_m : xmax))
    y2=$((y + bloque_m < ymax ? y + bloque_m : ymax))
    n=$((n + 1))
    destino="$trabajo/bloques/mdt05_$n.tif"
    echo "Bloque $n: x $x..$x2 y $y..$y2"
    # El formato `image/tiff` es el nativo (no GEOTIFFINT16: redondearia a metros). VERIFICAR: limite de tamano del WCS.
    curl -fsS --retry 3 --retry-delay 10 --retry-all-errors --connect-timeout 30 --max-time 1800 -G "$wcs" \
      --data-urlencode "service=WCS" --data-urlencode "version=2.0.1" --data-urlencode "request=GetCoverage" \
      --data-urlencode "coverageId=$cobertura" --data-urlencode "format=image/tiff" \
      --data-urlencode "subset=${eje_x}($((x - solape_m)),$((x2 + solape_m)))" \
      --data-urlencode "subset=${eje_y}($((y - solape_m)),$((y2 + solape_m)))" -o "$destino" \
      || fallo "El WCS del IGN fallo en el bloque $n (reduce BLOQUE_M si el servidor limita el tamano)"
    gdalinfo "$destino" > /dev/null 2>&1 \
      || fallo "El bloque $n no es un GeoTIFF valido; respuesta del WCS: $(head -c 400 "$destino" | tr '\n' ' ')"
  done
done
echo "Bloques descargados: $n ($(du -sh "$trabajo/bloques" | cut -f1))"
gdalbuildvrt -q "$trabajo/mdt05.vrt" "$trabajo"/bloques/*.tif

# --- 2. Relieve Terrarium -------------------------------------------------------------------------------------------
"$python_gdal" -I - "$trabajo/mdt05.vrt" "$trabajo/dem-z${zmax_relieve}.tif" "$trabajo/relieve.mbtiles" "$BBOX" \
  "$zmin_relieve" "$zmax_relieve" "$atribucion" << 'PY'
import math
import sqlite3
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
vrt, dem_ruta, mbtiles, bbox, zmin, zmax, atribucion = sys.argv[1:8]
zmin, zmax = int(zmin), int(zmax)
oeste, sur, este, norte = (float(v) for v in bbox.split(","))

ORIGEN = 20037508.342789244  # pi * 6378137
TAM = 512
ALTURA_MIN, ALTURA_MAX = -100.0, 2500.0  # fuera de este rango = sin dato (el mar vale 0)


def merc(lon, lat):
    return lon * ORIGEN / 180.0, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137.0


def lado(z):
    return 2 * ORIGEN / (2 ** z)


def rango(z):
    """Teselas (tx0, ty0, tx1, ty1), ambas esquinas incluidas, que cubren el BBOX."""
    t = lado(z)
    x0, y0 = merc(oeste, norte)
    x1, y1 = merc(este, sur)
    return int((x0 + ORIGEN) // t), int((ORIGEN - y0) // t), int((x1 + ORIGEN) // t), int((ORIGEN - y1) // t)


# DEM en coma flotante, EPSG:3857, alineado con la rejilla de teselas de zmax (1 px del DEM = 1 px de tesela).
t = lado(zmax)
px = t / TAM
tx0, ty0, tx1, ty1 = rango(zmax)
limites = (tx0 * t - ORIGEN, ORIGEN - (ty1 + 1) * t, (tx1 + 1) * t - ORIGEN, ORIGEN - ty0 * t)
bruto = dem_ruta + ".bruto.tif"
print(f"DEM z{zmax}: {(tx1 - tx0 + 1) * TAM} x {(ty1 - ty0 + 1) * TAM} px, {px:.3f} m/px (EPSG:3857)", flush=True)
gdal.Warp(
    bruto, vrt,
    options=gdal.WarpOptions(
        format="GTiff", dstSRS="EPSG:3857", outputBounds=limites, xRes=px, yRes=px, resampleAlg="average",
        outputType=gdal.GDT_Float32, multithread=True, warpOptions=["NUM_THREADS=ALL_CPUS"], warpMemoryLimit=1024,
        creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=3", "BIGTIFF=IF_SAFER"],
    ),
)

# Copia saneada: lo que no es una altura valida pasa a 0 y se elimina la declaracion de nodata.
origen = gdal.Open(bruto)
ancho, alto = origen.RasterXSize, origen.RasterYSize
destino = gdal.GetDriverByName("GTiff").Create(
    dem_ruta, ancho, alto, 1, gdal.GDT_Float32,
    options=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=3", "BIGTIFF=IF_SAFER"],
)
destino.SetGeoTransform(origen.GetGeoTransform())
destino.SetProjection(origen.GetProjection())
banda_o, banda_d = origen.GetRasterBand(1), destino.GetRasterBand(1)
maximo = -1e9
invalidos = 0
for fila in range(0, alto, TAM):
    n = min(TAM, alto - fila)
    a = banda_o.ReadAsArray(0, fila, ancho, n).astype(np.float32)
    valido = np.isfinite(a) & (a > ALTURA_MIN) & (a < ALTURA_MAX)
    invalidos += int(a.size - valido.sum())
    a = np.where(valido, a, np.float32(0.0))
    maximo = max(maximo, float(a.max()))
    banda_d.WriteArray(a, 0, fila)
banda_d.FlushCache()
destino = None
origen = None
print(f"DEM saneado: altura maxima {maximo:.1f} m; pixeles sin dato (puestos a 0): {invalidos}", flush=True)
# Sanidad: el Puig Major (1445 m) es el punto mas alto de Mallorca.
if not 1300.0 <= maximo <= 1600.0:
    print(f"::error::Altura maxima {maximo:.1f} m fuera de lo esperable para Mallorca (1300-1600 m)", file=sys.stderr)
    sys.exit(1)

ds = gdal.Open(dem_ruta)
png = gdal.GetDriverByName("PNG")
mem = gdal.GetDriverByName("MEM")

con = sqlite3.connect(mbtiles)
con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
con.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
con.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")


def leer_vsimem(ruta):
    f = gdal.VSIFOpenL(ruta, "rb")
    gdal.VSIFSeekL(f, 0, 2)
    tam = gdal.VSIFTellL(f)
    gdal.VSIFSeekL(f, 0, 0)
    datos = gdal.VSIFReadL(1, tam, f)
    gdal.VSIFCloseL(f)
    return bytes(datos)


def terrarium_png(alt):
    """Altura (m, float64, 512x512) -> PNG RGB Terrarium: (R*256 + G + B/256) - 32768, alturas a 0,25 m."""
    v = np.round(alt * 4.0) / 4.0 + 32768.0
    entero = np.floor(v)
    r = (entero // 256).astype(np.uint8)
    g = (entero % 256).astype(np.uint8)
    b = np.floor((v - entero) * 256.0).astype(np.uint8)
    m = mem.Create("", TAM, TAM, 3, gdal.GDT_Byte)
    for i, canal in enumerate((r, g, b), start=1):
        m.GetRasterBand(i).WriteArray(canal)
    ruta = "/vsimem/tesela.png"
    png.CreateCopy(ruta, m, options=["ZLEVEL=9"]).FlushCache()
    m = None
    datos = leer_vsimem(ruta)
    gdal.Unlink(ruta)
    return datos


total = 0
for z in range(zmin, zmax + 1):
    t = lado(z)
    a0, b0, a1, b1 = rango(z)
    en_zoom = 0
    for ty in range(b0, b1 + 1):
        for tx in range(a0, a1 + 1):
            minx = tx * t - ORIGEN
            maxy = ORIGEN - ty * t
            tesela = gdal.Warp(
                "", ds,
                options=gdal.WarpOptions(
                    format="MEM", outputBounds=(minx, maxy - t, minx + t, maxy), width=TAM, height=TAM,
                    resampleAlg="average", outputType=gdal.GDT_Float32,
                ),
            )
            alt = tesela.GetRasterBand(1).ReadAsArray().astype(np.float64)
            tesela = None
            alt = np.where(np.isfinite(alt) & (alt > ALTURA_MIN) & (alt < ALTURA_MAX), alt, 0.0)
            if alt.max() <= 0.0:
                continue  # mar abierto: sin tesela
            con.execute(
                "INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, tx, (1 << z) - 1 - ty, terrarium_png(alt)))
            en_zoom += 1
    total += en_zoom
    print(f"z{z}: {en_zoom} teselas", flush=True)

if total == 0:
    print("::error::No se ha generado ninguna tesela de relieve", file=sys.stderr)
    sys.exit(1)
for nombre, valor in (
    ("name", "Relieve Mallorca (Terrarium)"), ("format", "png"), ("type", "baselayer"), ("version", "1"),
    ("minzoom", str(zmin)), ("maxzoom", str(zmax)), ("bounds", f"{oeste},{sur},{este},{norte}"),
    ("description", "raster-dem Terrarium: (R*256 + G + B/256) - 32768 m; teselas de 512 px; alturas a 0,25 m"),
    ("attribution", atribucion),
):
    con.execute("INSERT INTO metadata VALUES (?, ?)", (nombre, valor))
con.commit()
con.close()
print(f"relieve: {total} teselas z{zmin}-z{zmax}")
PY

rm -f "$trabajo/dem-z${zmax_relieve}.tif.bruto.tif" "$trabajo/relieve-mallorca.pmtiles"
pmtiles convert "$trabajo/relieve.mbtiles" "$trabajo/relieve-mallorca.pmtiles"
pmtiles show "$trabajo/relieve-mallorca.pmtiles"

# --- 3. Curvas de nivel -----------------------------------------------------------------------------------------------
dem="$trabajo/dem-z${zmax_relieve}.tif"
gdal_contour -q -i 10 -a ele -f GPKG -nln contour "$dem" "$trabajo/curvas.gpkg"

# `ele` entero e `indice` (1 = multiplo de 50). SQL nativo de GeoPackage; la geometria de gdal_contour se llama `geom`.
# VERIFICAR en la primera ejecucion que ogr2ogr conserva la geometria con este SQL.
for tipo in indice fina; do
  if [ "$tipo" = indice ]; then
    condicion="CAST(ROUND(ele) AS INTEGER) % 50 = 0"
    marca=1
  else
    condicion="CAST(ROUND(ele) AS INTEGER) % 50 <> 0"
    marca=0
  fi
  ogr2ogr -f GeoJSONSeq -t_srs EPSG:4326 -lco COORDINATE_PRECISION=6 \
    -sql "SELECT CAST(ROUND(ele) AS INTEGER) AS ele, $marca AS indice, geom FROM contour WHERE ele > 0 AND $condicion" \
    "$trabajo/curvas-$tipo.geojsonl" "$trabajo/curvas.gpkg"
  lineas="$(wc -l < "$trabajo/curvas-$tipo.geojsonl")"
  echo "curvas $tipo: $lineas lineas"
  [ "$lineas" -gt 0 ] || fallo "gdal_contour/ogr2ogr no genero curvas '$tipo'"
done

# Capa `curvas` en las dos: tile-join junta las teselas (a z12-14 las de 10 m se suman a las de 50 m).
# VERIFICAR: que tile-join fusione ambas en una sola capa `curvas` (si no, revisar `source-layer` en estilo.mjs).
tippecanoe -q -f -P -l curvas -Z"$zmin_curvas" -z"$zmax_curvas" --drop-densest-as-needed -A "$atribucion" \
  -o "$trabajo/curvas-indice.mbtiles" "$trabajo/curvas-indice.geojsonl"
tippecanoe -q -f -P -l curvas -Z"$zmin_curvas_finas" -z"$zmax_curvas" --drop-densest-as-needed -A "$atribucion" \
  -o "$trabajo/curvas-fina.mbtiles" "$trabajo/curvas-fina.geojsonl"
tile-join -q -f -o "$trabajo/curvas.mbtiles" "$trabajo/curvas-indice.mbtiles" "$trabajo/curvas-fina.mbtiles"

rm -f "$trabajo/curvas-mallorca.pmtiles"
pmtiles convert "$trabajo/curvas.mbtiles" "$trabajo/curvas-mallorca.pmtiles"
pmtiles show "$trabajo/curvas-mallorca.pmtiles"

# --- Resultado (solo se copia a la carpeta de salida si todo ha ido bien) -------------------------------------------------
[ -s "$trabajo/relieve-mallorca.pmtiles" ] || fallo "relieve-mallorca.pmtiles esta vacio"
[ -s "$trabajo/curvas-mallorca.pmtiles" ] || fallo "curvas-mallorca.pmtiles esta vacio"
cp "$trabajo/relieve-mallorca.pmtiles" "$trabajo/curvas-mallorca.pmtiles" "$salida_abs/"
echo "relieve-mallorca.pmtiles: $(stat -c %s "$salida_abs/relieve-mallorca.pmtiles") bytes"
echo "curvas-mallorca.pmtiles: $(stat -c %s "$salida_abs/curvas-mallorca.pmtiles") bytes"
