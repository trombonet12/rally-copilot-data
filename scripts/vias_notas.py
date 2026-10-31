"""Datos de carretera para el motor de notas de rally: etiquetas de OSM y perfil de altura de cada vía.

Dos subcomandos (los imports de osmium y GDAL van dentro de cada uno: las pruebas se ejecutan sin ellos):

  python -I scripts/vias_notas.py etiquetas mallorca.osm.pbf etiquetas.tsv                       (pyosmium)
  /usr/bin/python3 -I scripts/vias_notas.py perfil vias-mallorca.tsv.gz mdt05.vrt etiquetas.tsv \
      vias-notas-mallorca.tsv.gz                                                                 (python3-gdal)

Formato de `vias-notas-mallorca.tsv.gz` (v1), UTF-8, campos separados por tabulador, una línea por registro:
  #vias-notas v1
  V  id_via  bridge  tunnel  junction  lanes  width  hazard  surface      (valores de OSM; vacíos si no hay)
  N  lat_e6,lon_e6  tipo                                                    (nodo con algo que avisar)
  P  id_via  5  z0_dm,d1,d2,...                                             (perfil de altura de la vía)
`V` solo existe para vías con alguna de esas etiquetas. `tipo` de `N`: valor de `traffic_calming` (bump, hump, table…),
`ford`, `level_crossing`, `stop`, `give_way`, `traffic_signals` o `hazard:<valor>`.
`P` va para CADA vía de vias-mallorca (mismo `id`; la geometría es la de ese archivo). Las alturas son del MDT05 en
decímetros enteros: la primera absoluta y las demás, diferencia con la anterior. Muestras a lo largo de la polilínea:
a 0, 5, 10… m desde el primer nodo y una última en el último nodo (distancia total L; nº de muestras = ceil(L/5) + 1).
La distancia entre nodos es equirrectangular: R = 6371000 m, cos(latitud media del tramo). En puentes y túneles
(`bridge`/`tunnel` distinto de vacío o `no`) la altura interior se interpola linealmente (por distancia) entre los
extremos, porque el MDT es terreno desnudo. Mar, sin dato o fuera del MDT: 0.
Datos © OpenStreetMap contributors (ODbL); MDT05 CC-BY 4.0 scne.es.
"""

import argparse
import gzip
import math
import os
import sys

CABECERA = "#vias-notas v1"
PASO = 5.0
RADIO = 6371000.0
# Etiquetas de la vía que se guardan, en el orden de las columnas de `V`.
ETIQUETAS_VIA = ("bridge", "tunnel", "junction", "lanes", "width", "hazard", "surface")
# highway=* de nodo que se avisa.
HIGHWAY_NODO = ("stop", "give_way", "traffic_signals")
# Altura valida del MDT en Mallorca (fuera: sin dato = 0), igual que relieve.sh.
ALTURA_MIN, ALTURA_MAX = -100.0, 2500.0


# --- Funciones puras ------------------------------------------------------------------------------------------------


def limpio(valor):
    return "" if valor is None else " ".join(str(valor).replace("\t", " ").split())


def campos_via(tags):
    """Valores de ETIQUETAS_VIA de una vía, o None si no tiene ninguna."""
    campos = [limpio(tags.get(k)) for k in ETIQUETAS_VIA]
    return campos if any(campos) else None


def tipo_nodo(tags):
    """Tipo de aviso de un nodo (ver cabecera) o None. Prioridad: traffic_calming, ford, paso a nivel, highway, hazard."""
    calming = limpio(tags.get("traffic_calming"))
    if calming and calming != "no":
        return calming
    if tags.get("ford") == "yes":
        return "ford"
    if tags.get("railway") == "level_crossing":
        return "level_crossing"
    if tags.get("highway") in HIGHWAY_NODO:
        return tags.get("highway")
    peligro = limpio(tags.get("hazard"))
    if peligro and peligro != "no":
        return "hazard:" + peligro
    return None


def es_estructura(bridge, tunnel):
    return any(v not in ("", "no") for v in (bridge, tunnel))


def ids_estructuras(lineas):
    """Ids de las vías con bridge o tunnel según las líneas `V` del TSV de etiquetas."""
    ids = set()
    for linea in lineas:
        if not linea.startswith("V\t"):
            continue
        c = linea.rstrip("\n").split("\t")
        if len(c) >= 4 and es_estructura(c[2], c[3]):
            ids.add(c[1])
    return ids


def leer_via(linea):
    """Línea de vias-mallorca.tsv.gz -> (id, [(lat_e6, lon_e6), ...])."""
    c = linea.rstrip("\n").split("\t")
    puntos = []
    for p in c[8].split(";"):
        lat, lon = p.split(",")
        puntos.append((int(lat), int(lon)))
    return c[0], puntos


