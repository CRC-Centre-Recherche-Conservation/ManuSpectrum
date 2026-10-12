import type { StyleSpecification } from "maplibre-gl";
import type { MapColours } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";

/** OpenFreeMap's TileJSON (OpenMapTiles schema). */
export const OPENFREEMAP_TILES = "https://tiles.openfreemap.org/planet";
export const OPENFREEMAP_GLYPHS =
    "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
export const OHM_TILES =
    "https://vtiles.openhistoricalmap.org/maps/ohm/{z}/{x}/{y}.pbf";
export const BASE_SOURCE = "openmaptiles";
export const WATER_LAYER = "water";
export const LABEL_FONT = ["Noto Sans Regular"];
export const LABEL_FONT_ITALIC = ["Noto Sans Italic"];
const RIVERS_MIN_ZOOM = 5;

/**
 * Paper land on pale water: background, sea, coastline and rivers only. No
 * boundary, road or label layer: the place names are the Explorer's own.
 */
export function baseStyle(colours: MapColours): StyleSpecification {
    return {
        version: 8,
        glyphs: OPENFREEMAP_GLYPHS,
        sources: {
            [BASE_SOURCE]: {
                type: "vector",
                url: OPENFREEMAP_TILES,
            },
        },
        layers: [
            {
                id: "background",
                type: "background",
                paint: { "background-color": colours.land },
            },
            {
                id: WATER_LAYER,
                type: "fill",
                source: BASE_SOURCE,
                "source-layer": "water",
                paint: { "fill-color": colours.sea, "fill-antialias": true },
            },
            {
                id: "water-outline",
                type: "line",
                source: BASE_SOURCE,
                "source-layer": "water",
                paint: {
                    "line-color": colours.coast,
                    "line-width": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        3,
                        0.75,
                        8,
                        1.5,
                    ],
                },
            },
            {
                id: "rivers",
                type: "line",
                source: BASE_SOURCE,
                "source-layer": "waterway",
                minzoom: RIVERS_MIN_ZOOM,
                filter: ["==", ["get", "class"], "river"],
                layout: { "line-cap": "round", "line-join": "round" },
                paint: {
                    "line-color": colours.coast,
                    "line-width": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        5,
                        0.6,
                        10,
                        1.4,
                    ],
                },
            },
        ],
    };
}
