import { intervalOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";

import type { Feature, FeatureCollection, Point } from "geojson";
import type {
    CertaintyScale,
    EventMaterial,
    Label,
    MapEvent,
    MapPlace,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { FocusMode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import type { LngLat } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { TrackedField } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/territories.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

/** Ranks of « Use with caution » and « Uncertain »: drawn pale, weighed ½. */
export const LOW_RANK = 2;
export const LOW_WEIGHT = 0.5;
export const RING_BASE_PX = 6;
export const RING_STEP_PX = 4;

export type Attestation = "firm" | "pale";

export interface PlaceSummary {
    id: string;
    name: Label;
    lngLat: LngLat;
    kind: "point" | "area";
    extentKm: number | null;
    documents: Set<string>;
    components: Set<string>;
    analyses: Set<string>;
    events: MapEvent[];
    tracked: Map<number, Attestation>;
    dashed: boolean;
    unpublished: boolean;
}

export interface PlaceProperties {
    id: string;
    kind: "point" | "area";
    ring: number;
    dashed: boolean;
    name: string;
    documents: number;
    components: number;
}

export function lowLevels(scale: CertaintyScale): Set<string> {
    return new Set(
        scale.levels
            .filter((level) => level.rank >= LOW_RANK)
            .map((level) => level.id),
    );
}

export function isLow(
    material: EventMaterial,
    low: ReadonlySet<string>,
): boolean {
    return material.reliability !== null && low.has(material.reliability);
}

/** Whether `event` lies in the brushed period (overlap); an undated event is kept only without a brush. */
export function inBrush(
    event: MapEvent,
    brush: readonly [number, number] | null,
): boolean {
    if (brush === null) return true;
    const interval = intervalOf(event.date);
    return (
        interval !== null && interval[0] <= brush[1] && interval[1] >= brush[0]
    );
}

export function withoutLow(
    events: readonly MapEvent[],
    low: ReadonlySet<string>,
): MapEvent[] {
    return events.map((event) => ({
        ...event,
        materials: event.materials.filter((m) => !isLow(m, low)),
    }));
}

export function ringRadius(documents: number): number {
    return RING_BASE_PX + Math.sqrt(documents) * RING_STEP_PX;
}

/** One summary per mapped place; an event without a place, or on a place without coordinates, is skipped. */
export function summarisePlaces(
    events: readonly MapEvent[],
    places: Readonly<Record<string, MapPlace>>,
    tracked: readonly TrackedMaterial[],
    low: ReadonlySet<string>,
): Map<string, PlaceSummary> {
    const found = new Map<string, PlaceSummary>();
    const sources = new Map<string, Set<string>>();
    const lows = new Map<string, Map<number, boolean>>();
    for (const event of events) {
        const place = event.place ? places[event.place] : undefined;
        if (!place?.lngLat) continue;
        let summary = found.get(place.id);
        if (!summary) {
            summary = {
                id: place.id,
                name: place.name,
                lngLat: place.lngLat,
                kind: place.geometryKind,
                extentKm: place.extentKm,
                documents: new Set(),
                components: new Set(),
                analyses: new Set(),
                events: [],
                tracked: new Map(),
                dashed: false,
                unpublished: place.unpublished,
            };
            found.set(place.id, summary);
            sources.set(place.id, new Set());
            lows.set(place.id, new Map());
        }
        summary.events.push(event);
        summary.documents.add(event.document.id);
        if (event.component) summary.components.add(event.component.id);
        for (const id of event.analyses) summary.analyses.add(id);
        sources.get(place.id)?.add(event.placeSource ?? "none");
        for (const { uri, slot } of tracked) {
            for (const material of event.materials) {
                if (material.id !== uri) continue;
                const allLow = lows.get(place.id) as Map<number, boolean>;
                allLow.set(
                    slot,
                    (allLow.get(slot) ?? true) && isLow(material, low),
                );
            }
        }
    }
    for (const summary of found.values()) {
        const seen = sources.get(summary.id) as Set<string>;
        summary.dashed =
            summary.kind === "area" || (seen.size === 1 && seen.has("parent"));
        for (const [slot, pale] of lows.get(summary.id) ?? []) {
            summary.tracked.set(slot, pale ? "pale" : "firm");
        }
    }
    return found;
}

export function placeFeatures(
    summaries: ReadonlyMap<string, PlaceSummary>,
): FeatureCollection<Point, PlaceProperties> {
    const features: Feature<Point, PlaceProperties>[] = [
        ...summaries.values(),
    ].map((s) => ({
        type: "Feature",
        id: s.id,
        geometry: { type: "Point", coordinates: [s.lngLat[0], s.lngLat[1]] },
        properties: {
            id: s.id,
            kind: s.kind,
            ring: ringRadius(s.documents.size),
            dashed: s.dashed,
            name: s.name.value,
            documents: s.documents.size,
            components: s.components.size,
        },
    }));
    return { type: "FeatureCollection", features };
}

/** The feature-state of a place: per slot 0 (absent), 1 (attested) or 2 (attested, low only); `dim` when `all` and a followed material is absent. */
export function featureStates(
    summary: PlaceSummary,
    tracked: readonly TrackedMaterial[],
    mode: FocusMode,
): Record<string, number | boolean> {
    const state: Record<string, number | boolean> = {
        t1: 0,
        t2: 0,
        t3: 0,
        t4: 0,
        dim: false,
    };
    for (const { slot } of tracked) {
        const found = summary.tracked.get(slot);
        state[`t${slot}`] = found === "firm" ? 1 : found === "pale" ? 2 : 0;
    }
    state.dim =
        mode === "all" &&
        tracked.length > 1 &&
        tracked.some(({ slot }) => !summary.tracked.has(slot));
    return state;
}

/** Documents plus components carrying `uri` among `events`, each ½ when all its attestations are low. */
export function attestationWeight(
    events: readonly MapEvent[],
    uri: string,
    low: ReadonlySet<string>,
): number {
    const carriers = new Map<string, boolean>();
    for (const event of events) {
        const found = event.materials.filter((m) => m.id === uri);
        if (found.length === 0) continue;
        const allLow = found.every((m) => isLow(m, low));
        for (const key of [
            `d:${event.document.id}`,
            ...(event.component ? [`c:${event.component.id}`] : []),
        ]) {
            carriers.set(key, (carriers.get(key) ?? true) && allLow);
        }
    }
    let weight = 0;
    for (const allLow of carriers.values()) {
        weight += allLow ? LOW_WEIGHT : 1;
    }
    return weight;
}

export function territoryFields(
    summaries: ReadonlyMap<string, PlaceSummary>,
    tracked: readonly TrackedMaterial[],
    low: ReadonlySet<string>,
): TrackedField[] {
    return tracked.map(({ uri, slot }) => ({
        slot,
        attestations: [...summaries.values()]
            .map((s) => ({
                lngLat: s.lngLat,
                weight: attestationWeight(s.events, uri, low),
                extentKm: s.extentKm ?? 0,
            }))
            .filter((a) => a.weight > 0),
    }));
}