def distancia_m(a, b):
    """Distancia en metros entre dos puntos (lat_e6, lon_e6), equirrectangular."""
    dlat = (b[0] - a[0]) / 1e6
    dlon = (b[1] - a[1]) / 1e6
    coslat = math.cos(math.radians((a[0] + b[0]) / 2e6))
    return math.radians(math.hypot(dlat, dlon * coslat)) * RADIO


def posiciones(puntos, paso=PASO):
    """Muestras (distancia_m, lat, lon) cada `paso` m desde el primer nodo, más el último punto (grados)."""
    if not puntos:
        return []
    if len(puntos) == 1:
        return [(0.0, puntos[0][0] / 1e6, puntos[0][1] / 1e6)]
    acumulado = [0.0]
    for a, b in zip(puntos, puntos[1:]):
        acumulado.append(acumulado[-1] + distancia_m(a, b))
    total = acumulado[-1]
    n = math.ceil(total / paso - 1e-9) if total > 0 else 0
    objetivos = [k * paso for k in range(n)] + [total]
    res = []
    i = 0
    for d in objetivos:
        while i < len(puntos) - 2 and acumulado[i + 1] < d:
            i += 1
        largo = acumulado[i + 1] - acumulado[i]
        t = 0.0 if largo <= 0 else min(1.0, max(0.0, (d - acumulado[i]) / largo))
        a, b = puntos[i], puntos[i + 1]
        res.append((d, (a[0] + (b[0] - a[0]) * t) / 1e6, (a[1] + (b[1] - a[1]) * t) / 1e6))
    return res


def muestrear(puntos, altura, paso=PASO):
    """(distancias, alturas) de la polilínea; `altura(lat, lon)` da la altura en metros."""
    pos = posiciones(puntos, paso)
    return [p[0] for p in pos], [altura(p[1], p[2]) for p in pos]


def aplanar_puente(distancias, alturas):
    """Interpola linealmente (por distancia) entre la primera y la última altura."""
    if len(alturas) < 3:
        return list(alturas)
    h0, h1 = alturas[0], alturas[-1]
    total = distancias[-1] - distancias[0]
    if total <= 0:
        return [h0] * len(alturas)
    return [h0 + (h1 - h0) * (d - distancias[0]) / total for d in distancias]


def decimetros(h):
    return int(math.floor(h * 10 + 0.5))


def codificar_delta(alturas):
    """Alturas (m) -> «z0_dm,d1,d2…»: la primera en decímetros enteros y después diferencias entre decímetros enteros."""
    dm = [decimetros(h) for h in alturas]
    return ",".join([str(dm[0])] + [str(b - a) for a, b in zip(dm, dm[1:])])


def decodificar_delta(texto):
    """Inverso de codificar_delta: decímetros absolutos."""
    valores = [int(v) for v in texto.split(",")]
    for i in range(1, len(valores)):
        valores[i] += valores[i - 1]
    return valores


def bilineal(pixel, col, fila):
    """Interpolación bilineal en coordenadas de píxel continuas (borde izquierdo/superior = 0); `pixel(c, f)` da el valor."""
    x = col - 0.5
    y = fila - 0.5
    c0 = math.floor(x)
    f0 = math.floor(y)
    tx = x - c0
    ty = y - f0
    arriba = pixel(c0, f0) * (1 - tx) + pixel(c0 + 1, f0) * tx
    abajo = pixel(c0, f0 + 1) * (1 - tx) + pixel(c0 + 1, f0 + 1) * tx
    return arriba * (1 - ty) + abajo * ty


# --- Subcomandos ----------------------------------------------------------------------------------------------------


def cmd_etiquetas(pbf, destino):
    import osmium

    # `python -I` no pone la carpeta del script en sys.path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from vias import CLASES

    class Etiquetas(osmium.SimpleHandler):
        def __init__(self, salida):
            super().__init__()
            self.salida = salida
            self.vias = 0
            self.nodos = 0

        def node(self, n):
            tipo = tipo_nodo(n.tags)
            if tipo is None or not n.location.valid():
                return
            self.salida.write(f"N\t{round(n.location.lat * 1e6)},{round(n.location.lon * 1e6)}\t{tipo}\n")
            self.nodos += 1

        def way(self, w):
            tags = w.tags
            if tags.get("highway") not in CLASES or tags.get("area") == "yes":
                return
            campos = campos_via(tags)
            if campos is None:
                return
            self.salida.write("\t".join(["V", str(w.id)] + campos) + "\n")
            self.vias += 1

    with open(destino, "w", encoding="utf-8", newline="\n") as salida:
        manejador = Etiquetas(salida)
        manejador.apply_file(pbf)
    print(f"etiquetas: {manejador.vias} vías, {manejador.nodos} nodos")
    return 0


