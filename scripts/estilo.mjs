// Genera estilo-mapa/ (estilos MapLibre vectorial y satélite + fuentes + sprites) para la app.
// Uso: node scripts/estilo.mjs <carpeta-salida> <sha-de-basemaps-assets>
// Requiere @protomaps/basemaps instalado (versión fijada en el workflow). Las rutas llevan el marcador {{DIR}}, que
// la app sustituye por la carpeta local donde guarda los mapas (file:///…/mapa).
//
// Además del mapa base, cada estilo lleva:
//  - relieve (hillshade sobre un raster-dem Terrarium) y curvas de nivel (vectorial), fuentes `relieve` y `curvas`,
//    con las capas apagadas (`layout.visibility: "none"`): la app las enciende con el interruptor de relieve. Los
//    archivos (relieve-mallorca.pmtiles, curvas-mallorca.pmtiles) son opcionales en el manifest; zooms alineados con
//    scripts/relieve.sh (relieve 7-13, curvas 11-14).
//  - placas de carretera: símbolos con el `ref` de la vía sobre imágenes de placa propias (sprite `placas`, generado
//    aquí sin dependencias) con `icon-text-fit`. Colores según docs/DECISIONES.md § Cartelería (repo de la app).
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { deflateSync } from "node:zlib";
import { layers, namedFlavor } from "@protomaps/basemaps";

const [, , salida, assetsSha] = process.argv;
if (!salida || !assetsSha) {
  console.error("Uso: node scripts/estilo.mjs <carpeta-salida> <sha-de-basemaps-assets>");
  process.exit(2);
}

const DIR = "{{DIR}}";
const ASSETS = `https://raw.githubusercontent.com/protomaps/basemaps-assets/${assetsSha}`;
// Latín básico, ampliado A/B, IPA y diacríticos, griego (no se usa pero es barato), puntuación general y símbolos.
const RANGOS = ["0-255", "256-511", "512-767", "768-1023", "8192-8447", "8448-8703"];
const OSM = "© OpenStreetMap contributors";
const PNOA = "PNOA CC-BY 4.0 scne.es";
const MDT = "MDT05 CC-BY 4.0 scne.es";

// --- placas:inicio (el generador de sprites no depende de nada del resto del archivo) ---------------------------
// Tabla de DECISIONES (placas): azul AP-/A-, naranja Ma- de 1-2 cifras (también autovías: Ma-19, Ma-13), amarillo Ma- de 4 cifras (en Mallorca no hay de 3); por matrícula, no por tipo de vía.
// VERIFICAR colores reales (hex no oficiales, ver docs/investigacion/carteleria.md en el repo de la app).
const PLACAS = [
  { nombre: "placa-azul", fondo: [0x02, 0x4d, 0xa1], borde: [0xff, 0xff, 0xff], texto: "#FFFFFF" },
  { nombre: "placa-naranja", fondo: [0xf8, 0x93, 0x1d], borde: [0x00, 0x00, 0x00], texto: "#000000" },
  { nombre: "placa-amarilla", fondo: [0xff, 0xdd, 0x00], borde: [0x00, 0x00, 0x00], texto: "#000000" },
];
// Medidas @1x en píxeles; en @2x todo se multiplica por 2.
const PLACA_LADO = 24;
const PLACA_RADIO = 6;
const PLACA_BORDE = 2;
const PLACA_SEPARACION = 1;
const PLACA_ESQUINA = 8; // las esquinas redondeadas (8 px) no se estiran con icon-text-fit
const PLACA_MARGEN_TEXTO = 4; // el texto ocupa el interior menos 4 px por lado (borde + aire)

function dentroRedondeado(x, y, lado, radio) {
  const c = lado / 2;
  const m = c - radio;
  const dx = Math.max(Math.abs(x - c) - m, 0);
  const dy = Math.max(Math.abs(y - c) - m, 0);
  return dx * dx + dy * dy <= radio * radio;
}

