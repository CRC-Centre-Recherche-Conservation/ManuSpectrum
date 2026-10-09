import { intervalOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";
import { foldText } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";

import type {
    EventType,
    Label,
    MapEvent,
    MapPlace,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

export type PanelSubject =
    | { kind: "place"; id: string }
    | { kind: "period"; from: number; to: number }
    | { kind: "document"; id: string }
    | { kind: "material"; uri: string }
    | { kind: "unplaced" };

export interface PanelComponent {
    id: string;
    name: Label;
    events: MapEvent[];
}

export interface PanelDocument {
    id: string;
    name: Label;
    /** Events carried by the document itself. */
    own: MapEvent[];
    components: PanelComponent[];
}

const TYPE_ORDER: readonly EventType[] = [
    "production",
    "modification",
    "alteration",
    "analysis",
    "sampling",
];

export function subjectEvents(
    events: readonly MapEvent[],
    places: Readonly<Record<string, MapPlace>>,
    subject: PanelSubject,
): MapEvent[] {
    return events.filter((event) => {
        switch (subject.kind) {
            case "place":
                return event.place === subject.id;
            case "period": {
                const interval = intervalOf(event.date);
                return (
                    interval !== null &&
                    interval[0] <= subject.to &&
                    interval[1] >= subject.from
                );
            }
            case "document":
                return event.document.id === subject.id;
            case "material":
                return event.materials.some((m) => m.id === subject.uri);
            case "unplaced":
                return !(event.place && places[event.place]?.lngLat);
        }
    });
}

function byTypeThenStart(a: MapEvent, b: MapEvent): number {
    return (
        TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type) ||
        (a.date.start ?? a.date.end ?? Infinity) -
            (b.date.start ?? b.date.end ?? Infinity)
    );
}

function byName(a: { name: Label }, b: { name: Label }): number {
    return foldText(a.name.value).localeCompare(foldText(b.name.value));
}

/** Events grouped by document (folded name), the document's own first, then each Component. */
export function panelContent(events: readonly MapEvent[]): {
    documents: PanelDocument[];
    analyses: string[];
    components: number;
} {
    const documents = new Map<string, PanelDocument>();
    const components = new Set<string>();
    for (const event of events) {
        let document = documents.get(event.document.id);
        if (!document) {
            document = {
                id: event.document.id,
                name: event.document.name,
                own: [],
                components: [],
            };
            documents.set(document.id, document);
        }
        if (!event.component) {
            document.own.push(event);
            continue;
        }
        components.add(event.component.id);
        let component = document.components.find(
            (c) => c.id === event.component?.id,
        );
        if (!component) {
            component = {
                id: event.component.id,
                name: event.component.name,
                events: [],
            };
            document.components.push(component);
        }
        component.events.push(event);
    }
    const ordered = [...documents.values()].sort(byName);
    const analyses: string[] = [];
    for (const document of ordered) {
        document.own.sort(byTypeThenStart);
        document.components.sort(byName);
        for (const component of document.components) {
            component.events.sort(byTypeThenStart);
        }
        const all = [
            ...document.own,
            ...document.components.flatMap((c) => c.events),
        ];
        for (const event of all) {
            for (const id of event.analyses) {
                if (!analyses.includes(id)) analyses.push(id);
            }
        }
    }
    return { documents: ordered, analyses, components: components.size };
}

/** The followed materials no event carries. */
export function absentTracked(
    events: readonly MapEvent[],
    tracked: readonly TrackedMaterial[],
): TrackedMaterial[] {
    const carried = new Set(
        events.flatMap((e) => e.materials.map((m) => m.id)),
    );
    return tracked.filter(({ uri }) => !carried.has(uri));
}
