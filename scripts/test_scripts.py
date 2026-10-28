"""Pruebas de los scripts sin red: python -I -m unittest discover -s scripts -p 'test_*.py'"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

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


if __name__ == "__main__":
    unittest.main()
