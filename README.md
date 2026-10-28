# Rally Copilot · datos de Mallorca

Datos offline de **Mallorca** para la app [Rally Copilot](https://github.com/trombonet12/Rally-Copilot): mapa
vectorial, estilo, vías con límite de velocidad y mapa satélite. Un workflow de GitHub Actions los regenera cada mes
y los publica en una GitHub Release (`datos-AAAA.MM.DD-N`). No hay servidor: la app descarga los archivos de la
release y solo baja los que han cambiado.

## Contenido de cada release

| Archivo | Qué es | Origen |
|---|---|---|
| `mallorca.pmtiles` | Mapa vectorial (teselas hasta z15) generado con Planetiler y el esquema de Protomaps | OpenStreetMap vía Geofabrik |
| `estilo-mapa.zip` | Estilos MapLibre (`vectorial.json`, `satelite.json`), sprites y fuentes (glifos). Las rutas llevan el marcador `{{DIR}}`, que la app sustituye por su carpeta local | Protomaps basemaps, Noto Sans |
| `vias-mallorca.tsv.gz` | Vías circulables con `maxspeed`, `oneway`, `ref` y `name` (formato `#vias-mallorca v1`) | OpenStreetMap |
| `pnoa-mallorca-z16.pmtiles` | Ortofoto satélite z0–16 (JPEG sin recomprimir) | PNOA, IGN |
| `manifest.json` | Índice: versión, tamaño, SHA-256, URL y atribución de cada archivo | Generado |

Cada archivo del manifest lleva su propia `version`. El satélite cambia rara vez: se reutiliza el de la release
anterior y conserva su versión.

Área: bbox `2.30,39.26,3.50,39.97` (oeste, sur, este, norte).

## URL estable

```
https://github.com/trombonet12/rally-copilot-data/releases/latest/download/manifest.json
```

La app lee ese manifest y descarga las `url` de los archivos cuyo SHA-256 no coincida con el que ya tiene.

## Cómo se lanza

- **Automático**: el día 1 de cada mes a las 03:00 UTC. Reutiliza el satélite de la última release.
- **Manual**: pestaña *Actions* → *Datos Mallorca* → *Run workflow*. La casilla `satelite` fuerza a descargar de nuevo
  las teselas PNOA (lento: decenas de miles de peticiones al IGN) y se activa sola si todavía no hay release con satélite.
- Conserva las 3 últimas releases `datos-*`; las anteriores se borran junto con su etiqueta.
- GitHub desactiva los workflows programados tras 60 días sin actividad en el repo: si pasa, se reactiva a mano desde
  *Actions*.

Versiones fijadas en `.github/workflows/datos.yml`: Planetiler vía `protomaps/basemaps` (SHA), `basemaps-assets` (SHA),
`osmium` (pip) y `pmtiles` (con comprobación de SHA-256). `@protomaps/basemaps` (npm) está fijado con lockfile
(`estilo/package.json` y `estilo/package-lock.json`) y se instala con `npm ci --ignore-scripts`. Las acciones van
fijadas por SHA y las actualiza Dependabot cada mes.

## Seguridad del workflow

- Tres jobs: `decidir` y `build` solo tienen `contents: read`; el código de terceros (Maven/Planetiler, npm, pip) se
  ejecuta en `build`, sin `GH_TOKEN`. Solo `publicar` tiene `contents: write`: descarga el artefacto, genera el
  manifest, crea la release y aplica la retención.
- El satélite reutilizado de la release anterior se verifica contra el SHA-256 de su `manifest.json` antes de usarlo.
- **Riesgos conocidos sin mitigar**: `osmium` de PyPI se fija por versión pero no por hash, y Planetiler descarga con
  `--download` fuentes auxiliares (p. ej. Natural Earth, datos de agua) sin comprobar su hash.

## Scripts

- `scripts/vias.py`: extrae las vías del PBF a TSV comprimido.
- `scripts/satelite.py`: descarga las teselas PNOA a un MBTiles (reanudable).
- `scripts/estilo.mjs`: genera estilos, sprites y fuentes (dependencia npm en `estilo/`).
- `scripts/manifest.py`: escribe `manifest.json`.
- `scripts/test_scripts.py`: pruebas sin red (`python -I -m unittest discover -s scripts -p 'test_*.py'`).

## Atribuciones y licencias

- Mapa y vías: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), licencia ODbL 1.0.
- Satélite: PNOA, © Instituto Geográfico Nacional de España, CC-BY 4.0 scne.es.
- Estilos y esquema de teselas: [Protomaps basemaps](https://github.com/protomaps/basemaps) (BSD-3-Clause) y
  [basemaps-assets](https://github.com/protomaps/basemaps-assets) (sprites CC0-1.0; fuentes Noto Sans, SIL OFL 1.1).
- Los scripts de este repositorio están bajo **GPL-3.0** (ver `LICENSE`). Los datos conservan las licencias de arriba.
