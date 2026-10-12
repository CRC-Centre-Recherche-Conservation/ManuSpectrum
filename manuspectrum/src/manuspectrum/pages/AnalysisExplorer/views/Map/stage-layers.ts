import {
    LABEL_FONT,
    LABEL_FONT_ITALIC,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/base-style.ts";

import type {
    ExpressionSpecification,
    FilterSpecification,
    LayerSpecification,
    SymbolLayerSpecification,
} from "maplibre-gl";
import type { MapColours } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";

const DEG = Math.PI / 180;

export const PLACES_SOURCE = "ms-places";
export const TERRITORIES_SOURCE = "ms-territories";
export const OHM_SOURCE = "ohm";
export const BORDERS_LAYER = "ohm-borders";
export const SLOTS = 4;
export const PIP_ANGLES_DEG = [-90, -40, 10, 60] as const;
/** A pip sits this far outside its place's ring, in CSS pixels. */
export const PIP_GAP_PX = 4;
/** The pip offset around the smallest ring (radius 10), in CSS pixels. */
export const PIP_OFFSET_PX = 14;
/** The four slot pips around the smallest ring; the layers place them on each ring's edge (`pipOffset`). */
export const PIP_OFFSETS: [number, number][] = PIP_ANGLES_DEG.map((angle) =>
    polar(angle, PIP_OFFSET_PX),
);
/** Layers that answer a click or a hover with the place's id. */
export const CLICKABLE_LAYERS = [
    "place-points",
    "place-badges",
    "place-rings",
    "place-rings-dashed",
] as const;

export const RING_DASHED_IMAGE = "ring-dashed";
export const HATCH_IMAGE = "hatch";
/** Image names of the firm and pale pip of `slot` (1–4). */
export const pipImage = (slot: number, pale: boolean): string =>
    `pip-${pale ? "pale" : "firm"}-${slot}`;

/** Device pixels per CSS pixel of the drawn images. */
export const IMAGE_PIXEL_RATIO = 2;
/** The dashed ring is drawn at this CSS size; `icon-size = ring / 16` scales it to the ring's radius. */
const RING_IMAGE_PX = 32;
const RING_ICON_DIVISOR = RING_IMAGE_PX / 2;
const PIP_IMAGE_PX = 14;
const HATCH_IMAGE_PX = 6;
const HATCH_LINE_PX = 1;
const HATCH_OPACITY = 0.55;
/** What an isolated territory leaves of the other slots' opacity. */
const ISOLATE_FADE = 0.2;
/** The pips' scale at the zooms of `PIP_SCALE_ZOOMS`: smaller around the fitted view, whole from zoom 7. */
const PIP_SCALE = [0.75, 1] as const;
const PIP_SCALE_ZOOMS = [4, 7] as const;
const RING_FILL_OPACITY = 0.22;
const LINKED_FADE = 0.35;
const POINT_RADIUS = 5;
const POINT_HOVER_RADIUS = 6;
/** A ring radius past which no place grows (sqrt of 1 000 000 documents). */
const RING_LIMIT_PX = 4096;
const BORDER_LEVELS = [1, 2];
const MID_YEAR = 0.5;
const OPEN_START = -1_000_000;
const OPEN_END = 1_000_000;

function polar(angle: number, radius: number): [number, number] {
    const round = (value: number): number => Math.round(value * 1000) / 1000;
    return [
        round(Math.cos(angle * DEG) * radius),
        round(Math.sin(angle * DEG) * radius),
    ];
}

const stateIs = (key: string): ExpressionSpecification => [
    "boolean",
    ["feature-state", key],
    false,
];
const dimmed = (opacity: number): ExpressionSpecification => [
    "case",
    stateIs("dim"),
    LINKED_FADE,
    opacity,
];
const isKind = (kind: "point" | "area"): FilterSpecification => [
    "==",
    ["get", "kind"],
    kind,
];

/** The pip of `slot` at `scale`, as an offset in icon units: `(ring + 4) / scale · (cos a, sin a)`. */
function ringOffset(slot: number, scale: number): ExpressionSpecification {
    const angle = PIP_ANGLES_DEG[slot - 1];
    return [
        "interpolate",
        ["linear"],
        ["get", "ring"],
        0,
        ["literal", polar(angle, PIP_GAP_PX / scale)],
        RING_LIMIT_PX,
        ["literal", polar(angle, (RING_LIMIT_PX + PIP_GAP_PX) / scale)],
    ];
}

/**
 * The offset of the pip of `slot` on the outer edge of a ring of radius
 * `["get", "ring"]`, `(ring + 4) · (cos a, sin a)` in CSS pixels at every
 * zoom. MapLibre multiplies `icon-offset` by `icon-size`, so each zoom stop
 * divides by the pip's scale there (`PIP_SCALE`). The offset is linear in
 * the ring, so an `interpolate` between two literal arrays gives it exactly.
 */
function pipOffset(slot: number): ExpressionSpecification {
    return [
        "interpolate",
        ["linear"],
        ["zoom"],
        PIP_SCALE_ZOOMS[0],
        ringOffset(slot, PIP_SCALE[0]),
        PIP_SCALE_ZOOMS[1],
        ringOffset(slot, PIP_SCALE[1]),
    ];
}

const PIP_SIZE: ExpressionSpecification = [
    "interpolate",
    ["linear"],
    ["zoom"],
    PIP_SCALE_ZOOMS[0],
    PIP_SCALE[0],
    PIP_SCALE_ZOOMS[1],
    PIP_SCALE[1],
];

function pipLayer(slot: number, pale: boolean): SymbolLayerSpecification {
    const level = pale ? 2 : 1;
    return {
        id: `pip-${slot}-${pale ? "pale" : "firm"}`,
        type: "symbol",
        source: PLACES_SOURCE,
        layout: {
            "icon-image": pipImage(slot, pale),
            "icon-size": PIP_SIZE,
            "icon-offset": pipOffset(slot),
            "icon-allow-overlap": true,
            "icon-ignore-placement": true,
        },
        paint: {
            "icon-opacity": [
                "match",
                ["feature-state", `t${slot}`],
                level,
                1,
                0,
            ],
        },
    };
}

function labelLayer(
    id: string,
    kind: "point" | "area",
    font: string[],
    colours: MapColours,
): SymbolLayerSpecification {
    return {
        id,
        type: "symbol",
        source: PLACES_SOURCE,
        filter: isKind(kind),
        layout: {
            "text-field": ["get", "name"],
            "text-font": font,
            "text-size": ["interpolate", ["linear"], ["zoom"], 4, 11, 8, 12.5],
            "text-offset": [0, 1.2],
            "text-variable-anchor": ["top", "bottom", "left", "right"],
            "text-radial-offset": 1,
            "text-optional": true,
            "text-allow-overlap": false,
            "symbol-sort-key": ["-", ["get", "documents"]],
        },
        paint: {
            "text-color": [
                "case",
                stateIs("selected"),
                colours.blue,
                colours.ink,
            ],
            "text-halo-color": colours.surface,
            "text-halo-width": 1.5,
            "text-halo-blur": 0.5,
            "text-opacity": dimmed(1),
        },
    };
}

/** Place layers, bottom to top: rings, dashed rings, points, pips (firm and pale per slot), labels and area badges. */
export function placeLayers(colours: MapColours): LayerSpecification[] {
    const pips = Array.from({ length: SLOTS }, (_, index) => [
        pipLayer(index + 1, false),
        pipLayer(index + 1, true),
    ]).flat();
    return [
        {
            id: "place-rings",
            type: "circle",
            source: PLACES_SOURCE,
            filter: ["!=", ["get", "dashed"], true],
            paint: {
                "circle-radius": ["get", "ring"],
                "circle-color": colours.ring,
                "circle-opacity": dimmed(RING_FILL_OPACITY),
                "circle-stroke-color": colours.ring,
                "circle-stroke-width": 1,
                "circle-stroke-opacity": dimmed(0.9),
                "circle-pitch-alignment": "map",
            },
        },
        {
            id: "place-rings-dashed",
            type: "symbol",
            source: PLACES_SOURCE,
            filter: ["==", ["get", "dashed"], true],
            layout: {
                "icon-image": RING_DASHED_IMAGE,
                "icon-size": ["/", ["get", "ring"], RING_ICON_DIVISOR],
                "icon-allow-overlap": true,
                "icon-ignore-placement": true,
            },
            paint: { "icon-opacity": dimmed(1) },
        },
        {
            id: "place-points",
            type: "circle",
            source: PLACES_SOURCE,
            filter: isKind("point"),
            paint: {
                "circle-radius": [
                    "case",
                    stateIs("hover"),
                    POINT_HOVER_RADIUS,
                    POINT_RADIUS,
                ],
                "circle-color": colours.ink,
                "circle-stroke-color": [
                    "case",
                    stateIs("selected"),
                    colours.blue,
                    colours.surface,
                ],
                "circle-stroke-width": ["case", stateIs("selected"), 3, 1.5],
                "circle-opacity": dimmed(1),
                "circle-stroke-opacity": dimmed(1),
            },
        },
        ...pips,
        labelLayer("place-labels", "point", LABEL_FONT, colours),
        labelLayer("place-badges", "area", LABEL_FONT_ITALIC, colours),
    ];
}

const slotColour = (
    colours: MapColours,
    otherwise: string,
): ExpressionSpecification => [
    "match",
    ["get", "slot"],
    1,
    colours.focus[0],
    2,
    colours.focus[1],
    3,
    colours.focus[2],
    4,
    colours.focus[3],
    otherwise,
];

/**
 * The opacity paint of the territory layers; with `slot`, the other slots
 * fade to `ISOLATE_FADE` of theirs, so that slot's zone reads alone.
 */
export function territoryOpacity(slot: number | null): {
    cells: ExpressionSpecification;
    hatch: ExpressionSpecification | number;
    edges: ExpressionSpecification | number;
} {
    const alpha: ExpressionSpecification = ["get", "alpha"];
    if (slot === null) {
        return { cells: alpha, hatch: HATCH_OPACITY, edges: 1 };
    }
    const isIt: ExpressionSpecification = ["==", ["get", "slot"], slot];
    return {
        cells: ["case", isIt, alpha, ["*", alpha, ISOLATE_FADE]],
        hatch: ["case", isIt, HATCH_OPACITY, HATCH_OPACITY * ISOLATE_FADE],
        edges: ["case", isIt, 1, ISOLATE_FADE],
    };
}

/** Territory layers, to be added before `WATER_LAYER` so the sea covers the grid. */
export function territoryLayers(colours: MapColours): LayerSpecification[] {
    const opacity = territoryOpacity(null);
    return [
        {
            id: "territory-cells",
            type: "fill",
            source: TERRITORIES_SOURCE,
            filter: ["==", ["get", "layer"], "cell"],
            paint: {
                "fill-color": slotColour(colours, colours.ink),
                "fill-opacity": opacity.cells,
                "fill-antialias": false,
            },
        },
        {
            id: "territory-hatch",
            type: "fill",
            source: TERRITORIES_SOURCE,
            filter: [
                "all",
                ["==", ["get", "layer"], "cell"],
                ["==", ["get", "hatched"], true],
            ],
            paint: {
                "fill-pattern": HATCH_IMAGE,
                "fill-opacity": opacity.hatch,
                "fill-antialias": false,
            },
        },
        {
            id: "territory-edges",
            type: "line",
            source: TERRITORIES_SOURCE,
            filter: ["==", ["get", "layer"], "edge"],
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
                "line-color": slotColour(colours, colours.surface),
                "line-width": ["match", ["get", "slot"], 0, 2, 2.2],
                "line-opacity": opacity.edges,
            },
        },
    ];
}