def cmd_perfil(vias_gz, vrt, etiquetas, destino):
    from collections import OrderedDict

    import numpy as np
    from osgeo import gdal, osr

    gdal.UseExceptions()
    gdal.SetCacheMax(256 * 1024 * 1024)
    ds = gdal.Open(vrt)
    banda = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    if gt[2] != 0 or gt[4] != 0 or gt[1] <= 0 or gt[5] >= 0:
        print(f"::error::Geotransformada inesperada del MDT: {gt}", file=sys.stderr)
        return 1
    ancho, alto = ds.RasterXSize, ds.RasterYSize
    nodata = banda.GetNoDataValue()
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    utm = osr.SpatialReference()
    utm.ImportFromEPSG(25830)
    for s in (wgs84, utm):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)  # lon/lat y este/norte
    transformacion = osr.CoordinateTransformation(wgs84, utm)

    lado = 256
    cache = OrderedDict()

    def bloque(bx, by):
        clave = (bx, by)
        b = cache.get(clave)
        if b is not None:
            cache.move_to_end(clave)
            return b
        x0, y0 = bx * lado, by * lado
        a = banda.ReadAsArray(x0, y0, min(lado, ancho - x0), min(lado, alto - y0)).astype(np.float32)
        valido = np.isfinite(a) & (a > ALTURA_MIN) & (a < ALTURA_MAX)
        if nodata is not None:
            valido &= a != nodata
        b = np.where(valido, a, np.float32(0.0))
        cache[clave] = b
        if len(cache) > 512:
            cache.popitem(last=False)
        return b

    def pixel(c, f):
        if c < 0 or f < 0 or c >= ancho or f >= alto:
            return 0.0
        return bloque(c // lado, f // lado).item(f % lado, c % lado)

    estado = {"fuera": 0, "maxima": -1e9}

    def altura(lat, lon):
        x, y, _ = transformacion.TransformPoint(lon, lat)
        col = (x - gt[0]) / gt[1]
        fila = (y - gt[3]) / gt[5]
        if not (0 <= col < ancho and 0 <= fila < alto):
            estado["fuera"] += 1
            return 0.0
        h = bilineal(pixel, col, fila)
        if h > estado["maxima"]:
            estado["maxima"] = h
        return h

    with open(etiquetas, encoding="utf-8") as f:
        lineas_etiquetas = f.readlines()
    estructuras = ids_estructuras(lineas_etiquetas)

    vias = muestras = 0
    with gzip.open(destino, "wt", encoding="utf-8", newline="\n", compresslevel=9) as salida:
        salida.write(CABECERA + "\n")
        for linea in lineas_etiquetas:
            salida.write(linea if linea.endswith("\n") else linea + "\n")
        with gzip.open(vias_gz, "rt", encoding="utf-8") as entrada:
            for linea in entrada:
                if linea.startswith("#") or not linea.strip():
                    continue
                id_via, puntos = leer_via(linea)
                distancias, alturas = muestrear(puntos, altura)
                if id_via in estructuras:
                    alturas = aplanar_puente(distancias, alturas)
                salida.write(f"P\t{id_via}\t{int(PASO)}\t{codificar_delta(alturas)}\n")
                vias += 1
                muestras += len(alturas)
    megas = os.path.getsize(destino) / 1e6
    print(
        f"perfil: {vias} vías, {muestras} muestras, {megas:.1f} MB; altura máxima {estado['maxima']:.1f} m; "
        f"muestras fuera del MDT (a 0): {estado['fuera']}")
    if vias == 0 or muestras == 0:
        print("::error::No se ha generado ningún perfil", file=sys.stderr)
        return 1
    # Sanidad: Mallorca tiene carreteras a más de 800 m y ninguna por encima de 1600 m. Un CRS mal puesto da 0 o basura.
    if estado["fuera"] > 0.05 * muestras or not 300.0 <= estado["maxima"] <= 1600.0:
        print("::error::El perfil no es creíble (muestras fuera del MDT o altura máxima fuera de 300-1600 m)", file=sys.stderr)
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="orden", required=True)
    e = sub.add_parser("etiquetas", help="etiquetas de vías y nodos de OSM -> TSV temporal (pyosmium)")
    e.add_argument("pbf")
    e.add_argument("destino")
    f = sub.add_parser("perfil", help="perfil de altura de cada vía + etiquetas -> vias-notas-mallorca.tsv.gz (GDAL)")
    f.add_argument("vias")
    f.add_argument("vrt")
    f.add_argument("etiquetas")
    f.add_argument("destino")
    a = p.parse_args()
    if a.orden == "etiquetas":
        return cmd_etiquetas(a.pbf, a.destino)
    return cmd_perfil(a.vias, a.vrt, a.etiquetas, a.destino)


if __name__ == "__main__":
    sys.exit(main())
