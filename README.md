# Rally Copilot · datos de Mallorca

Datos offline de **Mallorca** para la app [Rally Copilot](https://github.com/trombonet12/Rally-Copilot): mapa
vectorial, estilo, vías con límite de velocidad, mapa satélite, índice de búsqueda, relieve, curvas de nivel y radares. Un workflow de GitHub Actions los regenera cada mes
y los publica en una GitHub Release (`datos-AAAA.MM.DD-N`). No hay servidor: la app descarga los archivos de la
release y solo baja los que han cambiado.

## Contenido de cada release

| Archivo | Qué es | Origen |
|---|---|---|
| `mallorca.pmtiles` | Mapa vectorial (teselas hasta z15) generado con Planetiler y el esquema de Protomaps | OpenStreetMap vía Geofabrik |
| `estilo-mapa.zip` | Estilos MapLibre (`vectorial.json`, `satelite.json`), sprites y fuentes (glifos). Las rutas llevan el marcador `{{DIR}}`, que la app sustituye por su carpeta local | Protomaps basemaps, Noto Sans |
| `vias-mallorca.tsv.gz` | Vías circulables con `maxspeed`, `oneway`, `ref` y `name` (formato `#vias-mallorca v1`) | OpenStreetMap |
| `pnoa-mallorca-z16.pmtiles` | Ortofoto satélite z0–16 (JPEG sin recomprimir) | PNOA, IGN |
| `pnoa-mallorca-z17.pmtiles` | Ortofoto satélite solo z17 (JPEG sin recomprimir; se superpone al z16 para más detalle). **Opcional y fuera de `manifest.json`**: va en `manifest-extra.json` (`id` `satelite-z17`) | PNOA, IGN |
| `valhalla-mallorca.tar` | Teselas de enrutado de Valhalla 3.9.1 (tar de extracción con `index.bin`) para [valhalla-mobile](https://github.com/Rallista/valhalla-mobile) 0.6.4. Archivo opcional en el manifest (`id` `valhalla`) | OpenStreetMap vía Geofabrik |
| `busqueda-mallorca.sqlite` | Índice de búsqueda: SQLite con la tabla `lugares` (lugares, calles y POIs con nombre; sin FTS5). Opcional (`id` `busqueda`) | OpenStreetMap |
| `relieve-mallorca.pmtiles` | Relieve para sombreado (`raster-dem` Terrarium, teselas PNG de 512 px, z7–13, alturas a 0,25 m). Opcional (`id` `relieve`) | MDT05, IGN |
| `curvas-mallorca.pmtiles` | Curvas de nivel cada 10 m (capa `curvas`, z11–14; atributos `ele` e `indice` = 1 cada 50 m). Opcional (`id` `curvas`) | MDT05, IGN |
| `vias-notas-mallorca.tsv.gz` | Etiquetas de vías y nodos de OSM y perfil de altura (5 m) de cada vía, para las notas de rally (formato `#vias-notas v1`, ver abajo). Opcional (`id` `vias-notas`) | OpenStreetMap, MDT05 (IGN) |
| `radares-mallorca.tsv` | Radares fijos, de tramo y zonas de radar móvil (formato `#radares v1`, ver abajo; pocos KB). Opcional (`id` `radares`) y **en `manifest.json`**, no en el extra | DGT (NAP), OpenStreetMap, informe de cinemómetros de la DGT |
| `manifest.json` | Índice: versión, tamaño, SHA-256, URL y atribución de cada archivo | Generado |
| `manifest-extra.json` | Mismo formato que `manifest.json`, solo con los archivos opcionales que las apps ya instaladas no deben bajar (hoy `satelite-z17`). Se omite si no hay ninguno | Generado |

Cada archivo del manifest lleva su propia `version`. El satélite (z16 y z17) cambia rara vez: se reutiliza el de la release
anterior, verificando su SHA-256, y conserva su versión.

El z17 está en `manifest-extra.json` y no en `manifest.json` porque las apps instaladas descargan **todos** los ids que
lista `manifest.json` (no ignoran los desconocidos) y su límite de espacio es de 2 GB. Para pasarlo a `manifest.json`
hay que vaciar `SEPARADOS` en `scripts/manifest.py`, cuando ya no queden apps antiguas.

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

### Vías para las notas de rally (`vias-notas-mallorca.tsv.gz`)

- `scripts/vias_notas.py etiquetas` (pyosmium) saca las etiquetas del PBF y `scripts/vias_notas.py perfil` (Python del sistema con
  `python3-gdal`) muestrea el VRT del MDT05 que deja `relieve.sh` en `trabajo/relieve/mdt05.vrt`. No cambia `vias-mallorca.tsv.gz`.
- Formato v1: UTF-8, campos separados por tabulador, primera línea `#vias-notas v1`:

  ```
  V  id_via  bridge  tunnel  junction  lanes  width  hazard  surface     (vacíos si no hay; solo vías con alguna)
  N  lat_e6,lon_e6  tipo                                                 (nodos, en millonésimas de grado)
  P  id_via  5  z0_dm,d1,d2,...                                          (una por cada vía de vias-mallorca)
  ```
- `tipo` de `N`: valor de `traffic_calming` (`bump`, `hump`, `table`…), `ford`, `level_crossing`, `stop`, `give_way`,
  `traffic_signals` o `hazard:<valor>`. Las clases de vía son las de `vias.py`.
- `P`: altura del MDT05 (interpolación bilineal) en decímetros enteros cada 5 m a lo largo de la polilínea de la vía en
  `vias-mallorca` (mismo `id`): muestras a 0, 5, 10… m desde el primer nodo y una última en el último nodo (L = longitud;
  nº de muestras = ceil(L/5) + 1; distancia equirrectangular, R = 6371000 m). El primer valor es absoluto y los demás,
  diferencias con el anterior. En vías con `bridge`/`tunnel` la altura interior se interpola linealmente entre los extremos
  (el MDT es terreno desnudo). Mar, sin dato o fuera del MDT: 0.
- Atribución: «© OpenStreetMap contributors; MDT05 CC-BY 4.0 scne.es» (ODbL-1.0, CC-BY-4.0).

### Radares (`radares-mallorca.tsv`)

- `scripts/radares.py` lo genera en el job `build` (sin token) justo después de recortar el PBF, con pyosmium para OSM y la
  librería estándar para el XML de la DGT. Falla (y con él el job) si salen **menos de 5 radares fijos**, si algún radar queda
  **fuera del bbox**, si hay ids repetidos o un tramo sin su pareja inicio/fin. Si solo falla la descarga del XML de la DGT,
  sale el TSV con OSM y un aviso.
- Fuentes:
  - **DGT**: XML DATEX II v1 de radares del NAP (`PredefinedLocationsPublication/radares/content.xml`), filtrado al bbox.
    Sus cabinas son `FIJO`; las que el informe de cinemómetros da como radar móvil en ese PK pasan a `ZONA_MOVIL` (ver abajo).
    Los tramos de velocidad media (`CinemometrosVelocidadMedia`, de `from` a `to`) serían `TRAMO_*`; el feed actual no trae
    ninguno en Mallorca. El XML no da límite ni sentido.
  - **OSM**: nodos `highway=speed_camera` (`maxspeed`, `direction`) y relaciones `type=enforcement`: `enforcement=maxspeed`
    (`device`, `from`, `to`) da los fijos y `enforcement=average_speed` los tramos (de `from` a `to`, o de un dispositivo al
    otro si faltan). El rumbo es `direction` o, si falta, el de `from` a `to`; un dispositivo con dos relaciones (una por
    sentido) da dos filas.
  - **Informe de cinemómetros de la DGT** (PDF, 2025-03-21), curado en `datos/cinemometros-mallorca.tsv` (filas de Baleares
    con carretera `Ma-*`; carretera, tipo, PK, sentido, fecha y fuente). No se lee el PDF en CI (la URL lleva fecha). Solo se usa
    para clasificar las cabinas del XML por PK exacto (el PDF y el XML no siempre coinciden en el nombre de la carretera).
    Los **rangos de PK** (`Ma-12 0.080 - 111.100`...) no se convierten en coordenadas: ni el PDF ni el XML dan el origen de
    los PK de cada carretera, así que hoy no salen como zonas.
- Fusión: un punto de la DGT absorbe los `FIJO` de OSM a menos de 100 m con rumbo compatible (las coordenadas de la DGT
  quedan a 8-94 m de la cámara de OSM) y conserva su posición, su tipo y su límite si lo tuviera; entre los `FIJO` restantes,
  los de menos de 50 m con rumbo compatible (menos de 90° de diferencia, o alguno sin rumbo) son uno. Los tramos no se fusionan.
- Formato `#radares v1`: UTF-8, campos separados por tabulador; línea 1 `#radares v1`, línea 2 los nombres de columna con
  `#`, y una fila por radar:

  ```
  tipo  id  lat  lon  rumbo  limite_kmh  tramo_id  fuente        (ejemplo, columnas alineadas solo para leerlas)
  FIJO          osm-n992002040      39.536760  2.728520  100  120            OSM
  FIJO          dgt-120643          39.634300  2.748535  215  120            DGT
  TRAMO_INICIO  osm-r20233503-ini   39.486943  2.746213  43   90   osm-r20233503  OSM
  TRAMO_FIN     osm-r20233503-fin   39.493085  2.753659  43   90   osm-r20233503  OSM
  ZONA_MOVIL    dgt-120651          39.456660  2.946660  270  80   dgt-120651     DGT-PDF
  ```
  - `tipo`: `FIJO`, `TRAMO_INICIO`, `TRAMO_FIN` o `ZONA_MOVIL`. `lat`/`lon`: grados decimales con 6 decimales.
  - `rumbo`: grados 0-359 hacia donde circulan los vehículos vigilados; **vacío = ambos sentidos o desconocido**. En OSM
    `direction` coincide con el sentido de la circulación (comprobado con las relaciones de Mallorca).
  - `limite_kmh`: entero o vacío. `fuente`: `DGT`, `OSM` o `DGT-PDF` (cabina que el informe de la DGT da como móvil).
  - `tramo_id`: vacío en `FIJO`. `TRAMO_INICIO` y `TRAMO_FIN` del mismo tramo comparten `tramo_id` y van en filas consecutivas
    (inicio antes que fin); `rumbo` y `limite_kmh` se repiten en las dos. Cada sentido de un tramo es otro tramo.
  - `ZONA_MOVIL`: **polilínea en filas consecutivas** con el mismo `tramo_id`, en orden de recorrido; una zona de un solo
    punto (todas las de hoy: las cabinas) es una fila con `tramo_id` = `id`. Es una zona probable, no un radar confirmado.
  - `id` es único por fila.

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

- **Automático**: el día 1 de cada mes a las 03:00 UTC. Reutiliza el satélite (z16 y z17) de la última release.
- **Manual**: pestaña *Actions* → *Datos Mallorca* → *Run workflow*. La casilla `satelite` fuerza a descargar de nuevo
  las teselas PNOA z16 y z17 (lento: decenas de miles de peticiones al IGN) y se activa sola, para cada una, si la última
  release no la trae. Para generar el z17 por primera vez basta lanzarlo con la casilla sin marcar: el z16 se reutiliza.
- El z17 se genera en el job propio `satelite_z17` (~4–5 h estimadas, en paralelo a `build`; límite de 6 h por job). Si el
  paso de descarga no termina guarda el progreso en la caché de Actions (`satelite-z17-*`) y al relanzar el workflow
  continúa. Un fallo del z17 no impide publicar la release: se reutiliza el z17 anterior o sale sin él.
- Conserva las 3 últimas releases `datos-*`; las anteriores se borran junto con su etiqueta.
- GitHub desactiva los workflows programados tras 60 días sin actividad en el repo: si pasa, se reactiva a mano desde
  *Actions*.

Versiones fijadas en `.github/workflows/datos.yml`: Planetiler vía `protomaps/basemaps` (SHA), `basemaps-assets` (SHA),
`osmium` (pip), GDAL y tippecanoe (apt de Ubuntu 24.04, sin fijar), la imagen de Valhalla (digest) y `pmtiles` (con comprobación de SHA-256). `@protomaps/basemaps` (npm) está fijado con lockfile
(`estilo/package.json` y `estilo/package-lock.json`) y se instala con `npm ci --ignore-scripts`. Las acciones van
fijadas por SHA y las actualiza Dependabot cada mes.

## Seguridad del workflow

- Cuatro jobs: `decidir`, `build` y `satelite_z17` solo tienen `contents: read`; el código de terceros (Maven/Planetiler,
  npm, pip) se ejecuta en `build`, sin `GH_TOKEN`. Solo `publicar` tiene `contents: write`: descarga el artefacto, genera el
  manifest, crea la release y aplica la retención.
- El satélite reutilizado de la release anterior se verifica contra el SHA-256 de su `manifest.json` (z16) o
  `manifest-extra.json` (z17) antes de usarlo.
- **Riesgos conocidos sin mitigar**: `osmium` de PyPI se fija por versión pero no por hash, y Planetiler descarga con
  `--download` fuentes auxiliares (p. ej. Natural Earth, datos de agua) sin comprobar su hash.

## Scripts

- `scripts/vias.py`: extrae las vías del PBF a TSV comprimido.
- `scripts/radares.py`: radares fijos, de tramo y zonas móviles (DGT + OSM) a `radares-mallorca.tsv`; `datos/cinemometros-mallorca.tsv` es el extracto curado del informe de la DGT y `scripts/fixtures/` un recorte real del XML para las pruebas.
- `scripts/vias_notas.py`: etiquetas de OSM y perfil de altura de las vías (`vias-notas-mallorca.tsv.gz`).
- `scripts/busqueda.py`: genera el índice de búsqueda SQLite (`busqueda-mallorca.sqlite`).
- `scripts/relieve.sh`: MDT05 por WCS -> `relieve-mallorca.pmtiles` y `curvas-mallorca.pmtiles` (GDAL, tippecanoe).
- `scripts/satelite.py`: descarga las teselas PNOA entre `--zmin` (0 por defecto) y `--zmax` a un MBTiles (reanudable; anota las teselas de mar en la tabla `sin_cobertura` para no repetirlas).
- `scripts/estilo.mjs`: genera estilos (con relieve, curvas y placas), sprites y fuentes (dependencia npm en `estilo/`).
- `scripts/valhalla.sh`: genera `valhalla-mallorca.tar` con la imagen Docker oficial de Valhalla.
- `scripts/manifest.py`: escribe `manifest.json` y, si hay archivos separados (z17), `manifest-extra.json` (los opcionales ausentes se omiten).
- `scripts/test_scripts.py`: pruebas sin red (`python -I -m unittest discover -s scripts -p 'test_*.py'`).

## Atribuciones y licencias

- Mapa, vías, índice de búsqueda y teselas de enrutado: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), licencia ODbL 1.0.
- Satélite: PNOA, © Instituto Geográfico Nacional de España, CC-BY 4.0 scne.es.
- Radares: DGT, [NAP](https://nap.dgt.es) (CC BY, según la ficha del dataset; **VERIFICAR** las condiciones de reutilización con nap@dgt.es) e
  informe de cinemómetros de la DGT; cámaras y relaciones `enforcement` de © OpenStreetMap contributors, licencia ODbL 1.0.
- Relieve y curvas de nivel: MDT05, © Instituto Geográfico Nacional de España, CC-BY 4.0 scne.es.
- Índice de búsqueda: © OpenStreetMap contributors, licencia ODbL 1.0.
- Estilos y esquema de teselas: [Protomaps basemaps](https://github.com/protomaps/basemaps) (BSD-3-Clause) y
  [basemaps-assets](https://github.com/protomaps/basemaps-assets) (sprites CC0-1.0; fuentes Noto Sans, SIL OFL 1.1).
- Los scripts de este repositorio están bajo **GPL-3.0** (ver `LICENSE`). Los datos conservan las licencias de arriba.
