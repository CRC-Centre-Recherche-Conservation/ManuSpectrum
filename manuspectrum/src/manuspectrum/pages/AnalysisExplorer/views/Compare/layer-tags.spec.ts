import { describe, expect, it } from "vitest";

import {
    label,
    layerOf,
    layerMethod,
    layerUnit,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    compareFamilies,
    layerTag,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const ELEMENT_MAP = valueRef("http://example.org/element-map", "Element map");
const COMPONENT = valueRef("http://example.org/pca", "Principal component");
const TOTAL = valueRef("http://example.org/total", "Total signal");
const PHOTO = valueRef("http://example.org/photo", "Photograph");
const NM = layerUnit("Nanometre", "nm");

function element(symbol: string): FileLayer["elements"][number] {
    return {
        value: valueRef(`http://example.org/el-${symbol}`, symbol),
        symbol,
    };
}

function tagged(overrides: Partial<FileLayer>): FileLayer {
    return layerOf({ index: 0, ...overrides });
}

describe("layerTag", () => {
    it("is null for a canvas without a tile", () => {
        expect(layerTag(layerOf({ index: 0, label: "Cu Ka" }))).toBeNull();
    });

    it("tags a single element by its symbol", () => {
        const tag = layerTag(
            tagged({ content: ELEMENT_MAP, elements: [element("Cu")] }),
        );
        expect(tag?.family).toBe("element:Cu");
        expect(tag?.key).toBe("element:Cu");
        expect(tag?.parts.symbols).toEqual(["Cu"]);
        expect(tag?.parts.line).toBeNull();
    });

    it("keeps the family of an element and tells its lines apart by key", () => {
        const base = { content: ELEMENT_MAP, elements: [element("Cu")] };
        const ka = layerTag(
            tagged({ ...base, emissionLine: valueRef("l:ka", "Kα") }),
        );
        const la = layerTag(
            tagged({ ...base, emissionLine: valueRef("l:la", "Lα") }),
        );
        const bare = layerTag(tagged(base));
        expect(ka?.key).toBe("element:Cu:Kα");
        expect(la?.key).toBe("element:Cu:Lα");
        expect(ka?.key).not.toBe(la?.key);
        expect(ka?.family).toBe("element:Cu");
        expect(la?.family).toBe(bare?.family);
        expect(ka?.parts.line?.value).toBe("Kα");
    });

    it("sorts the symbols of a composite and joins them with +", () => {
        const tag = layerTag(
            tagged({
                content: ELEMENT_MAP,
                elements: [element("Pb"), element("Cu"), element("Fe")],
            }),
        );
        expect(tag?.family).toBe("element:Cu+Fe+Pb");
        expect(tag?.parts.symbols).toEqual(["Cu", "Fe", "Pb"]);
    });

    it("ignores an element without a symbol", () => {
        const tag = layerTag(
            tagged({
                content: ELEMENT_MAP,
                elements: [{ value: valueRef("e:x", "Unknown"), symbol: null }],
            }),
        );
        expect(tag?.family).toBeNull();
        expect(tag?.key).toBe(`kind:${ELEMENT_MAP.id}`);
    });

    it("tags a band by its value, normalised, and its unit", () => {
        const tag = layerTag(
            tagged({
                content: valueRef("c:hsi", "Band"),
                band: { value: 650.0, lower: null, upper: null, unit: NM },
            }),
        );
        expect(tag?.family).toBe("band:650:nm");
        expect(tag?.key).toBe("band:650:nm");
        expect(tag?.parts.band?.value).toBe(650);
    });

    it("keys a band on the unit's symbol, never on its localized label", () => {
        const band = { value: 650, lower: null, upper: null };
        const english = layerTag(
            tagged({
                content: valueRef("c:hsi", "Band"),
                band: { ...band, unit: layerUnit("Nanometre", "nm", "en") },
            }),
        );
        const french = layerTag(
            tagged({
                content: valueRef("c:hsi", "Band"),
                band: { ...band, unit: layerUnit("Nanomètre", "nm", "fr") },
            }),
        );
        expect(english?.family).toBe("band:650:nm");
        expect(french?.family).toBe(english?.family);
        expect(english?.parts.unit).toBe("nm");
    });

    it("shows the label of a unit without a symbol and keys it on the unit's id", () => {
        const tag = layerTag(
            tagged({
                content: valueRef("c:hsi", "Band"),
                band: {
                    value: 650,
                    lower: null,
                    upper: null,
                    unit: layerUnit("Nanometre", null),
                },
            }),
        );
        expect(tag?.parts.unit).toBe("Nanometre");
        expect(tag?.family).toBe("band:650:http://example.org/unit-nm");
    });

    it("tags a band given by an interval", () => {
        const tag = layerTag(
            tagged({
                content: valueRef("c:hsi", "Band"),
                band: { value: null, lower: 600, upper: 700, unit: NM },
            }),
        );
        expect(tag?.family).toBe("band:600-700:nm");
    });

    it("leaves the unit empty when the band has none", () => {
        const tag = layerTag(
            tagged({
                content: valueRef("c:hsi", "Band"),
                band: { value: 550, lower: null, upper: null, unit: null },
            }),
        );
        expect(tag?.family).toBe("band:550:");
    });

    it("tags a component by its method and index", () => {
        const tag = layerTag(
            tagged({
                content: COMPONENT,
                processing: {
                    method: layerMethod(
                        "Principal component analysis",
                        "PCA",
                        "m:pca",
                    ),
                    index: 3,
                    inputs: null,
                },
            }),
        );
        expect(tag?.family).toBe("component:m:pca:3");
        expect(tag?.parts.index).toBe(3);
        expect(tag?.parts.method).toBe("PCA");
    });

    it("falls back to the method's label when it has no symbol", () => {
        const tag = layerTag(
            tagged({
                content: COMPONENT,
                processing: {
                    method: layerMethod("Deconvolution", null, "m:dec"),
                    index: 1,
                    inputs: null,
                },
            }),
        );
        expect(tag?.parts.method).toBe("Deconvolution");
    });

    it("marks an unknown method with a question mark", () => {
        const tag = layerTag(
            tagged({
                content: COMPONENT,
                processing: { method: null, index: 2, inputs: null },
            }),
        );
        expect(tag?.family).toBe("component:?:2");
        expect(tag?.parts.method).toBeNull();
    });

    it("gives a content alone a key and no family", () => {
        const tag = layerTag(tagged({ content: PHOTO }));
        expect(tag).toEqual({
            key: `kind:${PHOTO.id}`,
            family: null,
            parts: expect.objectContaining({
                contentLabel: label("Photograph"),
            }),
        });
        expect(layerTag(tagged({ content: TOTAL }))?.family).toBeNull();
    });
});

describe("compareFamilies", () => {
    const sorted = (families: string[]): string[] =>
        [...families].sort(compareFamilies);

    it("puts elements by atomic number, then bands by value, then components by index, then the rest", () => {
        expect(
            sorted([
                "kind:z",
                "component:m:2",
                "band:650:nm",
                "element:Pb",
                "component:m:1",
                "band:550:nm",
                "element:Cu",
                "element:H",
            ]),
        ).toEqual([
            "element:H",
            "element:Cu",
            "element:Pb",
            "band:550:nm",
            "band:650:nm",
            "component:m:1",
            "component:m:2",
            "kind:z",
        ]);
    });

    it("orders a composite after its first element and by label otherwise", () => {
        expect(
            sorted(["element:Fe+Pb", "element:Ca+Fe", "kind:b", "kind:a"]),
        ).toEqual(["element:Ca+Fe", "element:Fe+Pb", "kind:a", "kind:b"]);
    });
});
