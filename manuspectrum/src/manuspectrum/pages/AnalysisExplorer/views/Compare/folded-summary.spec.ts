import { describe, expect, it } from "vitest";

import {
    analysisHit,
    fileEntry,
    imagingEntry,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { foldedSummary } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/folded-summary.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    FileLine,
    MapLine,
    ChemicalImagingWindow,
    XyWindow,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const FTIR = technique("http://example.org/ftir", "FTIR", 2, uuid(901));

function curve(slot: number, n = slot, withTechnique = FTIR): FileLine {
    const analysis = analysisHit(n, { technique: withTechnique });
    return {
        key: `an:${analysis.id}:-`,
        slot,
        analysis,
        file: fileEntry({ id: uuid(700 + n), name: `S${n}.csv` }),
    };
}

function xyWindow(curves: FileLine[]): XyWindow {
    return {
        id: "auto:xy:ftir",
        kind: "xy",
        keys: [...new Set(curves.map((line) => line.key))],
        axisKey: "ftir",
        configName: "FTIR",
        xLabel: null,
        yLabel: null,
        folded: true,
        curves,
    };
}

function elementLayer(index: number, symbol: string): FileLayer {
    return {
        index,
        label: symbol,
        image: {
            service: `https://iiif.example/image/${symbol}`,
            url: null,
            width: 2000,
            height: 3000,
        },
    };
}

function mapLine(slot: number, symbols: string[]): MapLine {
    const analysis = analysisHit(slot);
    return {
        key: `an:${analysis.id}:-`,
        slot,
        analysis,
        file: imagingEntry({
            id: `${analysis.id}:imaging:0`,
            layers: symbols.map((symbol, index) => elementLayer(index, symbol)),
        }),
        named: null,
    };
}

function mapsWindow(maps: MapLine[]): ChemicalImagingWindow {
    return {
        id: "auto:chemical-imaging",
        kind: "chemical-imaging",
        keys: maps.map((line) => line.key),
        folded: true,
        maps,
    };
}

describe("foldedSummary", () => {
    it("counts the spectra of an XY window, with its slots once each and its technique codes", () => {
        const summary = foldedSummary(
            xyWindow([curve(11), curve(12), curve(12, 13), curve(14)]),
        );
        expect(summary).toEqual({
            kind: "xy",
            count: 4,
            slots: [11, 12, 14],
            names: ["FTIR"],
        });
    });

    it("names no technique when the spectra carry none", () => {
        const summary = foldedSummary(
            xyWindow([curve(0, 0, null as never), curve(1, 1, null as never)]),
        );
        expect(summary?.names).toEqual([]);
    });

    it("counts the maps of the chemical imaging window and lists every distinct layer label met", () => {
        const summary = foldedSummary(
            mapsWindow([mapLine(3, ["Pb", "Fe"]), mapLine(1, ["Hg", "Pb"])]),
        );
        expect(summary).toEqual({
            kind: "maps",
            count: 2,
            slots: [1, 3],
            names: ["Pb", "Fe", "Hg"],
        });
    });

    it("has nothing to say for a window that does not fold", () => {
        expect(
            foldedSummary({
                id: "auto:micro",
                kind: "micro",
                keys: [],
                images: [],
            }),
        ).toBeNull();
    });
});
