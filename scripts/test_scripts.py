"""Pruebas de los scripts sin red: python -I -m unittest discover -s scripts -p 'test_*.py'"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import busqueda  # noqa: E402
import manifest  # noqa: E402
import satelite  # noqa: E402

MALLORCA = (2.30, 39.26, 3.50, 39.97)


class TeselasTest(unittest.TestCase):
    def test_palma_en_z16_es_la_tesela_conocida(self):
        # Catedral de Palma (39.5675, 2.6483): tesela XYZ 16/33250/24913 (comprobada con log(tan(π/4 + φ/2))).
        self.assertEqual(satelite.lon_a_x(2.6483, 16), 33250)
        self.assertEqual(satelite.lat_a_y(39.5675, 16), 24913)

    def test_fila_tms_invierte_el_eje_y(self):
        self.assertEqual(satelite.fila_tms(0, 0), 0)
        self.assertEqual(satelite.fila_tms(16, 24913), 2**16 - 1 - 24913)

    def test_z0_es_una_sola_tesela_y_el_total_es_razonable(self):
        lista = list(satelite.teselas(MALLORCA, 0, 16))
        self.assertEqual([t for t in lista if t[0] == 0], [(0, 0, 0)])
        self.assertEqual(len(lista), len(set(lista)))
        self.assertTrue(40_000 < len(lista) < 60_000, len(lista))

    def test_es_jpeg(self):
        self.assertTrue(satelite.es_jpeg(b"\xff\xd8\xff\xe0resto"))
        self.assertFalse(satelite.es_jpeg(b"<html>"))


class ManifestTest(unittest.TestCase):
    def test_construye_entradas_con_hash_tamano_y_url(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            m = manifest.construir(carpeta, "2026.10.28-1", "datos-2026.10.28-1", "o/r", "2026.10.01-1", "T")
        self.assertEqual(m["esquema"], 1)
        self.assertEqual({a["id"] for a in m["archivos"]}, {"vectorial", "estilo", "vias", "satelite"})
        vect = next(a for a in m["archivos"] if a["id"] == "vectorial")
        self.assertEqual(vect["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(vect["bytes"], 3)
        self.assertEqual(vect["url"], "https://github.com/o/r/releases/download/datos-2026.10.28-1/mallorca.pmtiles")
        self.assertEqual(vect["version"], "2026.10.28-1")
        sat = next(a for a in m["archivos"] if a["id"] == "satelite")
        self.assertEqual(sat["version"], "2026.10.01-1")
        json.dumps(m)

    def test_valhalla_es_opcional_y_se_incluye_si_existe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            sin = manifest.construir(carpeta, "2026.10.28-1", "datos-2026.10.28-1", "o/r", None, "T")
            with open(os.path.join(carpeta, "valhalla-mallorca.tar"), "wb") as f:
                f.write(b"abc")
            con = manifest.construir(carpeta, "2026.10.28-1", "datos-2026.10.28-1", "o/r", None, "T")
        self.assertNotIn("valhalla", {a["id"] for a in sin["archivos"]})
        valhalla = next(a for a in con["archivos"] if a["id"] == "valhalla")
        self.assertEqual(valhalla["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(valhalla["atribucion"], "© OpenStreetMap contributors")
        self.assertEqual(
            valhalla["url"], "https://github.com/o/r/releases/download/datos-2026.10.28-1/valhalla-mallorca.tar")
        self.assertEqual({a["id"] for a in con["archivos"]} - {a["id"] for a in sin["archivos"]}, {"valhalla"})

    def test_archivo_obligatorio_ausente_falla(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with self.assertRaises(OSError):
                manifest.construir(carpeta, "v", "t", "o/r", None, "T")

    def test_busqueda_relieve_y_curvas_son_opcionales_con_su_atribucion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            sin = manifest.construir(carpeta, "2026.10.28-1", "datos-2026.10.28-1", "o/r", None, "T")
            for nombre in ("busqueda-mallorca.sqlite", "relieve-mallorca.pmtiles", "curvas-mallorca.pmtiles"):
                with open(os.path.join(carpeta, nombre), "wb") as f:
                    f.write(b"abc")
            con = manifest.construir(carpeta, "2026.10.28-1", "datos-2026.10.28-1", "o/r", None, "T")
        self.assertEqual(manifest.OPCIONALES, {"valhalla", "busqueda", "relieve", "curvas"})
        self.assertTrue({"busqueda", "relieve", "curvas"}.isdisjoint({a["id"] for a in sin["archivos"]}))
        por_id = {a["id"]: a for a in con["archivos"]}
        self.assertEqual(por_id["busqueda"]["atribucion"], "© OpenStreetMap contributors")
        self.assertEqual(por_id["busqueda"]["licencia"], "ODbL-1.0")
        self.assertEqual(por_id["relieve"]["atribucion"], "MDT05 CC-BY 4.0 scne.es")
        self.assertEqual(por_id["curvas"]["licencia"], "CC-BY-4.0")
        self.assertEqual(
            por_id["curvas"]["url"], "https://github.com/o/r/releases/download/datos-2026.10.28-1/curvas-mallorca.pmtiles")
        self.assertEqual(por_id["relieve"]["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class ClasificacionBusquedaTest(unittest.TestCase):
    def test_lugares_por_place(self):
        self.assertEqual(busqueda.clasificar_lugar({"place": "city"}), ("place:city", "ciudad", 100))
        self.assertEqual(busqueda.clasificar_lugar({"place": "village"}), ("place:village", "pueblo", 80))
        self.assertEqual(busqueda.clasificar_lugar({"place": "town"})[1], "pueblo")
        self.assertEqual(busqueda.clasificar_lugar({"place": "hamlet"})[1], "aldea")
        self.assertEqual(busqueda.clasificar_lugar({"place": "neighbourhood"})[1], "barrio")
        self.assertEqual(busqueda.clasificar_lugar({"place": "locality"})[1], "paraje")
        self.assertIsNone(busqueda.clasificar_lugar({"place": "island"}))
        self.assertIsNone(busqueda.clasificar_lugar({"amenity": "cafe"}))

    def test_orden_de_importancia_ciudad_pueblo_poi_calle(self):
        ciudad = busqueda.clasificar_lugar({"place": "city"})[2]
        pueblo = busqueda.clasificar_lugar({"place": "town"})[2]
        aldea = busqueda.clasificar_lugar({"place": "hamlet"})[2]
        poi = busqueda.clasificar_poi({"amenity": "restaurant"})[2]
        playa = busqueda.clasificar_poi({"natural": "beach"})[2]
        calle_mayor = busqueda.clasificar_calle({"highway": "primary"})
        calle_menor = busqueda.clasificar_calle({"highway": "footway"})
        self.assertGreater(ciudad, pueblo)
        self.assertGreater(pueblo, aldea)
        self.assertGreater(aldea, playa)
        self.assertGreater(playa, poi)
        self.assertGreater(poi, calle_mayor)
        self.assertGreater(calle_mayor, calle_menor)

    def test_pois_tipo_categoria_e_importancia(self):
        casos = [
            ({"natural": "peak"}, ("natural:peak", "pico", 40)),
            ({"natural": "bay"}, ("natural:bay", "cala", 40)),
            ({"natural": "cape"}, ("natural:cape", "cabo", 40)),
            ({"natural": "beach", "name": "Platja de Muro"}, ("natural:beach", "playa", 40)),
            ({"natural": "beach", "name": "Cala Agulla"}, ("natural:beach", "cala", 40)),
            ({"natural": "beach", "name": "Caló des Moro"}, ("natural:beach", "cala", 40)),
            ({"tourism": "viewpoint"}, ("tourism:viewpoint", "mirador", 36)),
            ({"tourism": "hotel", "amenity": "restaurant"}, ("tourism:hotel", "hotel", 36)),
            ({"tourism": "hostel"}, ("tourism:hostel", "hotel", 36)),
            ({"tourism": "museum"}, ("tourism:museum", "museo", 36)),
            ({"amenity": "fuel"}, ("amenity:fuel", "gasolinera", 32)),
            ({"amenity": "parking"}, ("amenity:parking", "aparcamiento", 32)),
            ({"amenity": "restaurant"}, ("amenity:restaurant", "restaurante", 32)),
            ({"amenity": "cafe"}, ("amenity:cafe", "cafeteria", 32)),
            ({"amenity": "place_of_worship"}, ("amenity:place_of_worship", "iglesia", 32)),
            ({"amenity": "monastery"}, ("amenity:monastery", "monasterio", 32)),
            ({"historic": "monastery"}, ("historic:monastery", "monasterio", 35)),
            ({"historic": "castle"}, ("historic:castle", "castillo", 35)),
            ({"amenity": "hospital"}, ("amenity:hospital", "hospital", 32)),
            ({"amenity": "pharmacy"}, ("amenity:pharmacy", "farmacia", 32)),
            ({"shop": "supermarket"}, ("shop:supermarket", "supermercado", 30)),
            ({"shop": "bakery"}, ("shop:bakery", "otro", 30)),
            ({"leisure": "marina"}, ("leisure:marina", "puerto", 31)),
            ({"leisure": "yes"}, ("leisure", "otro", 31)),
            ({"man_made": "lighthouse"}, ("man_made:lighthouse", "faro", 36)),
            ({"aeroway": "aerodrome"}, ("aeroway:aerodrome", "aeropuerto", 38)),
        ]
        for etiquetas, esperado in casos:
            self.assertEqual(busqueda.clasificar_poi(etiquetas), esperado, etiquetas)

    def test_pois_excluidos(self):
        self.assertIsNone(busqueda.clasificar_poi({"natural": "tree"}))
        self.assertIsNone(busqueda.clasificar_poi({"amenity": "bench"}))
        self.assertIsNone(busqueda.clasificar_poi({"tourism": "information", "information": "guidepost"}))
        self.assertEqual(
            busqueda.clasificar_poi({"tourism": "information", "information": "office"}),
            ("tourism:information", "otro", 36))
        self.assertIsNone(busqueda.clasificar_poi({"shop": "no"}))

    def test_categorias_son_las_acordadas(self):
        acordadas = {
            "playa", "cala", "cabo", "pico", "mirador", "gasolinera", "aparcamiento", "restaurante", "cafeteria", "hotel",
            "faro", "monasterio", "iglesia", "museo", "castillo", "puerto", "aeropuerto", "hospital", "farmacia",
            "supermercado", "otro"}
        usadas = {c for _, c in busqueda.CATEGORIAS} | {c for c, _ in busqueda.NATURALES.values()} | {"otro"}
        self.assertEqual(usadas, acordadas)

    def test_calles(self):
        self.assertEqual(busqueda.clasificar_calle({"highway": "residential"}), 15)
        self.assertEqual(busqueda.clasificar_calle({"highway": "track"}), busqueda.IMPORTANCIA_VIA_DEFECTO)
        self.assertIsNone(busqueda.clasificar_calle({"highway": "construction"}))
        self.assertIsNone(busqueda.clasificar_calle({"building": "yes"}))

    def test_nombres_incluye_name_es_solo_si_difiere(self):
        self.assertEqual(busqueda.nombres_de({}), [])
        self.assertEqual(busqueda.nombres_de({"name": "  Sóller "}), ["Sóller"])
        self.assertEqual(busqueda.nombres_de({"name": "Sóller", "name:es": "Soller"}), ["Sóller"])
        self.assertEqual(busqueda.nombres_de({"name": "Alcúdia", "name:es": "Alcudia"}), ["Alcúdia"])
        self.assertEqual(
            busqueda.nombres_de({"name": "Sant Elm", "name:es": "San Telmo"}), ["Sant Elm", "San Telmo"])

    def test_limpio_quita_tabuladores_y_espacios_repetidos(self):
        self.assertEqual(busqueda.limpio("Carrer\tMajor   12"), "Carrer Major 12")
        self.assertEqual(busqueda.limpio(None), "")


# Casos compartidos con la app (Kotlin): la misma tabla debe dar las mismas salidas.
CASOS_NOMBRE_NORM = [
    ("Sóller", "soller"),
    ("Cala d'Or", "cala d or"),
    ("Cala d’Or", "cala d or"),
    ("Coll de sa Batalla", "coll de sa batalla"),
    ("Ses Salines", "ses salines"),
    ("Port d'Andratx", "port d andratx"),
    ("Sa Pobla", "sa pobla"),
    ("Col·legi", "collegi"),
    ("COL·LEGI Públic", "collegi public"),
    ("Paŀlada", "pallada"),
    ("Sant-Jordi", "sant jordi"),
    ("S'Arenal", "s arenal"),
    ("Pollença", "pollenca"),
    ("Alcúdia", "alcudia"),
    ("Caló des Moro", "calo des moro"),
    ("  Carrer   de\tla  Lluna ", "carrer de la lluna"),
    ("Ma-13", "ma 13"),
    ("Es Pil·larí", "es pillari"),
    ("", ""),
]


class NombreNormTest(unittest.TestCase):
    def test_tabla_de_casos(self):
        for entrada, esperado in CASOS_NOMBRE_NORM:
            self.assertEqual(busqueda.nombre_norm(entrada), esperado, entrada)

    def test_es_idempotente(self):
        for entrada, _ in CASOS_NOMBRE_NORM:
            normal = busqueda.nombre_norm(entrada)
            self.assertEqual(busqueda.nombre_norm(normal), normal)


class GeometriaBusquedaTest(unittest.TestCase):
    def test_punto_medio_por_longitud(self):
        # Tramos de 1 y 3 milesimas de grado: la mitad (2) cae en el segundo tramo.
        lon, lat = busqueda.punto_medio([(3.0, 39.5), (3.0, 39.501), (3.0, 39.504)])
        self.assertAlmostEqual(lon, 3.0)
        self.assertAlmostEqual(lat, 39.502, places=6)
        self.assertEqual(busqueda.punto_medio([(3.0, 39.5)]), (3.0, 39.5))
        self.assertEqual(busqueda.punto_medio([(3.0, 39.5), (3.0, 39.5)]), (3.0, 39.5))

    def test_representante_es_el_punto_mas_cercano_al_centro(self):
        puntos = [(2.0, 39.0), (2.5, 39.0), (3.0, 39.0)]
        self.assertEqual(busqueda.representante(puntos), (2.5, 39.0))
        self.assertEqual(busqueda.representante([(2.0, 39.0)]), (2.0, 39.0))

    def test_punto_en_anillo_por_bandas(self):
        cuadrado = [(0, 0), (10, 0), (10, 10), (0, 10)]
        anillo = busqueda.Anillo(cuadrado, bandas=4)
        for lat in (0.5, 3, 6, 9.5):
            self.assertTrue(anillo.contiene(5, lat), lat)
            self.assertFalse(anillo.contiene(11, lat), lat)
            self.assertFalse(anillo.contiene(-1, lat), lat)
        self.assertFalse(anillo.contiene(5, 10.5))

    def test_poligono_concavo(self):
        # «L»: el cuadrante superior derecho (5..10, 5..10) queda fuera.
        ele = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
        anillo = busqueda.Anillo(ele)
        self.assertTrue(anillo.contiene(2, 8))
        self.assertTrue(anillo.contiene(8, 2))
        self.assertFalse(anillo.contiene(8, 8))

    def test_municipio_con_hueco_enclave_y_varias_partes(self):
        a = busqueda.Municipio("A")
        a.anadir_parte([(0, 0), (10, 0), (10, 10), (0, 10)], [[(4, 4), (6, 4), (6, 6), (4, 6)]])
        a.anadir_parte([(20, 0), (22, 0), (22, 2), (20, 2)], [])
        enclave = busqueda.Municipio("B")
        enclave.anadir_parte([(4, 4), (6, 4), (6, 6), (4, 6)], [])
        municipios = [a, enclave]
        self.assertEqual(busqueda.municipio_de(1, 1, municipios), "A")
        self.assertEqual(busqueda.municipio_de(5, 5, municipios), "B")
        self.assertEqual(busqueda.municipio_de(21, 1, municipios), "A")
        self.assertEqual(busqueda.municipio_de(15, 1, municipios), "")

    def test_anillo_degenerado_no_rompe(self):
        anillo = busqueda.Anillo([(1, 1), (2, 1), (3, 1)])  # todo en la misma latitud
        self.assertFalse(anillo.contiene(2, 1.5))




class SqliteBusquedaTest(unittest.TestCase):
    # (nombre, tipo, categoria, municipio, lat, lon, importancia)
    FILAS = [
        ("Palma", "place:city", "ciudad", "Palma", 39.5696, 2.6502, 100),
        ("Sóller", "place:town", "pueblo", "Sóller", 39.7667, 2.7167, 90),
        ("Carrer de la Lluna", "highway:residential", "calle", "Sóller", 39.7661, 2.7150, 15),
        ("Cala d'Or", "place:village", "pueblo", "Santanyí", 39.3797, 3.2287, 80),
        ("Col·legi Públic", "amenity:school", "otro", "Palma", 39.57, 2.65, 32),
    ]

    def test_esquema_indice_y_busqueda_por_prefijo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "b.sqlite")
            self.assertEqual(busqueda.escribir_sqlite(ruta, self.FILAS), 5)
            self.assertFalse(os.path.exists(ruta + ".tmp"))
            con = sqlite3.connect(ruta)
            try:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
                columnas = [(r[1], r[2]) for r in con.execute("PRAGMA table_info(lugares)")]
                self.assertEqual(columnas, [
                    ("nombre", "TEXT"), ("nombre_norm", "TEXT"), ("tipo", "TEXT"), ("categoria", "TEXT"),
                    ("municipio", "TEXT"), ("lat", "REAL"), ("lon", "REAL"), ("importancia", "INTEGER")])
                indices = [r[1] for r in con.execute("PRAGMA index_list(lugares)")]
                self.assertEqual(indices, ["lugares_nombre_norm"])
                plan = " ".join(str(r) for r in con.execute(
                    "EXPLAIN QUERY PLAN SELECT nombre FROM lugares WHERE nombre_norm >= 'soll' AND nombre_norm < 'solm'"))
                self.assertIn("lugares_nombre_norm", plan)

                def buscar(prefijo):
                    sql = ("SELECT nombre FROM lugares WHERE nombre_norm >= ? AND nombre_norm < ? "
                           "ORDER BY importancia DESC")
                    return [r[0] for r in con.execute(sql, (prefijo, prefijo[:-1] + chr(ord(prefijo[-1]) + 1)))]

                self.assertEqual(buscar("soll"), ["Sóller"])
                self.assertEqual(buscar("cala d or"), ["Cala d'Or"])
                self.assertEqual(buscar("collegi"), ["Col·legi Públic"])
                self.assertEqual(buscar("pal"), ["Palma"])
                fila = con.execute(
                    "SELECT nombre_norm, tipo, categoria, municipio, typeof(lat), typeof(lon), typeof(importancia) "
                    "FROM lugares WHERE nombre = 'Palma'").fetchone()
                self.assertEqual(fila, ("palma", "place:city", "ciudad", "Palma", "real", "real", "integer"))
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
