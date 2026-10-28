"""Extrae las vías circulables de Mallorca con su límite de velocidad a un TSV comprimido.

Uso: python -I scripts/vias.py mallorca.osm.pbf vias-mallorca.tsv.gz

Formato (v1, lo lee `LectorVias` del motor de Rally Copilot), una vía por línea, campos separados por tabulador:
  id  highway  maxspeed  maxspeed:forward  maxspeed:backward  oneway  ref  name  coordenadas
Las coordenadas son «lat,lon;lat,lon;…» en millonésimas de grado (enteros). Campos vacíos si OSM no los tiene.
La primera línea es la cabecera `#vias-mallorca v1`. Datos © OpenStreetMap contributors (ODbL).
"""

import gzip
import sys

import osmium

# Vías por las que se conduce. Sin service ni track: atraerían la posición GPS en aparcamientos y caminos paralelos.
CLASES = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street", "road",
}
CABECERA = "#vias-mallorca v1"
ETIQUETAS = ("maxspeed", "maxspeed:forward", "maxspeed:backward", "oneway", "ref", "name")


def limpio(valor: str | None) -> str:
    return "" if valor is None else " ".join(valor.replace("\t", " ").split())


class Vias(osmium.SimpleHandler):
    def __init__(self, salida):
        super().__init__()
        self.salida = salida
        self.total = 0
        self.con_limite = 0

    def way(self, w):
        tags = w.tags
        if tags.get("highway") not in CLASES or tags.get("area") == "yes":
            return
        puntos = []
        for n in w.nodes:
            if not n.location.valid():
                return
            puntos.append(f"{round(n.location.lat * 1e6)},{round(n.location.lon * 1e6)}")
        if len(puntos) < 2:
            return
        campos = [str(w.id), tags.get("highway")] + [limpio(tags.get(k)) for k in ETIQUETAS] + [";".join(puntos)]
        self.salida.write("\t".join(campos) + "\n")
        self.total += 1
        if tags.get("maxspeed") or tags.get("maxspeed:forward") or tags.get("maxspeed:backward"):
            self.con_limite += 1


def main() -> int:
    entrada, destino = sys.argv[1], sys.argv[2]
    with gzip.open(destino, "wt", encoding="utf-8", newline="\n", compresslevel=9) as salida:
        salida.write(CABECERA + "\n")
        vias = Vias(salida)
        vias.apply_file(entrada, locations=True)
    print(f"vías: {vias.total}; con maxspeed: {vias.con_limite}")
    return 0 if vias.total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
