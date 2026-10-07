import type {
    EventType,
    PeriodEvent,
    PeriodMatch,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

// 'an:<analysisId>:-' | 'af:<analysisId>:<fileId>' | 'im:<analysisId>:<mapIndex>' | 'ch:<characterizationId>:-'
export type ItemKey = string;
export type ExplorerView = "corpus" | "map" | "compare";
export type CorpusScreen = "home" | "results" | "document";
// the Corpus screen a document screen was entered from
export type DocumentOrigin = Exclude<CorpusScreen, "document">;
export type BasketKind =
    | "analysis"
    | "analysis-file"
    | "imaging"
    | "characterization";
export type ListFilterKey =
    | "place"
    | "partType"
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
    partType: string[];
    technique: string[];
    part: string[];
    material: string[];
    colour: string[];
    element: string[];
    layer: string[];
    project: string[];
    operator: string[];
    year: number[];
    place: string[];
    // whole years, both included; null = no period
    period: [number, number] | null;
    // overlap the period, or lie entirely within it
    periodMatch: PeriodMatch;
    // the dated event the period bears on
    periodEvent: PeriodEvent;
    // with a period: also keep the rows without a date for the event
    undated: boolean;
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

export type ToolKind = "coverage" | "periodic" | "folio";

/** How the Materials window of Compare groups its identified materials. */
export type MaterialsGrouping = "record" | "pair" | "component";

export interface ToolWindow {
    id: string;
    kind: ToolKind;
    params: Record<string, string>;
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

/** The last grouped change of the Selection, kept for the status line and its undo. */
export interface BulkStatus {
    kind: "added" | "removed" | "emptied";
    keys: ItemKey[];
    /** Slot labels (« A3 ») of the keys, in the order of `keys`. */
    slots: string[];
    /** Size of the Selection after the change. */
    total: number;
}
