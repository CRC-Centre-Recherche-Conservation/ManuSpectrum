import { describe, expect, it } from "vitest";

import {
    filterParts,
    folioMarks,
    offeredTools,
    restrictingFilters,
    selectionSlots,
    staleToolFilters,
    toolView,
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
import type { ToolFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const C1 = "https://iiif.example/c1";
const C2 = "https://iiif.example/c2";
const C3 = "https://iiif.example/c3";
const XRF = technique("http://example.org/xrf", "XRF", 1, "xrf");
const BLUE = valueRef("http://example.org/blue", "Blue");
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
        canvases: [],
        confidenceBest: null,
        count: 1,
        techniques: ["xrf"],
        ...overrides,
    };
}

const AZURITE_PAIR = pair({
    colour: BLUE,
    material: AZURITE,
    elements: [COPPER],
    canvases: [C1],
    count: 2,
});
const CHALK_PAIR = pair({ elements: [CALCIUM], canvases: [C2] });

const SYNTHESIS: SynthesisResponse = {
    coverage: [
        { canvas: C1, label: "f. 1r", document: "d", counts: { xrf: 2 } },
        { canvas: C2, label: "f. 1v", document: "d", counts: { xrf: 1 } },
        { canvas: C3, label: "f. 2r", document: "d", counts: { xrf: 1 } },
    ],
    canvases: [
        { canvas: C1, label: "f. 1r", document: "d" },
        { canvas: C2, label: "f. 1v", document: "d" },
        { canvas: C3, label: "f. 2r", document: "d" },
    ],
    techniques: [XRF],
    pairs: [AZURITE_PAIR, CHALK_PAIR],
    elements: [
        { symbol: "Cu", level: null, count: 2 },
        { symbol: "Ca", level: null, count: 1 },
    ],
    unpublishedCount: 0,
};

const NONE: ToolFilters = { element: null, cell: null, pair: null };

