"""Hitos kilométricos de Mallorca (puntos kilométricos de las carreteras) a un TSV pequeño: pk-mallorca.tsv.

Uso:
  python -I scripts/pk.py --pbf mallorca.osm.pbf --salida pk-mallorca.tsv [--recortar]

Fuente: nodos `highway=milestone` de OSM (pyosmium, como vias.py) con la carretera en `ref` («Ma-13»; con varias, separadas
por `;`, sale una fila por cada una) y el punto kilométrico en `distance` (o, si falta, `pk`): «23», «44.8», «23 km», «23,5».
Se descartan los nodos sin carretera, sin kilómetro legible (otras unidades, texto) o con un kilómetro fuera de 0-400.

Formato v1 (UTF-8, campos separados por tabulador, primera línea `#pk v1`, segunda línea con los nombres de columna precedida
de `#`; el resto, una fila por hito, ordenadas por carretera, kilómetro y posición):
  ref  km  lat  lon
  ref  carretera tal como la escribe OSM («Ma-13», «Ma-1C»); la app la compara sin distinguir mayúsculas ni guiones.
  km   punto kilométrico en km (decimal con punto, hasta 3 decimales).
  lat, lon  grados decimales WGS84 con 6 decimales.
Un mismo hito mapeado dos veces (misma ref y km a menos de 15 m) sale una sola vez. Datos © OpenStreetMap contributors (ODbL).
"""

import argparse
import math
import re
import sys

CABECERA = "#pk v1"
COLUMNAS = ("ref", "km", "lat", "lon")
BBOX = (2.30, 39.26, 3.50, 39.97)  # oeste, sur, este, norte
MIN_HITOS = 20
KM_MAX = 400.0
UMBRAL_DUPLICADO_M = 15.0
_KM = re.compile(r"^\s*(\d{1,3}(?:[.,]\d{1,3})?)\s*(?:km)?\s*$", re.IGNORECASE)


def en_bbox(lat: float, lon: float, bbox=BBOX) -> bool:
    return bbox[1] <= lat <= bbox[3] and bbox[0] <= lon <= bbox[2]


def distancia_m(a, b) -> float:
    """Distancia equirectangular en metros entre dos (lat, lon); sobra para decenas de metros."""
    dy = math.radians(b[0] - a[0]) * 6371000.0
    dx = math.radians(b[1] - a[1]) * 6371000.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def parsear_km(valor: str | None) -> float | None:
    """«23» -> 23.0, «44.8» -> 44.8, «23,5 km» -> 23.5. Otras unidades («3 mi»), texto o fuera de 0-400 -> None."""
    if valor is None:
        return None
    m = _KM.match(valor)
    if not m:
        return None
    km = float(m.group(1).replace(",", "."))
    return km if 0 <= km <= KM_MAX else None


def parsear_refs(valor: str | None) -> list[str]:
    """«Ma-13;Ma-13A» -> ['Ma-13', 'Ma-13A']. Una ref sin ninguna letra (solo la numeración del hito) no sirve."""
    if not valor:
        return []
    refs = []
    for parte in valor.split(";"):
        ref = " ".join(parte.split())
        if ref and re.search(r"[A-Za-z]", ref) and ref not in refs:
            refs.append(ref)
    return refs


def hitos_de_nodo(tags: dict, lat: float, lon: float) -> list[dict]:
    """Filas (una por ref) de un nodo `highway=milestone`; lista vacía si no sirve."""
    if tags.get("highway") != "milestone":
        return []
    km = parsear_km(tags.get("distance"))
    if km is None:
        km = parsear_km(tags.get("pk"))
    if km is None:
        return []
    return [{"ref": ref, "km": km, "lat": lat, "lon": lon} for ref in parsear_refs(tags.get("ref"))]


def deduplicar(hitos: list[dict]) -> list[dict]:
    """Quita los hitos repetidos (misma ref y km a menos de UMBRAL_DUPLICADO_M); el primero gana."""
    unicos: list[dict] = []
    for h in hitos:
        if any(u["ref"] == h["ref"] and u["km"] == h["km"]
               and distancia_m((u["lat"], u["lon"]), (h["lat"], h["lon"])) < UMBRAL_DUPLICADO_M for u in unicos):
            continue
        unicos.append(h)
    return unicos


def validar(hitos: list[dict], bbox=BBOX, minimo=MIN_HITOS) -> list[str]:
    """Lista de errores (vacía = válido): menos de `minimo` hitos o alguno fuera del bbox."""
    errores = []
    if len(hitos) < minimo:
        errores.append(f"solo {len(hitos)} hitos (mínimo {minimo})")
    for h in hitos:
        if not en_bbox(h["lat"], h["lon"], bbox):
            errores.append(f"{h['ref']} km {h['km']} fuera del bbox: {h['lat']}, {h['lon']}")
    return errores


def _clave(h: dict):
    # «Ma-2» antes que «Ma-10»: orden natural por los números de la ref.
    return ([int(t) if t.isdigit() else t for t in re.split(r"(\d+)", h["ref"])], h["km"], h["lat"], h["lon"])


def _km_texto(km: float) -> str:
    return f"{km:.3f}".rstrip("0").rstrip(".")


def escribir(hitos: list[dict], destino: str) -> None:
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(CABECERA + "\n")
        f.write("#" + "\t".join(COLUMNAS) + "\n")
        for h in sorted(hitos, key=_clave):
            f.write(f"{h['ref']}\t{_km_texto(h['km'])}\t{h['lat']:.6f}\t{h['lon']:.6f}\n")


def leer_osm(ruta: str) -> list[dict]:
    """Lee el PBF con pyosmium y devuelve los hitos (sin deduplicar)."""
    import osmium  # noqa: PLC0415  (import diferido: las pruebas sin PBF no lo necesitan)

    hitos: list[dict] = []

    class Hitos(osmium.SimpleHandler):
        def node(self, n):
            if n.tags.get("highway") == "milestone" and n.location.valid():
                tags = {k: n.tags.get(k) for k in ("highway", "distance", "pk", "ref")}
                hitos.extend(hitos_de_nodo(tags, n.location.lat, n.location.lon))

    Hitos().apply_file(ruta)
    return hitos


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pbf", required=True)
    p.add_argument("--salida", required=True)
    p.add_argument("--recortar", action="store_true",
                   help="descarta lo de fuera del bbox en vez de fallar (para un PBF sin recortar)")
    args = p.parse_args()

    hitos = leer_osm(args.pbf)
    if args.recortar:
        hitos = [h for h in hitos if en_bbox(h["lat"], h["lon"])]
    hitos = deduplicar(sorted(hitos, key=_clave))
    errores = validar(hitos)
    print(f"hitos: {len(hitos)}; carreteras: {len({h['ref'] for h in hitos})}")
    if errores:
        for e in errores[:10]:
            print(f"::error::pk: {e}", file=sys.stderr)
        if len(errores) > 10:
            print(f"::error::pk: y {len(errores) - 10} errores más", file=sys.stderr)
        return 1
    escribir(hitos, args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
