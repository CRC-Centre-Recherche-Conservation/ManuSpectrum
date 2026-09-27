import type {
    BasketItem,
    BasketKind,
    ItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export type AutoWindowKind =
    | "xy"
    | "micro"
    | "characterizations"
    | "not-in-chart";

/** A window arranged from the Selection, and the Selection items it shows. */
export interface AutoWindow {
    id: string;
    kind: AutoWindowKind;
    keys: ItemKey[];
}

const WINDOW_OF: Record<BasketKind, { id: string; kind: AutoWindowKind }> = {
    "analysis-file": { id: "auto:xy:all", kind: "xy" },
    analysis: { id: "auto:micro", kind: "micro" },
    characterization: {
        id: "auto:characterizations",
        kind: "characterizations",
    },
    imaging: { id: "auto:not-in-chart", kind: "not-in-chart" },
};

const WINDOW_ORDER: readonly AutoWindowKind[] = [
    "xy",
    "micro",
    "characterizations",
    "not-in-chart",
];

/**
 * One empty window per kind of Selection item, until the windows are read
 * from the items themselves (one per axis, micro-images, materials).
 */
export function placeholderWindows(
    basket: readonly BasketItem[],
): AutoWindow[] {
    const byId = new Map<string, AutoWindow>();
    for (const item of [...basket].sort((a, b) => a.slot - b.slot)) {
        const { id, kind } = WINDOW_OF[item.kind];
        const window = byId.get(id) ?? { id, kind, keys: [] };
        window.keys.push(item.key);
        byId.set(id, window);
    }
    return [...byId.values()].sort(
        (a, b) => WINDOW_ORDER.indexOf(a.kind) - WINDOW_ORDER.indexOf(b.kind),
    );
}
