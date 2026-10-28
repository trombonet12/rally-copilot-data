"""Genera el indice de busqueda offline de Mallorca: una base SQLite con una tabla normal y portable (sin FTS5).

Uso: python -I scripts/busqueda.py mallorca.osm.pbf busqueda-mallorca.sqlite [--limites limites.osm.pbf]

Tabla `lugares` (`PRAGMA user_version` = 2), indice `lugares_nombre_norm` sobre `nombre_norm`:
  nombre        TEXT. Nombre tal cual en OSM (`name`, y `name:es` si difiere)
  nombre_norm   TEXT. Nombre normalizado para buscar (ver `nombre_norm`)
  tipo          TEXT. `clave:valor` de OSM: place:city, highway:residential, natural:beach, amenity:restaurant...
                (`clave` sola si el valor es `yes`)
  categoria     TEXT. Categoria propia en español:
                  lugares: ciudad | pueblo | aldea | barrio | paraje
                  calles:  calle
                  POIs:    playa | cala | cabo | pico | mirador | gasolinera | aparcamiento | restaurante | cafeteria |
                           hotel | faro | monasterio | iglesia | museo | castillo | puerto | aeropuerto | hospital |
                           farmacia | supermercado | otro
  municipio     TEXT. Municipio (relacion boundary=administrative + admin_level=8) o cadena vacia
  lat, lon      REAL. Grados decimales (6 decimales)
  importancia   INTEGER. Para ordenar (mayor = mas importante): ciudad 100 > pueblo 90/80 > aldea 60 > barrio 50 >
                paraje 45 > playa/pico/cala/cabo 40 > aeropuerto 38 > POIs 36-30 > calles 20-10

Funcion `nombre_norm(texto)` (la app la replica en Kotlin con los mismos casos de test; ver test_scripts.py):
  1. minusculas (`str.lower`)
  2. `l·l` y `ŀl` (ele geminada catalana, U+00B7 / U+0140) -> `ll`
  3. descomposicion Unicode NFD y se quitan las marcas combinantes (diacriticos)
  4. apostrofos (' ’ ʼ ` ´), guiones (- ‐ ‑ – —) y cualquier `·` restante -> espacio
  5. espacios colapsados (varios -> uno) y recortados por los extremos
  Ejemplos: «Sóller» -> «soller», «Cala d'Or» -> «cala d or», «Col·legi» -> «collegi».
Busqueda: la consulta se normaliza igual. Prefijo del nombre (usa el indice):
  SELECT nombre, categoria, municipio, lat, lon FROM lugares
  WHERE nombre_norm >= 'soll' AND nombre_norm < 'solm' ORDER BY importancia DESC LIMIT 20;
Prefijo de cualquier palabra (sin indice): `nombre_norm LIKE 'soll%' OR nombre_norm LIKE '% soll%'`.

Municipio de cada punto: punto en poligono contra los municipios (admin_level=8). El poligono se indexa por bandas de
latitud para que cada consulta recorra pocas aristas; los puntos fuera de todo poligono (p. ej. en el mar) quedan con
municipio vacio. Calles: una fila por (nombre, municipio), en el punto de la via mas cercano al centro del conjunto
de sus vias, que es el punto medio de la via (por longitud).

Datos © OpenStreetMap contributors (ODbL). `osmium` (pyosmium) solo se importa al ejecutar, para que las pruebas de
las partes puras corran sin el.
"""

import argparse
import math
import os
import sqlite3
import sys
import unicodedata

# ---------------------------------------------------------------------------------------------------------------
# Clasificacion (funciones puras)
# ---------------------------------------------------------------------------------------------------------------

