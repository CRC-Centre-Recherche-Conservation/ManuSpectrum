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
        const shapes = component.zones
            .filter(
                (zone) =>
                    zone.canvas === position &&
                    shapeBounds(zone.shape) !== null,
            )
            .map((zone) => zone.shape);
        return shapes.length > 0
            ? [{ id: component.id, name: component.name, shapes }]
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
