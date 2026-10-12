import { intervalOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";
import {
    summarisePlaces,
    type PlaceSummary,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

import type {
    Label,
    MapEvent,
    MapPlace,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import { project } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";

import type {
    Bounds,
    LngLat,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

export const MULTIPLES_PER_PAGE = 12;
/** The drawing box of a mini map, in SVG units. */
export const MINI_WIDTH = 220;
export const MINI_HEIGHT = 160;
const CENTURY = 100;

export interface MiniDot {
    id: string;
    lngLat: LngLat;
    /** Radius factor: √ of the components (material) or documents (century) there, at least 1. */
    size: number;
    /** False for an analysed place without the material (drawn hollow). */
    attested: boolean;
    /** Attested on low-certainty ground only. */
    pale: boolean;
    /** Followed slots present there (centuries). */
    slots: number[];
    /** An attributed place (an area, or placed through its parent), drawn dashed. */
    dashed: boolean;
}

export interface MiniMap {
    key: string;
    title: Label | null;
    /** Material uri (`byMaterial`) or null. */
    uri: string | null;
    /** Century index, 0-based (`floor((year - 1) / 100)`; 1301–1400 is 13) or null. */
    century: number | null;
    /** Places where the material, or an event of the century, is attested. */
    places: number;
    documents: number;
    components: number;
    dots: MiniDot[];
}

/** The stage's picture behind the mini maps, and the bounds the picture shows. */
export interface MapSnapshot {
    url: string;
    bounds: Bounds;
}

/** Where a mini map draws `snapshot` so that it lines up with dots projected in `bounds`. */
export function snapshotFrame(
    snapshot: MapSnapshot,
    bounds: Bounds,
): { x: number; y: number; width: number; height: number } {
    const shown = snapshot.bounds;
    const [left, top] = project(
        [shown.west, shown.north],
        bounds,
        MINI_WIDTH,
        MINI_HEIGHT,
    );
    const [right, bottom] = project(
        [shown.east, shown.south],
        bounds,
        MINI_WIDTH,
        MINI_HEIGHT,
    );
    return { x: left, y: top, width: right - left, height: bottom - top };
}

/** Century indexes touched by `range`, e.g. [1250, 1420] gives [12, 13, 14]. */
export function centuriesIn(range: readonly [number, number]): number[] {
    const first = Math.floor((range[0] - 1) / CENTURY);
    const last = Math.floor((range[1] - 1) / CENTURY);
    const out: number[] = [];
    for (let century = first; century <= last; century++) out.push(century);
    return out;
}

export function pageOf<T>(items: readonly T[], page: number): T[] {
    const pages = Math.max(1, Math.ceil(items.length / MULTIPLES_PER_PAGE));
    const index = Math.min(Math.max(0, page), pages - 1);
    return items.slice(
        index * MULTIPLES_PER_PAGE,
        (index + 1) * MULTIPLES_PER_PAGE,
    );
}

function dotsOf(
    summaries: ReadonlyMap<string, PlaceSummary>,
    sizeOf: (summary: PlaceSummary) => number,
): MiniDot[] {
    return [...summaries.values()].map((summary) => ({
        id: summary.id,
        lngLat: summary.lngLat,
        size: Math.max(1, Math.sqrt(sizeOf(summary))),
        attested: summary.tracked.size > 0,
        pale:
            summary.tracked.size > 0 &&
            [...summary.tracked.values()].every((v) => v === "pale"),
        slots: [...summary.tracked.keys()].sort((a, b) => a - b),
        dashed: summary.dashed,
    }));
}

/**
 * One mini map per material, the followed ones first in slot order, then
 * most components first; every analysed place is a dot, hollow where the
 * material is not attested.
 */
export function byMaterial(
    events: readonly MapEvent[],
    places: Readonly<Record<string, MapPlace>>,
    uris: readonly string[],
    low: ReadonlySet<string>,
    tracked: readonly TrackedMaterial[] = [],
): MiniMap[] {
    const slots = new Map(tracked.map(({ uri, slot }) => [uri, slot]));
    const slotOf = (map: MiniMap): number =>
        (map.uri === null ? undefined : slots.get(map.uri)) ?? Infinity;
    const maps = uris.map((uri): MiniMap => {
        const summaries = summarisePlaces(
            events,
            places,
            [{ uri, slot: 1 }],
            low,
        );
        const carrying = new Set<string>();
        const documents = new Set<string>();
        let title: Label | null = null;
        for (const event of events) {
            const material = event.materials.find((m) => m.id === uri);
            if (!material) continue;
            title ??= material.name;
            documents.add(event.document.id);
            if (event.component) carrying.add(event.component.id);
        }
        const componentsAt = (summary: PlaceSummary): number => {
            const ids = new Set<string>();
            for (const event of summary.events) {
                if (
                    event.component &&
                    event.materials.some((m) => m.id === uri)
                ) {
                    ids.add(event.component.id);
                }
            }
            return ids.size;
        };
        const dots = dotsOf(summaries, componentsAt);
        return {
            key: uri,
            title,
            uri,
            century: null,
            places: dots.filter((dot) => dot.attested).length,
            documents: documents.size,
            components: carrying.size,
            dots,
        };
    });
    return maps.sort(
        (a, b) =>
            slotOf(a) - slotOf(b) ||
            b.components - a.components ||
            (a.title?.value ?? "").localeCompare(b.title?.value ?? ""),
    );
}

/** One mini map per century of `range`; an event counts in every century its interval overlaps. */
export function byCentury(
    events: readonly MapEvent[],
    places: Readonly<Record<string, MapPlace>>,
    tracked: readonly TrackedMaterial[],
    low: ReadonlySet<string>,
    range: readonly [number, number],
): MiniMap[] {
    return centuriesIn(range).map((century) => {
        const from = century * CENTURY + 1;
        const to = (century + 1) * CENTURY;
        const inside = events.filter((event) => {
            const interval = intervalOf(event.date);
            return (
                interval !== null && interval[0] <= to && interval[1] >= from
            );
        });
        const summaries = summarisePlaces(inside, places, tracked, low);
        const components = new Set<string>();
        const documents = new Set<string>();
        for (const event of inside) {
            documents.add(event.document.id);
            if (event.component) components.add(event.component.id);
        }
        const dots = dotsOf(summaries, (summary) => summary.documents.size).map(
            (dot) => ({
                ...dot,
                attested: tracked.length === 0 || dot.attested,
            }),
        );
        return {
            key: `century:${century}`,
            title: null,
            uri: null,
            century,
            places: dots.filter((dot) => dot.attested).length,
            documents: documents.size,
            components: components.size,
            dots,
        };
    });
}