/** Hoja de sprites RGBA con todas las placas en una fila y su JSON (con stretchX/stretchY/content para icon-text-fit). */
function dibujarPlacas(escala) {
  const lado = PLACA_LADO * escala;
  const radio = PLACA_RADIO * escala;
  const borde = PLACA_BORDE * escala;
  const separacion = PLACA_SEPARACION * escala;
  const ancho = PLACAS.length * lado + (PLACAS.length - 1) * separacion;
  const rgba = Buffer.alloc(ancho * lado * 4);
  const SS = 4; // supersampling 4x4 para suavizar los bordes
  const json = {};
  PLACAS.forEach((placa, i) => {
    const x0 = i * (lado + separacion);
    for (let y = 0; y < lado; y++) {
      for (let x = 0; x < lado; x++) {
        let cubierto = 0;
        let interior = 0;
        for (let sy = 0; sy < SS; sy++) {
          for (let sx = 0; sx < SS; sx++) {
            const px = x + (sx + 0.5) / SS;
            const py = y + (sy + 0.5) / SS;
            if (!dentroRedondeado(px, py, lado, radio)) continue;
            cubierto++;
            if (dentroRedondeado(px - borde, py - borde, lado - 2 * borde, Math.max(radio - borde, 0))) interior++;
          }
        }
        if (cubierto === 0) continue;
        const o = ((y * ancho) + x0 + x) * 4;
        for (let c = 0; c < 3; c++) {
          rgba[o + c] = Math.round((interior * placa.fondo[c] + (cubierto - interior) * placa.borde[c]) / cubierto);
        }
        rgba[o + 3] = Math.round((cubierto / (SS * SS)) * 255);
      }
    }
    const esquina = PLACA_ESQUINA * escala;
    const margen = PLACA_MARGEN_TEXTO * escala;
    json[placa.nombre] = {
      x: x0, y: 0, width: lado, height: lado, pixelRatio: escala,
      stretchX: [[esquina, lado - esquina]], stretchY: [[esquina, lado - esquina]],
      content: [margen, margen, lado - margen, lado - margen],
    };
  });
  return { ancho, alto: lado, rgba, json };
}

