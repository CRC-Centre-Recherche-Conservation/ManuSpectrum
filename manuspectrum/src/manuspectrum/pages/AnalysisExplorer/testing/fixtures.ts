import type {
    AnalysisHit,
    AnalysisPayload,
    CharacterizationSummary,
    DocumentAnalysis,
    DocumentHit,
    DocumentMatch,
    DocumentPayload,
    Facet,
    FacetValue,
    FileEntry,
    HomeResponse,
    ProductLink,
    SampleSummary,
    SearchResponse,
    SharePayload,
    Technique,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    Annotation,
    UnlocatedAnalysis,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";

export function uuid(n: number): string {
    return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

export function label(value: string): { value: string; lang: string } {
    return { value, lang: "en" };
}

export function documentHit(
    n: number,
    overrides: Partial<DocumentHit> = {},
): DocumentHit {
    return {
        type: "document",
        id: uuid(n),
        name: label(`Manuscript ${n}`),
        holding: null,
        analysisCount: n,
        thumbnail: `/thumbnail/${uuid(n)}`,
        unpublished: false,
        shelfmark: null,
        dates: null,
        description: null,
        documentType: null,
        ...overrides,
    };
}

export function analysisHit(
    n: number,
    overrides: Partial<AnalysisHit> = {},
): AnalysisHit {
    return {
        type: "analysis",
        id: uuid(100 + n),
        name: label(`MS${n}_f12_XRF_03`),
        technique: technique("http://example.org/xrf", "XRF", 1, uuid(900)),
        document: {
            id: uuid(1),
            model: "document",
            name: label("Manuscript 1"),
        },
        component: null,
        canvas: null,
        date: "2023-05",
        dataKinds: ["xy"],
        materials: [],
        unpublished: false,
        ...overrides,
    };
}

const GROUP_OF: Record<Facet["key"], Facet["group"]> = {
    partType: "part",
    partColour: "part",
    part: "part",
    project: "analysis",
    technique: "analysis",
    operator: "analysis",
    year: "analysis",
    material: "characterization",
    colour: "characterization",
    layer: "characterization",
    element: "characterization",
};

/** One facet value without mark nor swatch. */
export function facetValue(
    id: string,
    text: string = id,
    overrides: Partial<FacetValue> = {},
): FacetValue {
    return {
        id,
        label: label(text),
        count: 1,
        mark: null,
        swatch: null,
        ...overrides,
    };
}

/** A facet of `count` values; technique values carry a mark (code = label, colour by value), colour values no swatch. */
export function facet(key: Facet["key"], count: number): Facet {
    return {
        key,
        group: GROUP_OF[key],
        values: Array.from({ length: count }, (_, n) => ({
            id: `${key}-${n}`,
            label: label(`${key} ${n}`),
            count: n + 1,
            mark:
                key === "technique"
                    ? { code: `T${n}`, colour: n + 1, family: `${key}-${n}` }
                    : null,
            swatch: null,
        })),
        total: count,
    };
}

/** The home: two techniques, one project, no document of the day. */
export function homeResponse(
    overrides: Partial<HomeResponse> = {},
): HomeResponse {
    return {
        documentCount: 3,
        techniques: facet("technique", 2).values,
        projects: facet("project", 1).values,
        featured: null,
        unpublishedCount: 0,
        ...overrides,
    };
}

export function searchResponse(
    overrides: Partial<SearchResponse> = {},
): SearchResponse {
    const results = overrides.results ?? [documentHit(1), documentHit(2)];
    return {
        total: results.length,
        page: { number: 1, size: 50, count: results.length },
        results,
        facets: [],
        unpublishedCount: 0,
        withoutAnalyses: 0,
        ...overrides,
    };
}

export function documentPayload(
    overrides: Partial<DocumentPayload> = {},
): DocumentPayload {
    return {
        id: uuid(1),
        name: label("Manuscript 1"),
        holding: label("Avranches, BM"),
        manifest: null,
        canvases: [
            {
                id: "https://iiif.example/c1",
                label: "f. 12r",
                image: { service: null, url: null, width: 1, height: 1 },
                analysisCount: 3,
                characterizationCount: 0,
            },
            {
                id: "https://iiif.example/c2",
                label: "f. 12v",
                image: { service: null, url: null, width: 1, height: 1 },
                analysisCount: 0,
                characterizationCount: 0,
            },
        ],
        techniques: {},
        analyses: [],
        characterizations: [],
        history: [],
        unpublishedCount: 0,
        unpublished: false,
        certaintyScale: { levels: [] },
        samples: [],
        ...overrides,
    };
}

export function documentMatch(
    overrides: Partial<DocumentMatch> = {},
): DocumentMatch {
    return {
        facets: [],
        kept: { analyses: [], characterizations: [] },
        total: 0,
        ...overrides,
    };
}

export interface DocumentShown extends Partial<DocumentPayload> {
    /** Zones drawn on the pages; their canvases must be canvases of the payload. */
    annotations?: Annotation[];
    unlocated?: UnlocatedAnalysis[];
    /** Identified materials the filters do not keep. */
    dimmed?: string[];
    facets?: Facet[];
}

/**
 * The document payload and the match the server sends for a document that
 * shows `annotations` and `unlocated` (in the order of their analyses' first
 * entry), each analysis kept when its entries match.
 */
export function documentResponses({
    annotations = [],
    unlocated = [],
    dimmed = [],
    facets = [],
    ...overrides
}: DocumentShown = {}): { payload: DocumentPayload; match: DocumentMatch } {
    const payload = documentPayload(overrides);
    const analyses = new Map<string, DocumentAnalysis>();
    const techniques: Record<string, Technique> = {};
    const kept = new Set<string>();
    for (const entry of [...annotations, ...unlocated]) {
        if (entry.technique) techniques[entry.technique.uri] = entry.technique;
        if (entry.match) kept.add(entry.analysis);
        if (!analyses.has(entry.analysis)) {
            analyses.set(entry.analysis, {
                id: entry.analysis,
                name: entry.name,
                technique: entry.technique?.uri ?? null,
                dataKind: entry.dataKind,
                unpublished: entry.unpublished,
                zones: [],
            });
        }
    }
    for (const entry of annotations) {
        const canvas = payload.canvases.findIndex(
            (candidate) => candidate.id === entry.canvas,
        );
        if (canvas < 0) throw new Error(`no canvas ${entry.canvas}`);
        analyses
            .get(entry.analysis)!
            .zones.push({ canvas, shape: entry.shape });
    }
    return {
        payload: { ...payload, techniques, analyses: [...analyses.values()] },
        match: documentMatch({
            facets,
            kept: {
                analyses: [...kept],
                characterizations: payload.characterizations
                    .map((summary) => summary.id)
                    .filter((id) => !dimmed.includes(id)),
            },
            total: kept.size,
        }),
    };
}

/** A technique as the server sends it: `code` defaults to the label, `family` to its own uri. */
export function technique(
    uri: string,
    text: string,
    colour: number | null = 1,
    id: string = uri,
    code: string = text,
    family: string = uri,
): Technique {
    return { id, uri, label: label(text), code, colour, family };
}

export function valueRef(uri: string, text: string): ValueRef {
    return { id: uri, uri, label: label(text) };
}

export function annotation(
    n: number,
    overrides: Partial<Annotation> = {},
): Annotation {
    return {
        key: `an:${uuid(100 + n)}:f${n}`,
        analysis: uuid(100 + n),
        canvas: "https://iiif.example/c1",
        shape: { type: "point", x: 100 * n, y: 50 * n },
        technique: technique("http://example.org/xrf", "XRF"),
        name: label(`MS1_f12_XRF_0${n}`),
        dataKind: "xy",
        unpublished: false,
        match: true,
        ...overrides,
    };
}

export function sample(
    n: number,
    overrides: Partial<SampleSummary> = {},
): SampleSummary {
    return {
        id: uuid(600 + n),
        name: label(`Sample ${n}`),
        zone: {
            canvas: "https://iiif.example/c1",
            shape: { type: "rect", x: 40 * n, y: 60 * n, w: 20, h: 10 },
        },
        analyses: [],
        unpublished: false,
        ...overrides,
    };
}

export function characterization(
    n: number,
    overrides: Partial<CharacterizationSummary> = {},
): CharacterizationSummary {
    return {
        id: uuid(500 + n),
        name: label(`Characterization ${n}`),
        objects: [],
        materials: [
            {
                value: valueRef("http://example.org/vermilion", "Vermilion"),
                confidence: null,
                proportion: null,
            },
        ],
        colours: [valueRef("http://example.org/red", "Red")],
        layers: [],
        elements: [],
        zone: null,
        evidence: [],
        note: null,
        sources: [],
        authors: [],
        date: { start: null, end: null },
        unpublished: false,
        ...overrides,
    };
}

export function fileEntry(overrides: Partial<FileEntry> = {}): FileEntry {
    return {
        id: uuid(700),
        name: "X01_f1v.csv",
        size: 4200,
        format: "text/csv",
        role: "readable",
        pairedWith: null,
        dataKind: "xy",
        viewer: {
            rendererConfigId: uuid(800),
            xLabel: "Energy (keV)",
            yLabel: "Counts",
            axisKey: "xrf:energy",
            axisTitle: label("Counts · Energy (keV)"),
            points: null,
            decimated: false,
        },
        layers: [],
        license: {
            id: "cc-by",
            url: "https://creativecommons.org/licenses/by/4.0/",
            label: label("CC BY 4.0"),
            attribution: null,
            noDerivatives: false,
            inRightsRegistry: true,
            isDefault: false,
        },
        downloadUrl: "http://testserver/files/x01.csv",
        previewUrl: `http://testserver/api/spectrum-preview/${uuid(700)}`,
        zone: null,
        ...overrides,
    };
}

export function imagingEntry(overrides: Partial<FileEntry> = {}): FileEntry {
    const image = {
        service: "https://iiif.example/image/pb",
        url: null,
        width: 2000,
        height: 3000,
    };
    return fileEntry({
        id: `${uuid(101)}:imaging:0`,
        name: "maXRF f. 1v",
        size: null,
        format: "application/ld+json",
        role: "other",
        dataKind: "chemical-imaging",
        viewer: {
            rendererConfigId: null,
            xLabel: null,
            yLabel: null,
            axisKey: null,
            axisTitle: null,
            points: null,
            decimated: false,
        },
        layers: [
            {
                index: 0,
                label: "Pb",
                kind: "element",
                element: "Pb",
                band: null,
                image,
            },
            {
                index: 1,
                label: "Hg",
                kind: "element",
                element: "Hg",
                band: null,
                image: { ...image, service: "https://iiif.example/image/hg" },
            },
        ],
        previewUrl: null,
        ...overrides,
    });
}

export function analysisPayload(
    overrides: Partial<AnalysisPayload> = {},
): AnalysisPayload {
    return {
        id: uuid(101),
        name: label("MS1_f12_XRF_03"),
        technique: technique("http://example.org/xrf", "XRF"),
        instrument: null,
        operators: [],
        projects: [],
        date: { start: "2023-05-02", end: null },
        document: {
            id: uuid(1),
            model: "document",
            name: label("Manuscript 1"),
        },
        component: null,
        sample: null,
        files: [fileEntry()],
        conditions: [],
        evidenceOf: [],
        dataset: null,
        bibliography: [],
        citation: {
            text: `MS1_f12_XRF_03 [Dataset]. ManuSpectrum. http://testserver/report/${uuid(101)}. Accessed 2026-09-26.`,
            bibtex: "@dataset{manuspectrumnd000000,\n\ttitle = {MS1_f12_XRF_03}\n}\n",
        },
        availability: `The data are available in ManuSpectrum (http://testserver/report/${uuid(101)}).`,
        manifest: `http://testserver/iiif/v3/explorer-manifest?ids=an:${uuid(101)}:-&lang=en`,
        permalink: `http://testserver/report/${uuid(101)}`,
        reportUrl: `/en/report/${uuid(101)}`,
        certaintyScale: { levels: [] },
        unpublished: false,
        ...overrides,
    };
}

/** A share payload of a document with one analysis, no dataset, within the export bounds. */
export function sharePayload(
    overrides: Partial<SharePayload> = {},
): SharePayload {
    const query = `document=${uuid(1)}`;
    const product = (route: string): ProductLink => {
        const path = `/${route}?${query}&lang=en`;
        return { url: `http://testserver${path}`, path };
    };
    return {
        scope: {
            kind: "document",
            key: query,
            analyses: 1,
            characterizations: 0,
            spectra: 1,
            drafts: 0,
            restricted: false,
            restrictedAvailable: 0,
            missing: [],
        },
        citations: [analysisPayload().citation],
        availability: `The data are available in ManuSpectrum (http://testserver/report/${uuid(1)}).`,
        export: { files: 2, bytes: 2_400_000, overLimit: false, documents: [] },
        links: {
            manifest: product("iiif/v3/explorer-manifest"),
            seriesCsv: null,
            export: product("api/explorer/export"),
            exportRestricted: null,
        },
        ...overrides,
    };
}
