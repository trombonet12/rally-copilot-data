"""Pruebas de scripts/voz.py (sin red): python -I -m unittest discover -s scripts -p 'test_*.py'"""

import io
import os
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import manifest  # noqa: E402
import voz  # noqa: E402


def _tar(ruta: str, miembros: dict[str, bytes], carpetas: tuple[str, ...] = (voz.RAIZ,)) -> None:
    with tarfile.open(ruta, "w:bz2") as tar:
        for c in carpetas:
            info = tarfile.TarInfo(c)
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for nombre, contenido in miembros.items():
            info = tarfile.TarInfo(nombre)
            info.size = len(contenido)
            tar.addfile(info, io.BytesIO(contenido))


COMPLETO = {
    f"{voz.RAIZ}/es_ES-sharvard-medium.onnx": b"modelo-onnx",
    f"{voz.RAIZ}/tokens.txt": b"tokens",
    f"{voz.RAIZ}/MODEL_CARD": b"card",
    f"{voz.RAIZ}/es_ES-sharvard-medium.onnx.json": b"{}",
    f"{voz.RAIZ}/espeak-ng-data/es_dict": b"dict",
    "../evil.txt": b"no",
}


class VozTest(unittest.TestCase):
    def test_extrae_solo_el_modelo_y_los_tokens_con_los_nombres_de_la_release(self):
        with tempfile.TemporaryDirectory() as carpeta:
            tar = os.path.join(carpeta, "voz.tar.bz2")
            salida = os.path.join(carpeta, "salida")
            _tar(tar, COMPLETO)

            hechos = voz.extraer(tar, salida)

            self.assertEqual(sorted(os.listdir(salida)), ["voz-sharvard-tokens.txt", "voz-sharvard.onnx"])
            self.assertEqual(len(hechos), 2)
            with open(os.path.join(salida, "voz-sharvard.onnx"), "rb") as f:
                self.assertEqual(f.read(), b"modelo-onnx")
            with open(os.path.join(salida, "voz-sharvard-tokens.txt"), "rb") as f:
                self.assertEqual(f.read(), b"tokens")
            self.assertFalse(os.path.exists(os.path.join(carpeta, "evil.txt")))

    def test_un_paquete_sin_los_tokens_falla(self):
        with tempfile.TemporaryDirectory() as carpeta:
            tar = os.path.join(carpeta, "voz.tar.bz2")
            _tar(tar, {f"{voz.RAIZ}/es_ES-sharvard-medium.onnx": b"x"})
            with self.assertRaises(ValueError):
                voz.extraer(tar, os.path.join(carpeta, "salida"))

    def test_un_modelo_vacio_falla(self):
        with tempfile.TemporaryDirectory() as carpeta:
            tar = os.path.join(carpeta, "voz.tar.bz2")
            _tar(tar, {f"{voz.RAIZ}/es_ES-sharvard-medium.onnx": b"", f"{voz.RAIZ}/tokens.txt": b"t"})
            with self.assertRaises(ValueError):
                voz.extraer(tar, os.path.join(carpeta, "salida"))

    def test_la_verificacion_rechaza_un_sha_distinto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "x")
            with open(ruta, "wb") as f:
                f.write(b"abc")
            voz.verificar(ruta, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            with self.assertRaises(ValueError):
                voz.verificar(ruta)

    def test_el_sha_fijado_es_el_de_app_build_gradle(self):
        self.assertEqual(voz.SHA256, "bf5507cbdedea650365bd6175b3164a8ecca5847533ddf97afcba9d76ea599d1")
        self.assertTrue(voz.URL.endswith("vits-piper-es_ES-sharvard-medium-int8.tar.bz2"))

    def test_los_nombres_de_salida_son_los_del_manifest(self):
        nombres = {a["nombre"] for a in manifest.ARCHIVOS}
        self.assertTrue(set(voz.MIEMBROS.values()) <= nombres)

    def test_la_voz_va_en_manifest_json_como_opcional_con_su_licencia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for a in manifest.ARCHIVOS:
                if a["id"] in manifest.OPCIONALES:
                    continue
                with open(os.path.join(carpeta, a["nombre"]), "wb") as f:
                    f.write(b"abc")
            sin = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
            for nombre in voz.MIEMBROS.values():
                with open(os.path.join(carpeta, nombre), "wb") as f:
                    f.write(b"abc")
            con = manifest.construir(carpeta, "v", "t", "o/r", None, "T")
            extra = manifest.construir(carpeta, "v", "t", "o/r", None, "T", None, separados=True)
        ids_sin = {a["id"] for a in sin["archivos"]}
        self.assertNotIn("voz-sharvard", ids_sin)
        self.assertNotIn("voz-sharvard-tokens", ids_sin)
        por_id = {a["id"]: a for a in con["archivos"]}
        self.assertEqual(por_id["voz-sharvard"]["nombre"], "voz-sharvard.onnx")
        self.assertEqual(por_id["voz-sharvard-tokens"]["nombre"], "voz-sharvard-tokens.txt")
        self.assertEqual(por_id["voz-sharvard"]["licencia"], "CC-BY-3.0")
        self.assertEqual(
            por_id["voz-sharvard"]["url"], "https://github.com/o/r/releases/download/t/voz-sharvard.onnx")
        self.assertEqual(extra["archivos"], [])


if __name__ == "__main__":
    unittest.main()
