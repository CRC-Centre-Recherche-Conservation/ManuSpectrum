import {
    componentNode,
    pairNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type {
    CharacterizationSummary,
    ColourRef,
    Label,
    NamedRef,
    RankedValue,
    Ref,
    SynthesisPair,
    SynthesisResponse,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { MaterialRow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

type Gettext = (msgid: string) => string;
type Ngettext = (singular: string, plural: string, n: number) => string;
type Interpolate = (
    message: string,
    values: Record<string, string | number>,
    disableEscaping?: boolean,
) => string;

/** The steps of the certainty scale a record is drawn on. */
export const CERTAINTY_STEPS = 4;

/** An identified material of the Materials window. */
export interface MaterialRecord {
    id: string;
    summary: CharacterizationSummary;
    /** A `ch:` item of the Selection itself, rather than a material only citing one of its analyses. */
    selected: boolean;
    /** Ids of the Selection's analyses it cites. */
    cites: readonly string[];
    /** Ids of the canvases it is placed on, in document then page order. */
    canvases: readonly string[];
    /** The components linked to it (`summary.components`). */
    components: readonly Ref[];
}

/** Elements named at one level (null: none stated), each element once. */
export interface ElementLevel {
    level: RankedValue | null;
    values: ValueRef[];
}

/** Rows gathered under one colour × material pair or one component. */
export interface MaterialGroup {
    node: NodeId;
    name: Label;
    /** The pair's colour; null for a pair without colour and for a component. */
    colour: ColourRef | null;
    records: MaterialRecord[];
}

/** Groups in their order, then the records no group holds. */
export interface GroupedRecords {
    groups: MaterialGroup[];
    rest: MaterialRecord[];
}

export interface MaterialCounts {
    total: number;
    selected: number;
    citing: number;
}

/**
 * The identified materials of the Materials window: every material of the
 * synthesis, the Selection's own first in slot order, then those citing one
 * of its analyses in the synthesis order; a `ch:` row the synthesis does not
 * hold (not answered yet) is kept as the Selection's own. Without a
 * synthesis, the rows alone.
 *
 * `analyses`, given while `synthesis` answers a previous Selection, are the
 * ids of the analyses the Selection holds now: of that synthesis only the
 * materials of `rows` and those citing one of `analyses` are kept, and only
 * those of `rows` are the Selection's own.
 */
export function materialRecords(
    rows: readonly MaterialRow[],
    synthesis: SynthesisResponse | null,
    analyses: ReadonlySet<string> | null = null,
): MaterialRecord[] {
    const firstSlot = new Map<string, number>();
    for (const row of rows) {
        const id = row.characterization.id;
        firstSlot.set(id, Math.min(row.slot, firstSlot.get(id) ?? row.slot));
    }
    const kept = (synthesis?.materials ?? []).filter(
        (material) =>
            analyses === null ||
            firstSlot.has(material.id) ||
            material.evidence.some((id) => analyses.has(id)),
    );
    const records: MaterialRecord[] = kept.map((material) => ({
        id: material.id,
        summary: material.summary,
        selected:
            (analyses === null && material.selected) ||
            firstSlot.has(material.id),
        cites: material.evidence,
        canvases: material.canvases,
        components: material.summary.components,
    }));
    const known = new Set(records.map((record) => record.id));
    for (const row of rows) {
        const summary = row.characterization;
        if (known.has(summary.id)) continue;
        known.add(summary.id);
        records.push({
            id: summary.id,
            summary,
            selected: true,
            cites: [],
            canvases: summary.zone ? [summary.zone.canvas] : [],
            components: summary.components,
        });
    }
    const order = (record: MaterialRecord): number =>
        record.selected
            ? firstSlot.get(record.id) ?? Number.MAX_SAFE_INTEGER
            : Number.POSITIVE_INFINITY;
    return records
        .map((record, index) => ({ record, index }))
        .sort(
            (left, right) =>
                order(left.record) - order(right.record) ||
                left.index - right.index,
        )
        .map(({ record }) => record);
}

export function materialCounts(
    records: readonly MaterialRecord[],
): MaterialCounts {
    const selected = records.filter((record) => record.selected).length;
    return {
        total: records.length,
        selected,
        citing: records.length - selected,
    };
}

/** The Selection's own records, or every record with `citing`. */
export function shownRecords(
    records: readonly MaterialRecord[],
    citing: boolean,
): MaterialRecord[] {
    return citing ? [...records] : records.filter((record) => record.selected);
}

/**
 * The records under each pair of the synthesis (a record under every pair
 * it carries), in the pairs' order; a pair holding none of `records` is
 * left out.
 */
export function groupByPair(
    records: readonly MaterialRecord[],
    pairs: readonly SynthesisPair[],
): GroupedRecords {
    const byId = new Map(records.map((record) => [record.id, record]));
    const grouped = new Set<string>();
    const groups: MaterialGroup[] = [];
    for (const pair of pairs) {
        const members = pair.materials.flatMap((id) => {
            const record = byId.get(id);
            return record ? [record] : [];
        });
        if (members.length === 0) continue;
        for (const record of members) grouped.add(record.id);
        groups.push({
            node: pairNode(pair.colour?.id ?? null, pair.material.id),
            name: pair.material.label,
            colour: pair.colour,
            records: sortedLike(members, records),
        });
    }
    return {
        groups,
        rest: records.filter((record) => !grouped.has(record.id)),
    };
}

/** The records under each component they observe (a record under every one), components in the order the records name them. */
export function groupByComponent(
    records: readonly MaterialRecord[],
): GroupedRecords {
    const groups = new Map<string, MaterialGroup>();
    const rest: MaterialRecord[] = [];
    for (const record of records) {
        const components = record.components;
        if (components.length === 0) rest.push(record);
        for (const component of components) {
            const group = groups.get(component.id) ?? {
                node: componentNode(component.id),
                name: component.name,
                colour: null,
                records: [],
            };
            group.records.push(record);
            groups.set(component.id, group);
        }
    }
    return { groups: [...groups.values()], rest };
}

function sortedLike(
    members: readonly MaterialRecord[],
    order: readonly MaterialRecord[],
): MaterialRecord[] {
    return [...members].sort(
        (left, right) => order.indexOf(left) - order.indexOf(right),
    );
}

/** Values of `lists` once each (by id), in first-seen order. */
export function unionById<T extends { id: string }>(
    lists: readonly (readonly T[])[],
): T[] {
    const seen = new Map<string, T>();
    for (const list of lists) {
        for (const entry of list) {
            if (!seen.has(entry.id)) seen.set(entry.id, entry);
        }
    }
    return [...seen.values()];
}

/** The canvases of `records`, once each, in first-seen order. */
export function unionCanvases(records: readonly MaterialRecord[]): string[] {
    return [...new Set(records.flatMap((record) => record.canvases))];
}

/** The analyses `records` cite, once each. */
export function unionEvidence(records: readonly MaterialRecord[]): NamedRef[] {
    return unionById(records.map((record) => record.summary.evidence));
}

/** The components `records` link to, once each. */
export function unionComponents(records: readonly MaterialRecord[]): Ref[] {
    return unionById(records.map((record) => record.components));
}

/** The colours `records` carry, once each. */
export function unionColours(records: readonly MaterialRecord[]): ColourRef[] {
    return unionById(records.map((record) => record.summary.colours));
}

/** The materials `records` name, once each. */
export function unionMaterials(records: readonly MaterialRecord[]): ValueRef[] {
    return unionById(
        records.map((record) =>
            record.summary.materials.map((entry) => entry.value),
        ),
    );
}

/**
 * The elements of `records` by level, strongest level first (lowest rank;
 * no level last), each element once at the strongest level a record gives
 * it.
 */
export function unionLevels(
    records: readonly MaterialRecord[],
): ElementLevel[] {
    const named = records.flatMap((record) => record.summary.elements);
    const ranked = named
        .map((group, index) => ({ group, index }))
        .sort(
            (left, right) =>
                levelRank(left.group.level) - levelRank(right.group.level) ||
                left.index - right.index,
        );
    const levels = new Map<string, ElementLevel>();
    const seen = new Set<string>();
    for (const { group } of ranked) {
        const key = group.level?.id ?? "";
        for (const value of group.values) {
            if (seen.has(value.id)) continue;
            seen.add(value.id);
            const level = levels.get(key) ?? { level: group.level, values: [] };
            level.values.push(value);
            levels.set(key, level);
        }
    }
    return [...levels.values()];
}

function levelRank(level: RankedValue | null): number {
    return level ? level.rank : Number.POSITIVE_INFINITY;
}

/** The most certain confidence `records` state (lowest rank, then id); null when none states one. */
export function bestConfidence(
    records: readonly MaterialRecord[],
): RankedValue | null {
    let best: RankedValue | null = null;
    for (const record of records) {
        for (const { confidence } of record.summary.materials) {
            if (
                confidence &&
                (!best ||
                    confidence.rank < best.rank ||
                    (confidence.rank === best.rank && confidence.id < best.id))
            ) {
                best = confidence;
            }
        }
    }
    return best;
}

/** The steps a confidence fills on the scale, 1 to 4: rank 0 (the most certain level of the list) fills all four. */
export function certaintySteps(confidence: RankedValue): number {
    return Math.min(
        CERTAINTY_STEPS,
        Math.max(1, CERTAINTY_STEPS - confidence.rank),
    );
}

/** The title of the Materials window; a literal `$gettext` call for extraction. */
export function materialsTitle($gettext: Gettext): string {
    return $gettext("Materials");
}

/** « 5 identified materials · 4 of the Selection · 1 citing it », the last two only when a material cites the Selection. */
export function materialsSubtitle(
    counts: MaterialCounts,
    $gettext: Gettext,
    $ngettext: Ngettext,
    interpolate: Interpolate,
): string {
    const total = interpolate(
        $ngettext(
            "%{n} identified material",
            "%{n} identified materials",
            counts.total,
        ),
        { n: counts.total },
        true,
    );
    if (counts.citing === 0) return total;
    return [
        total,
        interpolate(
            $gettext("%{n} of the Selection"),
            { n: counts.selected },
            true,
        ),
        interpolate($gettext("%{n} citing it"), { n: counts.citing }, true),
    ].join(" · ");
}
