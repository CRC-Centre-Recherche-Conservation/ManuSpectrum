import { computed, effectScope, ref, shallowRef } from "vue";

import { useLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    characterization,
    fileEntry,
    imagingEntry,
    layerOf,
    label,
    technique,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { EffectScope } from "vue";

import type {
    Item,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
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
                layerOf({
                    index: 0,
                    label: "Fe Ka",
                    image: { service: null, url: null, width: 1, height: 1 },
                }),
                layerOf({
                    index: 1,
                    label: "Pb La",
                    image: { service: null, url: null, width: 1, height: 1 },
                }),
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

const A3: Extract<Item, { kind: "characterization" }> = {
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
        {
            canvas: C1,
            label: "f. 12r",
            document: D1,
            counts: { xrf: 1 },
            components: [{ component: null, counts: { xrf: 1 } }],
        },
        {
            canvas: C2,
            label: "f. 12v",
            document: D1,
            counts: { raman: 1 },
            components: [{ component: null, counts: { raman: 1 } }],
        },
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
            count: 2,
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
            count: 1,
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
            objects: [D1],
            summary: A3.characterization,
            selected: true,
        },
        {
            id: CH2,
            evidence: [AN1],
            canvases: [C1],
            objects: [D1],
            summary: characterization(2, {
                colours: [BLUE],
                materials: [
                    { value: AZURITE, confidence: null, proportion: null },
                ],
                objects: [DOCUMENT],
                evidence: [{ id: AN1, name: label("MS1_f12_XRF_01") }],
            }),
            selected: false,
        },
        {
            id: CH3,
            evidence: [AN2],
            canvases: [C2],
            objects: [D1],
            summary: characterization(3, {
                colours: [],
                materials: [
                    { value: CHALK, confidence: null, proportion: null },
                ],
                objects: [DOCUMENT],
                evidence: [{ id: AN2, name: label("MS1_f12_XRF_02") }],
            }),
            selected: false,
        },
    ],
    unpublishedCount: 0,
};

/** A component of D1, « Initial T », on C1. */
export const K1 = uuid(951);
export const COMPONENT = {
    id: K1,
    model: "component",
    name: label("Initial T"),
};

/** The Selection with A1 observing `COMPONENT`. */
export const BY_KEY_WITH_COMPONENT: ReadonlyMap<string, Item> = new Map(
    ITEMS.map((item) => [
        item.key,
        item.kind === "analysis" && item.analysis.id === AN1
            ? { ...item, analysis: { ...item.analysis, component: COMPONENT } }
            : item,
    ]),
);

/** The synthesis of `BY_KEY_WITH_COMPONENT`: C1's XRF counted on `COMPONENT`, `ch3` observing it too. */
export const SYNTHESIS_WITH_COMPONENT: SynthesisResponse = {
    ...SYNTHESIS,
    coverage: SYNTHESIS.coverage.map((row) =>
        row.canvas === C1
            ? {
                  ...row,
                  components: [{ component: COMPONENT, counts: row.counts }],
              }
            : row,
    ),
    materials: SYNTHESIS.materials.map((material) =>
        material.id === CH3
            ? {
                  ...material,
                  objects: [D1, K1],
                  summary: {
                      ...material.summary,
                      objects: [DOCUMENT, COMPONENT],
                  },
              }
            : material,
    ),
};

/**
 * A linked selection over this Selection, read and answered: the basket
 * of the active Pinia store is filled with `BASKET` first. `stop` ends
 * its scope.
 */
export function startLinkedSelection(
    announce: (message: string) => void = () => undefined,
    synthesis: SynthesisResponse = SYNTHESIS,
    byKey: ReadonlyMap<string, Item> = BY_KEY,
): { linked: LinkedSelection; stop: () => void } {
    const store = useExplorerStore();
    store.addManyToBasket(BASKET.map((item) => item.key));
    const keys = store.basket.map((item) => item.key);
    const scope: EffectScope = effectScope();
    const linked = scope.run(() =>
        useLinkedSelection({
            items: {
                byKey: ref(new Map(byKey)),
                missing: ref(new Set<string>()),
                settled: computed(() => true),
                status: ref<RequestStatus>("ready"),
                retry: () => undefined,
            },
            synthesis: {
                status: ref<RequestStatus>("ready"),
                data: shallowRef(synthesis),
                loaded: ref([...new Set(keys)].sort().join(",")),
                retry: () => undefined,
            },
            announce,
        }),
    )!;
    return { linked, stop: () => scope.stop() };
}
