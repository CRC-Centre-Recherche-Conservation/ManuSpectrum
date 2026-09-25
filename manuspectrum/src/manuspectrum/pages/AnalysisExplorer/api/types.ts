// Contract of the explorer API (spec §5 and its dated amendments). The Python
// mirror is tests/explorer_contract.py; types.spec.ts compares the two.

export type Label = { value: string; lang: string };
export type Ref = { id: string; model: string; name: Label };
export type ValueRef = { id: string; uri: string; label: Label };
export type RankedValue = ValueRef & { rank: number };
export type DataKind = "xy" | "chemical-imaging" | "micro-imaging" | "file";
export type Shape =
    | { type: "point"; x: number; y: number }
    | { type: "rect"; x: number; y: number; w: number; h: number }
    | { type: "polygon"; points: [number, number][] };
export type ImageRef = {
    service: string | null;
    url: string | null;
    width: number;
    height: number;
};
export type EventType =
    | "production"
    | "current-location"
    | "modification"
    | "alteration"
    | "analysis"
    | "sampling";
export type FacetKey =
    | "technique"
    | "part"
    | "operator"
    | "year"
    | "material"
    | "colour"
    | "element"
    | "layer"
    | "project";
export type DateRange = { start: string | null; end: string | null };

export interface FacetValue {
    id: string;
    label: Label;
    count: number;
    selected: boolean;
}

export interface Facet {
    key: FacetKey;
    values: FacetValue[];
}

export interface DocumentHit {
    type: "document";
    id: string;
    name: Label;
    holding: Label | null;
    analysisCount: number;
    thumbnail: string | null;
    unpublished: boolean;
}

export interface AnalysisHit {
    type: "analysis";
    id: string;
    name: Label;
    technique: ValueRef | null;
    document: Ref;
    component: Ref | null;
    canvas: string | null;
    date: string | null;
    dataKinds: DataKind[];
    materials: ValueRef[];
    unpublished: boolean;
}

export interface SearchResponse {
    total: number;
    page: { number: number; size: number; count: number };
    results: (DocumentHit | AnalysisHit)[];
    facets: Facet[];
    unpublishedCount: number;
}

export interface Annotation {
    key: string;
    analysis: string;
    name: Label;
    canvas: string;
    shape: Shape;
    technique: ValueRef | null;
    dataKind: DataKind;
    unpublished: boolean;
    match: boolean;
}

export interface UnlocatedAnalysis {
    analysis: string;
    name: Label;
    technique: ValueRef | null;
    dataKind: DataKind;
    unpublished: boolean;
    match: boolean;
}

export interface SampleSummary {
    id: string;
    name: Label;
    zone: { canvas: string; shape: Shape } | null;
    analyses: string[];
    unpublished: boolean;
}

export interface HistoryLine {
    type: EventType;
    place: Label | null;
    date: DateRange;
}

export interface CharacterizationSummary {
    id: string;
    name: Label;
    objects: Ref[];
    materials: {
        value: ValueRef;
        confidence: RankedValue | null;
        proportion: { value: number; unit: ValueRef | null } | null;
    }[];
    colours: ValueRef[];
    layers: ValueRef[];
    elements: { level: RankedValue | null; values: ValueRef[] }[];
    zone: { canvas: string; shape: Shape; source: "own" | "component" } | null;
    evidence: string[];
    note: { html: string; lang: string } | null;
    sources: { title: Label | null; url: string | null; ref: Ref | null }[];
    authors: Ref[];
    date: DateRange;
    unpublished: boolean;
}

export interface CertaintyScale {
    levels: RankedValue[];
}

export interface DocumentCanvas {
    id: string;
    label: string;
    image: ImageRef;
    analysisCount: number;
    characterizationCount: number;
}

export interface DocumentPayload {
    id: string;
    name: Label;
    holding: Label | null;
    manifest: string | null;
    canvases: DocumentCanvas[];
    annotations: Annotation[];
    characterizations: CharacterizationSummary[];
    history: HistoryLine[];
    unpublishedCount: number;
    unpublished: boolean;
    certaintyScale: CertaintyScale;
    unlocated: UnlocatedAnalysis[];
    samples: SampleSummary[];
}

export interface FileLayer {
    index: number;
    label: string;
    kind: "element" | "band" | "other";
    element: string | null;
    band: { value: number; unit: string } | null;
    image: ImageRef;
}

export interface FileEntry {
    id: string;
    name: string;
    size: number | null;
    format: string;
    role: "readable" | "raw" | "other";
    pairedWith: string | null;
    dataKind: DataKind;
    viewer: {
        rendererConfigId: string | null;
        xLabel: string | null;
        yLabel: string | null;
        axisKey: string | null;
        axisTitle: Label | null;
        points: number | null;
        decimated: boolean;
    };
    layers: FileLayer[];
    license: {
        id: string;
        url: string | null;
        label: Label;
        attribution: string | null;
        noDerivatives: boolean;
        inRightsRegistry: boolean;
        isDefault: boolean;
    };
    downloadUrl: string;
    previewUrl: string | null;
    zone: Shape | null;
}

