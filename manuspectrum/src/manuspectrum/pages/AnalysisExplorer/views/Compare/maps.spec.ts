import { describe, expect, it } from "vitest";

import {
    analysisHit,
    imagingEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    layerIdOf,
    layerIn,
    sharedKind,
    sharedLayers,
    startLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/maps.ts";

import type {
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const IMAGE = { service: null, url: null, width: 0, height: 0 };

function element(index: number, symbol: string): FileLayer {
    return {
        index,
        label: symbol,
        kind: "element",
        element: symbol,
        band: null,
        image: IMAGE,
    };
}

function band(index: number, value: number, unit = "nm"): FileLayer {
    return {
        index,
        label: `${value} ${unit}`,
        kind: "band",
        element: null,
        band: { value, unit },
        image: IMAGE,
    };
}

function other(index: number, label: string): FileLayer {
    return {
        index,
        label,
        kind: "other",
        element: null,
        band: null,
        image: IMAGE,
    };
}

function line(
    slot: number,
    layers: FileLayer[],
    named: number | null = null,
): MapLine {
    const file: FileEntry = imagingEntry({ name: `map ${slot}`, layers });
    return {
        key: `an:${slot}:-`,
        slot,
        analysis: analysisHit(slot),
        file,
        named,
    };
}

describe("sharedLayers", () => {
    it("holds each element once, in the order the manifests give them", () => {
        const layers = sharedLayers([
            line(0, [element(0, "Pb"), element(1, "Hg")]),
            line(1, [element(0, "Cu"), element(1, "Pb")]),
        ]);
        expect(layers.map((layer) => layer.label)).toEqual(["Pb", "Hg", "Cu"]);
        expect(layers.map((layer) => layer.kind)).toEqual([
            "element",
            "element",
            "element",
        ]);
    });

    it("sorts the bands by value, one unit after another, after the elements and before the other layers", () => {
        const layers = sharedLayers([
            line(0, [band(0, 650), other(1, "UV fluorescence"), band(2, 400)]),
            line(1, [
                band(0, 1650, "cm-1"),
                band(1, 450),
                element(2, "Fe"),
                band(3, 650),
            ]),
        ]);
        expect(layers.map((layer) => layer.label)).toEqual([
            "Fe",
            "1650 cm-1",
            "400 nm",
            "450 nm",
            "650 nm",
            "UV fluorescence",
        ]);
    });
});

describe("layerIn", () => {
    it("finds the same element, band or layer in another map, else nothing", () => {
        const file = imagingEntry({
            layers: [element(0, "Pb"), band(1, 650), other(2, "RGB")],
        });
        expect(layerIn(file, layerIdOf(element(5, "Pb")))?.index).toBe(0);
        expect(layerIn(file, layerIdOf(band(9, 650)))?.index).toBe(1);
        expect(layerIn(file, layerIdOf(other(3, "RGB")))?.index).toBe(2);
        expect(layerIn(file, layerIdOf(element(0, "Cu")))).toBeNull();
        expect(layerIn(file, null)).toBeNull();
    });
});

describe("sharedKind", () => {
    it("names the layers by their kind when they share one, else as layers", () => {
        expect(sharedKind(sharedLayers([line(0, [element(0, "Pb")])]))).toBe(
            "element",
        );
        expect(sharedKind(sharedLayers([line(0, [band(0, 400)])]))).toBe(
            "band",
        );
        expect(
            sharedKind(
                sharedLayers([line(0, [element(0, "Pb"), band(1, 400)])]),
            ),
        ).toBe("other");
        expect(sharedKind([])).toBe("other");
    });
});

describe("startLayer", () => {
    it("starts on the layer the first one-layer key names, else on the first layer", () => {
        const maps = [
            line(0, [element(0, "Pb"), element(1, "Hg")]),
            line(1, [element(0, "Cu"), element(1, "Fe")], 1),
        ];
        const layers = sharedLayers(maps);
        expect(layers[startLayer(maps, layers)].label).toBe("Fe");
        expect(startLayer(maps.slice(0, 1), layers)).toBe(0);
    });
});