# place=* -> (categoria, importancia)
LUGARES = {
    "city": ("ciudad", 100),
    "town": ("pueblo", 90),
    "village": ("pueblo", 80),
    "hamlet": ("aldea", 60),
    "neighbourhood": ("barrio", 50),
    "locality": ("paraje", 45),
}
# natural=* -> (categoria, importancia). `beach` pasa a `cala` si el nombre empieza por «Cala»/«Caló».
NATURALES = {"beach": ("playa", 40), "peak": ("pico", 40), "bay": ("cala", 40), "cape": ("cabo", 40)}
# Clave OSM -> importancia de un POI generico. El orden decide la clave que gana si un objeto lleva varias.
CLAVES_POI = (("tourism", 36), ("historic", 35), ("amenity", 32), ("leisure", 31), ("shop", 30))
# (clave, valor) -> categoria propia; lo demas es «otro». Gana la primera que coincida.
CATEGORIAS = (
    (("natural", "beach"), "playa"), (("natural", "bay"), "cala"), (("natural", "cape"), "cabo"),
    (("natural", "peak"), "pico"), (("tourism", "viewpoint"), "mirador"), (("amenity", "fuel"), "gasolinera"),
    (("amenity", "parking"), "aparcamiento"), (("amenity", "restaurant"), "restaurante"),
    (("amenity", "cafe"), "cafeteria"), (("tourism", "hotel"), "hotel"), (("tourism", "hostel"), "hotel"),
    (("tourism", "guest_house"), "hotel"), (("tourism", "motel"), "hotel"),
    (("man_made", "lighthouse"), "faro"), (("amenity", "monastery"), "monasterio"),
    (("historic", "monastery"), "monasterio"), (("amenity", "place_of_worship"), "iglesia"),
    (("tourism", "museum"), "museo"), (("historic", "castle"), "castillo"), (("historic", "fort"), "castillo"),
    (("leisure", "marina"), "puerto"), (("aeroway", "aerodrome"), "aeropuerto"),
    (("amenity", "hospital"), "hospital"), (("amenity", "pharmacy"), "farmacia"),
    (("shop", "supermarket"), "supermercado"),
)
# Valores sin interes para buscar aunque tengan nombre.
POI_EXCLUIDOS = {
    "amenity": {"bench", "waste_basket", "parking_space", "bicycle_parking", "motorcycle_parking", "waste_disposal"},
}
INFORMACION_EXCLUIDA = {"guidepost", "board", "map", "route_marker"}
# highway=* sin nombre util para buscar o que no existe todavia.
VIAS_EXCLUIDAS = {"proposed", "construction", "razed", "abandoned", "platform"}
IMPORTANCIA_VIA = {
    "motorway": 20, "trunk": 20, "primary": 19, "secondary": 18, "tertiary": 17,
    "unclassified": 15, "residential": 15, "living_street": 14, "pedestrian": 13, "service": 11,
}
IMPORTANCIA_VIA_DEFECTO = 10
VERSION_ESQUEMA = 2
CATEGORIAS_FIJAS = {"ciudad", "pueblo", "aldea", "barrio", "paraje", "calle"}


def limpio(valor) -> str:
    return "" if valor is None else " ".join(str(valor).replace("\t", " ").split())


_APOSTROFOS_Y_GUIONES = str.maketrans({c: " " for c in "'’ʼ`´-‐‑–—·"})


def nombre_norm(texto: str) -> str:
    """Nombre normalizado para buscar (pasos exactos en el docstring del modulo)."""
    t = texto.lower().replace("l·l", "ll").replace("ŀl", "ll")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    return " ".join(t.translate(_APOSTROFOS_Y_GUIONES).split())


def nombres_de(etiquetas) -> list[str]:
    """`name` y, si difiere de verdad, `name:es` (el mapa muestra los nombres en español)."""
    nombre = limpio(etiquetas.get("name"))
    if not nombre:
        return []
    nombres = [nombre]
    alternativo = limpio(etiquetas.get("name:es"))
    if alternativo and nombre_norm(alternativo) != nombre_norm(nombre):
        nombres.append(alternativo)
    return nombres


def clasificar_lugar(etiquetas) -> tuple[str, str, int] | None:
    """place=city|town|village|hamlet|locality|neighbourhood -> (tipo, categoria, importancia)."""
    valor = etiquetas.get("place")
    if valor not in LUGARES:
        return None
    categoria, importancia = LUGARES[valor]
    return f"place:{valor}", categoria, importancia