/**
 * Country-level borders of OpenHistoricalMap alive in the middle of `year`
 * (an open start or end counts as always), or every one without a year.
 */
export function bordersFilter(year: number | null): FilterSpecification {
    const level: FilterSpecification = [
        "in",
        ["get", "admin_level"],
        ["literal", BORDER_LEVELS],
    ];
    if (year === null) return ["all", level];
    const moment = year + MID_YEAR;
    return [
        "all",
        level,
        ["<=", ["coalesce", ["get", "start_decdate"], OPEN_START], moment],
        [">=", ["coalesce", ["get", "end_decdate"], OPEN_END], moment],
    ];
}

export function bordersLayer(
    year: number | null,
    colours: MapColours,
    visible: boolean,
): LayerSpecification {
    return {
        id: BORDERS_LAYER,
        type: "line",
        source: OHM_SOURCE,
        "source-layer": "land_ohm_lines",
        filter: bordersFilter(year),
        layout: { visibility: visible ? "visible" : "none" },
        paint: {
            "line-color": colours.ring,
            "line-width": 1,
            "line-dasharray": [3, 2],
        },
    };
}

export interface DrawnImage {
    width: number;
    height: number;
    data: Uint8Array;
}

/** A context to draw on, or null when the browser gives none (jsdom, a refused canvas). */
export type CanvasFactory = (
    width: number,
    height: number,
) => CanvasRenderingContext2D | null;

