import type { ExplorerView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export interface ExplorerViewEntry {
    id: ExplorerView;
    available: boolean;
}

// Map & timeline and Compare are unavailable: not built yet.
export const EXPLORER_VIEWS: readonly ExplorerViewEntry[] = [
    { id: "corpus", available: true },
    { id: "map", available: false },
    { id: "compare", available: false },
];

export function isViewAvailable(view: ExplorerView): boolean {
    return EXPLORER_VIEWS.some((entry) => entry.id === view && entry.available);
}

export function availableViews(): ExplorerView[] {
    return EXPLORER_VIEWS.filter((entry) => entry.available).map(
        (entry) => entry.id,
    );
}
