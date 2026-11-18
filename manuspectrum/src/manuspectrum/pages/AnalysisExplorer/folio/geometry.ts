import type { Feature, Point, Polygon } from "geojson";

import type {
    DocumentPayload,
    Label,
    Shape,
    ZoneUnit,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { Annotation } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";

/**
 * Pixels per Leaflet unit of the folio's own boxes (`registration.ts`), and
 * the unit of a canvas whose payload gives none.
 */
export const ANNOTATION_SCALE = 32;

export type LatLng = [number, number];

/**
 * Where the canvas pixel (`x`, `y`) lies on the page's leaflet-iiif layer.
 * `unit` is the canvas's `zoneUnit`: the pixels the server counted per stored
 * Leaflet unit. Dividing by it gives back the stored coordinates, the ones the
 * Arches IIIF viewer draws over the same layer, whatever the size and the
 * tiles of the image. Without a unit, `ANNOTATION_SCALE` on both axes.
 */
export function toLatLng(
    x: number,
    y: number,
    unit: ZoneUnit | null = null,
): LatLng {
    const perX = unit?.x || ANNOTATION_SCALE;
    const perY = unit?.y || ANNOTATION_SCALE;
    return [y === 0 ? 0 : -y / perY, x / perX];
}

/** The frame of a live leaflet-iiif layer: its `maxNativeZoom` and the image size its info.json gave. */
export interface LayerFrame {
    zoom: number;
    width: number;
    height: number;
}

/**
 * The unit of a canvas's zones on a live layer: the canvas pixels per Leaflet
 * unit of a layer that spans `frame.width / 2^zoom` units for the
 * `canvas.width` pixels of the canvas. Measured, so `read` is true.
 */
export function liveUnit(
    frame: LayerFrame,
    canvas: { width: number; height: number },
): ZoneUnit {
    return {
        x: (2 ** frame.zoom * canvas.width) / frame.width,
        y: (2 ** frame.zoom * canvas.height) / frame.height,
        read: true,
    };
}

/**
 * The unit a zone is placed with: its own when the server could not measure
 * its frame (it stays where Arches draws it), else the live layer's, else the
 * canvas's `zoneUnit`.
 */
export function zoneUnitFor(
    zone: { unit?: ZoneUnit | null },
    live: ZoneUnit | null,
    fallback: ZoneUnit | null,
): ZoneUnit | null {
    return zone.unit ?? live ?? fallback;
}

function corners(shape: Shape): [number, number][] {
    if (shape.type === "point") return [[shape.x, shape.y]];
    if (shape.type === "rect") {
        return [
            [shape.x, shape.y],
            [shape.x + shape.w, shape.y],
            [shape.x + shape.w, shape.y + shape.h],
            [shape.x, shape.y + shape.h],
        ];
    }
    return shape.points.filter((point) => point.every(Number.isFinite));
}

export function shapeCentre(
    shape: Shape,
    unit: ZoneUnit | null = null,
): LatLng | null {
    const points = corners(shape);
    if (points.length === 0) return null;
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    return toLatLng(
        (Math.min(...xs) + Math.max(...xs)) / 2,
        (Math.min(...ys) + Math.max(...ys)) / 2,
        unit,
    );
}

/** South-west and north-east corners of a rectangle or polygon; null for a point or an empty polygon. */
export function shapeBounds(
    shape: Shape,
    unit: ZoneUnit | null = null,
): [LatLng, LatLng] | null {
    if (shape.type === "point") return null;
    const points = corners(shape);
    if (points.length === 0) return null;
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    return [
        toLatLng(Math.min(...xs), Math.max(...ys), unit),
        toLatLng(Math.max(...xs), Math.min(...ys), unit),
    ];
}

/** North-west corner of a rectangle or polygon, where a label sits inside it; null for a point or an empty polygon. */
export function shapeCorner(
    shape: Shape,
    unit: ZoneUnit | null = null,
): LatLng | null {
    const bounds = shapeBounds(shape, unit);
    return bounds ? [bounds[1][0], bounds[0][1]] : null;
}

/** A Component outlined on one folio: its zones there with an extent. */
export interface ComponentOutline {
    id: string;
    name: Label;
    shapes: Shape[];
    /** The own unit of each of `shapes`, by position (`zoneUnitFor`); null when measured. */
    units: (ZoneUnit | null)[];
}

/** The Components of `payload` outlined on the canvas `canvasId`, in the payload's order; a Component with no extent there is left out. */
export function componentOutlines(
    payload: DocumentPayload,
    canvasId: string,
): ComponentOutline[] {
    const position = payload.canvases.findIndex(
        (canvas) => canvas.id === canvasId,
    );
    if (position < 0) return [];
    return payload.components.flatMap((component) => {
        const zones = component.zones.filter(
            (zone) =>
                zone.canvas === position && shapeBounds(zone.shape) !== null,
        );
        return zones.length > 0
            ? [
                  {
                      id: component.id,
                      name: component.name,
                      shapes: zones.map((zone) => zone.shape),
                      units: zones.map((zone) => zone.unit),
                  },
              ]
            : [];
    });
}

export function shapeFeature<P extends Record<string, unknown>>(
    shape: Shape,
    properties: P,
    unit: ZoneUnit | null = null,
): Feature<Point | Polygon, P> | null {
    const points = corners(shape);
    if (points.length === 0) return null;
    const coordinate = ([x, y]: [number, number]): [number, number] => {
        const [lat, lng] = toLatLng(x, y, unit);
        return [lng, lat];
    };
    if (shape.type === "point") {
        return {
            type: "Feature",
            properties,
            geometry: { type: "Point", coordinates: coordinate(points[0]) },
        };
    }
    const ring = points.map(coordinate);
    ring.push(ring[0]);
    return {
        type: "Feature",
        properties,
        geometry: { type: "Polygon", coordinates: [ring] },
    };
}

/**
 * The annotation that stands for each analysis among `annotations`, in their
 * order: the analysis's first zone with an extent, else its first point. The
 * analysis's marker and its laid maps sit on it.
 */
export function markedZones(annotations: readonly Annotation[]): Annotation[] {
    const marked = new Map<string, Annotation>();
    for (const annotation of annotations) {
        const current = marked.get(annotation.analysis);
        if (
            !current ||
            (shapeBounds(current.shape) === null &&
                shapeBounds(annotation.shape) !== null)
        ) {
            marked.set(annotation.analysis, annotation);
        }
    }
    return [...marked.values()];
}