def categoria_poi(etiquetas, clave_elegida: str | None = None) -> str:
    """Categoria en español de un POI segun sus etiquetas («otro» si no hay una propia).

    `clave_elegida`: la clave que decidio el `tipo` (solo cuenta esa; si es None, valen todas).
    """
    for (clave, valor), categoria in CATEGORIAS:
        if clave_elegida is not None and clave != clave_elegida:
            continue
        if etiquetas.get(clave) == valor:
            if (clave, valor) == ("natural", "beach") and nombre_norm(limpio(etiquetas.get("name"))).startswith(
                    ("cala ", "calo ")):
                return "cala"
            return categoria
    return "otro"


def clasificar_poi(etiquetas) -> tuple[str, str, int] | None:
    """POI con nombre -> (tipo, categoria, importancia).

    Admite natural=beach|peak|bay|cape, man_made=lighthouse, aeroway=aerodrome, tourism, historic, amenity, leisure, shop.
    """
    natural = etiquetas.get("natural")
    if natural in NATURALES:
        return f"natural:{natural}", categoria_poi(etiquetas, "natural"), NATURALES[natural][1]
    if etiquetas.get("man_made") == "lighthouse":
        return "man_made:lighthouse", "faro", 36
    if etiquetas.get("aeroway") == "aerodrome":
        return "aeroway:aerodrome", "aeropuerto", 38
    for clave, importancia in CLAVES_POI:
        valor = etiquetas.get(clave)
        if not valor or valor == "no":
            continue
        if valor in POI_EXCLUIDOS.get(clave, ()):
            continue
        if clave == "tourism" and etiquetas.get("information") in INFORMACION_EXCLUIDA:
            continue
        # «yes» no aporta nada como tipo
        return (clave if valor == "yes" else f"{clave}:{valor}"), categoria_poi(etiquetas, clave), importancia
    return None


def clasificar_calle(etiquetas) -> int | None:
    """highway=* con nombre -> importancia (None si no es una calle buscable)."""
    via = etiquetas.get("highway")
    if not via or via in VIAS_EXCLUIDAS:
        return None
    return IMPORTANCIA_VIA.get(via, IMPORTANCIA_VIA_DEFECTO)


# ---------------------------------------------------------------------------------------------------------------
# Geometria (funciones puras). Puntos como (lon, lat).
# ---------------------------------------------------------------------------------------------------------------

def distancia_m(a, b) -> float:
    """Distancia aproximada (equirectangular) en metros; sobra para ordenar puntos de una misma isla."""
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat)
    dy = math.radians(b[1] - a[1])
    return 6371000.0 * math.hypot(dx, dy)


def punto_medio(puntos):
    """Punto situado a la mitad de la longitud de la polilinea."""
    if len(puntos) == 1:
        return puntos[0]
    tramos = [distancia_m(puntos[i], puntos[i + 1]) for i in range(len(puntos) - 1)]
    mitad = sum(tramos) / 2
    recorrido = 0.0
    for i, largo in enumerate(tramos):
        if recorrido + largo >= mitad:
            f = 0.0 if largo == 0 else (mitad - recorrido) / largo
            a, b = puntos[i], puntos[i + 1]
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        recorrido += largo
    return puntos[-1]


def centroide(puntos):
    """Media de los vertices: suficiente para situar un POI dibujado como area."""
    return (sum(p[0] for p in puntos) / len(puntos), sum(p[1] for p in puntos) / len(puntos))


def representante(puntos):
    """De varios puntos (uno por via), el mas cercano a su centro: una calle partida en tramos queda en uno de ellos."""
    if len(puntos) == 1:
        return puntos[0]
    centro = centroide(puntos)
    return min(puntos, key=lambda p: distancia_m(p, centro))


