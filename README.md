# Rally Copilot · datos de Mallorca

Datos offline de **Mallorca** para la app [Rally Copilot](https://github.com/trombonet12/Rally-Copilot): mapa
vectorial, estilo, vías con límite de velocidad, mapa satélite, índice de búsqueda, relieve y curvas de nivel. Un workflow de GitHub Actions los regenera cada mes
y los publica en una GitHub Release (`datos-AAAA.MM.DD-N`). No hay servidor: la app descarga los archivos de la
release y solo baja los que han cambiado.

## Contenido de cada release

| Archivo | Qué es | Origen |
|---|---|---|
| `mallorca.pmtiles` | Mapa vectorial (teselas hasta z15) generado con Planetiler y el esquema de Protomaps | OpenStreetMap vía Geofabrik |
| `estilo-mapa.zip` | Estilos MapLibre (`vectorial.json`, `satelite.json`), sprites y fuentes (glifos). Las rutas llevan el marcador `{{DIR}}`, que la app sustituye por su carpeta local | Protomaps basemaps, Noto Sans |
| `vias-mallorca.tsv.gz` | Vías circulables con `maxspeed`, `oneway`, `ref` y `name` (formato `#vias-mallorca v1`) | OpenStreetMap |
| `pnoa-mallorca-z16.pmtiles` | Ortofoto satélite z0–16 (JPEG sin recomprimir) | PNOA, IGN |
| `valhalla-mallorca.tar` | Teselas de enrutado de Valhalla 3.9.1 (tar de extracción con `index.bin`) para [valhalla-mobile](https://github.com/Rallista/valhalla-mobile) 0.6.4. Archivo opcional en el manifest (`id` `valhalla`) | OpenStreetMap vía Geofabrik |
| `busqueda-mallorca.sqlite` | Índice de búsqueda: SQLite con la tabla `lugares` (lugares, calles y POIs con nombre; sin FTS5). Opcional (`id` `busqueda`) | OpenStreetMap |
| `relieve-mallorca.pmtiles` | Relieve para sombreado (`raster-dem` Terrarium, teselas PNG de 512 px, z7–13, alturas a 0,25 m). Opcional (`id` `relieve`) | MDT05, IGN |
| `curvas-mallorca.pmtiles` | Curvas de nivel cada 10 m (capa `curvas`, z11–14; atributos `ele` e `indice` = 1 cada 50 m). Opcional (`id` `curvas`) | MDT05, IGN |
| `manifest.json` | Índice: versión, tamaño, SHA-256, URL y atribución de cada archivo | Generado |

Cada archivo del manifest lleva su propia `version`. El satélite cambia rara vez: se reutiliza el de la release
anterior y conserva su versión.

Área: bbox `2.30,39.26,3.50,39.97` (oeste, sur, este, norte).

### Teselas de enrutado (Valhalla)

- Se generan en el job `build` con la imagen oficial `ghcr.io/valhalla/valhalla:3.9.1`, fijada por digest, mediante
  `scripts/valhalla.sh`: `valhalla_build_config`, `valhalla_build_admins`, `valhalla_build_tiles` y
  `valhalla_build_extract`. La versión debe coincidir con la de Valhalla que lleva valhalla-mobile (0.6.4 usa el
  commit de Valhalla 3.9.1); al actualizar la librería hay que actualizar etiqueta y digest.
- No se generan la base de zonas horarias (solo sirve para enrutado dependiente de la hora) ni datos de elevación. La
  base de administraciones se intenta construir del mismo PBF; si falla, se avisa y se siguen generando teselas.
- No se publica ningún JSON de configuración: la app lo construye con
  `ValhallaConfigFactory.usingTileExtract(<ruta del tar>)`, que parte de los valores por defecto de Valhalla y solo
  fija `mjolnir.tile_extract`. El tar debe guardarse en el almacenamiento de la app (p. ej. con `ValhallaFile`).

### Índice de búsqueda

- `scripts/busqueda.py` (pyosmium) lee el PBF de Mallorca y escribe `busqueda-mallorca.sqlite`: una tabla normal, portable
  (sin FTS5, funciona con la SQLite de Android), con `PRAGMA user_version = 2` e índice sobre `nombre_norm`:

  ```sql
  lugares(nombre TEXT, nombre_norm TEXT, tipo TEXT, categoria TEXT, municipio TEXT, lat REAL, lon REAL, importancia INTEGER)
  CREATE INDEX lugares_nombre_norm ON lugares (nombre_norm);
  -- prefijo del nombre (usa el índice); la consulta se normaliza igual que `nombre_norm`
  SELECT nombre, categoria, municipio, lat, lon FROM lugares
  WHERE nombre_norm >= 'soll' AND nombre_norm < 'solm' ORDER BY importancia DESC LIMIT 20;
  ```
- `nombre_norm` (la app la replica en Kotlin; la tabla de casos está en `scripts/test_scripts.py`): minúsculas; `l·l` y `ŀl` -> `ll`;
  NFD y quitar marcas combinantes; apóstrofos (`' ’ ʼ ` ´`), guiones y `·` restantes -> espacio; espacios colapsados y recortados.
  «Sóller» -> `soller`, «Cala d'Or» -> `cala d or`, «Col·legi» -> `collegi`.
- Contenido: `place` = city/town/village/hamlet/locality/neighbourhood; calles (`highway` con `name`, una fila por calle y
  municipio, en el punto medio de la vía); POIs con nombre (`amenity`, `tourism`, `historic`, `leisure`, `shop`,
  `natural` = beach/peak/bay/cape, `man_made=lighthouse`, `aeroway=aerodrome`; nodos y vías, se ignoran los multipolígonos).
  Si `name:es` difiere de `name`, se añade una fila más con ese nombre.
- `tipo`: `clave:valor` de OSM (`place:city`, `highway:residential`, `amenity:restaurant`; solo la clave si el valor es `yes`).
  `categoria` (en español): lugares `ciudad`, `pueblo`, `aldea`, `barrio`, `paraje`; calles `calle`; POIs `playa`, `cala`, `cabo`,
  `pico`, `mirador`, `gasolinera`, `aparcamiento`, `restaurante`, `cafeteria`, `hotel`, `faro`, `monasterio`, `iglesia`,
  `museo`, `castillo`, `puerto`, `aeropuerto`, `hospital`, `farmacia`, `supermercado` u `otro`. Una playa cuyo nombre empieza por
  «Cala»/«Caló» es `cala`; `natural=bay` también.
- `importancia`: ciudad 100 > pueblo 90/80 > aldea 60 > barrio 50 > paraje 45 > playa/pico/cala/cabo 40 > aeropuerto 38 >
  turismo/histórico/faro 36–35 > amenity/ocio/tienda 32–30 > calles 20–10.
- Municipio: punto en polígono contra las relaciones `boundary=administrative` + `admin_level=8` (índice por bandas de
  latitud). Los límites se extraen del PBF completo de Baleares con `osmium tags-filter r/admin_level=8` (el recorte a
  Mallorca no trae enteras las relaciones que salen del recuadro, p. ej. Palma con Cabrera). Fuera de todo municipio: vacío.

### Relieve y curvas de nivel (MDT05)

- `scripts/relieve.sh` descarga el MDT05 (5 m) del IGN por WCS 2.0.1 (`https://servicios.idee.es/wcs-inspire/mdt`, cobertura
  `Elevacion25830_5`, formato `image/tiff`) en bloques de 20 km, los junta, los pasa a EPSG:3857 en la rejilla de teselas de
  512 px de z13 y genera:
  - `relieve-mallorca.pmtiles`: Terrarium (`R*256 + G + B/256 − 32768` m), PNG sin pérdida, z7–13, alturas redondeadas a 0,25 m;
    sin teselas de mar abierto. El remuestreo de cada zoom se hace sobre la altura antes de codificar.
  - `curvas-mallorca.pmtiles`: `gdal_contour -i 10` (sin la curva 0), teselado con tippecanoe: curvas de 50 m (`indice` = 1) desde
    z11 y las demás (`indice` = 0) desde z12, en la capa `curvas`.
- Si el WCS no responde o devuelve algo que no es un GeoTIFF, el script falla con un mensaje claro (no hay otra fuente).
- Necesita `gdal-bin`, `python3-gdal`, `python3-numpy` y `tippecanoe` (apt de Ubuntu 24.04) y `pmtiles`.
- En los estilos (`vectorial.json`, `satelite.json`) las fuentes `relieve` y `curvas` y las capas `relieve-sombra`, `curvas-linea`,
  `curvas-indice` y `curvas-etiqueta` van con `layout.visibility: "none"`: la app las enciende. Atribución: «MDT05 CC-BY 4.0 scne.es».

### Placas de carretera

`estilo.mjs` sustituye la capa `roads_shields` de Protomaps (solo pinta rutas con `network`) por tres capas de símbolo con la
`ref` de la vía (la primera si hay varias) sobre un sprite propio (`sprites/placas*.json/.png`, generado en el script sin
dependencias), enlazado como sprite múltiple junto al de Protomaps (`placas:placa-azul`):

| Placa | Regla | Fondo / texto y borde |
|---|---|---|
| `placa-azul` | `kind_detail` = `motorway`, o `ref` AP-… / A-… | `#024DA1` / blanco |
| `placa-naranja` | `ref` `Ma-` de ≤ 6 caracteres (Ma-10, Ma-15A) | `#F8931D` / negro |
| `placa-amarilla` | `ref` `Ma-` de 7–8 caracteres (Ma-1110, Ma-1110a) | `#FFDD00` / negro |

Los colores no son oficiales (ver `docs/DECISIONES.md` en el repo de la app).

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
`osmium` (pip), GDAL y tippecanoe (apt de Ubuntu 24.04, sin fijar), la imagen de Valhalla (digest) y `pmtiles` (con comprobación de SHA-256). `@protomaps/basemaps` (npm) está fijado con lockfile
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
- `scripts/busqueda.py`: genera el índice de búsqueda SQLite (`busqueda-mallorca.sqlite`).
- `scripts/relieve.sh`: MDT05 por WCS -> `relieve-mallorca.pmtiles` y `curvas-mallorca.pmtiles` (GDAL, tippecanoe).
- `scripts/satelite.py`: descarga las teselas PNOA a un MBTiles (reanudable).
- `scripts/estilo.mjs`: genera estilos (con relieve, curvas y placas), sprites y fuentes (dependencia npm en `estilo/`).
- `scripts/valhalla.sh`: genera `valhalla-mallorca.tar` con la imagen Docker oficial de Valhalla.
- `scripts/manifest.py`: escribe `manifest.json` (los archivos opcionales ausentes se omiten).
- `scripts/test_scripts.py`: pruebas sin red (`python -I -m unittest discover -s scripts -p 'test_*.py'`).

## Atribuciones y licencias

- Mapa, vías, índice de búsqueda y teselas de enrutado: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), licencia ODbL 1.0.
- Satélite: PNOA, © Instituto Geográfico Nacional de España, CC-BY 4.0 scne.es.
- Relieve y curvas de nivel: MDT05, © Instituto Geográfico Nacional de España, CC-BY 4.0 scne.es.
- Índice de búsqueda: © OpenStreetMap contributors, licencia ODbL 1.0.
- Estilos y esquema de teselas: [Protomaps basemaps](https://github.com/protomaps/basemaps) (BSD-3-Clause) y
  [basemaps-assets](https://github.com/protomaps/basemaps-assets) (sprites CC0-1.0; fuentes Noto Sans, SIL OFL 1.1).
- Los scripts de este repositorio están bajo **GPL-3.0** (ver `LICENSE`). Los datos conservan las licencias de arriba.
