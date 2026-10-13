import type { ExplorerView } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export interface ExplorerViewEntry {
    id: ExplorerView;
    available: boolean;
}

export const EXPLORER_VIEWS: readonly ExplorerViewEntry[] = [
    { id: "corpus", available: true },
    { id: "map", available: true },
    { id: "compare", available: true },
];

export function isViewAvailable(view: ExplorerView): boolean {
    return EXPLORER_VIEWS.some((entry) => entry.id === view && entry.available);
}

export function availableViews(): ExplorerView[] {
    return EXPLORER_VIEWS.filter((entry) => entry.available).map(
        (entry) => entry.id,
    );
}