const TABLA_CRC = (() => {
  const tabla = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    tabla[n] = c >>> 0;
  }
  return tabla;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = TABLA_CRC[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function bloquePng(tipo, datos) {
  const longitud = Buffer.alloc(4);
  longitud.writeUInt32BE(datos.length);
  const cuerpo = Buffer.concat([Buffer.from(tipo, "ascii"), datos]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(cuerpo));
  return Buffer.concat([longitud, cuerpo, crc]);
}

/** PNG RGBA de 8 bits, sin entrelazado, escrito a mano con zlib de Node. */
function codificarPng(ancho, alto, rgba) {
  const fila = ancho * 4 + 1;
  const datos = Buffer.alloc(fila * alto);
  for (let y = 0; y < alto; y++) {
    datos[y * fila] = 0; // filtro 0 (sin filtro)
    rgba.copy(datos, y * fila + 1, y * ancho * 4, (y + 1) * ancho * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(ancho, 0);
  ihdr.writeUInt32BE(alto, 4);
  ihdr[8] = 8; // profundidad
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    bloquePng("IHDR", ihdr),
    bloquePng("IDAT", deflateSync(datos, { level: 9 })),
    bloquePng("IEND", Buffer.alloc(0)),
  ]);
}
// --- placas:fin ------------------------------------------------------------------------------------------------

// --- Expresiones de las placas -----------------------------------------------------------------------------------
// MapLibre no tiene expresiones regulares: el patrón de la `ref` se resuelve con prefijo (slice) y longitud.
// `ref` puede traer varias («Ma-11;Ma-10»): se toma la primera.
const REF1 = [
  "let", "r", ["to-string", ["get", "ref"]],
  ["case", [">=", ["index-of", ";", ["var", "r"]], 0],
    ["slice", ["var", "r"], 0, ["index-of", ";", ["var", "r"]]],
    ["var", "r"]],
];
const empieza = (prefijo) => ["==", ["slice", REF1, 0, prefijo.length], prefijo];
const LARGO = ["length", REF1];
// Sin `["in", …]` en los filtros: en la sintaxis antigua `in` significa otra cosa y MapLibre Native podria interpretar
// el filtro entero como antiguo.
const BASE_PLACA = [
  "all",
  ["any", ["==", ["get", "kind"], "highway"], ["==", ["get", "kind"], "major_road"], ["==", ["get", "kind"], "minor_road"]],
  ["has", "ref"],
  ["!=", ["get", "ref"], ""],
];
const PLACAS_CAPAS = [
  // [placa, minzoom, filtro]. Color por matrícula, no por tipo de vía (decisión 2026-10-31, Joan): AP-/A- azul; Ma- de
  // 1-2 cifras con sufijo (≤ 6 caracteres: «Ma-15A», «Ma-19») naranja; Ma- de 4 cifras con sufijo (7-8 caracteres:
  // «Ma-1110», «Ma-1110a») amarillo.
  ["placa-azul", 9, ["all", BASE_PLACA, ["any", empieza("AP-"), empieza("A-")]]],
  ["placa-naranja", 10, ["all", BASE_PLACA, empieza("Ma-"), ["<=", LARGO, 6]]],
  ["placa-amarilla", 12, ["all", BASE_PLACA, empieza("Ma-"), [">=", LARGO, 7], ["<=", LARGO, 8]]],
];

function capasPlacas() {
  return PLACAS_CAPAS.map(([nombre, minzoom, filtro]) => ({
    id: nombre.replace("placa-", "placas-"),
    type: "symbol",
    source: "protomaps",
    "source-layer": "roads",
    minzoom,
    filter: filtro,
    layout: {
      "icon-image": `placas:${nombre}`,
      "icon-text-fit": "both",
      "text-field": REF1,
      "text-font": ["Noto Sans Medium"],
      "text-size": 11,
      "symbol-placement": "line",
      "symbol-spacing": 400,
      "icon-rotation-alignment": "viewport",
      "text-rotation-alignment": "viewport",
    },
    paint: { "text-color": PLACAS.find((p) => p.nombre === nombre).texto },
  }));
}

/** Sustituye la capa de escudos de Protomaps (solo pinta rutas con `network`, que Mallorca no tiene) por las placas. */
function conPlacas(capas) {
  const i = capas.findIndex((c) => c.id === "roads_shields");
  if (i < 0) return [...capas, ...capasPlacas()];
  return [...capas.slice(0, i), ...capasPlacas(), ...capas.slice(i + 1)];
}

// --- Relieve y curvas de nivel ------------------------------------------------------------------------------------
const fuentesRelieve = {
  relieve: {
    type: "raster-dem", url: `pmtiles://${DIR}/relieve-mallorca.pmtiles`, encoding: "terrarium", tileSize: 512,
    minzoom: 7, maxzoom: 13, attribution: MDT,
  },
  curvas: { type: "vector", url: `pmtiles://${DIR}/curvas-mallorca.pmtiles`, minzoom: 11, maxzoom: 14, attribution: MDT },
};
const APAGADA = { visibility: "none" };

/** Capas que van bajo las vías (sombra y líneas) y capa de etiquetas, que va arriba. `exageracion`: hillshade. */
function capasRelieve(exageracion) {
  const debajo = [
    {
      id: "relieve-sombra", type: "hillshade", source: "relieve", layout: { ...APAGADA },
      paint: {
        "hillshade-method": "standard", "hillshade-exaggeration": exageracion,
        "hillshade-shadow-color": "#000000", "hillshade-highlight-color": "#8a97a8", "hillshade-accent-color": "#000000",
      },
    },
    {
      id: "curvas-linea", type: "line", source: "curvas", "source-layer": "curvas", minzoom: 12,
      filter: ["==", ["get", "indice"], 0], layout: { ...APAGADA, "line-join": "round" },
      paint: {
        "line-color": "#c9b48f", "line-opacity": 0.35,
        "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.4, 16, 0.9],
      },
    },
    {
      id: "curvas-indice", type: "line", source: "curvas", "source-layer": "curvas", minzoom: 11,
      filter: ["==", ["get", "indice"], 1], layout: { ...APAGADA, "line-join": "round" },
      paint: {
        "line-color": "#c9b48f", "line-opacity": 0.65,
        "line-width": ["interpolate", ["linear"], ["zoom"], 11, 0.6, 16, 1.6],
      },
    },
  ];
  const etiqueta = {
    id: "curvas-etiqueta", type: "symbol", source: "curvas", "source-layer": "curvas", minzoom: 13,
    filter: ["==", ["get", "indice"], 1],
    layout: {
      ...APAGADA, "symbol-placement": "line", "symbol-spacing": 300, "text-field": ["to-string", ["get", "ele"]],
      "text-font": ["Noto Sans Regular"], "text-size": 10,
    },
    paint: { "text-color": "#e6d9bf", "text-halo-color": "#000000", "text-halo-width": 1 },
  };
  return { debajo, etiqueta };
}

/** Inserta el relieve justo antes de las vías (tras el agua y los usos del suelo). */
function conRelieveVectorial(capas) {
  const { debajo, etiqueta } = capasRelieve(0.4);
  let i = capas.findIndex((c) => c.id.startsWith("roads_tunnels"));
  if (i < 0) i = capas.findIndex((c) => c.id === "buildings");
  if (i < 0) i = 1;
  return [...capas.slice(0, i), ...debajo, ...capas.slice(i), etiqueta];
}

// --- Estilos -------------------------------------------------------------------------------------------------------
const vectorial = { type: "vector", url: `pmtiles://${DIR}/mallorca.pmtiles`, attribution: OSM };
// Sprite múltiple (MapLibre Native: soportado desde 2024, mbgl #1858): `default` es el de Protomaps y las placas se
// piden como «placas:placa-azul».
const comun = {
  version: 8,
  glyphs: `${DIR}/fuentes/{fontstack}/{range}.pbf`,
  sprite: [
    { id: "default", url: `${DIR}/sprites/dark` },
    { id: "placas", url: `${DIR}/sprites/placas` },
  ],
};

const estiloVectorial = {
  ...comun,
  name: "Rally Copilot · vectorial",
  sources: { protomaps: vectorial, ...fuentesRelieve },
  layers: conRelieveVectorial(conPlacas(layers("protomaps", namedFlavor("dark"), { lang: "es" }))),
};

const relieveSatelite = capasRelieve(0.25);
const estiloSatelite = {
  ...comun,
  name: "Rally Copilot · satélite",
  sources: {
    pnoa: { type: "raster", url: `pmtiles://${DIR}/pnoa-mallorca-z16.pmtiles`, tileSize: 256, attribution: PNOA },
    protomaps: vectorial,
    ...fuentesRelieve,
  },
  layers: [
    { id: "pnoa", type: "raster", source: "pnoa" },
    ...relieveSatelite.debajo,
    ...conPlacas(layers("protomaps", namedFlavor("dark"), { lang: "es", labelsOnly: true })),
    relieveSatelite.etiqueta,
  ],
};

/** Nombres de fuente usados en cualquier expresión del estilo. */
function fuentes(estilo) {
  const nombres = new Set();
  const recorrer = (v) => {
    // Devanagari solo se usa para nombres en esa escritura: no los hay en Mallorca.
    if (typeof v === "string" && v.startsWith("Noto Sans") && !v.includes("Devanagari")) nombres.add(v);
    else if (Array.isArray(v)) v.forEach(recorrer);
    else if (v && typeof v === "object") Object.values(v).forEach(recorrer);
  };
  estilo.layers.forEach((capa) => recorrer(capa.layout?.["text-font"]));
  return [...nombres];
}

async function bajar(url, destino) {
  const respuesta = await fetch(url);
  if (!respuesta.ok) throw new Error(`${respuesta.status} ${url}`);
  await writeFile(destino, Buffer.from(await respuesta.arrayBuffer()));
}

/** Comprueba que cada capa apunta a una fuente definida y que los ids no se repiten. */
function validar(estilo) {
  const ids = new Set();
  for (const capa of estilo.layers) {
    if (ids.has(capa.id)) throw new Error(`${estilo.name}: capa repetida ${capa.id}`);
    ids.add(capa.id);
    if (capa.source && !estilo.sources[capa.source]) throw new Error(`${estilo.name}: ${capa.id} usa la fuente ${capa.source}, que no existe`);
  }
}
validar(estiloVectorial);
validar(estiloSatelite);

await mkdir(join(salida, "sprites"), { recursive: true });
await writeFile(join(salida, "vectorial.json"), JSON.stringify(estiloVectorial));
await writeFile(join(salida, "satelite.json"), JSON.stringify(estiloSatelite));

for (const nombre of ["dark.json", "dark.png", "dark@2x.json", "dark@2x.png"]) {
  await bajar(`${ASSETS}/sprites/v4/${nombre}`, join(salida, "sprites", nombre));
}
for (const [escala, sufijo] of [[1, ""], [2, "@2x"]]) {
  const { ancho, alto, rgba, json } = dibujarPlacas(escala);
  await writeFile(join(salida, "sprites", `placas${sufijo}.png`), codificarPng(ancho, alto, rgba));
  await writeFile(join(salida, "sprites", `placas${sufijo}.json`), JSON.stringify(json));
}
const usadas = new Set([...fuentes(estiloVectorial), ...fuentes(estiloSatelite)]);
for (const fuente of usadas) {
  await mkdir(join(salida, "fuentes", fuente), { recursive: true });
  for (const rango of RANGOS) {
    await bajar(`${ASSETS}/fonts/${encodeURIComponent(fuente)}/${rango}.pbf`, join(salida, "fuentes", fuente, `${rango}.pbf`));
  }
}
await bajar(`${ASSETS}/fonts/OFL.txt`, join(salida, "fuentes", "OFL.txt"));
console.log(`estilos: vectorial (${estiloVectorial.layers.length} capas), satélite (${estiloSatelite.layers.length}); fuentes: ${[...usadas].join(", ")}`);