class Anillo:
    """Poligono cerrado con aristas indexadas por bandas de latitud para acelerar el punto en poligono."""

    def __init__(self, puntos, bandas: int | None = None):
        self.min_lon = min(p[0] for p in puntos)
        self.max_lon = max(p[0] for p in puntos)
        self.min_lat = min(p[1] for p in puntos)
        self.max_lat = max(p[1] for p in puntos)
        n = len(puntos)
        self.n_bandas = bandas if bandas else max(1, min(128, n // 16))
        self.alto = (self.max_lat - self.min_lat) or 1e-12
        self.bandas = [[] for _ in range(self.n_bandas)]
        for i in range(n):
            x1, y1 = puntos[i]
            x2, y2 = puntos[(i + 1) % n]
            if y1 == y2:
                continue  # las aristas horizontales no cruzan el rayo
            b0, b1 = sorted((self._banda(y1), self._banda(y2)))
            for b in range(b0, b1 + 1):
                self.bandas[b].append((x1, y1, x2, y2))

    def _banda(self, lat: float) -> int:
        return min(self.n_bandas - 1, max(0, int((lat - self.min_lat) / self.alto * self.n_bandas)))

    def contiene(self, lon: float, lat: float) -> bool:
        if not (self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat):
            return False
        dentro = False
        for x1, y1, x2, y2 in self.bandas[self._banda(lat)]:
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                dentro = not dentro
        return dentro


class Municipio:
    """Nombre y partes (anillo exterior + huecos) de un municipio."""

    def __init__(self, nombre: str):
        self.nombre = nombre
        self.partes: list[tuple[Anillo, list[Anillo]]] = []

    def anadir_parte(self, exterior, huecos) -> None:
        if len(exterior) >= 3:
            self.partes.append((Anillo(exterior), [Anillo(h) for h in huecos if len(h) >= 3]))

    def contiene(self, lon: float, lat: float) -> bool:
        for exterior, huecos in self.partes:
            if exterior.contiene(lon, lat) and not any(h.contiene(lon, lat) for h in huecos):
                return True
        return False


def municipio_de(lon: float, lat: float, municipios) -> str:
    """Nombre del municipio que contiene el punto, o cadena vacia."""
    for m in municipios:
        if m.contiene(lon, lat):
            return m.nombre
    return ""


# ---------------------------------------------------------------------------------------------------------------
# Salida SQLite
# ---------------------------------------------------------------------------------------------------------------

def escribir_sqlite(ruta: str, filas) -> int:
    """Escribe la tabla `lugares` en `ruta` (via un temporal y os.replace). Devuelve el numero de filas.

    Cada fila: (nombre, tipo, categoria, municipio, lat, lon, importancia); `nombre_norm` se calcula aqui.
    """
    temporal = ruta + ".tmp"
    if os.path.exists(temporal):
        os.remove(temporal)
    con = sqlite3.connect(temporal)
    try:
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        con.execute(
            "CREATE TABLE lugares (nombre TEXT NOT NULL, nombre_norm TEXT NOT NULL, tipo TEXT NOT NULL, "
            "categoria TEXT NOT NULL, municipio TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, "
            "importancia INTEGER NOT NULL)"
        )
        con.executemany(
            "INSERT INTO lugares (nombre, nombre_norm, tipo, categoria, municipio, lat, lon, importancia) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ((f[0], nombre_norm(f[0]), f[1], f[2], f[3], f[4], f[5], f[6]) for f in filas),
        )
        con.execute("CREATE INDEX lugares_nombre_norm ON lugares (nombre_norm)")
        con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        con.commit()
        total = con.execute("SELECT count(*) FROM lugares").fetchone()[0]
        con.execute("VACUUM")
    finally:
        con.close()
    os.replace(temporal, ruta)
    return total


# ---------------------------------------------------------------------------------------------------------------
# Lectura del PBF (pyosmium). VERIFICAR en CI la primera vez: no se ha podido ejecutar fuera de Actions.
# ---------------------------------------------------------------------------------------------------------------

def _crear_handlers():
    import osmium  # noqa: PLC0415  (import diferido: las pruebas no lo necesitan)

    class Limites(osmium.SimpleHandler):
        """Municipios: areas con boundary=administrative y admin_level=8."""

        def __init__(self):
            super().__init__()
            self.por_nombre: dict[str, Municipio] = {}

        def area(self, a):
            etiquetas = a.tags
            if etiquetas.get("boundary") != "administrative" or etiquetas.get("admin_level") != "8":
                return
            nombre = limpio(etiquetas.get("name"))
            if not nombre:
                return
            municipio = self.por_nombre.setdefault(nombre, Municipio(nombre))
            for exterior in a.outer_rings():
                anillo = [(n.lon, n.lat) for n in exterior]
                huecos = [[(n.lon, n.lat) for n in interior] for interior in a.inner_rings(exterior)]
                municipio.anadir_parte(anillo, huecos)

    class Lugares(osmium.SimpleHandler):
        """Lugares, POIs y calles con nombre (nodos y vias; las relaciones/multipoligonos no se leen)."""

        def __init__(self, municipios):
            super().__init__()
            self.municipios = municipios
            self.filas: set[tuple] = set()
            self.calles: dict[tuple[str, str], list] = {}

        def _fila(self, nombre, tipo, categoria, lon, lat, importancia):
            municipio = municipio_de(lon, lat, self.municipios)
            self.filas.add((nombre, tipo, categoria, municipio, round(lat, 6), round(lon, 6), importancia))

        def _objeto(self, etiquetas, lon, lat):
            nombres = nombres_de(etiquetas)
            if not nombres:
                return
            lugar = clasificar_lugar(etiquetas) or clasificar_poi(etiquetas)
            if lugar:
                for nombre in nombres:
                    self._fila(nombre, lugar[0], lugar[1], lon, lat, lugar[2])

        def node(self, n):
            if not n.tags or not n.location.valid():
                return
            self._objeto(n.tags, n.location.lon, n.location.lat)

        def way(self, w):
            etiquetas = w.tags
            if not etiquetas.get("name"):
                return
            puntos = [(n.location.lon, n.location.lat) for n in w.nodes if n.location.valid()]
            if not puntos:
                return
            importancia = clasificar_calle(etiquetas)
            if importancia is not None:
                lon, lat = punto_medio(puntos)
                municipio = municipio_de(lon, lat, self.municipios)
                for nombre in nombres_de(etiquetas):
                    grupo = self.calles.setdefault((nombre, municipio), [[], -1, ""])
                    grupo[0].append((lon, lat))
                    if importancia > grupo[1]:  # el tipo de la via mas importante del grupo
                        grupo[1], grupo[2] = importancia, f"highway:{etiquetas.get('highway')}"
                return
            # POI dibujado como area o linea: se coloca en el centro de sus vertices
            lon, lat = centroide(puntos)
            self._objeto(etiquetas, lon, lat)

    return Limites, Lugares


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("entrada", help="PBF de Mallorca")
    p.add_argument("salida", help="busqueda-mallorca.sqlite")
    p.add_argument("--limites", help="PBF con las relaciones admin_level=8 y sus miembros (por defecto, la entrada)")
    args = p.parse_args()

    Limites, Lugares = _crear_handlers()
    limites = Limites()
    limites.apply_file(args.limites or args.entrada, locations=True)
    municipios = sorted(limites.por_nombre.values(), key=lambda m: m.nombre)
    print(f"municipios: {len(municipios)}")
    if not municipios:
        print("::error::No se ha podido construir ningun municipio (admin_level=8); revisa --limites", file=sys.stderr)
        return 1

    lugares = Lugares(municipios)
    lugares.apply_file(args.entrada, locations=True)

    filas = set(lugares.filas)
    for (nombre, municipio), (puntos, importancia, tipo) in lugares.calles.items():
        lon, lat = representante(puntos)
        filas.add((nombre, tipo, "calle", municipio, round(lat, 6), round(lon, 6), importancia))
    filas = sorted(filas, key=lambda f: (-f[6], f[0], f[3], f[1]))

    total = escribir_sqlite(args.salida, filas)
    por_tipo: dict[str, int] = {}
    for f in filas:
        clave = f[2] if f[2] in CATEGORIAS_FIJAS else "poi"
        por_tipo[clave] = por_tipo.get(clave, 0) + 1
    sin_municipio = sum(1 for f in filas if not f[3])
    print(f"filas: {total} ({', '.join(f'{k} {v}' for k, v in sorted(por_tipo.items()))}); sin municipio: {sin_municipio}")
    print(f"{args.salida}: {os.path.getsize(args.salida)} bytes")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
