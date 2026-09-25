import type { Feature, Point, Polygon } from "geojson";

import type {
    Annotation,
    Shape,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * Canvas pixels per Leaflet unit in the Arches annotation space: the zoom 5 of
 * `BBoxCalculator` (`utils/iiif_tools.py`), which turned the stored annotation
 * into the pixels of the contract. Reversing it puts a shape back where the
 * Arches IIIF viewer draws it over the same leaflet-iiif layer.
 */
export const ANNOTATION_SCALE = 32;

export type LatLng = [number, number];

export function toLatLng(x: number, y: number): LatLng {
    return [y === 0 ? 0 : -y / ANNOTATION_SCALE, x / ANNOTATION_SCALE];
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

export function shapeCentre(shape: Shape): LatLng | null {
    const points = corners(shape);
    if (points.length === 0) return null;
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    return toLatLng(
        (Math.min(...xs) + Math.max(...xs)) / 2,
        (Math.min(...ys) + Math.max(...ys)) / 2,
    );
}

/** South-west and north-east corners of a rectangle or polygon; null for a point or an empty polygon. */
export function shapeBounds(shape: Shape): [LatLng, LatLng] | null {
    if (shape.type === "point") return null;
    const points = corners(shape);
    if (points.length === 0) return null;
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    return [
        toLatLng(Math.min(...xs), Math.max(...ys)),
        toLatLng(Math.max(...xs), Math.min(...ys)),
    ];
}

export function shapeFeature<P extends Record<string, unknown>>(
    shape: Shape,
    properties: P,
): Feature<Point | Polygon, P> | null {
    const points = corners(shape);
    if (points.length === 0) return null;
    const coordinate = ([x, y]: [number, number]): [number, number] => {
        const [lat, lng] = toLatLng(x, y);
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
