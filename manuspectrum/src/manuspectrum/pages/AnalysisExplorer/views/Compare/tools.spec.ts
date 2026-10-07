import { describe, expect, it } from "vitest";

import {
    coverageRows,
    folioMarks,
    offeredTools,
    selectionSlots,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";
import {
    characterization,
    documentPayload,
    label,
    technique,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    SynthesisPair,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const C1 = "https://iiif.example/c1";
const C2 = "https://iiif.example/c2";
const C3 = "https://iiif.example/c3";
const XRF = technique("http://example.org/xrf", "XRF", 1, "xrf");
const BLUE = { ...valueRef("http://example.org/blue", "Blue"), swatch: null };
const AZURITE = valueRef("http://example.org/azurite", "Azurite");
const CHALK = valueRef("http://example.org/chalk", "Chalk");
const COPPER = { ...valueRef("http://example.org/cu", "Copper"), symbol: "Cu" };
const CALCIUM = {
    ...valueRef("http://example.org/ca", "Calcium"),
    symbol: "Ca",
};

function pair(overrides: Partial<SynthesisPair>): SynthesisPair {
    return {
        colour: null,
        material: CHALK,
        elements: [],
        materials: [],
        count: 1,
        ...overrides,
    };
}

const AZURITE_PAIR = pair({
    colour: BLUE,
    material: AZURITE,
    elements: [COPPER],
    count: 2,
});
const CHALK_PAIR = pair({
    elements: [CALCIUM],
});

const SYNTHESIS: SynthesisResponse = {
    coverage: [
        {
            canvas: C1,
            label: "f. 1r",
            document: "d",
            counts: { xrf: 2 },
            components: [{ component: null, counts: { xrf: 2 } }],
        },
        {
            canvas: C2,
            label: "f. 1v",
            document: "d",
            counts: { xrf: 1 },
            components: [{ component: null, counts: { xrf: 1 } }],
        },
        {
            canvas: C3,
            label: "f. 2r",
            document: "d",
            counts: { xrf: 1 },
            components: [{ component: null, counts: { xrf: 1 } }],
        },
    ],
    canvases: [
        {
            canvas: C1,
            label: "f. 1r",
            document: "d",
            selected: true,
            analyses: [],
            materials: [],
        },
        {
            canvas: C2,
            label: "f. 1v",
            document: "d",
            selected: true,
            analyses: [],
            materials: [],
        },
        {
            canvas: C3,
            label: "f. 2r",
            document: "d",
            selected: true,
            analyses: [],
            materials: [],
        },
    ],
    techniques: [XRF],
    pairs: [AZURITE_PAIR, CHALK_PAIR],
    elements: [
        { symbol: "Cu", level: null, count: 2, materials: [] },
        { symbol: "Ca", level: null, count: 1, materials: [] },
    ],
    materials: [],
    unpublishedCount: 0,
};

describe("offeredTools", () => {
    it("offers every tool whose payload holds something", () => {
        expect(offeredTools(SYNTHESIS)).toEqual([
            "coverage",
            "periodic",
            "folio",
        ]);
    });

    it("leaves out a tool whose payload is empty", () => {
        expect(
            offeredTools({
                ...SYNTHESIS,
                coverage: [],
                canvases: [],
                elements: [],
            }),
        ).toEqual([]);
        expect(offeredTools({ ...SYNTHESIS, pairs: [] })).toEqual([
            "coverage",
            "periodic",
            "folio",
        ]);
    });

    it("offers the folio image on a canvas holding no analysis with a technique", () => {
        expect(offeredTools({ ...SYNTHESIS, coverage: [] })).toEqual([
            "periodic",
            "folio",
        ]);
        expect(
            offeredTools({ ...SYNTHESIS, coverage: [], canvases: [] }),
        ).toEqual(["periodic"]);
    });

    it("offers the folio image only on a canvas holding an item of the Selection", () => {
        const citing = SYNTHESIS.canvases.map((entry) => ({
            ...entry,
            selected: false,
            analyses: [],
            materials: [],
        }));
        expect(offeredTools({ ...SYNTHESIS, canvases: citing })).toEqual([
            "coverage",
            "periodic",
        ]);
    });
});

describe("coverageRows", () => {
    const INITIAL = {
        id: uuid(951),
        model: "component",
        name: label("Initial T"),
    };

    it("splits each folio by the components observed on it, the folio alone first", () => {
        expect(
            coverageRows([
                {
                    canvas: C1,
                    label: "f. 5",
                    document: uuid(1),
                    counts: { xrf: 3 },
                    components: [
                        { component: null, counts: { xrf: 1 } },
                        { component: INITIAL, counts: { xrf: 2 } },
                    ],
                },
            ]),
        ).toEqual([
            { canvas: C1, label: "f. 5", component: null, counts: { xrf: 1 } },
            {
                canvas: C1,
                label: "f. 5",
                component: INITIAL,
                counts: { xrf: 2 },
            },
        ]);
    });

    it("keeps one row for a folio the synthesis does not split", () => {
        expect(
            coverageRows([
                {
                    canvas: C2,
                    label: "f. 6",
                    document: uuid(1),
                    counts: { xrf: 1 },
                    components: [],
                },
            ]),
        ).toEqual([
            { canvas: C2, label: "f. 6", component: null, counts: { xrf: 1 } },
        ]);
    });
});

describe("selectionSlots", () => {
    it("gives each analysis and identified material the slots of its keys, in order", () => {
        const slots = selectionSlots([
            {
                key: `af:${uuid(101)}:${uuid(700)}`,
                kind: "analysis-file",
                slot: 4,
            },
            { key: `an:${uuid(101)}:-`, kind: "analysis", slot: 0 },
            { key: `im:${uuid(102)}:0`, kind: "imaging", slot: 2 },
            { key: `ch:${uuid(501)}:-`, kind: "characterization", slot: 1 },
        ]);
        expect(slots).toEqual(
            new Map([
                [uuid(101), [0, 4]],
                [uuid(102), [2]],
                [uuid(501), [1]],
            ]),
        );
    });
});

describe("folioMarks", () => {
    const XRF_URI = "http://example.org/xrf";
    const payload = documentPayload({
        techniques: { [XRF_URI]: technique(XRF_URI, "XRF") },
        analyses: [
            {
                id: uuid(101),
                name: label("A"),
                technique: XRF_URI,
                dataKind: "xy",
                unpublished: false,
                zones: [
                    {
                        canvas: 0,
                        shape: { type: "point", x: 1, y: 2 },
                        feature: "f1",
                    },
                    {
                        canvas: 1,
                        shape: { type: "point", x: 3, y: 4 },
                        feature: "f2",
                    },
                ],
            },
            {
                id: uuid(102),
                name: label("B"),
                technique: null,
                dataKind: "xy",
                unpublished: false,
                zones: [
                    {
                        canvas: 0,
                        shape: { type: "point", x: 5, y: 6 },
                        feature: "f3",
                    },
                ],
            },
        ],
        characterizations: [
            characterization(1, {
                zone: {
                    canvas: "https://iiif.example/c1",
                    shape: { type: "rect", x: 0, y: 0, w: 10, h: 10 },
                    source: "own",
                },
            }),
            characterization(2, {
                zone: {
                    canvas: "https://iiif.example/c2",
                    shape: { type: "point", x: 0, y: 0 },
                    source: "own",
                },
            }),
        ],
    });

    it("marks the Selection's analyses and identified materials placed on the canvas, by first slot", () => {
        const marks = folioMarks(
            payload,
            "https://iiif.example/c1",
            new Map([
                [uuid(101), [3]],
                [uuid(501), [0, 5]],
                [uuid(502), [1]],
            ]),
        );
        expect(
            marks.map((mark) => [mark.id, mark.kind, mark.slots, mark.shapes]),
        ).toEqual([
            [
                uuid(501),
                "characterization",
                [0, 5],
                [{ type: "rect", x: 0, y: 0, w: 10, h: 10 }],
            ],
            [uuid(101), "analysis", [3], [{ type: "point", x: 1, y: 2 }]],
        ]);
        expect(marks[1].technique?.code).toBe("XRF");
    });

    it("marks nothing on a canvas the document does not list", () => {
        expect(
            folioMarks(
                payload,
                "https://other/c9",
                new Map([[uuid(101), [0]]]),
            ),
        ).toEqual([]);
    });
});