describe("offeredTools", () => {
    it("offers every tool whose payload holds something", () => {
        expect(offeredTools(SYNTHESIS)).toEqual([
            "coverage",
            "colour-material",
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
        ).toEqual(["colour-material"]);
        expect(offeredTools({ ...SYNTHESIS, pairs: [] })).toEqual([
            "coverage",
            "periodic",
            "folio",
        ]);
    });

    it("offers the folio image on a canvas holding no analysis with a technique", () => {
        expect(offeredTools({ ...SYNTHESIS, coverage: [] })).toEqual([
            "colour-material",
            "periodic",
            "folio",
        ]);
        expect(
            offeredTools({ ...SYNTHESIS, coverage: [], canvases: [] }),
        ).toEqual(["colour-material", "periodic"]);
    });
});

describe("toolView", () => {
    it("shows everything without a filter", () => {
        expect(toolView(SYNTHESIS, NONE, "coverage").coverage).toHaveLength(3);
        expect(toolView(SYNTHESIS, NONE, "colour-material").pairs).toHaveLength(
            2,
        );
        expect(toolView(SYNTHESIS, NONE, "periodic").elements).toHaveLength(2);
    });

    it("an element keeps the pairs naming it and the canvases of those pairs", () => {
        const filters = { ...NONE, element: "Cu" };
        expect(toolView(SYNTHESIS, filters, "colour-material").pairs).toEqual([
            AZURITE_PAIR,
        ]);
        expect(
            toolView(SYNTHESIS, filters, "coverage").coverage.map(
                (row) => row.canvas,
            ),
        ).toEqual([C1]);
    });

    it("a cell keeps the pairs on its canvas and their elements", () => {
        const filters: ToolFilters = { ...NONE, cell: [C2, "xrf"] };
        expect(toolView(SYNTHESIS, filters, "colour-material").pairs).toEqual([
            CHALK_PAIR,
        ]);
        expect(
            toolView(SYNTHESIS, filters, "periodic").elements.map(
                (element) => element.symbol,
            ),
        ).toEqual(["Ca"]);
    });

    it("a cell keeps only the pairs carrying its technique", () => {
        const ochre = pair({
            material: valueRef("http://example.org/ochre", "Ochre"),
            canvases: [C2],
            techniques: ["fors"],
        });
        const synthesis = {
            ...SYNTHESIS,
            pairs: [AZURITE_PAIR, CHALK_PAIR, ochre],
        };
        expect(
            toolView(
                synthesis,
                { ...NONE, cell: [C2, "xrf"] },
                "colour-material",
            ).pairs,
        ).toEqual([CHALK_PAIR]);
        expect(
            toolView(
                synthesis,
                { ...NONE, cell: [C2, "fors"] },
                "colour-material",
            ).pairs,
        ).toEqual([ochre]);
    });

    it("a pair keeps its canvases and its elements", () => {
        const filters: ToolFilters = { ...NONE, pair: [BLUE.id, AZURITE.id] };
        expect(
            toolView(SYNTHESIS, filters, "coverage").coverage.map(
                (row) => row.canvas,
            ),
        ).toEqual([C1]);
        expect(
            toolView(SYNTHESIS, filters, "periodic").elements.map(
                (element) => element.symbol,
            ),
        ).toEqual(["Cu"]);
    });

    it("a pair without colour is told apart from the colours of its material", () => {
        const filters: ToolFilters = { ...NONE, pair: [null, CHALK.id] };
        expect(
            toolView(SYNTHESIS, filters, "coverage").coverage.map(
                (row) => row.canvas,
            ),
        ).toEqual([C2]);
    });

    it("never filters a tool by its own filter", () => {
        const filters: ToolFilters = {
            element: "Cu",
            cell: [C2, "xrf"],
            pair: [null, CHALK.id],
        };
        expect(toolView(SYNTHESIS, filters, "periodic").elements).toEqual([
            { symbol: "Ca", level: null, count: 1 },
        ]);
        expect(toolView(SYNTHESIS, filters, "colour-material").pairs).toEqual(
            [],
        );
    });
});

describe("restrictingFilters", () => {
    it("lists the filters set by the other tools", () => {
        const filters: ToolFilters = {
            element: "Cu",
            cell: [C1, "xrf"],
            pair: null,
        };
        expect(restrictingFilters("coverage", filters)).toEqual(["element"]);
        expect(restrictingFilters("periodic", filters)).toEqual(["cell"]);
        expect(restrictingFilters("colour-material", filters)).toEqual([
            "element",
            "cell",
        ]);
        expect(restrictingFilters("folio", filters)).toEqual([]);
    });
});

describe("staleToolFilters", () => {
    it("names the filters whose value the synthesis no longer holds", () => {
        expect(
            staleToolFilters(SYNTHESIS, {
                element: "Pb",
                cell: [C3, "fors"],
                pair: [BLUE.id, CHALK.id],
            }),
        ).toEqual(["element", "cell", "pair"]);
        expect(
            staleToolFilters(SYNTHESIS, {
                element: "Cu",
                cell: [C3, "xrf"],
                pair: [null, CHALK.id],
            }),
        ).toEqual([]);
    });
});

describe("filterParts", () => {
    it("names what each filter holds", () => {
        const filters: ToolFilters = {
            element: "Cu",
            cell: [C1, "xrf"],
            pair: [BLUE.id, AZURITE.id],
        };
        expect(filterParts(SYNTHESIS, filters, "element")).toEqual(["Cu"]);
        expect(filterParts(SYNTHESIS, filters, "cell")).toEqual([
            "f. 1r",
            "XRF",
        ]);
        expect(filterParts(SYNTHESIS, filters, "pair")).toEqual([
            "Blue",
            "Azurite",
        ]);
        expect(
            filterParts(
                SYNTHESIS,
                { ...filters, pair: [null, CHALK.id] },
                "pair",
            ),
        ).toEqual(["Chalk"]);
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
