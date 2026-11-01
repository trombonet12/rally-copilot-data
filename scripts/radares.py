"""Radares de Mallorca (fijos, de tramo y zonas de radar móvil) a un TSV pequeño: radares-mallorca.tsv.

Uso:
  python -I scripts/radares.py --pbf mallorca.osm.pbf --dgt radares.xml --salida radares-mallorca.tsv \
      [--cinemometros datos/cinemometros-mallorca.tsv] [--recortar]

Fuentes (todas opcionales salvo que haya al menos 5 radares fijos en total):
  - DGT: XML DATEX II v1 de «radares» del NAP (cabinas de cinemómetro y tramos de velocidad media), filtrado al bbox.
  - OSM: nodos `highway=speed_camera` y relaciones `type=enforcement` con `enforcement=maxspeed|average_speed`
    (pyosmium, igual que vias.py). Los de tramo salen de las relaciones `average_speed`.
  - `datos/cinemometros-mallorca.tsv` (curado del PDF «Informe de cinemómetros» de la DGT): sirve para distinguir las
    cabinas de la DGT que son de radar MÓVIL (ZONA_MOVIL) de las de radar fijo, cruzando por el PK.

Formato v1 (UTF-8, campos separados por tabulador, primera línea `#radares v1`, segunda línea con los nombres de columna
precedida de `#`; el resto, una fila por línea):
  tipo       FIJO | TRAMO_INICIO | TRAMO_FIN | ZONA_MOVIL
  id         único por fila (`dgt-120451`, `osm-n992002040`, `osm-r20233503-ini`...)
  lat, lon   grados decimales WGS84 con 6 decimales
  rumbo      grados 0-359 hacia donde circulan los vehículos vigilados; vacío = ambos sentidos / desconocido
  limite_kmh límite en km/h o vacío
  tramo_id   FIJO: vacío. TRAMO_INICIO y TRAMO_FIN del mismo tramo comparten tramo_id (filas consecutivas, inicio antes
             que fin). ZONA_MOVIL: los puntos de una zona comparten tramo_id y van en filas consecutivas, en orden,
             formando una polilínea (una zona de un solo punto = una fila).
  fuente     DGT | OSM | DGT-PDF
Datos © OpenStreetMap contributors (ODbL) y DGT (CC BY, NAP).
"""

import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET

CABECERA = "#radares v1"
COLUMNAS = ("tipo", "id", "lat", "lon", "rumbo", "limite_kmh", "tramo_id", "fuente")
FIJO, TRAMO_INICIO, TRAMO_FIN, ZONA_MOVIL = "FIJO", "TRAMO_INICIO", "TRAMO_FIN", "ZONA_MOVIL"
# oeste, sur, este, norte (el mismo recuadro que BBOX del workflow)
BBOX = (2.30, 39.26, 3.50, 39.97)
UMBRAL_DEDUP_M = 50.0
# DGT <-> OSM: las coordenadas de la DGT quedan a 8-94 m de la cámara de OSM correspondiente (medido con las 13 cabinas de
# Mallorca; la siguiente cámara más cercana está a más de 290 m), así que con 50 m se quedarían 6 duplicadas.
UMBRAL_DGT_OSM_M = 100.0
MIN_FIJOS = 5
# Un FIJO de OSM con from/to a menos de esto no da un rumbo fiable.
MIN_RUMBO_M = 40.0
_N = "{http://datex2.eu/schema/1_0/1_0}"
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
_CARDINALES = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5, "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


# --------------------------------------------------------------------------------------------------------------------
# Geometría y utilidades
# --------------------------------------------------------------------------------------------------------------------

