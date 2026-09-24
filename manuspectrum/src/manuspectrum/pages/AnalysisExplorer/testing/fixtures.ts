import type {
    AnalysisHit,
    DocumentHit,
    DocumentPayload,
    Facet,
    SearchResponse,
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