const defaultCanvas: CanvasFactory = (width, height) => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    try {
        return canvas.getContext("2d");
    } catch {
        return null;
    }
};

/** `draw` on a `size`×`size` CSS-pixel canvas at `IMAGE_PIXEL_RATIO`; a transparent image of the same size without a 2D context. */
function drawImage(
    size: number,
    draw: (context: CanvasRenderingContext2D, side: number) => void,
    make: CanvasFactory,
): DrawnImage {
    const side = size * IMAGE_PIXEL_RATIO;
    const context = make(side, side);
    if (!context) {
        return {
            width: side,
            height: side,
            data: new Uint8Array(side * side * 4),
        };
    }
    draw(context, side);
    const pixels = context.getImageData(0, 0, side, side);
    return { width: side, height: side, data: new Uint8Array(pixels.data) };
}

/** The dashed ring of an attributed place: 1 CSS px stroke, 8/6 device px dashes, filled at 22 %. */
export function dashedRingImage(
    colour: string,
    make: CanvasFactory = defaultCanvas,
): DrawnImage {
    return drawImage(
        RING_IMAGE_PX,
        (context, side) => {
            const centre = side / 2;
            context.beginPath();
            context.arc(centre, centre, centre - 1, 0, 2 * Math.PI);
            context.globalAlpha = RING_FILL_OPACITY;
            context.fillStyle = colour;
            context.fill();
            context.globalAlpha = 1;
            context.strokeStyle = colour;
            context.lineWidth = IMAGE_PIXEL_RATIO;
            context.setLineDash([8, 6]);
            context.stroke();
        },
        make,
    );
}

