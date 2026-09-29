import { describe, expect, it } from "vitest";

import {
    analysisHit,
    characterization,
    fileEntry,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    BASKET,
    BY_KEY,
    CH1,
    CH2,
    CH3,
    ITEMS,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    autoWindows,
    keepUnchangedCurves,
    windowIdsOf,
    xyCurvesGained,
    xySpectraCount,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

import type {
    AnalysisHit,
    FileEntry,
    Item,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { BasketItem } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type {
    AutoWindow,
    XyWindow,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const XRF = "counts|energy (kev)|asc";
const RAMAN = "intensity|raman shift|asc";
const FORS = "reflectance|wavelength|asc";
const FTIR = "reflectance|wavenumber|desc";

function spectrum(n: number, axisKey: string | null, extra = {}): FileEntry {
    const base = fileEntry();
    return fileEntry({
        id: uuid(700 + n),
        name: `S${n}.csv`,
        viewer: { ...base.viewer, axisKey, ...extra },
    });
}

function micro(n: number): FileEntry {
    return fileEntry({
        id: uuid(750 + n),
        name: `M${n}.jpg`,
        dataKind: "micro-imaging",
        role: "other",
        previewUrl: null,
    });
}

function whole(n: number, files: FileEntry[], hit?: AnalysisHit): Item {
    const analysis = hit ?? analysisHit(n);
    return {
        key: `an:${analysis.id}:-`,
        kind: "analysis",
        analysis,
        files,
    };
}

function held(items: Item[], slots?: number[]) {
    const basket: BasketItem[] = items.map((item, index) => ({
        key: item.key,
        kind: item.kind,
        slot: slots?.[index] ?? index,
    }));
    return {
        basket,
        byKey: new Map(items.map((item) => [item.key, item])),
    };
}

function derive(items: Item[], slots?: number[], missing: string[] = []) {
    const { basket, byKey } = held(items, slots);
    const gone: BasketItem[] = missing.map((key, index) => ({
        key,
        kind: "analysis",
        slot: 20 + index,
    }));
    return autoWindows([...basket, ...gone], byKey, new Set(missing));
}

function xy(windows: AutoWindow[]): XyWindow[] {
    return windows.filter((window): window is XyWindow => window.kind === "xy");
}

describe("autoWindows", () => {
    it("is empty for an empty Selection", () => {
        expect(autoWindows([], new Map(), new Set())).toEqual([]);
    });

    it("opens one XY window per axis group, in the order of the first slot showing it", () => {
        const first = whole(1, [spectrum(1, RAMAN), spectrum(2, XRF)]);
        const second = whole(2, [spectrum(3, XRF)]);
        const windows = derive([first, second], [4, 1]);
        expect(windowIdsOf(windows)).toEqual([
            `auto:xy:${XRF}`,
            `auto:xy:${RAMAN}`,
        ]);
        const [xrf, raman] = xy(windows);
        expect(
            xrf.curves.map((curve) => [curve.slot, curve.file.name]),
        ).toEqual([
            [1, "S3.csv"],
            [4, "S2.csv"],
        ]);
        expect(xrf.keys).toEqual([second.key, first.key]);
        expect(raman.curves.map((curve) => curve.file.name)).toEqual([
            "S1.csv",
        ]);
    });

    it("keeps every readable file of an analysis in its slot, in file order", () => {
        const item = whole(1, [spectrum(1, XRF), spectrum(2, XRF)]);
        const [window] = xy(derive([item], [7]));
        expect(
            window.curves.map((curve) => [curve.slot, curve.file.name]),
        ).toEqual([
            [7, "S1.csv"],
            [7, "S2.csv"],
        ]);
        expect(window.keys).toEqual([item.key]);
    });

    it("names an XY window by the first stored configuration name and axis titles in slot order", () => {
        const unnamed = whole(1, [
            spectrum(1, XRF, { configName: null, xLabel: null, yLabel: "" }),
        ]);
        const named = whole(2, [
            spectrum(2, XRF, {
                configName: "XRF spectrum",
                xLabel: "Energy (keV)",
                yLabel: "Counts",
            }),
        ]);
        const other = whole(3, [
            spectrum(3, XRF, {
                configName: "Other",
                xLabel: "E",
                yLabel: "N",
            }),
        ]);
        const [window] = xy(derive([unnamed, named, other]));
        expect(window.configName).toBe("XRF spectrum");
        expect(window.xLabel).toBe("Energy (keV)");
        expect(window.yLabel).toBe("Counts");
        expect(window.axisKey).toBe(XRF);
    });

    it("groups readable spectra without axis titles in their own window", () => {
        const item = whole(1, [
            spectrum(1, null, { configName: null, xLabel: null, yLabel: null }),
        ]);
        const [window] = xy(derive([item]));
        expect(window.id).toBe("auto:xy:-");
        expect(window.axisKey).toBeNull();
        expect(window.configName).toBeNull();
    });

    it("folds the XY windows after the third", () => {
        const items = [XRF, RAMAN, FORS, FTIR].map((axisKey, n) =>
            whole(n + 1, [spectrum(n + 1, axisKey)]),
        );
        expect(xy(derive(items)).map((window) => window.folded)).toEqual([
            false,
            false,
            false,
            true,
        ]);
    });

    it("puts micro-images side by side, materials in one table, in slot order", () => {
        const images = whole(1, [micro(1), micro(2)]);
        const material = {
            key: `ch:${uuid(501)}:-`,
            kind: "characterization" as const,
            characterization: characterization(1),
        };
        const windows = derive([material, images], [3, 0]);
        expect(windowIdsOf(windows)).toEqual([
            "auto:micro",
            "auto:characterizations",
        ]);
        const [microWindow, materials] = windows;
        expect(microWindow.kind === "micro" && microWindow.images).toEqual([
            {
                key: images.key,
                slot: 0,
                analysis: (images as { analysis: AnalysisHit }).analysis,
                file: micro(1),
            },
            {
                key: images.key,
                slot: 0,
                analysis: (images as { analysis: AnalysisHit }).analysis,
                file: micro(2),
            },
        ]);
        expect(
            materials.kind === "characterizations" && materials.rows,
        ).toEqual([
            {
                key: material.key,
                slot: 3,
                characterization: material.characterization,
            },
        ]);
    });

    it("lists in the materials window the synthesis' materials citing the Selection, with its analyses", () => {
        const materials = autoWindows(
            BASKET,
            BY_KEY,
            new Set(),
            SYNTHESIS,
        ).find((window) => window.kind === "characterizations");
        expect(
            materials?.kind === "characterizations" &&
                materials.records.map((record) => [record.id, record.selected]),
        ).toEqual([
            [CH1, true],
            [CH2, false],
            [CH3, false],
        ]);
        expect(
            materials?.kind === "characterizations" &&
                materials.analyses.map((analysis) => analysis.id),
        ).toEqual(
            ITEMS.flatMap((item) =>
                item.kind === "characterization" ? [] : [item.analysis.id],
            ),
        );
        expect(materials?.keys).toEqual([`ch:${CH1}:-`]);
    });

    it("opens the materials window for materials citing a Selection of analyses only", () => {
        const analyses = BASKET.filter(
            (item) => item.kind !== "characterization",
        );
        const windows = autoWindows(analyses, BY_KEY, new Set(), SYNTHESIS);
        const materials = windows.find(
            (window) => window.kind === "characterizations",
        );
        expect(materials?.keys).toEqual([]);
        expect(
            materials?.kind === "characterizations" &&
                materials.records.map((record) => record.id),
        ).toEqual([CH1, CH2, CH3]);
        expect(
            autoWindows(analyses, BY_KEY, new Set(), {
                ...SYNTHESIS,
                materials: [],
            }).some((window) => window.kind === "characterizations"),
        ).toBe(false);
    });

    it("lists what no window draws, with the reason, once per item", () => {
        const empty = whole(2, []);
        const blank = whole(3, [imagingEntry({ layers: [] })]);
        const gone = `an:${uuid(199)}:-`;
        const windows = derive([empty, blank], undefined, [gone]);
        expect(windowIdsOf(windows)).toEqual(["auto:not-in-chart"]);
        const [window] = windows;
        expect(
            window.kind === "not-in-chart" &&
                window.entries.map((entry) => [entry.key, entry.reason]),
        ).toEqual([
            [empty.key, "no-data"],
            [blank.key, "no-data"],
            [gone, "missing"],
        ]);
        expect(window.keys).toEqual([empty.key, blank.key, gone]);
    });

    it("puts every layered map of the Selection in one window, after the XY windows, in slot order", () => {
        const hsi = imagingEntry({ id: `${uuid(102)}:imaging:0`, name: "HSI" });
        const layers = whole(1, [spectrum(1, XRF), imagingEntry()]);
        const cube = whole(2, [hsi]);
        const images = whole(3, [micro(1)]);
        const windows = derive([images, cube, layers], [0, 2, 1]);
        expect(windowIdsOf(windows)).toEqual([
            `auto:xy:${XRF}`,
            "auto:chemical-imaging",
            "auto:micro",
        ]);
        const maps = windows[1];
        expect(
            maps.kind === "chemical-imaging" &&
                maps.maps.map((line) => [
                    line.slot,
                    line.file.name,
                    line.named,
                ]),
        ).toEqual([
            [1, "maXRF f. 1v", null],
            [2, "HSI", null],
        ]);
        expect(maps.keys).toEqual([layers.key, cube.key]);
        expect(maps.kind === "chemical-imaging" && maps.folded).toBe(false);
    });

    it("opens the chemical imaging window folded when three XY windows are already drawn", () => {
        const items = [XRF, RAMAN, FORS].map((axisKey, n) =>
            whole(n + 1, [spectrum(n + 1, axisKey)]),
        );
        const maps = derive([...items, whole(4, [imagingEntry()])]).find(
            (window) => window.kind === "chemical-imaging",
        );
        expect(maps?.kind === "chemical-imaging" && maps.folded).toBe(true);
    });

    it("reads the older one-file and one-layer keys into the same windows", () => {
        const hit = analysisHit(1);
        const readable: Item = {
            key: `af:${hit.id}:${uuid(701)}`,
            kind: "analysis-file",
            analysis: hit,
            file: spectrum(1, XRF),
        };
        const image: Item = {
            key: `af:${hit.id}:${uuid(751)}`,
            kind: "analysis-file",
            analysis: hit,
            file: micro(1),
        };
        const raw: Item = {
            key: `af:${hit.id}:${uuid(702)}`,
            kind: "analysis-file",
            analysis: hit,
            file: fileEntry({
                id: uuid(702),
                name: "S1.mca",
                role: "raw",
                dataKind: "file",
                previewUrl: null,
            }),
        };
        const other: Item = {
            key: `af:${hit.id}:${uuid(703)}`,
            kind: "analysis-file",
            analysis: hit,
            file: fileEntry({
                id: uuid(703),
                name: "notes.pdf",
                role: "other",
                dataKind: "file",
                previewUrl: null,
            }),
        };
        const layer: Item = {
            key: `im:${hit.id}:1`,
            kind: "imaging",
            analysis: hit,
            file: imagingEntry(),
        };
        const windows = derive([readable, image, raw, other, layer]);
        expect(windowIdsOf(windows)).toEqual([
            `auto:xy:${XRF}`,
            "auto:chemical-imaging",
            "auto:micro",
            "auto:not-in-chart",
        ]);
        const maps = windows[1];
        expect(
            maps.kind === "chemical-imaging" &&
                maps.maps.map((line) => [line.key, line.named]),
        ).toEqual([[layer.key, 1]]);
        const notInChart = windows[3];
        expect(
            notInChart.kind === "not-in-chart" &&
                notInChart.entries.map((entry) => [
                    entry.key,
                    entry.reason,
                    entry.file?.name,
                ]),
        ).toEqual([
            [raw.key, "raw-file", "S1.mca"],
            [other.key, "file", "notes.pdf"],
        ]);
    });

    it("waits for an item not read yet, and keeps the windows of the others", () => {
        const item = whole(1, [spectrum(1, XRF)]);
        const { basket, byKey } = held([item]);
        const windows = autoWindows(
            [
                ...basket,
                { key: `ch:${uuid(501)}:-`, kind: "characterization", slot: 1 },
            ],
            byKey,
            new Set(),
        );
        expect(windowIdsOf(windows)).toEqual([`auto:xy:${XRF}`]);
    });

    it("drops a window once its items have left the Selection", () => {
        const first = whole(1, [spectrum(1, XRF)]);
        const second = whole(2, [micro(1)]);
        const { basket, byKey } = held([first, second]);
        expect(windowIdsOf(autoWindows(basket, byKey, new Set()))).toEqual([
            `auto:xy:${XRF}`,
            "auto:micro",
        ]);
        expect(
            windowIdsOf(autoWindows(basket.slice(1), byKey, new Set())),
        ).toEqual(["auto:micro"]);
    });
});

describe("keepUnchangedCurves", () => {
    it("keeps the curves of an XY window whose files did not change, and takes the new ones of another", () => {
        const first = whole(1, [spectrum(1, XRF)]);
        const second = whole(2, [spectrum(2, RAMAN)]);
        const third = whole(3, [spectrum(3, RAMAN)]);
        const before = derive([first, second]);
        const after = keepUnchangedCurves(
            before,
            derive([first, second, third]),
        );
        expect(xy(after)[0].curves).toBe(xy(before)[0].curves);
        expect(xy(after)[1].curves).not.toBe(xy(before)[1].curves);
        expect(xy(after)[1].curves).toHaveLength(2);
    });

    it("takes new curves when a file moves to another slot", () => {
        const first = whole(1, [spectrum(1, XRF)]);
        const before = derive([first], [0]);
        const after = keepUnchangedCurves(before, derive([first], [3]));
        expect(xy(after)[0].curves[0].slot).toBe(3);
    });
});

describe("xyCurvesGained", () => {
    it("counts, per XY window, the spectra it holds that its namesake did not hold", () => {
        const first = whole(1, [spectrum(1, XRF)]);
        const second = whole(2, [spectrum(2, RAMAN)]);
        const third = whole(3, [spectrum(3, XRF), spectrum(4, XRF), micro(1)]);
        const before = derive([first, second]);
        expect(xyCurvesGained(before, derive([first, second, third]))).toEqual(
            new Map([[`auto:xy:${XRF}`, 2]]),
        );
        expect(xyCurvesGained(before, derive([first])).size).toBe(0);
        expect(xyCurvesGained(before, derive([second, third], [1, 2]))).toEqual(
            new Map([[`auto:xy:${XRF}`, 2]]),
        );
        expect(xyCurvesGained([], derive([first]))).toEqual(
            new Map([[`auto:xy:${XRF}`, 1]]),
        );
    });
});

describe("xySpectraCount", () => {
    it("counts the spectra with a preview of every XY window", () => {
        const unread = fileEntry({
            id: uuid(790),
            name: "S90.csv",
            previewUrl: null,
            viewer: { ...fileEntry().viewer, axisKey: XRF },
        });
        const windows = derive([
            whole(1, [spectrum(1, XRF), spectrum(2, XRF), unread]),
            whole(2, [spectrum(3, RAMAN), micro(1)]),
        ]);
        expect(xySpectraCount(windows)).toBe(3);
        expect(xySpectraCount([])).toBe(0);
    });
});
