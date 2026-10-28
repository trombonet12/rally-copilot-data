// Genera estilo-mapa/ (estilos MapLibre vectorial y satélite + fuentes + sprites) para la app.
// Uso: node scripts/estilo.mjs <carpeta-salida> <sha-de-basemaps-assets>
// Requiere @protomaps/basemaps instalado (versión fijada en el workflow). Las rutas llevan el marcador {{DIR}}, que
// la app sustituye por la carpeta local donde guarda los mapas (file:///…/mapa).
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
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

const vectorial = { type: "vector", url: `pmtiles://${DIR}/mallorca.pmtiles`, attribution: OSM };
const comun = { version: 8, glyphs: `${DIR}/fuentes/{fontstack}/{range}.pbf`, sprite: `${DIR}/sprites/dark` };

const estiloVectorial = {
  ...comun,
  name: "Rally Copilot · vectorial",
  sources: { protomaps: vectorial },
  layers: layers("protomaps", namedFlavor("dark"), { lang: "es" }),
};

const estiloSatelite = {
  ...comun,
  name: "Rally Copilot · satélite",
  sources: {
    pnoa: { type: "raster", url: `pmtiles://${DIR}/pnoa-mallorca-z16.pmtiles`, tileSize: 256, attribution: PNOA },
    protomaps: vectorial,
  },
  layers: [
    { id: "pnoa", type: "raster", source: "pnoa" },
    ...layers("protomaps", namedFlavor("dark"), { lang: "es", labelsOnly: true }),
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

await mkdir(join(salida, "sprites"), { recursive: true });
await writeFile(join(salida, "vectorial.json"), JSON.stringify(estiloVectorial));
await writeFile(join(salida, "satelite.json"), JSON.stringify(estiloSatelite));

for (const nombre of ["dark.json", "dark.png", "dark@2x.json", "dark@2x.png"]) {
  await bajar(`${ASSETS}/sprites/v4/${nombre}`, join(salida, "sprites", nombre));
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
