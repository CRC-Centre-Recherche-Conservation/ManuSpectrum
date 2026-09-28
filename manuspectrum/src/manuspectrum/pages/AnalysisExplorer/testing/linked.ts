import {
    analysisHit,
    characterization,
    fileEntry,
    imagingEntry,
    label,
    technique,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    Item,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/**
 * A small Selection for the linked-selection specs, one document D1 with
 * two canvases:
 * - A1 `an1` (XRF, on C1): a spectrum `F1` and an element map `F2` (Fe, Pb);
 * - A2 `an2` (Raman, on C2): a spectrum `F3`;
 * - A3 `ch1` (Blue azurite on C1, citing `an1`).
 * The synthesis adds `ch2` (Blue azurite, citing `an1`) and `ch3` (chalk on
 * C2, citing `an2`), outside the Selection; Cu names `ch1` and `ch2`, Ca
 * names `ch3`.
 */
export const C1 = "https://iiif.example/c1";
export const C2 = "https://iiif.example/c2";
export const D1 = uuid(1);
export const XRF = technique("http://example.org/xrf", "XRF", 1, "xrf");
export const RAMAN = technique("http://example.org/raman", "Raman", 2, "raman");
export const BLUE = valueRef("http://example.org/blue", "Blue");
export const AZURITE = valueRef("http://example.org/azurite", "Azurite");
export const CHALK = valueRef("http://example.org/chalk", "Chalk");

export const AN1 = uuid(101);
export const AN2 = uuid(102);
export const CH1 = uuid(501);
export const CH2 = uuid(502);
export const CH3 = uuid(503);
export const F1 = uuid(701);
export const F2 = uuid(702);
export const F3 = uuid(703);

const DOCUMENT = { id: D1, model: "document", name: label("Manuscript 1") };

const A1: Item = {
    key: `an:${AN1}:-`,
    kind: "analysis",
    analysis: analysisHit(1, {
        technique: XRF,
        canvas: C1,
        document: DOCUMENT,
    }),
    files: [
        fileEntry({ id: F1, name: "F1.csv" }),
        imagingEntry({
            id: F2,
            name: "F2.tif",
            layers: [
                {
                    index: 0,
                    label: "Fe Ka",
                    kind: "element",
                    element: "Fe",
                    band: null,
                    image: { service: null, url: null, width: 1, height: 1 },
                },
                {
                    index: 1,
                    label: "Pb La",
                    kind: "element",
                    element: "Pb",
                    band: null,
                    image: { service: null, url: null, width: 1, height: 1 },
                },
            ],
        }),
    ],
};

const A2: Item = {
    key: `an:${AN2}:-`,
    kind: "analysis",
    analysis: analysisHit(2, {
        technique: RAMAN,
        canvas: C2,
        document: DOCUMENT,
    }),
    files: [fileEntry({ id: F3, name: "F3.csv" })],
};

const A3: Item = {
    key: `ch:${CH1}:-`,
    kind: "characterization",
    characterization: characterization(1, {
        name: label("Blue of the mantle"),
        colours: [BLUE],
        materials: [{ value: AZURITE, confidence: null, proportion: null }],
        objects: [DOCUMENT],
        zone: {
            canvas: C1,
            shape: { type: "point", x: 1, y: 1 },
            source: "own",
        },
        evidence: [{ id: AN1, name: label("MS1_f12_XRF_01") }],
    }),
};

export const ITEMS: readonly Item[] = [A1, A2, A3];

export const BASKET: readonly BasketItem[] = ITEMS.map((item, slot) => ({
    key: item.key,
    kind: item.kind,
    slot,
}));

export const BY_KEY: ReadonlyMap<string, Item> = new Map(
    ITEMS.map((item) => [item.key, item]),
);

export const SYNTHESIS: SynthesisResponse = {
    coverage: [
        { canvas: C1, label: "f. 12r", document: D1, counts: { xrf: 1 } },
        { canvas: C2, label: "f. 12v", document: D1, counts: { raman: 1 } },
    ],
    canvases: [
        {
            canvas: C1,
            label: "f. 12r",
            document: D1,
            selected: true,
            analyses: [AN1],
            materials: [CH1, CH2],
        },
        {
            canvas: C2,
            label: "f. 12v",
            document: D1,
            selected: true,
            analyses: [AN2],
            materials: [CH3],
        },
    ],
    techniques: [RAMAN, XRF],
    pairs: [
        {
            colour: BLUE,
            material: AZURITE,
            elements: [
                {
                    ...valueRef("http://example.org/cu", "Copper"),
                    symbol: "Cu",
                },
            ],
            canvases: [C1],
            confidenceBest: null,
            count: 2,
            cells: [[C1, "xrf"]],
            materials: [CH1, CH2],
        },
        {
            colour: null,
            material: CHALK,
            elements: [
                {
                    ...valueRef("http://example.org/ca", "Calcium"),
                    symbol: "Ca",
                },
            ],
            canvases: [C2],
            confidenceBest: null,
            count: 1,
            cells: [[C2, "raman"]],
            materials: [CH3],
        },
    ],
    elements: [
        { symbol: "Cu", level: null, count: 2, materials: [CH1, CH2] },
        { symbol: "Ca", level: null, count: 1, materials: [CH3] },
    ],
    materials: [
        {
            id: CH1,
            evidence: [AN1],
            canvases: [C1],
            cells: [[C1, "xrf"]],
            objects: [D1],
        },
        {
            id: CH2,
            evidence: [AN1],
            canvases: [C1],
            cells: [[C1, "xrf"]],
            objects: [D1],
        },
        {
            id: CH3,
            evidence: [AN2],
            canvases: [C2],
            cells: [[C2, "raman"]],
            objects: [D1],
        },
    ],
    unpublishedCount: 0,
};
