import type {
    AnalysisHit,
    AnalysisPayload,
    Annotation,
    CharacterizationSummary,
    DocumentHit,
    DocumentPayload,
    Facet,
    FileEntry,
    SearchResponse,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

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
        technique: {
            id: uuid(900),
            uri: "http://example.org/xrf",
            label: label("XRF"),
        },
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

export function facet(key: Facet["key"], count: number): Facet {
    return {
        key,
        values: Array.from({ length: count }, (_, n) => ({
            id: `${key}-${n}`,
            label: label(`${key} ${n}`),
            count: n + 1,
            selected: false,
        })),
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
        annotations: [],
        characterizations: [],
        history: [],
        unpublishedCount: 0,
        unpublished: false,
        certaintyScale: { levels: [] },
        unlocated: [],
        ...overrides,
    };
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
        technique: valueRef("http://example.org/xrf", "XRF"),
        name: label(`MS1_f12_XRF_0${n}`),
        dataKind: "xy",
        unpublished: false,
        match: true,
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
        technique: valueRef("http://example.org/xrf", "XRF"),
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
        citation: null,
        permalink: `http://testserver/report/${uuid(101)}`,
        certaintyScale: { levels: [] },
        unpublished: false,
        ...overrides,
    };
}
