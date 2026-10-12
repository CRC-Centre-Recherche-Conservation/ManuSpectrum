import type {
    Label,
    MapColour,
    MapEvent,
    MapMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export interface MaterialRow {
    uri: string;
    label: Label;
    /** Distinct documents / components among the events carrying it. */
    documents: number;
    components: number;
    /** Observed colour uris, most frequent first. */
    colours: string[];
    /**
     * The ticked colour of the group the row stands in; its counts are then
     * those of the events where it is observed in that colour. Null for a
     * usual row (all colours counted).
     */
    observedIn: string | null;
}

export interface ColourGroup {
    /** Colour uri; null for the materials without a recorded colour. */
    colour: string | null;
    label: Label | null;
    swatch: string | null;
    rows: MaterialRow[];
    /** Distinct over the rows' events, never a sum. */
    documents: number;
    components: number;
}

interface Carried {
    label: Label;
    documents: Set<string>;
    components: Set<string>;
}

function carriedBy(
    events: readonly MapEvent[],
    colour: string | null = null,
): Map<string, Carried> {
    const found = new Map<string, Carried>();
    for (const event of events) {
        for (const material of event.materials) {
            if (colour !== null && !material.colours.includes(colour)) continue;
            let entry = found.get(material.id);
            if (!entry) {
                entry = {
                    label: material.name,
                    documents: new Set(),
                    components: new Set(),
                };
                found.set(material.id, entry);
            }
            entry.documents.add(event.document.id);
            if (event.component) entry.components.add(event.component.id);
        }
    }
    return found;
}

/** Every material of `events` with the documents and components carrying it. */
export function materialCounts(
    events: readonly MapEvent[],
): Map<string, { documents: number; components: number; label: Label }> {
    return new Map(
        [...carriedBy(events)].map(([uri, entry]) => [
            uri,
            {
                label: entry.label,
                documents: entry.documents.size,
                components: entry.components.size,
            },
        ]),
    );
}

function byLabel(a: Label | null, b: Label | null): number {
    return (a?.value ?? "").localeCompare(b?.value ?? "");
}

function observedRow(
    row: MaterialRow,
    entry: Carried,
    colour: string,
): MaterialRow {
    return {
        ...row,
        documents: entry.documents.size,
        components: entry.components.size,
        observedIn: colour,
    };
}

/** Whether *event* carries a row of `rows` (uri → its `observedIn`). */
function carries(
    event: MapEvent,
    rows: ReadonlyMap<string, string | null>,
): boolean {
    return event.materials.some((m) => {
        if (!rows.has(m.id)) return false;
        const colour = rows.get(m.id) ?? null;
        return colour === null || m.colours.includes(colour);
    });
}

/**
 * Materials grouped by their first observed colour, those without one last.
 * Groups by components then label, rows likewise; `only` narrows to those
 * uris and empty groups are left out, except a group of each `ticked` colour
 * that `colours` names, kept without rows. A ticked colour's group lists,
 * once each, every material an event observes in that colour (the event
 * material's own `colours`), its own materials and those whose main colour
 * is another, with `observedIn` set and the counts of those events only; a
 * material of the group that no kept event observes in it keeps its usual
 * row.
 */
export function colourTree(
    events: readonly MapEvent[],
    materials: Readonly<Record<string, MapMaterial>>,
    colours: Readonly<Record<string, MapColour>>,
    only?: ReadonlySet<string>,
    ticked: readonly string[] = [],
): ColourGroup[] {
    const kept = events
        .map((event) => ({
            ...event,
            materials: event.materials.filter(
                (m) => only === undefined || only.has(m.id),
            ),
        }))
        .filter((event) => event.materials.length > 0);
    const carried = carriedBy(kept);
    const members = new Map<string | null, MaterialRow[]>();
    for (const [uri, entry] of carried) {
        const known = materials[uri];
        const row: MaterialRow = {
            uri,
            label: known?.label ?? entry.label,
            documents: entry.documents.size,
            components: entry.components.size,
            colours: known?.colours ?? [],
            observedIn: null,
        };
        const key = row.colours[0] ?? null;
        members.set(key, [...(members.get(key) ?? []), row]);
    }
    for (const colour of new Set(ticked)) {
        if (!colours[colour]) continue;
        const usual = members.get(colour) ?? [];
        const listed = new Set(usual.map((row) => row.uri));
        const inColour = carriedBy(kept, colour);
        const rows = usual.map((row): MaterialRow => {
            const entry = inColour.get(row.uri);
            return entry ? observedRow(row, entry, colour) : row;
        });
        for (const [uri, entry] of inColour) {
            if (listed.has(uri)) continue;
            const known = materials[uri];
            rows.push(
                observedRow(
                    {
                        uri,
                        label: known?.label ?? entry.label,
                        documents: 0,
                        components: 0,
                        colours: known?.colours ?? [],
                        observedIn: null,
                    },
                    entry,
                    colour,
                ),
            );
        }
        members.set(colour, rows);
    }
    const groups = [...members].map(([colour, rows]): ColourGroup => {
        const own = new Map(rows.map((row) => [row.uri, row.observedIn]));
        const documents = new Set<string>();
        const components = new Set<string>();
        for (const event of kept) {
            if (!carries(event, own)) continue;
            documents.add(event.document.id);
            if (event.component) components.add(event.component.id);
        }
        const known = colour === null ? undefined : colours[colour];
        return {
            colour,
            label: known?.label ?? null,
            swatch: known?.swatch ?? null,
            rows: rows.sort(
                (a, b) =>
                    b.components - a.components || byLabel(a.label, b.label),
            ),
            documents: documents.size,
            components: components.size,
        };
    });
    return groups.sort((a, b) => {
        if ((a.colour === null) !== (b.colour === null)) {
            return a.colour === null ? 1 : -1;
        }
        return b.components - a.components || byLabel(a.label, b.label);
    });
}