def distancia_m(a, b) -> float:
    """Distancia equirectangular en metros entre dos (lat, lon); sobra para decenas de metros."""
    dy = math.radians(b[0] - a[0]) * 6371000.0
    dx = math.radians(b[1] - a[1]) * 6371000.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def rumbo_entre(a, b) -> int:
    """Rumbo inicial en grados enteros 0-359 de a hacia b."""
    la1, lo1, la2, lo2 = (math.radians(v) for v in (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return round((math.degrees(math.atan2(y, x)) + 360.0) % 360.0) % 360


def diferencia_angular(a: int, b: int) -> int:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def rumbos_compatibles(a: int | None, b: int | None) -> bool:
    """Sin rumbo = ambos sentidos: compatible con todo. Con rumbo en los dos: menos de 90° de diferencia."""
    return a is None or b is None or diferencia_angular(a, b) < 90


def en_bbox(lat: float, lon: float, bbox=BBOX) -> bool:
    return bbox[1] <= lat <= bbox[3] and bbox[0] <= lon <= bbox[2]


def parsear_limite(valor: str | None) -> int | None:
    """«90» -> 90. Solo km/h enteros entre 5 y 200; «50 mph», «walk», «none»... -> None."""
    if valor is None:
        return None
    valor = valor.strip()
    if not valor.isdigit():
        return None
    n = int(valor)
    return n if 5 <= n <= 200 else None


def parsear_direccion(valor: str | None) -> int | None:
    """`direction` de OSM: grados («75», «260.5») o cardinal («NE»). Con varios valores («30;255») toma el primero.
    `forward`/`backward`/`both` dependen de la vía y no se pueden resolver aquí -> None."""
    if not valor:
        return None
    primero = valor.split(";")[0].strip()
    if primero.upper() in _CARDINALES:
        return round(_CARDINALES[primero.upper()]) % 360
    try:
        grados = float(primero)
    except ValueError:
        return None
    if not 0 <= grados <= 360:
        return None
    return round(grados) % 360


def radar(tipo, ident, lat, lon, fuente, rumbo=None, limite=None, tramo=""):
    return {"tipo": tipo, "id": ident, "lat": lat, "lon": lon, "rumbo": rumbo, "limite": limite, "tramo": tramo,
            "fuente": fuente}


# --------------------------------------------------------------------------------------------------------------------
# DGT (DATEX II v1, PredefinedLocationsPublication)
# --------------------------------------------------------------------------------------------------------------------

def _coordenadas(elem):
    if elem is None:
        return None
    lat, lon = elem.findtext(_N + "latitude"), elem.findtext(_N + "longitude")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def leer_dgt(origen, bbox=BBOX):
    """Devuelve (cabinas, tramos) dentro del bbox.

    cabinas: [{'id': '120451', 'lat', 'lon', 'carretera', 'pk_m' (int|None)}]
    tramos:  [{'id': '161274', 'ini': (lat, lon), 'fin': (lat, lon)}]   (`from` = inicio, `to` = fin: se ha comprobado que
             las distancias de referencia van en el sentido from -> to).
    `origen` es una ruta o un objeto de archivo."""
    raiz = ET.parse(origen).getroot()
    cabinas, tramos = [], []
    for loc in raiz.iter(_N + "predefinedLocation"):
        guid = loc.get("id")
        interior = loc.find(_N + "predefinedLocation")
        if not guid or interior is None:
            continue
        tipo = interior.get(_XSI_TYPE, "")
        if tipo.endswith("Point"):
            punto = _coordenadas(interior.find(f"{_N}tpegpointLocation/{_N}point/{_N}pointCoordinates"))
            if punto is None or not en_bbox(*punto, bbox):
                continue
            pk = interior.findtext(f".//{_N}referencePointDistance")
            cabinas.append({
                "id": guid.rsplit("_", 1)[-1], "lat": punto[0], "lon": punto[1],
                "carretera": interior.findtext(f".//{_N}roadNumber") or "",
                "pk_m": round(float(pk)) if pk else None,
            })
        elif tipo.endswith("Linear"):
            ini = _coordenadas(interior.find(f"{_N}tpeglinearLocation/{_N}from/{_N}pointCoordinates"))
            fin = _coordenadas(interior.find(f"{_N}tpeglinearLocation/{_N}to/{_N}pointCoordinates"))
            if ini is None or fin is None or not (en_bbox(*ini, bbox) and en_bbox(*fin, bbox)):
                continue
            tramos.append({"id": guid.rsplit("_", 1)[-1], "ini": ini, "fin": fin})
    return cabinas, tramos


def leer_cinemometros(ruta):
    """datos/cinemometros-mallorca.tsv -> {'fijos': {pk_m}, 'moviles': {pk_m}} con los PK de un solo punto."""
    fijos, moviles = set(), set()
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            if not linea or linea.startswith("#"):
                continue
            campos = linea.split("\t")
            tipo, pk_ini, pk_fin = campos[1], campos[2], campos[3]
            if not pk_ini or pk_fin:  # solo PK de un punto: los rangos no son una cabina concreta
                continue
            pk_m = round(float(pk_ini) * 1000)
            (fijos if tipo == "FIJO" else moviles).add(pk_m)
    return {"fijos": fijos, "moviles": moviles}


def radares_dgt(cabinas, tramos, cinemometros=None):
    """Cabinas -> FIJO, salvo las que el PDF de la DGT da como radar móvil en ese PK (-> ZONA_MOVIL de un punto,
    fuente DGT-PDF). Los tramos de velocidad media -> TRAMO_INICIO + TRAMO_FIN. La DGT no publica límite ni sentido."""
    cinemometros = cinemometros or {"fijos": set(), "moviles": set()}
    salida = []
    for c in cabinas:
        ident = f"dgt-{c['id']}"
        movil = c["pk_m"] in cinemometros["moviles"] and c["pk_m"] not in cinemometros["fijos"]
        if movil:
            salida.append(radar(ZONA_MOVIL, ident, c["lat"], c["lon"], "DGT-PDF", tramo=ident))
        else:
            salida.append(radar(FIJO, ident, c["lat"], c["lon"], "DGT"))
    for t in tramos:
        base = f"dgt-cvm-{t['id']}"
        salida.append(radar(TRAMO_INICIO, f"{base}-ini", *t["ini"], "DGT", tramo=base))
        salida.append(radar(TRAMO_FIN, f"{base}-fin", *t["fin"], "DGT", tramo=base))
    return salida


# --------------------------------------------------------------------------------------------------------------------
# OSM
# --------------------------------------------------------------------------------------------------------------------

def radares_osm(camaras, relaciones, ubic_nodos, ubic_vias):
    """Radares de OSM.

    camaras:    {id_nodo: {'lat', 'lon', 'tags'}} de los nodos `highway=speed_camera`.
    relaciones: [{'id', 'tags', 'miembros': [(tipo 'n'|'w'|'r', ref, rol)]}] de las relaciones `type=enforcement`.
    ubic_nodos: {id_nodo: (lat, lon)} de las camaras y de los nodos miembros; ubic_vias: {id_via: (lat, lon)} (punto medio).

    `direction` de OSM coincide con el sentido de la circulación vigilada (se comprobó con las relaciones de Mallorca:
    el rumbo from -> to difiere de él menos de 45° en 22 de las 23 relaciones con ambos datos; la otra es la del sentido
    contrario de un dispositivo que vigila los dos). Un dispositivo que está en dos relaciones (una por
    sentido) da dos FIJO con el rumbo de cada relación."""
    def ubic(miembro):
        tipo, ref = miembro[0], miembro[1]
        return ubic_nodos.get(ref) if tipo == "n" else ubic_vias.get(ref) if tipo == "w" else None

    fijas_por_dispositivo: dict[int, list] = {}
    consumidos: set[int] = set()
    salida = []
    for r in sorted(relaciones, key=lambda r: r["id"]):
        enforcement = r["tags"].get("enforcement")
        if enforcement not in ("maxspeed", "average_speed"):
            continue
        limite_rel = parsear_limite(r["tags"].get("maxspeed"))
        dispositivos = [m[1] for m in r["miembros"] if m[2] == "device" and m[0] == "n"]
        desde = next((ubic(m) for m in r["miembros"] if m[2] == "from"), None)
        hasta = next((ubic(m) for m in r["miembros"] if m[2] == "to"), None)
        if enforcement == "maxspeed":
            for d in dispositivos:
                fijas_por_dispositivo.setdefault(d, []).append((r["id"], desde, hasta, limite_rel))
            continue
        # average_speed: de `from` a `to`, o de un dispositivo al otro si faltan.
        puntos = [ubic_nodos.get(d) for d in dispositivos]
        puntos = [p for p in puntos if p is not None]
        ini = desde or (puntos[0] if puntos else None)
        fin = hasta or (puntos[-1] if puntos else None)
        if ini is None or fin is None or distancia_m(ini, fin) < MIN_RUMBO_M:
            continue
        consumidos.update(dispositivos)
        limite = limite_rel
        if limite is None:
            limite = next((parsear_limite(camaras[d]["tags"].get("maxspeed")) for d in dispositivos
                           if d in camaras and parsear_limite(camaras[d]["tags"].get("maxspeed"))), None)
        tramo = f"osm-r{r['id']}"
        rumbo = rumbo_entre(ini, fin)
        salida.append(radar(TRAMO_INICIO, f"{tramo}-ini", *ini, "OSM", rumbo, limite, tramo))
        salida.append(radar(TRAMO_FIN, f"{tramo}-fin", *fin, "OSM", rumbo, limite, tramo))

    # Fijos: nodos speed_camera (con o sin relación) y dispositivos de relaciones `maxspeed` sin esa etiqueta.
    for nodo in sorted(set(camaras) | set(fijas_por_dispositivo)):
        if nodo in consumidos or nodo not in ubic_nodos:
            continue
        lat, lon = ubic_nodos[nodo]
        tags = camaras[nodo]["tags"] if nodo in camaras else {}
        limite_nodo = parsear_limite(tags.get("maxspeed"))
        rumbo_nodo = parsear_direccion(tags.get("direction"))
        relaciones_nodo = fijas_por_dispositivo.get(nodo, [])
        if len(relaciones_nodo) <= 1:
            rid, desde, hasta, limite_rel = relaciones_nodo[0] if relaciones_nodo else (None, None, None, None)
            rumbo = rumbo_nodo
            if rumbo is None and desde and hasta and distancia_m(desde, hasta) >= MIN_RUMBO_M:
                rumbo = rumbo_entre(desde, hasta)
            salida.append(radar(FIJO, f"osm-n{nodo}", lat, lon, "OSM", rumbo, limite_nodo or limite_rel))
        else:
            for rid, desde, hasta, limite_rel in relaciones_nodo:
                rumbo = rumbo_entre(desde, hasta) if desde and hasta and distancia_m(desde, hasta) >= MIN_RUMBO_M \
                    else None
                salida.append(radar(FIJO, f"osm-n{nodo}-r{rid}", lat, lon, "OSM", rumbo, limite_nodo or limite_rel))
    return salida


def leer_osm(ruta):
    """Lee el PBF con pyosmium en dos pasadas: relaciones `enforcement` y, con sus miembros, ubicaciones."""
    import osmium  # noqa: PLC0415  (import diferido: las pruebas no lo necesitan)

    relaciones = []

    class Relaciones(osmium.SimpleHandler):
        def relation(self, r):
            if r.tags.get("type") == "enforcement" and r.tags.get("enforcement") in ("maxspeed", "average_speed"):
                relaciones.append({
                    "id": r.id,
                    "tags": {k: v for k, v in ((t.k, t.v) for t in r.tags) if k in ("enforcement", "maxspeed")},
                    "miembros": [(m.type, m.ref, m.role) for m in r.members],
                })

    Relaciones().apply_file(ruta)
    nodos_miembro = {m[1] for r in relaciones for m in r["miembros"] if m[0] == "n"}
    vias_miembro = {m[1] for r in relaciones for m in r["miembros"] if m[0] == "w"}
    camaras, ubic_nodos, ubic_vias = {}, {}, {}

    class Puntos(osmium.SimpleHandler):
        def node(self, n):
            es_camara = n.tags.get("highway") == "speed_camera"
            if (es_camara or n.id in nodos_miembro) and n.location.valid():
                ubic_nodos[n.id] = (n.location.lat, n.location.lon)
                if es_camara:
                    camaras[n.id] = {"lat": n.location.lat, "lon": n.location.lon,
                                     "tags": {t.k: t.v for t in n.tags if t.k in ("maxspeed", "direction")}}

        def way(self, w):
            if w.id in vias_miembro:
                nodos = [n for n in w.nodes if n.location.valid()]
                if nodos:
                    medio = nodos[len(nodos) // 2].location
                    ubic_vias[w.id] = (medio.lat, medio.lon)

    Puntos().apply_file(ruta, locations=True)
    return camaras, relaciones, ubic_nodos, ubic_vias


# --------------------------------------------------------------------------------------------------------------------
# Fusión, validación y escritura
# --------------------------------------------------------------------------------------------------------------------

def fusionar(dgt, osm):
    """DGT + OSM sin duplicados. Un punto de la DGT (cabina FIJO o ZONA_MOVIL) absorbe los FIJO de OSM a menos de
    UMBRAL_DGT_OSM_M (100 m) con rumbo compatible: queda con la posición, el tipo y el límite de la DGT (si lo tiene) y
    con el rumbo y el límite de OSM. Si OSM tiene dos FIJO en ese punto (uno por sentido) salen dos filas. Entre los FIJO
    restantes, los de menos de UMBRAL_DEDUP_M (50 m) y rumbo compatible son uno (gana el primero: DGT, luego OSM por id).
    Los tramos no se fusionan."""
    osm_fijos = [o for o in osm if o["tipo"] == FIJO]
    usados: set[str] = set()
    salida = []
    for d in dgt:
        if d["tipo"] not in (FIJO, ZONA_MOVIL):
            salida.append(d)
            continue
        coincidencias = [o for o in osm_fijos if o["id"] not in usados
                         and distancia_m((d["lat"], d["lon"]), (o["lat"], o["lon"])) <= UMBRAL_DGT_OSM_M
                         and rumbos_compatibles(d["rumbo"], o["rumbo"])]
        if not coincidencias:
            salida.append(d)
            continue
        for k, o in enumerate(coincidencias):
            usados.add(o["id"])
            ident = d["id"] if k == 0 else f"{d['id']}-{k + 1}"
            fila = {**d, "id": ident, "rumbo": o["rumbo"], "limite": d["limite"] or o["limite"]}
            if d["tipo"] == ZONA_MOVIL:
                fila["tramo"] = ident
            salida.append(fila)
    for o in osm:
        if o["id"] not in usados:
            salida.append(o)
    # Deduplicado de FIJO restantes (p. ej. un nodo de OSM repetido por otro mapeador).
    unicos = []
    for r in salida:
        if r["tipo"] == FIJO and any(
                u["tipo"] == FIJO and distancia_m((u["lat"], u["lon"]), (r["lat"], r["lon"])) < UMBRAL_DEDUP_M
                and rumbos_compatibles(u["rumbo"], r["rumbo"]) for u in unicos):
            continue
        unicos.append(r)
    return unicos


def validar(radares, bbox=BBOX, minimo_fijos=MIN_FIJOS):
    """Lista de errores (vacía = válido): menos de `minimo_fijos` FIJO, alguno fuera del bbox, ids repetidos o tramos
    sin su pareja inicio/fin."""
    errores = []
    fijos = sum(1 for r in radares if r["tipo"] == FIJO)
    if fijos < minimo_fijos:
        errores.append(f"solo {fijos} radares fijos (mínimo {minimo_fijos})")
    for r in radares:
        if not en_bbox(r["lat"], r["lon"], bbox):
            errores.append(f"{r['id']} fuera del bbox: {r['lat']}, {r['lon']}")
    ids = [r["id"] for r in radares]
    if len(ids) != len(set(ids)):
        errores.append("ids repetidos")
    tramos: dict[str, list[str]] = {}
    for r in radares:
        if r["tipo"] in (TRAMO_INICIO, TRAMO_FIN):
            tramos.setdefault(r["tramo"], []).append(r["tipo"])
    for tramo, tipos in tramos.items():
        if sorted(tipos) != [TRAMO_FIN, TRAMO_INICIO]:
            errores.append(f"tramo {tramo} sin pareja inicio/fin")
    return errores


_ORDEN = {FIJO: 0, TRAMO_INICIO: 1, TRAMO_FIN: 2, ZONA_MOVIL: 3}


def escribir(radares, destino):
    """Orden estable: FIJO por id, luego los tramos (inicio antes que fin, agrupados por tramo_id) y las zonas."""
    def clave(r):
        if r["tipo"] == FIJO:
            return (0, r["id"], 0)
        grupo = 1 if r["tipo"] in (TRAMO_INICIO, TRAMO_FIN) else 2
        return (grupo, r["tramo"], _ORDEN[r["tipo"]])

    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(CABECERA + "\n")
        f.write("#" + "\t".join(COLUMNAS) + "\n")
        for r in sorted(radares, key=clave):
            f.write("\t".join([
                r["tipo"], r["id"], f"{r['lat']:.6f}", f"{r['lon']:.6f}",
                "" if r["rumbo"] is None else str(r["rumbo"]),
                "" if r["limite"] is None else str(r["limite"]),
                r["tramo"], r["fuente"],
            ]) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pbf", help="PBF de Mallorca (OSM); sin él solo sale la DGT")
    p.add_argument("--dgt", help="XML de radares de la DGT; sin él solo sale OSM")
    p.add_argument("--cinemometros", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "datos", "cinemometros-mallorca.tsv"))
    p.add_argument("--salida", required=True)
    p.add_argument("--recortar", action="store_true",
                   help="descarta lo de OSM fuera del bbox en vez de fallar (para un PBF sin recortar)")
    args = p.parse_args()

    dgt = []
    if args.dgt:
        cabinas, tramos = leer_dgt(args.dgt)
        cinemometros = leer_cinemometros(args.cinemometros) if os.path.isfile(args.cinemometros) else None
        dgt = radares_dgt(cabinas, tramos, cinemometros)
    osm = []
    if args.pbf:
        osm = radares_osm(*leer_osm(args.pbf))
        if args.recortar:
            osm = [r for r in osm if en_bbox(r["lat"], r["lon"])]
    radares = fusionar(dgt, osm)
    errores = validar(radares)
    cuentas = {t: sum(1 for r in radares if r["tipo"] == t) for t in _ORDEN}
    print(f"DGT: {len(dgt)} filas; OSM: {len(osm)} filas; salida: {cuentas}")
    if errores:
        for e in errores[:10]:
            print(f"::error::radares: {e}", file=sys.stderr)
        if len(errores) > 10:
            print(f"::error::radares: y {len(errores) - 10} errores más", file=sys.stderr)
        return 1
    escribir(radares, args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
