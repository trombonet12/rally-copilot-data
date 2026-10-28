"""Descarga las teselas PNOA (IGN) de Mallorca z0–16 en un MBTiles, sin recomprimir.

Uso: python -I scripts/satelite.py --bbox 2.30,39.26,3.50,39.97 --zmax 16 --salida pnoa.mbtiles

Reanudable: las teselas que ya están en el MBTiles no se vuelven a pedir. Pocas peticiones simultáneas y
User-Agent identificable, por cortesía con el servicio del IGN. Datos: PNOA CC-BY 4.0 scne.es.
"""

import argparse
import concurrent.futures as cf
import math
import sqlite3
import sys
import time
import urllib.error
import urllib.request

URL = "https://tms-pnoa-ma.idee.es/1.0.0/pnoa-ma/{z}/{x}/{y}.jpeg"  # y en esquema TMS (origen abajo)
USER_AGENT = "RallyCopilotData/1 (+https://github.com/trombonet12/rally-copilot-data)"
REINTENTOS = 5
ATRIBUCION = "PNOA CC-BY 4.0 scne.es"


def lon_a_x(lon: float, z: int) -> int:
    return min(int((lon + 180.0) / 360.0 * 2**z), 2**z - 1)


def lat_a_y(lat: float, z: int) -> int:
    """Fila XYZ (origen arriba) de la latitud en Web Mercator."""
    r = math.radians(lat)
    return min(int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * 2**z), 2**z - 1)


def teselas(bbox: tuple[float, float, float, float], zmin: int, zmax: int):
    """Teselas XYZ (z, x, y) que tocan el bbox (oeste, sur, este, norte)."""
    oeste, sur, este, norte = bbox
    for z in range(zmin, zmax + 1):
        for x in range(lon_a_x(oeste, z), lon_a_x(este, z) + 1):
            for y in range(lat_a_y(norte, z), lat_a_y(sur, z) + 1):
                yield z, x, y


def fila_tms(z: int, y: int) -> int:
    return 2**z - 1 - y


def es_jpeg(datos: bytes) -> bool:
    return datos[:3] == b"\xff\xd8\xff"


def descargar(z: int, x: int, y: int) -> bytes | None:
    """JPEG de la tesela, o None si el IGN no la tiene (404). Reintenta errores de red y 5xx."""
    url = URL.format(z=z, x=x, y=fila_tms(z, y))
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for intento in range(REINTENTOS):
        try:
            with urllib.request.urlopen(peticion, timeout=30) as respuesta:
                datos = respuesta.read()
            if datos[:4] == b"\x89PNG":
                return None  # fuera de cobertura (mar): el IGN sirve un PNG transparente de ~660 bytes
            if not es_jpeg(datos):
                raise ValueError(f"no es JPEG: {url}")
            return datos
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            espera = 2**intento
        except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError):
            espera = 2**intento
        time.sleep(espera)
    raise RuntimeError(f"tesela {z}/{x}/{y} falló tras {REINTENTOS} intentos")


def abrir(ruta: str, bbox, zmax: int) -> sqlite3.Connection:
    db = sqlite3.connect(ruta)
    db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, "
        "tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))"
    )
    oeste, sur, este, norte = bbox
    metadatos = {
        "name": "PNOA Mallorca",
        "format": "jpg",
        "type": "baselayer",
        "minzoom": "0",
        "maxzoom": str(zmax),
        "bounds": f"{oeste},{sur},{este},{norte}",
        "center": f"{(oeste + este) / 2},{(sur + norte) / 2},10",
        "attribution": ATRIBUCION,
    }
    db.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)", metadatos.items())
    db.commit()
    return db


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bbox", required=True, help="oeste,sur,este,norte")
    p.add_argument("--zmax", type=int, default=16)
    p.add_argument("--salida", required=True)
    p.add_argument("--hilos", type=int, default=4)
    args = p.parse_args()
    bbox = tuple(float(v) for v in args.bbox.split(","))
    db = abrir(args.salida, bbox, args.zmax)
    hechas = set(db.execute("SELECT zoom_level, tile_column, tile_row FROM tiles"))
    pendientes = [(z, x, y) for z, x, y in teselas(bbox, 0, args.zmax) if (z, x, fila_tms(z, y)) not in hechas]
    print(f"teselas pendientes: {len(pendientes)} (ya descargadas: {len(hechas)})", flush=True)
    vacias = 0
    with cf.ThreadPoolExecutor(max_workers=args.hilos) as pool:
        futuros = {pool.submit(descargar, *t): t for t in pendientes}
        for i, futuro in enumerate(cf.as_completed(futuros), 1):
            z, x, y = futuros.pop(futuro)  # pop: si no, los ~450 MB de JPEG se quedan en memoria
            datos = futuro.result()
            if datos is None:
                vacias += 1
            else:
                db.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)", (z, x, fila_tms(z, y), datos))
            if i % 1000 == 0:
                db.commit()
                print(f"{i}/{len(pendientes)}", flush=True)
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
    print(f"teselas guardadas: {total}; sin cobertura (404): {vacias}", flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
