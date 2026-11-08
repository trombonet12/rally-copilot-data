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
import pk  # noqa: E402
import radares  # noqa: E402
import satelite  # noqa: E402
import vias_notas  # noqa: E402

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

    def test_solo_z17_son_teselas_de_z17_y_cuatro_veces_las_de_z16(self):
        z16 = list(satelite.teselas(MALLORCA, 16, 16))
        z17 = list(satelite.teselas(MALLORCA, 17, 17))
        self.assertTrue(all(z == 17 for z, _, _ in z17))
        self.assertEqual(len(z17), len(set(z17)))
        self.assertTrue(3.8 * len(z16) < len(z17) < 4.3 * len(z16), (len(z16), len(z17)))
        # Catedral de Palma: su tesela z17 es hija de la z16 conocida (16/33250/24913).
        self.assertEqual(satelite.lon_a_x(2.6483, 17) // 2, 33250)
        self.assertEqual(satelite.lat_a_y(39.5675, 17) // 2, 24913)
        self.assertIn((17, satelite.lon_a_x(2.6483, 17), satelite.lat_a_y(39.5675, 17)), z17)

    def test_abrir_anota_el_rango_de_zoom_y_la_tabla_de_mar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            db = satelite.abrir(os.path.join(carpeta, "z17.mbtiles"), MALLORCA, 17, 17)
            meta = dict(db.execute("SELECT name, value FROM metadata"))
            tablas = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            db.close()
            por_defecto = satelite.abrir(os.path.join(carpeta, "z16.mbtiles"), MALLORCA, 16)
            meta16 = dict(por_defecto.execute("SELECT name, value FROM metadata"))
            por_defecto.close()
        self.assertEqual((meta["minzoom"], meta["maxzoom"]), ("17", "17"))
        self.assertEqual(meta["center"].split(",")[2], "17")
        self.assertEqual((meta16["minzoom"], meta16["maxzoom"]), ("0", "16"))
        self.assertEqual(meta16["center"].split(",")[2], "10")
        self.assertTrue({"tiles", "metadata", "sin_cobertura"} <= tablas)

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
        self.assertEqual(
            manifest.OPCIONALES,
            {"valhalla", "busqueda", "relieve", "curvas", "vias-notas", "radares", "pk", "satelite-z17",
             "voz-sharvard", "voz-sharvard-tokens"})
        self.assertTrue({"busqueda", "relieve", "curvas"}.isdisjoint({a["id"] for a in sin["archivos"]}))
        por_id = {a["id"]: a for a in con["archivos"]}
        self.assertEqual(por_id["busqueda"]["atribucion"], "© OpenStreetMap contributors")
        self.assertEqual(por_id["busqueda"]["licencia"], "ODbL-1.0")
        self.assertEqual(por_id["relieve"]["atribucion"], "MDT05 CC-BY 4.0 scne.es")
        self.assertEqual(por_id["curvas"]["licencia"], "CC-BY-4.0")
        self.assertEqual(
            por_id["curvas"]["url"], "https://github.com/o/r/releases/download/datos-2026.10.28-1/curvas-mallorca.pmtiles")
        self.assertEqual(por_id["relieve"]["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_satelite_z17_va_solo_en_manifest_extra_y_nunca_en_manifest(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            sin = manifest.construir(carpeta, "v", "t", "o/r", None, "T", None, separados=True)
            with open(os.path.join(carpeta, "pnoa-mallorca-z17.pmtiles"), "wb") as f:
                f.write(b"abc")
            principal = manifest.construir(carpeta, "2026.11.01-1", "datos-2026.11.01-1", "o/r", "2026.10.01-1", "T",
                                           "2026.10.15-3")
            extra = manifest.construir(carpeta, "2026.11.01-1", "datos-2026.11.01-1", "o/r", "2026.10.01-1", "T",
                                       "2026.10.15-3", separados=True)
        self.assertEqual(sin["archivos"], [])
        self.assertNotIn("satelite-z17", {a["id"] for a in principal["archivos"]})
        self.assertEqual([a["id"] for a in extra["archivos"]], ["satelite-z17"])
        z17 = extra["archivos"][0]
        self.assertEqual(z17["nombre"], "pnoa-mallorca-z17.pmtiles")
        self.assertEqual(z17["version"], "2026.10.15-3")
        self.assertEqual(z17["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(z17["licencia"], "CC-BY-4.0")
        self.assertEqual(z17["url"], "https://github.com/o/r/releases/download/datos-2026.11.01-1/pnoa-mallorca-z17.pmtiles")
        sat = next(a for a in principal["archivos"] if a["id"] == "satelite")
        self.assertEqual(sat["version"], "2026.10.01-1")

    def test_vectorial_reutilizado_conserva_su_version(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            nuevo = manifest.construir(carpeta, "2026.11.06-1", "datos-2026.11.06-1", "o/r", "2026.10.01-1", "T")
            reutil = manifest.construir(carpeta, "2026.11.06-1", "datos-2026.11.06-1", "o/r", "2026.10.01-1", "T",
                                        version_vectorial="2026.11.01-2")
        vec = {a["id"]: a for a in nuevo["archivos"]}["vectorial"]
        self.assertEqual(vec["version"], "2026.11.06-1")
        vec = {a["id"]: a for a in reutil["archivos"]}["vectorial"]
        self.assertEqual(vec["version"], "2026.11.01-2")
        self.assertEqual(vec["nombre"], "mallorca.pmtiles")
        self.assertEqual(vec["url"], "https://github.com/o/r/releases/download/datos-2026.11.06-1/mallorca.pmtiles")

    def test_radares_va_en_manifest_json_como_opcional_con_su_atribucion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            sin = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
            with open(os.path.join(carpeta, "radares-mallorca.tsv"), "wb") as f:
                f.write(b"abc")
            con = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
            extra = manifest.construir(carpeta, "v", "t", "o/r", None, "T", None, separados=True)
        self.assertNotIn("radares", {a["id"] for a in sin["archivos"]})
        self.assertNotIn("radares", manifest.SEPARADOS)
        self.assertEqual(extra["archivos"], [])
        r = next(a for a in con["archivos"] if a["id"] == "radares")
        self.assertEqual(r["nombre"], "radares-mallorca.tsv")
        self.assertEqual(r["licencia"], "CC-BY, ODbL-1.0")
        self.assertIn("DGT", r["atribucion"])
        self.assertIn("OpenStreetMap", r["atribucion"])

    def test_vias_notas_es_opcional_con_su_atribucion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            sin = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
            with open(os.path.join(carpeta, "vias-notas-mallorca.tsv.gz"), "wb") as f:
                f.write(b"abc")
            con = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
        self.assertNotIn("vias-notas", {a["id"] for a in sin["archivos"]})
        notas = next(a for a in con["archivos"] if a["id"] == "vias-notas")
        self.assertEqual(notas["nombre"], "vias-notas-mallorca.tsv.gz")
        self.assertEqual(notas["atribucion"], "© OpenStreetMap contributors; MDT05 CC-BY 4.0 scne.es")
        self.assertEqual(notas["licencia"], "ODbL-1.0, CC-BY-4.0")


class ViasNotasTest(unittest.TestCase):
    # 1000 millonésimas de grado de latitud = R * rad(0.001°) ≈ 111,195 m.
    def test_distancia_de_un_meridiano(self):
        self.assertAlmostEqual(vias_notas.distancia_m((39_000_000, 3_000_000), (39_001_000, 3_000_000)), 111.195, delta=0.01)

    def test_muestreo_cada_5_m_desde_el_primer_nodo_mas_el_ultimo(self):
        puntos = [(39_000_000, 3_000_000), (39_001_000, 3_000_000)]
        distancias, alturas = vias_notas.muestrear(puntos, lambda lat, lon: (lat - 39.0) * 1e5)
        total = vias_notas.distancia_m(*puntos)
        self.assertEqual(len(distancias), 24)  # ceil(111,195 / 5) = 23 muestras + el último punto
        self.assertEqual(distancias[:4], [0.0, 5.0, 10.0, 15.0])
        self.assertAlmostEqual(distancias[22], 110.0)
        self.assertAlmostEqual(distancias[-1], total)
        self.assertAlmostEqual(alturas[0], 0.0)
        self.assertAlmostEqual(alturas[1], 4.4966, delta=0.01)  # 5 m = 4,4966e-5° de latitud -> *1e5
        self.assertAlmostEqual(alturas[-1], 100.0, delta=0.01)  # 0,001° * 1e5

    def test_muestreo_con_una_esquina_sigue_la_polilinea(self):
        # Tramo norte de ~111,2 m y luego tramo este: la 2.ª muestra tras la esquina está al este de ella.
        puntos = [(39_000_000, 3_000_000), (39_001_000, 3_000_000), (39_001_000, 3_001_000)]
        pos = vias_notas.posiciones(puntos)
        esquina = vias_notas.distancia_m(puntos[0], puntos[1])
        despues = [p for p in pos if p[0] > esquina + 1e-9 and p is not pos[-1]]
        self.assertTrue(despues)
        for _, lat, lon in despues:
            self.assertAlmostEqual(lat, 39.001, places=6)
            self.assertGreater(lon, 3.0)
        total = esquina + vias_notas.distancia_m(puntos[1], puntos[2])
        self.assertAlmostEqual(pos[-1][0], total)
        self.assertAlmostEqual(pos[-1][2], 3.001, places=6)

    def test_polilineas_degeneradas(self):
        self.assertEqual(vias_notas.posiciones([]), [])
        self.assertEqual(vias_notas.posiciones([(39_000_000, 3_000_000)]), [(0.0, 39.0, 3.0)])
        iguales = vias_notas.posiciones([(39_000_000, 3_000_000), (39_000_000, 3_000_000)])
        self.assertEqual(iguales, [(0.0, 39.0, 3.0)])

    def test_codificacion_delta_y_ida_y_vuelta(self):
        self.assertEqual(vias_notas.codificar_delta([12.34, 12.36, 12.0, 11.5]), "123,1,-4,-5")
        self.assertEqual(vias_notas.codificar_delta([0.0]), "0")
        self.assertEqual(vias_notas.codificar_delta([-0.04, 0.0, 0.0]), "0,0,0")
        self.assertEqual(vias_notas.decodificar_delta("123,1,-4,-5"), [123, 124, 120, 115])
        alturas = [0.0, 3.26, 9.99, 9.99, 4.5, -0.3]
        dm = [vias_notas.decimetros(h) for h in alturas]
        self.assertEqual(vias_notas.decodificar_delta(vias_notas.codificar_delta(alturas)), dm)

    def test_puentes_y_tuneles_interpolan_entre_los_extremos(self):
        self.assertEqual(
            vias_notas.aplanar_puente([0, 5, 10, 15, 20], [10, 99, -5, 50, 20]), [10, 12.5, 15, 17.5, 20])
        # Última muestra a distancia no múltiplo de 5: la interpolación es por distancia, no por índice.
        interpolado = vias_notas.aplanar_puente([0, 5, 8], [0, 77, 8])
        self.assertAlmostEqual(interpolado[1], 5.0)
        self.assertEqual(vias_notas.aplanar_puente([0, 3], [4, 9]), [4, 9])

    def test_estructuras_desde_las_lineas_v(self):
        lineas = [
            "V\t1\tyes\t\t\t\t\t\t\n",
            "V\t2\t\tbuilding_passage\t\t\t\t\t\n",
            "V\t3\tno\tno\troundabout\t2\t\t\tasphalt\n",
            "V\t4\t\t\t\t\t\t\tgravel\n",
            "N\t39000000,3000000\tbump\n",
        ]
        self.assertEqual(vias_notas.ids_estructuras(lineas), {"1", "2"})

    def test_etiquetas_de_via(self):
        self.assertIsNone(vias_notas.campos_via({"highway": "primary", "name": "Ma-10"}))
        self.assertEqual(
            vias_notas.campos_via({"bridge": "viaduct", "lanes": "2", "surface": "asphalt", "width": "6\t5"}),
            ["viaduct", "", "", "2", "6 5", "", "asphalt"])
        self.assertEqual(
            vias_notas.campos_via({"junction": "roundabout", "hazard": "animals"}),
            ["", "", "roundabout", "", "", "animals", ""])

    def test_tipo_de_nodo(self):
        tipo = vias_notas.tipo_nodo
        self.assertEqual(tipo({"traffic_calming": "bump"}), "bump")
        self.assertEqual(tipo({"traffic_calming": "table"}), "table")
        self.assertEqual(tipo({"traffic_calming": "hump"}), "hump")
        self.assertIsNone(tipo({"traffic_calming": "no"}))
        self.assertEqual(tipo({"ford": "yes"}), "ford")
        self.assertIsNone(tipo({"ford": "no"}))
        self.assertEqual(tipo({"railway": "level_crossing"}), "level_crossing")
        self.assertIsNone(tipo({"railway": "station"}))
        for valor in ("stop", "give_way", "traffic_signals"):
            self.assertEqual(tipo({"highway": valor}), valor)
        self.assertIsNone(tipo({"highway": "crossing"}))
        self.assertEqual(tipo({"hazard": "animals"}), "hazard:animals")
        self.assertIsNone(tipo({"hazard": "no"}))
        self.assertIsNone(tipo({}))
        self.assertEqual(tipo({"highway": "stop", "traffic_calming": "bump"}), "bump")

    def test_lectura_de_via(self):
        linea = "42\tprimary\t90\t\t\tyes\tMa-10\tCarretera\t39000000,3000000;39001000,3000500\n"
        self.assertEqual(vias_notas.leer_via(linea), ("42", [(39_000_000, 3_000_000), (39_001_000, 3_000_500)]))

    def test_lectura_de_via_con_junction_bridge_tunnel_layer(self):
        linea = "42\tprimary\t90\t\t\tyes\tMa-10\tCarretera\t\tyes\t\t1\t39000000,3000000;39001000,3000500\n"
        self.assertEqual(vias_notas.leer_via(linea), ("42", [(39_000_000, 3_000_000), (39_001_000, 3_000_500)]))

    def test_bilineal(self):
        valores = {(0, 0): 0.0, (1, 0): 10.0, (0, 1): 20.0, (1, 1): 30.0}
        pixel = lambda c, f: valores[(c, f)]  # noqa: E731
        self.assertAlmostEqual(vias_notas.bilineal(pixel, 1.0, 1.0), 15.0)  # esquina común de los 4 píxeles
        self.assertAlmostEqual(vias_notas.bilineal(pixel, 0.5, 0.5), 0.0)  # centro del píxel (0, 0)
        self.assertAlmostEqual(vias_notas.bilineal(pixel, 1.0, 0.5), 5.0)


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
                    ("municipio", "TEXT"), ("lat", "REAL"), ("lon", "REAL"), ("importancia", "INTEGER"),
                    ("municipio_norm", "TEXT")])
                indices = [r[1] for r in con.execute("PRAGMA index_list(lugares)")]
                self.assertEqual(indices, ["lugares_nombre_norm"])
                self.assertEqual([(r[1], r[2], r[3], r[5]) for r in con.execute("PRAGMA table_info(palabras)")],
                                 [("palabra", "TEXT", 1, 1), ("lugar", "INTEGER", 1, 2)])  # (nombre, tipo, notnull, pk)
                self.assertIn("WITHOUT ROWID", con.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'palabras'").fetchone()[0])
                self.assertEqual(
                    con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'index' AND tbl_name = 'palabras' "
                                "AND sql IS NOT NULL").fetchone()[0], 0)  # ningun indice aparte
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


class PalabrasBusquedaTest(unittest.TestCase):
    FILAS = SqliteBusquedaTest.FILAS + [
        ("Hospital Universitari Son Espases", "amenity:hospital", "hospital", "Palma", 39.605, 2.605, 32),
        ("Carrer de Colom", "highway:residential", "calle", "Palma", 39.57, 2.65, 15),
        ("Plaça d'Es Born", "highway:pedestrian", "calle", "", 39.571, 2.651, 13),
    ]

    def test_palabras_de_normaliza_deduplica_y_quita_vacias(self):
        self.assertEqual(busqueda.palabras_de("Hospital Universitari Son Espases"),
                         ["hospital", "universitari", "son", "espases"])
        self.assertEqual(busqueda.palabras_de("Carrer de la Lluna", "Sóller"), ["carrer", "lluna", "soller"])
        self.assertEqual(busqueda.palabras_de("Cala d'Or", "Santanyí"), ["cala", "or", "santanyi"])
        self.assertEqual(busqueda.palabras_de("Sa Pobla", "Sa Pobla"), ["pobla"])
        self.assertEqual(busqueda.palabras_de("Es Pil·larí", ""), ["pillari"])
        self.assertEqual(busqueda.palabras_de("Es"), [])
        self.assertEqual(busqueda.palabras_de(""), [])

    def test_lista_de_palabras_vacias(self):
        self.assertEqual(
            sorted(busqueda.PALABRAS_VACIAS),
            sorted("de del la el les los las d l s sa es en i y a al".split()))

    def _abrir(self, carpeta):
        ruta = os.path.join(carpeta, "b.sqlite")
        busqueda.escribir_sqlite(ruta, self.FILAS)
        return sqlite3.connect(ruta)

    def test_palabras_del_nombre_y_del_municipio_enlazadas_por_rowid(self):
        with tempfile.TemporaryDirectory() as carpeta:
            con = self._abrir(carpeta)
            try:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
                por_lugar = {}
                for nombre, palabra in con.execute(
                        "SELECT l.nombre, p.palabra FROM palabras p JOIN lugares l ON l.rowid = p.lugar"):
                    por_lugar.setdefault(nombre, set()).add(palabra)
                self.assertEqual(por_lugar["Hospital Universitari Son Espases"],
                                 {"hospital", "universitari", "son", "espases", "palma"})
                self.assertEqual(por_lugar["Carrer de Colom"], {"carrer", "colom", "palma"})
                self.assertEqual(por_lugar["Plaça d'Es Born"], {"placa", "born"})  # sin municipio
                self.assertEqual(por_lugar["Cala d'Or"], {"cala", "or", "santanyi"})
                self.assertEqual(por_lugar["Palma"], {"palma"})
                vacias = tuple(busqueda.PALABRAS_VACIAS)
                self.assertEqual(con.execute(
                    f"SELECT count(*) FROM palabras WHERE palabra IN ({','.join('?' * len(vacias))}) OR palabra = ''",
                    vacias).fetchone()[0], 0)
                self.assertEqual(con.execute(
                    "SELECT count(*) FROM (SELECT 1 FROM palabras GROUP BY palabra, lugar HAVING count(*) > 1)"
                ).fetchone()[0], 0)
                self.assertEqual(
                    con.execute("SELECT municipio_norm FROM lugares WHERE nombre = ?", ("Sóller",)).fetchone()[0],
                    "soller")
                self.assertEqual(
                    con.execute("SELECT municipio_norm FROM lugares WHERE nombre = ?", ("Plaça d'Es Born",)).fetchone()[0],
                    "")
            finally:
                con.close()

    def test_busqueda_por_palabras_con_prefijo_y_usa_el_indice(self):
        def buscar(con, *consulta):
            sql = "SELECT nombre FROM lugares WHERE 1"
            args = []
            for palabra in consulta:
                sql += " AND rowid IN (SELECT lugar FROM palabras WHERE palabra >= ? AND palabra < ?)"
                args += [palabra, palabra[:-1] + chr(ord(palabra[-1]) + 1)]
            return [r[0] for r in con.execute(sql + " ORDER BY importancia DESC", args)]

        with tempfile.TemporaryDirectory() as carpeta:
            con = self._abrir(carpeta)
            try:
                self.assertEqual(buscar(con, "hospital", "espases"), ["Hospital Universitari Son Espases"])
                self.assertEqual(buscar(con, "espas", "hosp"), ["Hospital Universitari Son Espases"])
                self.assertEqual(buscar(con, "colom", "palma"), ["Carrer de Colom"])
                self.assertEqual(buscar(con, "colom", "soller"), [])
                self.assertEqual(buscar(con, "palma"), [
                    "Palma", "Col·legi Públic", "Hospital Universitari Son Espases", "Carrer de Colom"])
                plan = " ".join(str(r) for r in con.execute(
                    "EXPLAIN QUERY PLAN SELECT lugar FROM palabras WHERE palabra >= 'colo' AND palabra < 'colp'"))
                self.assertIn("PRIMARY KEY", plan)
            finally:
                con.close()


class GeometriaAreasTest(unittest.TestCase):
    def test_area_y_centroide_de_un_poligono(self):
        rectangulo = [(0, 0), (4, 0), (4, 2), (0, 2)]
        self.assertAlmostEqual(busqueda.area_anillo(rectangulo), 8)
        self.assertEqual(busqueda.centroide_poligono(rectangulo), (2.0, 1.0))
        self.assertEqual(busqueda.centroide_poligono(list(reversed(rectangulo))), (2.0, 1.0))
        # «L»: el centroide ponderado no es la media de los vertices
        ele = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
        x, y = busqueda.centroide_poligono(ele)
        self.assertAlmostEqual(x, 1.357143, places=5)
        self.assertAlmostEqual(y, 1.357143, places=5)
        # degenerado (area nula): media de vertices
        self.assertEqual(busqueda.centroide_poligono([(0, 0), (2, 0), (4, 0)]), (2.0, 0.0))

    def test_deduplica_mismo_nombre_a_menos_de_100_m(self):
        base = [
            ("Hospital Son Espases", "amenity:hospital", "hospital", "Palma", 39.6050, 2.6050, 32),
            ("Castell de Bellver", "historic:castle", "castillo", "Palma", 39.5600, 2.6200, 35),
            ("Carrer del Parc", "highway:residential", "calle", "Palma", 39.5700, 2.6500, 15),
        ]
        nuevas = {
            # ~11 m del nodo existente (con otra grafia): fuera
            ("Hôspital Son Espases", "amenity:hospital", "hospital", "Palma", 39.6051, 2.6050, 32),
            # mismo nombre pero a ~1,1 km: se queda
            ("Castell de Bellver", "historic:castle", "castillo", "Palma", 39.5700, 2.6200, 35),
            # mismo nombre que una calle, en el mismo sitio: una calle no la absorbe
            ("Carrer del Parc", "leisure:park", "otro", "Palma", 39.5700, 2.6500, 31),
            # dos areas iguales entre si: solo una
            ("Campus UIB", "amenity:university", "otro", "Palma", 39.6360, 2.6490, 32),
            ("Campus UIB", "amenity:university", "otro", "Palma", 39.6361, 2.6490, 32),
        }
        salida = busqueda.deduplicar_areas(base, nuevas)
        self.assertEqual(sorted(f[0] for f in salida), ["Campus UIB", "Carrer del Parc", "Castell de Bellver"])
        # radio ajustable: a ~11 m cae dentro de 100 m y fuera de 5 m
        cerca = [("Hospital Son Espases", "amenity:hospital", "hospital", "Palma", 39.6051, 2.6050, 32)]
        self.assertEqual(busqueda.deduplicar_areas(base, cerca), [])
        self.assertEqual(busqueda.deduplicar_areas(base, cerca, radio_m=5), cerca)


class NegociosBusquedaTest(unittest.TestCase):
    def test_negocios_con_nombre_se_clasifican_como_poi(self):
        casos = [
            ({"shop": "bakery"}, ("shop:bakery", "otro", 30)),
            ({"shop": "supermarket"}, ("shop:supermarket", "supermercado", 30)),
            ({"amenity": "bar"}, ("amenity:bar", "otro", 32)),
            ({"amenity": "bank"}, ("amenity:bank", "otro", 32)),
            ({"amenity": "bicycle_rental"}, ("amenity:bicycle_rental", "otro", 32)),
            ({"tourism": "apartment"}, ("tourism:apartment", "otro", 36)),
            ({"leisure": "fitness_centre"}, ("leisure:fitness_centre", "otro", 31)),
        ]
        for etiquetas, esperado in casos:
            self.assertEqual(busqueda.clasificar_poi(etiquetas), esperado, etiquetas)

    def test_lugares_por_encima_de_negocios_y_estos_por_encima_de_calles(self):
        negocio_max = max(i for _, i in busqueda.CLAVES_POI)
        negocio_min = min(i for _, i in busqueda.CLAVES_POI)
        lugar_min = min(i for _, i in busqueda.LUGARES.values())
        calle_max = max(busqueda.IMPORTANCIA_VIA.values())
        self.assertGreater(lugar_min, negocio_max)
        self.assertGreater(negocio_min, calle_max)  # las calles quedan POR DEBAJO de los negocios en empate de texto


def _escribir_pbf_sintetico(ruta):
    """Palma (admin_level=8, cuadrado 2.50..2.80 x 39.50..39.70) con un hospital como nodo y como multipoligono (a ~8 m),
    un castillo y un campus solo como multipoligono, una relacion sin etiquetas de POI, una calle, un negocio y una aldea."""
    import osmium  # noqa: PLC0415
    from osmium.osm import mutable  # noqa: PLC0415

    def cuadrado(ids, lon0, lat0, lon1, lat1):
        return [mutable.Node(id=i, location=(x, y)) for i, (x, y) in
                zip(ids, [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)])]

    nodos = (
        cuadrado([1, 2, 3, 4], 2.50, 39.50, 2.80, 39.70)  # Palma
        + cuadrado([11, 12, 13, 14], 2.600, 39.600, 2.610, 39.610)  # hospital (centroide 2.605, 39.605)
        + cuadrado([15, 16, 17, 18], 2.620, 39.550, 2.630, 39.560)  # castillo
        + cuadrado([19, 20, 24, 25], 2.700, 39.640, 2.710, 39.650)  # campus
        + cuadrado([26, 27, 28, 29], 2.520, 39.520, 2.530, 39.530)  # solar sin POI
        + [mutable.Node(id=21, location=(2.6051, 39.6050),
                        tags={"name": "Hospital Universitari Son Espases", "amenity": "hospital"}),
           mutable.Node(id=22, location=(2.700, 39.600), tags={"name": "Forn Colom", "shop": "bakery"}),
           mutable.Node(id=23, location=(2.720, 39.650), tags={"name": "Colom", "place": "hamlet"}),
           mutable.Node(id=31, location=(2.650, 39.570)), mutable.Node(id=32, location=(2.651, 39.570))])
    nodos.sort(key=lambda n: n.id)
    vias = [
        mutable.Way(id=100, nodes=[1, 2, 3, 4, 1]),
        mutable.Way(id=101, nodes=[11, 12, 13, 14, 11]),
        mutable.Way(id=102, nodes=[15, 16, 17, 18, 15]),
        mutable.Way(id=103, nodes=[31, 32], tags={"name": "Carrer de Colom", "highway": "residential"}),
        mutable.Way(id=104, nodes=[19, 20, 24, 25, 19]),
        mutable.Way(id=105, nodes=[26, 27, 28, 29, 26]),
    ]
    relaciones = [
        mutable.Relation(id=200, members=[("w", 100, "outer")],
                         tags={"type": "boundary", "boundary": "administrative", "admin_level": "8", "name": "Palma"}),
        mutable.Relation(id=201, members=[("w", 101, "outer")],
                         tags={"type": "multipolygon", "name": "Hospital Universitari Son Espases",
                               "amenity": "hospital"}),
        mutable.Relation(id=202, members=[("w", 102, "outer")],
                         tags={"type": "multipolygon", "name": "Castell de Bellver", "historic": "castle"}),
        mutable.Relation(id=203, members=[("w", 104, "outer")],
                         tags={"type": "multipolygon", "name": "Campus Universitari", "amenity": "university"}),
        mutable.Relation(id=204, members=[("w", 105, "outer")],
                         tags={"type": "multipolygon", "name": "Solar", "landuse": "brownfield"}),
    ]
    with osmium.SimpleWriter(ruta, overwrite=True) as w:
        for objeto in nodos:
            w.add_node(objeto)
        for objeto in vias:
            w.add_way(objeto)
        for objeto in relaciones:
            w.add_relation(objeto)


try:
    import osmium as _osmium  # noqa: F401

    HAY_OSMIUM = True
except ImportError:
    HAY_OSMIUM = False


@unittest.skipUnless(HAY_OSMIUM, "pyosmium no esta instalado (el workflow lo instala antes de la segunda tanda de pruebas)")
class PbfSinteticoBusquedaTest(unittest.TestCase):
    def test_pipeline_completo_con_multipoligonos_palabras_y_user_version(self):
        with tempfile.TemporaryDirectory() as carpeta:
            pbf = os.path.join(carpeta, "sintetico.osm.pbf")
            salida = os.path.join(carpeta, "busqueda.sqlite")
            _escribir_pbf_sintetico(pbf)
            self.assertEqual(busqueda.generar(pbf, salida), 0)
            con = sqlite3.connect(salida)
            try:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
                filas = {(r[0], r[1]): r[2:] for r in con.execute(
                    "SELECT nombre, categoria, municipio, municipio_norm, importancia, lat, lon FROM lugares")}
                # el hospital sale una sola vez (el multipoligono se descarta por estar a < 100 m del nodo)
                self.assertEqual(
                    [k for k in filas if k[0] == "Hospital Universitari Son Espases"],
                    [("Hospital Universitari Son Espases", "hospital")])
                castillo = filas[("Castell de Bellver", "castillo")]
                self.assertEqual(castillo[0:2], ("Palma", "palma"))
                self.assertAlmostEqual(castillo[3], 39.555, places=5)
                self.assertAlmostEqual(castillo[4], 2.625, places=5)
                campus = filas[("Campus Universitari", "otro")]
                self.assertEqual((campus[0], campus[2]), ("Palma", 32))
                self.assertAlmostEqual(campus[3], 39.645, places=5)
                self.assertNotIn("Solar", {k[0] for k in filas})  # relacion sin etiquetas de POI
                self.assertEqual(filas[("Forn Colom", "otro")][0], "Palma")
                self.assertEqual(filas[("Carrer de Colom", "calle")][0], "Palma")

                def buscar(*consulta):
                    sql = "SELECT nombre FROM lugares WHERE 1"
                    args = []
                    for palabra in consulta:
                        sql += " AND rowid IN (SELECT lugar FROM palabras WHERE palabra >= ? AND palabra < ?)"
                        args += [palabra, palabra[:-1] + chr(ord(palabra[-1]) + 1)]
                    return [r[0] for r in con.execute(sql + " ORDER BY importancia DESC, nombre", args)]

                self.assertEqual(buscar("hospital", "espases"), ["Hospital Universitari Son Espases"])
                self.assertEqual(buscar("castell", "palma"), ["Castell de Bellver"])
                self.assertEqual(buscar("campus"), ["Campus Universitari"])
                # lugar (aldea 60) > negocio (30) > calle (15) con el mismo texto
                self.assertEqual(buscar("colom", "palma"), ["Colom", "Forn Colom", "Carrer de Colom"])
                self.assertEqual(buscar("colom"), ["Colom", "Forn Colom", "Carrer de Colom"])
            finally:
                con.close()


class PkTest(unittest.TestCase):
    def test_parsea_el_kilometro(self):
        casos = {"23": 23.0, "44.8": 44.8, "23,5": 23.5, " 7 km ": 7.0, "12 KM": 12.0, "0": 0.0}
        for texto, esperado in casos.items():
            self.assertEqual(pk.parsear_km(texto), esperado, texto)
        for texto in (None, "", "km 5", "3 mi", "abc", "401", "-2", "1.2.3", "12 m"):
            self.assertIsNone(pk.parsear_km(texto), texto)

    def test_parsea_las_refs(self):
        self.assertEqual(pk.parsear_refs("Ma-13;Ma-13A"), ["Ma-13", "Ma-13A"])
        self.assertEqual(pk.parsear_refs(" Ma-1C "), ["Ma-1C"])
        self.assertEqual(pk.parsear_refs("Ma-13;Ma-13"), ["Ma-13"])
        self.assertEqual(pk.parsear_refs("12"), [])  # solo la numeracion del hito
        self.assertEqual(pk.parsear_refs(None), [])

    def test_hito_de_un_nodo(self):
        tags = {"highway": "milestone", "distance": "18", "ref": "Ma-19"}
        self.assertEqual(pk.hitos_de_nodo(tags, 39.5, 2.9), [{"ref": "Ma-19", "km": 18.0, "lat": 39.5, "lon": 2.9}])
        # `pk` sirve si no hay `distance`; con las dos manda `distance`
        self.assertEqual(pk.hitos_de_nodo({"highway": "milestone", "pk": "4", "ref": "Ma-1"}, 39.5, 2.9)[0]["km"], 4.0)
        self.assertEqual(pk.hitos_de_nodo({**tags, "pk": "9"}, 39.5, 2.9)[0]["km"], 18.0)
        # dos carreteras = dos filas
        self.assertEqual(len(pk.hitos_de_nodo({**tags, "ref": "Ma-13;Ma-13A"}, 39.5, 2.9)), 2)

    def test_descarta_nodos_sin_carretera_o_sin_km(self):
        self.assertEqual(pk.hitos_de_nodo({"highway": "milestone", "name": "km 5"}, 39.5, 2.9), [])
        self.assertEqual(pk.hitos_de_nodo({"highway": "milestone", "ref": "Ma-1C"}, 39.5, 2.9), [])
        self.assertEqual(pk.hitos_de_nodo({"highway": "milestone", "distance": "5"}, 39.5, 2.9), [])
        self.assertEqual(pk.hitos_de_nodo({"highway": "bus_stop", "distance": "5", "ref": "Ma-1"}, 39.5, 2.9), [])

    def test_deduplica_el_mismo_hito_cercano_pero_no_otra_ref_ni_otro_km(self):
        base = {"ref": "Ma-13", "km": 5.0, "lat": 39.7, "lon": 2.9}
        cerca = {**base, "lat": 39.70005}  # ~5 m
        lejos = {**base, "lat": 39.701}  # ~110 m
        unicos = pk.deduplicar([base, cerca, lejos, {**base, "ref": "Ma-1"}, {**base, "km": 6.0}])
        self.assertEqual(len(unicos), 4)

    def test_validacion(self):
        hitos = [{"ref": "Ma-1", "km": float(i), "lat": 39.5, "lon": 2.6} for i in range(20)]
        self.assertEqual(pk.validar(hitos), [])
        self.assertIn("solo 19 hitos", pk.validar(hitos[:19])[0])
        errores = pk.validar(hitos + [{"ref": "Ma-1", "km": 30.0, "lat": 41.6, "lon": -0.9}])
        self.assertEqual(len(errores), 1)
        self.assertIn("fuera del bbox", errores[0])

    def test_escribe_el_formato_v1_en_orden_natural(self):
        hitos = [
            {"ref": "Ma-10", "km": 23.0, "lat": 39.7, "lon": 2.7},
            {"ref": "Ma-2", "km": 1.5, "lat": 39.6, "lon": 2.6},
            {"ref": "Ma-10", "km": 4.0, "lat": 39.75, "lon": 2.75},
            {"ref": "Ma-1C", "km": 44.8, "lat": 39.5123456, "lon": 2.9},
        ]
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "pk.tsv")
            pk.escribir(hitos, ruta)
            with open(ruta, encoding="utf-8", newline="") as f:
                texto = f.read()
        self.assertEqual(texto.split("\n"), [
            "#pk v1",
            "#ref\tkm\tlat\tlon",
            "Ma-1C\t44.8\t39.512346\t2.900000",
            "Ma-2\t1.5\t39.600000\t2.600000",
            "Ma-10\t4\t39.750000\t2.750000",
            "Ma-10\t23\t39.700000\t2.700000",
            "",
        ])

    def test_el_manifest_lo_incluye_solo_si_existe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] not in manifest.OPCIONALES:
                    with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                        f.write(b"abc")
            sin = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
            with open(os.path.join(carpeta, "pk-mallorca.tsv"), "wb") as f:
                f.write(b"abc")
            con = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
        self.assertNotIn("pk", {a["id"] for a in sin["archivos"]})
        entrada = next(a for a in con["archivos"] if a["id"] == "pk")
        self.assertEqual(entrada["url"], "https://github.com/o/r/releases/download/t/pk-mallorca.tsv")
        self.assertEqual(entrada["licencia"], "ODbL-1.0")

    def test_lee_un_pbf_sintetico(self):
        try:
            import osmium  # noqa: F401, PLC0415
        except ImportError:
            self.skipTest("pyosmium no esta instalado")
        from osmium.osm import mutable  # noqa: PLC0415

        nodos = [
            mutable.Node(id=1, location=(2.70, 39.70), tags={"highway": "milestone", "distance": "23", "ref": "Ma-10"}),
            mutable.Node(id=2, location=(2.71, 39.71), tags={"highway": "milestone", "distance": "24 km",
                                                              "ref": "Ma-10;Ma-10A"}),
            mutable.Node(id=3, location=(2.72, 39.72), tags={"highway": "milestone", "name": "km 5"}),
            mutable.Node(id=4, location=(2.73, 39.73), tags={"highway": "bus_stop", "ref": "Ma-10", "distance": "9"}),
        ]
        with tempfile.TemporaryDirectory() as carpeta:
            pbf = os.path.join(carpeta, "pk.osm.pbf")
            with osmium.SimpleWriter(pbf) as w:
                for n in nodos:
                    w.add_node(n)
            hitos = pk.leer_osm(pbf)
        self.assertEqual(
            sorted((h["ref"], h["km"]) for h in hitos), [("Ma-10", 23.0), ("Ma-10", 24.0), ("Ma-10A", 24.0)])
        self.assertAlmostEqual(hitos[0]["lat"], 39.70, places=5)


if __name__ == "__main__":
    unittest.main()


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DGT_RECORTE = os.path.join(FIXTURES, "dgt-radares-recorte.xml")  # extracto real del XML de la DGT (2025-12-18)
CINEMOMETROS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datos", "cinemometros-mallorca.tsv")
ZARAGOZA = (-1.0, 41.0, -0.5, 42.0)


def punto(ident, lat, lon, rumbo=None, limite=None, tipo=radares.FIJO, fuente="OSM", tramo=""):
    return radares.radar(tipo, ident, lat, lon, fuente, rumbo, limite, tramo)


class RadaresDgtTest(unittest.TestCase):
    def test_lee_las_cabinas_de_mallorca_y_descarta_las_de_fuera_del_bbox(self):
        cabinas, tramos = radares.leer_dgt(DGT_RECORTE)
        self.assertEqual([c["id"] for c in cabinas], ["120451", "120645", "120646"])  # 120001 es de Zaragoza
        self.assertEqual(tramos, [])
        c = cabinas[0]
        self.assertEqual((c["lat"], c["lon"], c["carretera"], c["pk_m"]), (39.522423, 2.5087774, "Ma-1", 15500))

    def test_lee_un_tramo_de_velocidad_media_con_from_como_inicio_y_to_como_fin(self):
        cabinas, tramos = radares.leer_dgt(DGT_RECORTE, ZARAGOZA)
        self.assertEqual(cabinas, [])  # la cabina 120001 (A-2) queda fuera de ese recuadro
        self.assertEqual(tramos, [{"id": "161274", "ini": (41.6088, -0.915697), "fin": (41.6192, -0.9496)}])
        filas = radares.radares_dgt([], tramos)
        self.assertEqual([(f["tipo"], f["id"], f["tramo"]) for f in filas],
                         [(radares.TRAMO_INICIO, "dgt-cvm-161274-ini", "dgt-cvm-161274"),
                          (radares.TRAMO_FIN, "dgt-cvm-161274-fin", "dgt-cvm-161274")])
        self.assertEqual(filas[0]["lat"], 41.6088)
        self.assertEqual(filas[1]["lat"], 41.6192)

    def test_cinemometros_curados_distinguen_las_cabinas_moviles(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "c.tsv")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("#cinemometros-mallorca v1\n#carretera\ttipo\tpk_ini\tpk_fin\tsentido\tfecha_informe\tfuente\n"
                        "Ma-11\tMOVIL\t15.5\t\tAMBOS\t2025-03-21\tDGT-PDF\n"
                        "Ma-12\tFIJO\t15.92\t\tDECRECIENTE\t2025-03-21\tDGT-PDF\n"
                        "Ma-12\tMOVIL\t0.080\t111.100\tAMBOS\t2025-03-21\tDGT-PDF\n"
                        "Ma-1015\tMOVIL\t\t\tAMBOS\t2025-03-21\tDGT-PDF\n")
            cin = radares.leer_cinemometros(ruta)
        self.assertEqual(cin, {"fijos": {15920}, "moviles": {15500}})
        cabinas, _ = radares.leer_dgt(DGT_RECORTE)
        filas = {f["id"]: f for f in radares.radares_dgt(cabinas, [], cin)}
        self.assertEqual(filas["dgt-120451"]["tipo"], radares.ZONA_MOVIL)  # PK 15 500 = móvil
        self.assertEqual(filas["dgt-120451"]["fuente"], "DGT-PDF")
        self.assertEqual(filas["dgt-120451"]["tramo"], "dgt-120451")
        self.assertEqual(filas["dgt-120645"]["tipo"], radares.FIJO)  # PK 15 920 = fijo
        self.assertEqual(filas["dgt-120646"]["tipo"], radares.FIJO)  # sin dato en el PDF: cabina, fijo por defecto
        self.assertEqual(filas["dgt-120645"]["fuente"], "DGT")

    def test_el_tsv_curado_del_repo_es_valido(self):
        cin = radares.leer_cinemometros(CINEMOMETROS)
        self.assertIn(15500, cin["moviles"])
        self.assertIn(15920, cin["fijos"])
        self.assertTrue(cin["moviles"].isdisjoint(cin["fijos"]))


class RadaresOsmTest(unittest.TestCase):
    def test_parsea_limite_y_direccion(self):
        self.assertEqual(radares.parsear_limite("90"), 90)
        self.assertIsNone(radares.parsear_limite("50 mph"))
        self.assertIsNone(radares.parsear_limite("none"))
        self.assertIsNone(radares.parsear_limite(None))
        self.assertEqual(radares.parsear_direccion("75"), 75)
        self.assertEqual(radares.parsear_direccion("260.4"), 260)
        self.assertEqual(radares.parsear_direccion("360"), 0)
        self.assertEqual(radares.parsear_direccion("SW"), 225)
        self.assertEqual(radares.parsear_direccion("30;255"), 30)
        self.assertIsNone(radares.parsear_direccion("forward"))
        self.assertIsNone(radares.parsear_direccion("400"))
        self.assertIsNone(radares.parsear_direccion(None))

    def test_rumbo_entre_puntos(self):
        self.assertEqual(radares.rumbo_entre((39.5, 2.5), (39.6, 2.5)), 0)
        self.assertEqual(radares.rumbo_entre((39.5, 2.5), (39.5, 2.6)), 90)
        self.assertEqual(radares.rumbo_entre((39.5, 2.5), (39.4, 2.5)), 180)
        self.assertEqual(radares.rumbo_entre((39.5, 2.5), (39.5, 2.4)), 270)

    def _sintetico(self):
        # Una camara suelta con direction, otra con maxspeed ilegible, un dispositivo de una relacion `maxspeed` con
        # from/to, un dispositivo que vigila los dos sentidos (dos relaciones) y un tramo de velocidad media.
        camaras = {
            1: {"lat": 39.60, "lon": 2.60, "tags": {"maxspeed": "90", "direction": "75"}},
            2: {"lat": 39.61, "lon": 2.61, "tags": {"maxspeed": "mph"}},
            3: {"lat": 39.62, "lon": 2.62, "tags": {"maxspeed": "50"}},
            4: {"lat": 39.63, "lon": 2.63, "tags": {}},
            5: {"lat": 39.64, "lon": 2.64, "tags": {"maxspeed": "80"}},
            6: {"lat": 39.65, "lon": 2.65, "tags": {"maxspeed": "80"}},
        }
        ubic_nodos = {k: (v["lat"], v["lon"]) for k, v in camaras.items()}
        ubic_nodos.update({10: (39.62, 2.617), 11: (39.62, 2.623),  # relacion del 3: de oeste a este
                           12: (39.63, 2.627), 13: (39.63, 2.629), 14: (39.63, 2.633), 15: (39.63, 2.631),  # del 4
                           20: (39.64, 2.64), 21: (39.65, 2.65)})
        relaciones = [
            {"id": 100, "tags": {"enforcement": "maxspeed", "maxspeed": "60"},
             "miembros": [("n", 3, "device"), ("n", 10, "from"), ("n", 11, "to")]},
            {"id": 101, "tags": {"enforcement": "maxspeed", "maxspeed": "70"},
             "miembros": [("n", 4, "device"), ("n", 12, "from"), ("n", 13, "to")]},
            {"id": 102, "tags": {"enforcement": "maxspeed", "maxspeed": "70"},
             "miembros": [("n", 4, "device"), ("n", 14, "from"), ("n", 15, "to")]},
            {"id": 103, "tags": {"enforcement": "average_speed", "maxspeed": "85"},
             "miembros": [("n", 5, "device"), ("n", 6, "device"), ("n", 20, "from"), ("n", 21, "to")]},
            {"id": 104, "tags": {"enforcement": "traffic_signals"},
             "miembros": [("n", 1, "device"), ("n", 10, "from")]},
            {"id": 105, "tags": {"enforcement": "maxspeed", "maxspeed": "50"}, "miembros": [("n", 10, "from")]},
        ]
        return camaras, relaciones, ubic_nodos, {}

    def test_construye_fijos_tramos_y_dispositivos_de_dos_sentidos(self):
        filas = {f["id"]: f for f in radares.radares_osm(*self._sintetico())}
        self.assertEqual(sorted(filas), ["osm-n1", "osm-n2", "osm-n3", "osm-n4-r101", "osm-n4-r102",
                                         "osm-r103-fin", "osm-r103-ini"])
        # camara suelta: direction y maxspeed de sus etiquetas
        self.assertEqual((filas["osm-n1"]["rumbo"], filas["osm-n1"]["limite"]), (75, 90))
        # maxspeed ilegible y sin relacion: sin limite ni rumbo (ambos sentidos)
        self.assertEqual((filas["osm-n2"]["rumbo"], filas["osm-n2"]["limite"]), (None, None))
        # una sola relacion: sin direction se usa el rumbo from -> to (este = 90); el limite del nodo gana al de la relacion
        self.assertEqual((filas["osm-n3"]["rumbo"], filas["osm-n3"]["limite"]), (90, 50))
        # dos relaciones: una fila por sentido, con el rumbo y el limite de cada relacion
        self.assertEqual((filas["osm-n4-r101"]["rumbo"], filas["osm-n4-r101"]["limite"]), (90, 70))
        self.assertEqual((filas["osm-n4-r102"]["rumbo"], filas["osm-n4-r102"]["limite"]), (270, 70))
        # los dispositivos 5 y 6 son del tramo y no salen como FIJO
        self.assertNotIn("osm-n5", filas)
        ini, fin = filas["osm-r103-ini"], filas["osm-r103-fin"]
        self.assertEqual((ini["tipo"], fin["tipo"]), (radares.TRAMO_INICIO, radares.TRAMO_FIN))
        self.assertEqual((ini["tramo"], fin["tramo"]), ("osm-r103", "osm-r103"))
        self.assertEqual((ini["lat"], ini["lon"]), (39.64, 2.64))
        self.assertEqual((fin["lat"], fin["lon"]), (39.65, 2.65))
        self.assertEqual((ini["limite"], ini["rumbo"], fin["rumbo"]), (85, 38, 38))

    def test_tramo_sin_from_ni_to_usa_el_primer_y_el_ultimo_dispositivo(self):
        camaras, _, ubic_nodos, _ = self._sintetico()
        rel = [{"id": 7, "tags": {"enforcement": "average_speed"},
                "miembros": [("n", 5, "device"), ("n", 6, "device")]}]
        filas = radares.radares_osm(camaras, rel, ubic_nodos, {})
        tramo = [f for f in filas if f["tramo"]]
        self.assertEqual([(f["tipo"], f["lat"]) for f in tramo],
                         [(radares.TRAMO_INICIO, 39.64), (radares.TRAMO_FIN, 39.65)])
        self.assertEqual({f["limite"] for f in tramo}, {80})  # sin maxspeed en la relacion: el de los dispositivos

    def test_from_y_to_pueden_ser_vias(self):
        camaras = {1: {"lat": 39.6, "lon": 2.6, "tags": {}}}
        ubic_nodos = {1: (39.6, 2.6)}
        ubic_vias = {50: (39.60, 2.600), 51: (39.60, 2.610)}
        rel = [{"id": 8, "tags": {"enforcement": "average_speed", "maxspeed": "70"},
                "miembros": [("n", 1, "device"), ("w", 50, "from"), ("w", 51, "to")]}]
        filas = radares.radares_osm(camaras, rel, ubic_nodos, ubic_vias)
        self.assertEqual([(f["tipo"], f["rumbo"]) for f in filas],
                         [(radares.TRAMO_INICIO, 90), (radares.TRAMO_FIN, 90)])


class RadaresFusionTest(unittest.TestCase):
    def test_la_dgt_absorbe_el_fijo_de_osm_cercano_y_conserva_su_limite(self):
        dgt = [punto("dgt-1", 39.5000, 2.5000, limite=100, fuente="DGT")]
        osm = [punto("osm-n1", 39.5004, 2.5000, rumbo=120, limite=90)]  # a 44 m
        salida = radares.fusionar(dgt, osm)
        self.assertEqual(len(salida), 1)
        f = salida[0]
        self.assertEqual((f["id"], f["fuente"], f["lat"], f["rumbo"], f["limite"]), ("dgt-1", "DGT", 39.5, 120, 100))

    def test_la_dgt_sin_limite_toma_el_de_osm_y_la_zona_movil_absorbe_el_fijo(self):
        dgt = [punto("dgt-2", 39.5000, 2.5000, tipo=radares.ZONA_MOVIL, fuente="DGT-PDF", tramo="dgt-2")]
        osm = [punto("osm-n2", 39.5007, 2.5000, rumbo=200, limite=80)]  # a 78 m: dentro de 100 m
        salida = radares.fusionar(dgt, osm)
        self.assertEqual([(f["tipo"], f["id"], f["tramo"], f["rumbo"], f["limite"]) for f in salida],
                         [(radares.ZONA_MOVIL, "dgt-2", "dgt-2", 200, 80)])

    def test_dos_osm_de_sentidos_opuestos_en_la_misma_cabina_dan_dos_filas(self):
        dgt = [punto("dgt-3", 39.5, 2.5, fuente="DGT")]
        osm = [punto("osm-a", 39.5, 2.5001, rumbo=90, limite=50), punto("osm-b", 39.5, 2.5001, rumbo=270, limite=50)]
        salida = radares.fusionar(dgt, osm)
        self.assertEqual([(f["id"], f["rumbo"]) for f in salida], [("dgt-3", 90), ("dgt-3-2", 270)])

    def test_osm_lejano_o_de_tramo_no_se_fusiona_y_los_tramos_pasan_intactos(self):
        dgt = [punto("dgt-4", 39.5, 2.5, fuente="DGT")]
        osm = [punto("osm-lejos", 39.5, 2.502, rumbo=10, limite=60),  # a 170 m
               punto("osm-t-ini", 39.5, 2.5, tipo=radares.TRAMO_INICIO, tramo="t"),
               punto("osm-t-fin", 39.51, 2.5, tipo=radares.TRAMO_FIN, tramo="t")]
        salida = radares.fusionar(dgt, osm)
        self.assertEqual(sorted(f["id"] for f in salida), ["dgt-4", "osm-lejos", "osm-t-fin", "osm-t-ini"])

    def test_dedup_de_fijos_de_osm_a_menos_de_50_m_solo_si_el_rumbo_es_compatible(self):
        osm = [punto("a", 39.5, 2.5, rumbo=90), punto("b", 39.5, 2.5002, rumbo=100),  # 17 m, 10 grados -> uno
               punto("c", 39.5, 2.5, rumbo=270),  # mismo sitio, sentido contrario -> otro
               punto("d", 39.5, 2.5, rumbo=None),  # sin rumbo: compatible con el primero
               punto("e", 39.5, 2.51, rumbo=90)]  # a 850 m
        salida = radares.fusionar([], osm)
        self.assertEqual([f["id"] for f in salida], ["a", "c", "e"])


class RadaresValidacionYFormatoTest(unittest.TestCase):
    def _fijos(self, n):
        return [punto(f"f{i}", 39.5 + i * 0.01, 2.6) for i in range(n)]

    def test_valido_con_cinco_fijos_dentro_del_bbox(self):
        self.assertEqual(radares.validar(self._fijos(5)), [])

    def test_falla_con_menos_de_cinco_fijos(self):
        errores = radares.validar(self._fijos(4))
        self.assertEqual(len(errores), 1)
        self.assertIn("solo 4 radares fijos", errores[0])

    def test_los_tramos_y_las_zonas_no_cuentan_como_fijos(self):
        extra = [punto("t-ini", 39.5, 2.5, tipo=radares.TRAMO_INICIO, tramo="t"),
                 punto("t-fin", 39.5, 2.6, tipo=radares.TRAMO_FIN, tramo="t"),
                 punto("z", 39.5, 2.5, tipo=radares.ZONA_MOVIL, tramo="z")]
        self.assertEqual(len(radares.validar(self._fijos(4) + extra)), 1)

    def test_falla_con_un_radar_fuera_del_bbox(self):
        errores = radares.validar(self._fijos(5) + [punto("lejos", 41.6, -0.9)])
        self.assertEqual(len(errores), 1)
        self.assertIn("lejos fuera del bbox", errores[0])

    def test_falla_con_ids_repetidos_o_tramo_incompleto(self):
        base = self._fijos(5)
        self.assertIn("ids repetidos", radares.validar(base + [punto("f0", 39.9, 3.0)]))
        huerfano = punto("t-ini", 39.5, 2.5, tipo=radares.TRAMO_INICIO, tramo="t")
        self.assertTrue(any("sin pareja" in e for e in radares.validar(base + [huerfano])))

    def test_escribe_el_formato_v1(self):
        filas = [
            punto("osm-n2", 39.5, 2.6, rumbo=90, limite=50),
            punto("osm-r1-fin", 39.6, 2.7, rumbo=45, limite=80, tipo=radares.TRAMO_FIN, tramo="osm-r1"),
            punto("osm-r1-ini", 39.55, 2.65, rumbo=45, limite=80, tipo=radares.TRAMO_INICIO, tramo="osm-r1"),
            punto("dgt-1", 39.52, 2.5087774, tipo=radares.ZONA_MOVIL, fuente="DGT-PDF", tramo="dgt-1"),
            punto("dgt-0", 39.58666, 3.247777, fuente="DGT"),
        ]
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "r.tsv")
            radares.escribir(filas, ruta)
            with open(ruta, encoding="utf-8", newline="") as f:
                texto = f.read()
        self.assertEqual(texto.split("\n"), [
            "#radares v1",
            "#tipo\tid\tlat\tlon\trumbo\tlimite_kmh\ttramo_id\tfuente",
            "FIJO\tdgt-0\t39.586660\t3.247777\t\t\t\tDGT",
            "FIJO\tosm-n2\t39.500000\t2.600000\t90\t50\t\tOSM",
            "TRAMO_INICIO\tosm-r1-ini\t39.550000\t2.650000\t45\t80\tosm-r1\tOSM",
            "TRAMO_FIN\tosm-r1-fin\t39.600000\t2.700000\t45\t80\tosm-r1\tOSM",
            "ZONA_MOVIL\tdgt-1\t39.520000\t2.508777\t\t\tdgt-1\tDGT-PDF",
            "",
        ])

    def test_de_la_cabina_real_a_la_fila_del_tsv(self):
        cabinas, _ = radares.leer_dgt(DGT_RECORTE)
        filas = radares.radares_dgt(cabinas, [])
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "r.tsv")
            radares.escribir(filas, ruta)
            with open(ruta, encoding="utf-8") as f:
                lineas = f.read().splitlines()
        self.assertEqual(lineas[2], "FIJO\tdgt-120451\t39.522423\t2.508777\t\t\t\tDGT")
