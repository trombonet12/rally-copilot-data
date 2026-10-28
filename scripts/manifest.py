"""Escribe manifest.json con versión, tamaño y SHA-256 de cada archivo de la release.

Uso: python -I scripts/manifest.py --carpeta salida --version 2026.10.28-1 --tag datos-2026.10.28-1 \
         --repo trombonet12/rally-copilot-data [--version-satelite 2026.10.28-1]

La app lee https://github.com/<repo>/releases/latest/download/manifest.json y baja solo los archivos cuyo SHA-256
no coincide con el que ya tiene. Los archivos opcionales (OPCIONALES) que no existan en la carpeta no se incluyen. `version` de cada archivo = release en la que se generó (el satélite se reutiliza
entre releases y conserva la suya).
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

ESQUEMA = 1
ARCHIVOS = [
    {"id": "vectorial", "nombre": "mallorca.pmtiles", "atribucion": "© OpenStreetMap contributors", "licencia": "ODbL-1.0"},
    {"id": "estilo", "nombre": "estilo-mapa.zip",
     "atribucion": "Protomaps basemaps; fuentes Noto Sans", "licencia": "BSD-3-Clause, CC0-1.0, OFL-1.1"},
    {"id": "vias", "nombre": "vias-mallorca.tsv.gz", "atribucion": "© OpenStreetMap contributors", "licencia": "ODbL-1.0"},
    {"id": "satelite", "nombre": "pnoa-mallorca-z16.pmtiles", "atribucion": "PNOA CC-BY 4.0 scne.es", "licencia": "CC-BY-4.0"},
    {"id": "valhalla", "nombre": "valhalla-mallorca.tar", "atribucion": "© OpenStreetMap contributors", "licencia": "ODbL-1.0"},
]
# Archivos que se omiten del manifest si no estan en la carpeta (la app actual solo exige los demas).
OPCIONALES = {"valhalla"}


def sha256(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def construir(carpeta: str, version: str, tag: str, repo: str, version_satelite: str | None, ahora: str) -> dict:
    archivos = []
    for a in ARCHIVOS:
        ruta = os.path.join(carpeta, a["nombre"])
        if a["id"] in OPCIONALES and not os.path.isfile(ruta):
            continue
        version_archivo = version_satelite if a["id"] == "satelite" and version_satelite else version
        archivos.append({
            **a,
            "url": f"https://github.com/{repo}/releases/download/{tag}/{a['nombre']}",
            "bytes": os.path.getsize(ruta),
            "sha256": sha256(ruta),
            "version": version_archivo,
        })
    return {"esquema": ESQUEMA, "version": version, "generado": ahora, "archivos": archivos}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--carpeta", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--version-satelite")
    args = p.parse_args()
    ahora = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = construir(args.carpeta, args.version, args.tag, args.repo, args.version_satelite, ahora)
    with open(os.path.join(args.carpeta, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    for a in manifest["archivos"]:
        print(f"{a['nombre']}: {a['bytes'] / 1e6:.1f} MB · {a['sha256'][:12]} · {a['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
