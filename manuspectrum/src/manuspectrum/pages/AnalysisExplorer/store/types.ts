import type { EventType } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

// 'af:<analysisId>:<fileId>' | 'im:<analysisId>:<mapIndex>' | 'ch:<characterizationId>:-'
export type ItemKey = string;
export type ExplorerView = "corpus" | "map" | "compare";
export type CorpusScreen = "home" | "results" | "document";
export type BasketKind = "analysis-file" | "imaging" | "characterization";
export type ListFilterKey =
    | "technique"
    | "part"
    | "material"
    | "colour"
    | "element"
    | "layer"
    | "project"
    | "operator";

export interface Filters {
    q: string;
    grain: "documents" | "analyses";
    onlyWithAnalyses: boolean;
    technique: string[];
    part: string[];
    material: string[];
    colour: string[];
    element: string[];
    layer: string[];
    project: string[];
    operator: string[];
    year: number[];
    // ignored by search: the Map & timeline view is not built yet
    place: string | null;
    // ignored by search: the Map & timeline view is not built yet
    period: [number, number] | null;
    // Map only; never filters Corpus
    eventType: EventType[];
}

export type FilterKey = keyof Filters;

export interface DocumentState {
    id: string;
    canvas: string | null;
}

export interface Focus {
    kind: "analysis" | "characterization" | "file";
    id: string;
}

export interface Overlay {
    element: string;
    opacity: number;
    on: boolean;
}

export interface BasketItem {
    key: ItemKey;
    kind: BasketKind;
    // 0–29: label A1…A30; never changes when another item leaves
    slot: number;
}

export type ToolKind =
    | "coverage"
    | "colour-material"
    | "periodic"
    | "folio"
    | "analysis-list";

export interface ToolWindow {
    id: string;
    kind: ToolKind;
    params: Record<string, string>;
}

export interface ToolFilters {
    element: string | null;
    cell: [string, string] | null;
    pair: [string | null, string] | null;
}

export interface LayerToggles {
    points: boolean;
    zones: boolean;
    characterizations: boolean;
}

export interface BasketAddResult {
    added: ItemKey[];
    refused: "full" | "invalid" | null;
    needed: number;
    free: number;
}

export interface BasketLoadResult {
    kept: ItemKey[];
    truncated: number;
}
