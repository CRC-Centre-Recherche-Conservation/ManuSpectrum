import type {
    EventMaterial,
    MapEvent,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** The materials of `event` that meet every active characterization filter. */
export function matchingMaterials(event: MapEvent): EventMaterial[] {
    return event.materials.filter((material) => material.matches);
}

/**
 * The events as the results show them: each with its matching materials
 * only. An event whose materials all fail the filters (its matching ones
 * hidden by a reliability level) is left out; one without materials stays.
 */
export function matchingEvents(events: readonly MapEvent[]): MapEvent[] {
    const shown: MapEvent[] = [];
    for (const event of events) {
        const materials = matchingMaterials(event);
        if (materials.length === 0 && event.materials.length > 0) continue;
        shown.push(
            materials.length === event.materials.length
                ? event
                : { ...event, materials },
        );
    }
    return shown;
}
