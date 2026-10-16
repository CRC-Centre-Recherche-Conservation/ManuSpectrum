import { describe, expect, it } from "vitest";

import {
    firstMatchingPage,
    pageCounts,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-counts.ts";
import {
    annotation,
    characterization,
    documentPayload,
    sample,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const C1 = "https://iiif.example/c1";
const C2 = "https://iiif.example/c2";

describe("pageCounts", () => {
    it("counts each page's analyses, those the filters keep, its identified materials and samples", () => {
        const counts = pageCounts({
            annotations: [
                annotation(1),
                annotation(1, { key: "second-zone" }),
                annotation(2, { match: false }),
                annotation(3, { canvas: C2, match: false }),
            ],
            characterizations: [
                characterization(1, {
                    zone: {
                        canvas: C2,
                        shape: { type: "point", x: 1, y: 1 },
                        source: "own",
                    },
                }),
                characterization(2),
            ],
            samples: [sample(1), sample(2), sample(3, { zone: null })],
        });
        expect(counts.get(C1)).toEqual({
            total: 2,
            matching: 1,
            materials: 0,
            samples: 2,
        });
        expect(counts.get(C2)).toEqual({
            total: 1,
            matching: 0,
            materials: 1,
            samples: 0,
        });
    });
});

describe("firstMatchingPage", () => {
    it("is the first page, in the document's order, with an analysis the filters keep", () => {
        const { canvases } = documentPayload();
        const counts = pageCounts({
            annotations: [
                annotation(1, { match: false }),
                annotation(2, { canvas: C2 }),
            ],
            characterizations: [],
            samples: [],
        });
        expect(firstMatchingPage(canvases, counts)).toBe(C2);
        expect(firstMatchingPage(canvases, new Map())).toBeNull();
    });
});
