import type { EventType } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

// 'af:<analysisId>:<fileId>' | 'im:<analysisId>:<mapIndex>' | 'ch:<characterizationId>:-'
export type ItemKey = string;
export type ExplorerView = "corpus" | "map" | "compare";
export type CorpusScreen = "home" | "results" | "document";
// the Corpus screen a document screen was entered from
export type DocumentOrigin = Exclude<CorpusScreen, "document">;
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

/** Results per page the search offers. */
export type PageSize = 10 | 25 | 50;

export interface Filters {
    q: string;
    grain: "documents" | "analyses";
    // documents grain: also list the documents that have no analysis
    empty: boolean;
    size: PageSize;
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

// what the folio draws: one kind of element at a time
export type FolioView = "analyses" | "characterizations" | "samples";

export interface Focus {
    kind: "analysis" | "characterization" | "file" | "sample";
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