/** The tie texture of Dominant: paper lines at 45°, 1 px wide, on a 6 px tile. */
export function hatchImage(
    colour: string,
    make: CanvasFactory = defaultCanvas,
): DrawnImage {
    return drawImage(
        HATCH_IMAGE_PX,
        (context, side) => {
            context.strokeStyle = colour;
            context.lineWidth = HATCH_LINE_PX * IMAGE_PIXEL_RATIO;
            context.lineCap = "square";
            context.beginPath();
            for (const shift of [-side, 0, side]) {
                context.moveTo(shift, side);
                context.lineTo(shift + side, 0);
            }
            context.stroke();
        },
        make,
    );
}

export const PIP_FONT = "700 18px 'JetBrains Mono', monospace";

/**
 * The pip of `slot`: firm is a disc in the slot hue with its digit in
 * `focusOn` and a 1.5 px surface rim; pale is hollow (surface fill, hue rim,
 * hue digit), the Explorer's « evidence » pip.
 */
export function pipDisc(
    slot: number,
    pale: boolean,
    colours: MapColours,
    make: CanvasFactory = defaultCanvas,
): DrawnImage {
    const hue = colours.focus[slot - 1];
    return drawImage(
        PIP_IMAGE_PX,
        (context, side) => {
            const centre = side / 2;
            const rim = 1.5 * IMAGE_PIXEL_RATIO;
            context.beginPath();
            context.arc(centre, centre, centre - rim / 2, 0, 2 * Math.PI);
            context.fillStyle = pale ? colours.surface : hue;
            context.fill();
            context.lineWidth = rim;
            context.strokeStyle = pale ? hue : colours.surface;
            context.stroke();
            context.fillStyle = pale ? hue : colours.focusOn;
            context.font = PIP_FONT;
            context.textAlign = "center";
            context.textBaseline = "middle";
            context.fillText(String(slot), centre, centre + 1);
        },
        make,
    );
}

/** Every image the place and territory layers name, keyed by image name. */
export function stageImages(
    colours: MapColours,
    make: CanvasFactory = defaultCanvas,
): Map<string, DrawnImage> {
    const images = new Map<string, DrawnImage>([
        [RING_DASHED_IMAGE, dashedRingImage(colours.ring, make)],
        [HATCH_IMAGE, hatchImage(colours.paper, make)],
    ]);
    for (let slot = 1; slot <= SLOTS; slot++) {
        images.set(pipImage(slot, false), pipDisc(slot, false, colours, make));
        images.set(pipImage(slot, true), pipDisc(slot, true, colours, make));
    }
    return images;
}
