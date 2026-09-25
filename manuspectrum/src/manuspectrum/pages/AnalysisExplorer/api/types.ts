// Contract of the explorer API (spec §5 and its dated amendments). The Python
// mirror is tests/explorer_contract.py; types.spec.ts compares the two.

export type Label = { value: string; lang: string };
export type Ref = { id: string; model: string; name: Label };
export type ValueRef = { id: string; uri: string; label: Label };
/** A resource named in the request language. */
export type NamedRef = { id: string; name: Label };
export type RankedValue = ValueRef & { rank: number };
/**
 * Identity of a technique on every screen, the same in every language and
 * document: `code` is its acronym (else first letters), `colour` the
 * `--tech-n` of its family (null: ink), `family` the uri of that family.
 */
export type TechniqueMark = {
    code: string;
    colour: number | null;
    family: string;
};
export type Technique = ValueRef & TechniqueMark;
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
    | "partType"
    | "partColour"
    | "part"
    | "technique"
    | "operator"
    | "year"
    | "material"
    | "colour"
    | "element"
    | "layer"
    | "project";
/** Level of the chain a facet filters: the studied part, the analysis, the identified material. */
export type FacetGroup = "part" | "analysis" | "characterization";
export type DateRange = { start: string | null; end: string | null };

export interface FacetValue {
    id: string;
    label: Label;
    count: number;
    /** Technique values only. */
    mark: TechniqueMark | null;
    /** Colour values only: CSS colour of the concept, the same in every language; null when its labels name none. */
    swatch: string | null;
}

/**
 * A facet of the search. On the whole-corpus search a lazy facet (`part`)
 * lists its first values and the selected ones; `total` is the number of
 * values it has, which `GET facet/<key>` lists in full; with `document=<id>`
 * that route answers the facet of one document's match.
 */
export interface Facet {
    key: FacetKey;
    group: FacetGroup;
    values: FacetValue[];
    total: number;
}

export interface DocumentHit {
    type: "document";
    id: string;
    name: Label;
    holding: Label | null;
    analysisCount: number;
    thumbnail: string | null;
    unpublished: boolean;
    shelfmark: Label | null;
    dates: DateRange | null;
    /** Plain text, cut on a word at about 220 characters with « … ». */
    description: Label | null;
    documentType: Label | null;
}

export interface AnalysisHit {
    type: "analysis";
    id: string;
    name: Label;
    technique: Technique | null;
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
    /** Null when the query said `facets=0`. */
    facets: Facet[] | null;
    unpublishedCount: number;
    /** Documents without analyses the query would list with `empty=1` (0 outside the documents grain). */
    withoutAnalyses: number;
}

/** Body of `GET home?day=YYYY-MM-DD`: the explorer home of the reader's day. */
export interface HomeResponse {
    /** Documents with a visible analysis. */
    documentCount: number;
    techniques: FacetValue[];
    projects: FacetValue[];
    /** The document of the day among those, in name order; null without any. */
    featured: DocumentHit | null;
    unpublishedCount: number;
}

/** One zone of an analysis on a page: `canvas` is the position of the page in `DocumentPayload.canvases`. */
export interface AnalysisZone {
    canvas: number;
    shape: Shape;
}

/** An analysis of a document; `technique` is a key of `DocumentPayload.techniques`; no zone: not located on a page. */
export interface DocumentAnalysis {
    id: string;
    name: Label;
    technique: string | null;
    dataKind: DataKind;
    unpublished: boolean;
    zones: AnalysisZone[];
}

export interface MatchKept {
    /** The analyses the filters keep; null when no filter is active (every analysis kept). */
    analyses: string[] | null;
    characterizations: string[];
}

