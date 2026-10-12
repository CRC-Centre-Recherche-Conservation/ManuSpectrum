import { generateArchesURL } from "@/arches/utils/generate-arches-url.ts";

import {
    getJson,
    peekJson,
} from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useRequest } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import { filterQuery } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSearch.ts";

import type { EventsResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { Filters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export const EVENTS_ROUTE = "manuspectrum:explorer-events";
export type EventsExportRoute =
    | "manuspectrum:explorer-events-csv"
    | "manuspectrum:explorer-events-geojson";

/**
 * The Corpus filters (as the search sends them, without grain, page and size)
 * plus the sorted event types. No type chosen sends none: the server then
 * keeps its default set (`MATERIAL_EVENTS` in `views/explorer/events.py`), one URL and one ETag.
 */
export function eventsQuery(filters: Filters): URLSearchParams {
    const query = filterQuery(filters);
    for (const type of [...filters.eventType].sort()) {
        query.append("eventType", type);
    }
    return query;
}

/** The map's events under `filters`; idle while null. A filter change waits for the filters to settle (`DEBOUNCE_MS`). */
export function useEvents(
    filters: () => Filters | null,
): RequestHandle<EventsResponse> {
    return useRequest(
        () => {
            const current = filters();
            return current === null ? null : eventsQuery(current).toString();
        },
        (source, signal, reload) =>
            getJson<EventsResponse>(EVENTS_ROUTE, {
                query: new URLSearchParams(source),
                signal,
                reload,
            }),
        {
            cached: (source) =>
                peekJson<EventsResponse>(EVENTS_ROUTE, {
                    query: new URLSearchParams(source),
                }),
            debounce: () => true,
        },
    );
}

/** The download address of an export of the kept events in `language`. */
export function exportHref(
    route: EventsExportRoute,
    filters: Filters,
    language: string,
): string {
    const query = eventsQuery(filters);
    query.set("lang", language);
    return `${generateArchesURL(route)}?${query.toString()}`;
}
