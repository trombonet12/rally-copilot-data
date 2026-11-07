"""Voz Sharvard (Piper es_ES, int8) para la release: voz-sharvard.onnx y voz-sharvard-tokens.txt.

Rally Copilot ya no empaqueta esta voz en el APK: la app la baja de la release de datos cuando se elige. Este script
descarga el paquete oficial de sherpa-onnx (`vits-piper-es_ES-sharvard-medium-int8.tar.bz2`), comprueba su SHA-256 (el mismo
que fijaba app/build.gradle.kts de Rally Copilot) y saca solo el modelo y los tokens, con los nombres que lista el
manifest. El `espeak-ng-data` NO se publica: la app usa el de la voz Dave, que sí va en el APK.

Uso: python -I scripts/voz.py --salida salida [--tar ruta/ya/descargado.tar.bz2]

Licencia de la voz: dataset Harvard sentences de la Universidad de Edimburgo, CC BY 3.0
(https://datashare.ed.ac.uk/handle/10283/574); modelo Piper afinado desde lessac (MIT).
"""

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import time
import urllib.request

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-es_ES-sharvard-medium-int8.tar.bz2"
SHA256 = "bf5507cbdedea650365bd6175b3164a8ecca5847533ddf97afcba9d76ea599d1"
RAIZ = "vits-piper-es_ES-sharvard-medium-int8"
# miembro del tar -> nombre en la release (los mismos que NOMBRE_MODELO_SHARVARD / NOMBRE_TOKENS_SHARVARD de la app)
MIEMBROS = {
    f"{RAIZ}/es_ES-sharvard-medium.onnx": "voz-sharvard.onnx",
    f"{RAIZ}/tokens.txt": "voz-sharvard-tokens.txt",
}


def sha256(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def descargar(url: str, destino: str, intentos: int = 3) -> None:
    for intento in range(1, intentos + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(destino, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except OSError as e:
            if intento == intentos:
                raise
            print(f"Descarga fallida ({e}); reintento {intento}/{intentos - 1}", file=sys.stderr)
            time.sleep(5 * intento)


def verificar(ruta: str, esperado: str = SHA256) -> None:
    real = sha256(ruta)
    if real != esperado:
        raise ValueError(f"SHA-256 inesperado en {os.path.basename(ruta)}: {real} (se esperaba {esperado})")


def extraer(tar_ruta: str, salida: str) -> list[str]:
    """Saca del tar los archivos de MIEMBROS (solo esos, por ruta exacta y como archivos normales) a `salida`."""
    os.makedirs(salida, exist_ok=True)
    hechos = []
    with tarfile.open(tar_ruta, "r:bz2") as tar:
        por_nombre = {m.name: m for m in tar.getmembers()}
        for miembro, nombre in MIEMBROS.items():
            info = por_nombre.get(miembro)
            if info is None or not info.isfile():
                raise ValueError(f"El paquete no trae {miembro}")
            origen = tar.extractfile(info)
            if origen is None:
                raise ValueError(f"No se puede leer {miembro}")
            ruta = os.path.join(salida, nombre)
            with origen, open(ruta, "wb") as f:
                shutil.copyfileobj(origen, f)
            if os.path.getsize(ruta) == 0:
                raise ValueError(f"{nombre} está vacío")
            hechos.append(ruta)
    return hechos


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--salida", required=True)
    p.add_argument("--tar", help="paquete ya descargado (si no, se descarga de sherpa-onnx)")
    args = p.parse_args()
    os.makedirs(args.salida, exist_ok=True)
    tar = args.tar or os.path.join(args.salida, f"{RAIZ}.tar.bz2.descarga")
    if not args.tar:
        descargar(URL, tar)
    try:
        verificar(tar)
        for ruta in extraer(tar, args.salida):
            print(f"{os.path.basename(ruta)}: {os.path.getsize(ruta) / 1e6:.1f} MB · {sha256(ruta)[:12]}")
    finally:
        if not args.tar and os.path.exists(tar):
            os.remove(tar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