/** Body of `GET document/<id>/match`: what the Corpus filters keep in one document, by the rule of the search. */
export interface DocumentMatch {
    /** The values the document's analyses carry plus the selected ones. */
    facets: Facet[];
    kept: MatchKept;
    /** Number of analyses kept. */
    total: number;
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
    /** The visible analyses cited, in id order. */
    evidence: NamedRef[];
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

/** Body of `GET document/<id>`, the same whatever the filters (`DocumentMatch` says what they keep). */
export interface DocumentPayload {
    id: string;
    name: Label;
    holding: Label | null;
    manifest: string | null;
    canvases: DocumentCanvas[];
    /** Each technique of the document's analyses, by uri. */
    techniques: Record<string, Technique>;
    analyses: DocumentAnalysis[];
    characterizations: CharacterizationSummary[];
    history: HistoryLine[];
    unpublishedCount: number;
    unpublished: boolean;
    certaintyScale: CertaintyScale;
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
    technique: Technique | null;
    instrument: Ref | null;
    operators: Ref[];
    projects: Ref[];
    date: DateRange;
    document: Ref;
    component: Ref | null;
    sample: Ref | null;
    files: FileEntry[];
    conditions: { type: ValueRef | null; html: string; lang: string }[];
    /** The identified materials citing this analysis as evidence. */
    evidenceOf: NamedRef[];
    dataset: { url: string; isDoi: boolean; label: string | null } | null;
    bibliography: Label[];
    citation: Citation | null;
    permalink: string;
    /** Path of the Arches report on this site, in the request language. */
    reportUrl: string;
    certaintyScale: CertaintyScale;
    unpublished: boolean;
}

/** A whole analysis in the Selection, with the files a viewer shows (raw files left out; possibly none). */
export interface AnalysisItem {
    key: string;
    kind: "analysis";
    analysis: AnalysisHit;
    files: FileEntry[];
}

export type Item =
    | AnalysisItem
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
    NamedRef: { id: true, name: true } satisfies Record<keyof NamedRef, true>,
    ImageRef: {
        service: true,
        url: true,
        width: true,
        height: true,
    } satisfies Record<keyof ImageRef, true>,
    Technique: {
        id: true,
        uri: true,
        label: true,
        code: true,
        colour: true,
        family: true,
    } satisfies Record<keyof Technique, true>,
    TechniqueMark: { code: true, colour: true, family: true } satisfies Record<
        keyof TechniqueMark,
        true
    >,
    Facet: {
        key: true,
        group: true,
        values: true,
        total: true,
    } satisfies Record<keyof Facet, true>,
    FacetValue: {
        id: true,
        label: true,
        count: true,
        mark: true,
        swatch: true,
    } satisfies Record<keyof FacetValue, true>,
    SearchResponse: {
        total: true,
        page: true,
        results: true,
        facets: true,
        unpublishedCount: true,
        withoutAnalyses: true,
    } satisfies Record<keyof SearchResponse, true>,
    HomeResponse: {
        documentCount: true,
        techniques: true,
        projects: true,
        featured: true,
        unpublishedCount: true,
    } satisfies Record<keyof HomeResponse, true>,
    DocumentHit: {
        type: true,
        id: true,
        name: true,
        holding: true,
        analysisCount: true,
        thumbnail: true,
        unpublished: true,
        shelfmark: true,
        dates: true,
        description: true,
        documentType: true,
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
        techniques: true,
        analyses: true,
        characterizations: true,
        history: true,
        unpublishedCount: true,
        unpublished: true,
        certaintyScale: true,
        samples: true,
    } satisfies Record<keyof DocumentPayload, true>,
    DocumentAnalysis: {
        id: true,
        name: true,
        technique: true,
        dataKind: true,
        unpublished: true,
        zones: true,
    } satisfies Record<keyof DocumentAnalysis, true>,
    AnalysisZone: { canvas: true, shape: true } satisfies Record<
        keyof AnalysisZone,
        true
    >,
    DocumentMatch: { facets: true, kept: true, total: true } satisfies Record<
        keyof DocumentMatch,
        true
    >,
    MatchKept: { analyses: true, characterizations: true } satisfies Record<
        keyof MatchKept,
        true
    >,
    SampleSummary: {
        id: true,
        name: true,
        zone: true,
        analyses: true,
        unpublished: true,
    } satisfies Record<keyof SampleSummary, true>,
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
        reportUrl: true,
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
    AnalysisItem: {
        key: true,
        kind: true,
        analysis: true,
        files: true,
    } satisfies Record<keyof AnalysisItem, true>,
    ItemsResponse: { items: true, missing: true } satisfies Record<
        keyof ItemsResponse,
        true
    >,
} as const;