export interface Citation {
    recommended: string;
    csl: object;
    bibtex: string;
    ris: string;
    availability: string;
}

export interface AnalysisPayload {
    id: string;
    name: Label;
    technique: ValueRef | null;
    instrument: Ref | null;
    operators: Ref[];
    projects: Ref[];
    date: DateRange;
    document: Ref;
    component: Ref | null;
    sample: Ref | null;
    files: FileEntry[];
    conditions: { type: ValueRef | null; html: string; lang: string }[];
    evidenceOf: CharacterizationSummary[];
    dataset: { url: string; isDoi: boolean; label: string | null } | null;
    bibliography: Label[];
    citation: Citation | null;
    permalink: string;
    certaintyScale: CertaintyScale;
    unpublished: boolean;
}

export type Item =
    | {
          key: string;
          kind: "analysis-file";
          analysis: AnalysisHit;
          file: FileEntry;
      }
    | { key: string; kind: "imaging"; analysis: AnalysisHit; file: FileEntry }
    | {
          key: string;
          kind: "characterization";
          characterization: CharacterizationSummary;
      };

export interface ItemsResponse {
    items: Item[];
    missing: string[];
}

/** Body of `GET /api/spectrum-preview/<file_id>?n=` (already through its renderer configuration). */
export interface Series {
    x: number[];
    y: number[];
    n_source: number;
    decimated: boolean;
    x_reversed: boolean;
}

export const SHAPE_KEYS = {
    Label: { value: true, lang: true } satisfies Record<keyof Label, true>,
    Ref: { id: true, model: true, name: true } satisfies Record<
        keyof Ref,
        true
    >,
    ValueRef: { id: true, uri: true, label: true } satisfies Record<
        keyof ValueRef,
        true
    >,
    RankedValue: {
        id: true,
        uri: true,
        label: true,
        rank: true,
    } satisfies Record<keyof RankedValue, true>,
    ImageRef: {
        service: true,
        url: true,
        width: true,
        height: true,
    } satisfies Record<keyof ImageRef, true>,
    Facet: { key: true, values: true } satisfies Record<keyof Facet, true>,
    SearchResponse: {
        total: true,
        page: true,
        results: true,
        facets: true,
        unpublishedCount: true,
    } satisfies Record<keyof SearchResponse, true>,
    DocumentHit: {
        type: true,
        id: true,
        name: true,
        holding: true,
        analysisCount: true,
        thumbnail: true,
        unpublished: true,
    } satisfies Record<keyof DocumentHit, true>,
    AnalysisHit: {
        type: true,
        id: true,
        name: true,
        technique: true,
        document: true,
        component: true,
        canvas: true,
        date: true,
        dataKinds: true,
        materials: true,
        unpublished: true,
    } satisfies Record<keyof AnalysisHit, true>,
    DocumentPayload: {
        id: true,
        name: true,
        holding: true,
        manifest: true,
        canvases: true,
        annotations: true,
        characterizations: true,
        history: true,
        unpublishedCount: true,
        unpublished: true,
        certaintyScale: true,
        unlocated: true,
        samples: true,
    } satisfies Record<keyof DocumentPayload, true>,
    Annotation: {
        key: true,
        analysis: true,
        name: true,
        canvas: true,
        shape: true,
        technique: true,
        dataKind: true,
        unpublished: true,
        match: true,
    } satisfies Record<keyof Annotation, true>,
    SampleSummary: {
        id: true,
        name: true,
        zone: true,
        analyses: true,
        unpublished: true,
    } satisfies Record<keyof SampleSummary, true>,
    UnlocatedAnalysis: {
        analysis: true,
        name: true,
        technique: true,
        dataKind: true,
        unpublished: true,
        match: true,
    } satisfies Record<keyof UnlocatedAnalysis, true>,
    CharacterizationSummary: {
        id: true,
        name: true,
        objects: true,
        materials: true,
        colours: true,
        layers: true,
        elements: true,
        zone: true,
        evidence: true,
        note: true,
        sources: true,
        authors: true,
        date: true,
        unpublished: true,
    } satisfies Record<keyof CharacterizationSummary, true>,
    AnalysisPayload: {
        id: true,
        name: true,
        technique: true,
        instrument: true,
        operators: true,
        projects: true,
        date: true,
        document: true,
        component: true,
        sample: true,
        files: true,
        conditions: true,
        evidenceOf: true,
        dataset: true,
        bibliography: true,
        citation: true,
        permalink: true,
        certaintyScale: true,
        unpublished: true,
    } satisfies Record<keyof AnalysisPayload, true>,
    FileEntry: {
        id: true,
        name: true,
        size: true,
        format: true,
        role: true,
        pairedWith: true,
        dataKind: true,
        viewer: true,
        layers: true,
        license: true,
        downloadUrl: true,
        previewUrl: true,
        zone: true,
    } satisfies Record<keyof FileEntry, true>,
    ItemsResponse: { items: true, missing: true } satisfies Record<
        keyof ItemsResponse,
        true
    >,
} as const;
