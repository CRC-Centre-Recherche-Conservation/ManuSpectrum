import { componentRefs } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

import type {
    CharacterizationSummary,
    Item,
    Label,
    Ref,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** A component of the Selection, with what observes it. */
export interface SelectionComponent {
    id: string;
    name: Label;
    /** The labels of the folios it is counted or placed on, in document then page order. */
    folios: string[];
    /** Number of analyses of the Selection observing it. */
    analyses: number;
    /** Number of identified materials (the Selection's and those citing it) observing it. */
    materials: number;
}

interface Gathered {
    name: Label;
    canvases: Set<string>;
    analyses: Set<string>;
    materials: Set<string>;
}

function gather(
    found: Map<string, Gathered>,
    id: string,
    name: Label,
): Gathered {
    let entry = found.get(id);
    if (!entry) {
        entry = {
            name,
            canvases: new Set(),
            analyses: new Set(),
            materials: new Set(),
        };
        found.set(id, entry);
    }
    return entry;
}

function gatherMaterial(
    found: Map<string, Gathered>,
    refs: ReadonlyMap<string, Ref>,
    summary: CharacterizationSummary,
    canvases: readonly string[],
): void {
    for (const id of summary.components) {
        const ref = refs.get(id);
        if (!ref) continue;
        const entry = gather(found, id, ref.name);
        entry.materials.add(summary.id);
        for (const canvas of canvases) entry.canvases.add(canvas);
    }
}

/**
 * The components of the Selection: those its analyses observe
 * (`AnalysisHit.component`) and those its identified materials are linked
 * to (`components`), the materials of the synthesis included; a linked
 * component no payload names is left out. Their folios are the coverage rows counting them and the
 * canvases of the materials observing them. In the server's order of the
 * coverage rows, then by name in `locale` (accents and case aside), then id.
 */
export function selectionComponents(
    basket: readonly BasketItem[],
    byKey: ReadonlyMap<string, Item>,
    synthesis: SynthesisResponse | null,
    locale: string | undefined = undefined,
): SelectionComponent[] {
    const found = new Map<string, Gathered>();
    const items = basket.flatMap(({ key }) => byKey.get(key) ?? []);
    const refs = componentRefs(
        [
            ...items.flatMap((item) =>
                item.kind === "characterization" ? [item.characterization] : [],
            ),
            ...(synthesis?.materials ?? []).map((material) => material.summary),
        ],
        synthesis,
        items.map((item) =>
            item.kind === "characterization" ? null : item.analysis.component,
        ),
    );
    for (const item of items) {
        if (item.kind === "characterization") {
            gatherMaterial(found, refs, item.characterization, []);
            continue;
        }
        const component = item.analysis.component;
        if (component) {
            gather(found, component.id, component.name).analyses.add(
                item.analysis.id,
            );
        }
    }
    const order: string[] = [];
    for (const row of synthesis?.coverage ?? []) {
        for (const { component } of row.components) {
            if (!component) continue;
            gather(found, component.id, component.name).canvases.add(
                row.canvas,
            );
            if (!order.includes(component.id)) order.push(component.id);
        }
    }
    for (const material of synthesis?.materials ?? []) {
        gatherMaterial(found, refs, material.summary, material.canvases);
    }
    const labels = new Map(
        (synthesis?.canvases ?? []).map((entry) => [entry.canvas, entry.label]),
    );
    const canvasOrder = [...labels.keys()];
    function rank(id: string): number {
        const index = order.indexOf(id);
        return index < 0 ? order.length : index;
    }
    return [...found]
        .sort(
            ([leftId, left], [rightId, right]) =>
                rank(leftId) - rank(rightId) ||
                left.name.value.localeCompare(right.name.value, locale, {
                    sensitivity: "base",
                }) ||
                leftId.localeCompare(rightId),
        )
        .map(([id, entry]) => ({
            id,
            name: entry.name,
            folios: canvasOrder
                .filter((canvas) => entry.canvases.has(canvas))
                .map((canvas) => labels.get(canvas) ?? canvas),
            analyses: entry.analyses.size,
            materials: entry.materials.size,
        }));
}
