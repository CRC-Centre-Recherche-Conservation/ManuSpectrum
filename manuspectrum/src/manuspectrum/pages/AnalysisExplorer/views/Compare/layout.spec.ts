import { afterEach, describe, expect, it, vi } from "vitest";

import {
    LAYOUT_STORAGE_KEY,
    clearBoxes,
    flowLayout,
    forgetWindows,
    keepWindows,
    nearestBox,
    parseLayout,
    readFolded,
    readHidden,
    readImaging,
    readLayout,
    readTools,
    readXrfSettings,
    readingOrder,
    sizeOf,
    writeFolded,
    writeHidden,
    writeImaging,
    writeLayout,
    writeTools,
    writeXrfSettings,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

afterEach(() => window.localStorage.clear());

describe("Compare window layout", () => {
    it("is stored under its own key and read back", () => {
        writeLayout({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } });
        expect(
            JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY)!),
        ).toEqual({
            version: 3,
            boxes: { "auto:micro": { x: 0, y: 0, w: 6, h: 5 } },
            hidden: [],
            folded: {},
        });
        expect(readLayout()).toEqual({
            "auto:micro": { x: 0, y: 0, w: 6, h: 5 },
        });
        clearBoxes();
        expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
        expect(readLayout()).toEqual({});
    });

    it("drops what is not a box on the grid", () => {
        expect(parseLayout(null)).toEqual({});
        expect(parseLayout("not json")).toEqual({});
        expect(parseLayout("[1, 2]")).toEqual({});
        expect(
            parseLayout(
                JSON.stringify({
                    good: { x: 6, y: 2, w: 6, h: 5 },
                    negative: { x: -1, y: 0, w: 6, h: 5 },
                    wide: { x: 0, y: 0, w: 13, h: 5 },
                    empty: { x: 0, y: 0, w: 0, h: 5 },
                    fraction: { x: 0.5, y: 0, w: 6, h: 5 },
                    text: { x: "0", y: 0, w: 6, h: 5 },
                    missing: { x: 0, y: 0, w: 6 },
                    scalar: 3,
                }),
            ),
        ).toEqual({ good: { x: 6, y: 2, w: 6, h: 5 } });
    });

    it("reads a layout saved before hidden windows existed", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } }),
        );
        expect(readLayout()).toEqual({
            "auto:micro": { x: 0, y: 0, w: 6, h: 5 },
        });
        expect(readHidden()).toEqual([]);
    });

    it("keeps the hidden windows next to the places, each written without losing the other", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        writeLayout({ "auto:micro": box });
        writeHidden(["auto:xy:-", "auto:micro"]);
        writeLayout({ "auto:micro": box, "auto:xy:-": box });
        expect(readHidden()).toEqual(["auto:xy:-", "auto:micro"]);
        expect(readLayout()).toEqual({ "auto:micro": box, "auto:xy:-": box });
        writeHidden([]);
        expect(readLayout()).toEqual({ "auto:micro": box, "auto:xy:-": box });
    });

    it("forgets the places only: the hidden, folded and open windows stay", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        writeLayout({ "auto:micro": box });
        writeHidden(["auto:xy:-"]);
        writeFolded({ "auto:maps": true });
        writeTools([{ kind: "periodic", params: {} }]);
        clearBoxes();
        expect(readLayout()).toEqual({});
        expect(readHidden()).toEqual(["auto:xy:-"]);
        expect(readFolded()).toEqual({ "auto:maps": true });
        expect(readTools()).toEqual([{ kind: "periodic", params: {} }]);
    });

    it("drops what is not a window id from the hidden windows", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: { bad: { x: -1 } },
                hidden: ["auto:micro", 3, null, "auto:micro", ""],
            }),
        );
        expect(readHidden()).toEqual(["auto:micro"]);
        expect(readLayout()).toEqual({});
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ version: 2, boxes: [], hidden: "auto:micro" }),
        );
        expect(readHidden()).toEqual([]);
        expect(readLayout()).toEqual({});
    });

    it("keeps the windows the reader folded or unfolded next to the places", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        writeLayout({ "auto:xy:-": box });
        writeFolded({ "auto:xy:-": true, "auto:xy:b": false });
        writeHidden(["auto:micro"]);
        expect(readFolded()).toEqual({ "auto:xy:-": true, "auto:xy:b": false });
        expect(readLayout()).toEqual({ "auto:xy:-": box });
        expect(readHidden()).toEqual(["auto:micro"]);
    });

    it("reads a layout saved before folded windows were kept, and drops what is not a fold state", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ version: 2, boxes: {}, hidden: [] }),
        );
        expect(readFolded()).toEqual({});
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: {},
                hidden: [],
                folded: { good: true, text: "true", number: 1, "": true },
            }),
        );
        expect(readFolded()).toEqual({ good: true });
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ version: 2, folded: [true] }),
        );
        expect(readFolded()).toEqual({});
    });

    it("keeps the open tools next to the places, and drops what is not a tool", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        writeLayout({ "tool:coverage:-": box });
        writeTools([
            { kind: "coverage", params: {} },
            { kind: "folio", params: { canvas: "c1" } },
        ]);
        expect(readTools()).toEqual([
            { kind: "coverage", params: {} },
            { kind: "folio", params: { canvas: "c1" } },
        ]);
        expect(readLayout()).toEqual({ "tool:coverage:-": box });
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                tools: [
                    { kind: "periodic", params: {} },
                    { kind: "unknown", params: {} },
                    { kind: "coverage", params: { n: 1 } },
                    { kind: "coverage" },
                    "periodic",
                ],
            }),
        );
        expect(readTools()).toEqual([{ kind: "periodic", params: {} }]);
    });

    it("drops a stored colours × materials tool, now part of the Materials window", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: { "tool:colour-material:-": { x: 0, y: 0, w: 6, h: 5 } },
                tools: [
                    { kind: "colour-material", params: {} },
                    { kind: "periodic", params: {} },
                ],
            }),
        );
        expect(readTools()).toEqual([{ kind: "periodic", params: {} }]);
        forgetWindows(["tool:periodic:-"]);
        expect(readLayout()).toEqual({});
        expect(readTools()).toEqual([{ kind: "periodic", params: {} }]);
    });

    it("keeps the open tools when windows are forgotten or the layout is emptied", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        writeTools([{ kind: "periodic", params: {} }]);
        writeLayout({ "auto:micro": box, "tool:periodic:-": box });
        forgetWindows(["tool:periodic:-"]);
        expect(readLayout()).toEqual({ "tool:periodic:-": box });
        expect(readTools()).toEqual([{ kind: "periodic", params: {} }]);
        clearBoxes();
        expect(readLayout()).toEqual({});
        expect(readTools()).toEqual([{ kind: "periodic", params: {} }]);
        writeTools([]);
        clearBoxes();
        expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
    });

    it("forgets the places and the hidden state of windows that are gone", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        writeLayout({ "auto:micro": box, "auto:xy:-": box });
        writeHidden(["auto:xy:-", "auto:characterizations"]);
        writeFolded({ "auto:xy:-": true, "auto:micro": false });
        forgetWindows(["auto:micro"]);
        expect(readLayout()).toEqual({ "auto:micro": box });
        expect(readHidden()).toEqual([]);
        expect(readFolded()).toEqual({ "auto:micro": false });
    });

    it("writes nothing when no window is gone", () => {
        forgetWindows(["auto:micro"]);
        expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
    });

    it("keeps only the windows shown", () => {
        const box = { x: 0, y: 0, w: 6, h: 5 };
        expect(
            keepWindows({ "auto:micro": box, "tool:periodic:-": box }, [
                "auto:micro",
            ]),
        ).toEqual({ "auto:micro": box });
    });

    it("reads windows row by row, left to right", () => {
        expect(
            readingOrder([
                { id: "c", x: 0, y: 5 },
                { id: "b", x: 6, y: 0 },
                { id: "a", x: 0, y: 0 },
            ]).map((box) => box.id),
        ).toEqual(["a", "b", "c"]);
    });

    it("lays windows out in the order given, a new row when one does not fit", () => {
        expect(
            flowLayout(
                [
                    { id: "a", w: 6, h: 5 },
                    { id: "b", w: 4, h: 4 },
                    { id: "c", w: 6, h: 5 },
                    { id: "d", w: 12, h: 6 },
                ],
                12,
            ),
        ).toEqual({
            a: { x: 0, y: 0, w: 6, h: 5 },
            b: { x: 6, y: 0, w: 4, h: 4 },
            c: { x: 0, y: 5, w: 6, h: 5 },
            d: { x: 0, y: 10, w: 12, h: 6 },
        });
    });

    it("stacks windows in one column", () => {
        expect(
            flowLayout(
                [
                    { id: "a", w: 6, h: 5 },
                    { id: "b", w: 4, h: 4 },
                ],
                1,
            ),
        ).toEqual({
            a: { x: 0, y: 0, w: 1, h: 5 },
            b: { x: 0, y: 5, w: 1, h: 4 },
        });
    });

    it("finds the box nearest another: edges first, then centres, then reading order", () => {
        const closed = { x: 0, y: 0, w: 6, h: 5 };
        const below = { id: "below", x: 0, y: 5, w: 6, h: 5 };
        const beside = { id: "beside", x: 6, y: 0, w: 4, h: 4 };
        const far = { id: "far", x: 0, y: 12, w: 12, h: 6 };
        expect(nearestBox(closed, [far, beside, below])?.id).toBe("below");
        expect(
            nearestBox(closed, [far, beside, { ...below, x: 0, y: 0 }])?.id,
        ).toBe("below");
        expect(
            nearestBox({ x: 6, y: 0, w: 6, h: 5 }, [
                { id: "right", x: 6, y: 5, w: 6, h: 5 },
                { id: "left", x: 0, y: 5, w: 6, h: 5 },
            ])?.id,
        ).toBe("right");
        expect(
            nearestBox({ x: 3, y: 0, w: 6, h: 5 }, [
                { id: "second", x: 6, y: 5, w: 6, h: 5 },
                { id: "first", x: 0, y: 5, w: 6, h: 5 },
            ])?.id,
        ).toBe("first");
        expect(nearestBox(closed, [far])?.id).toBe("far");
        expect(nearestBox(closed, [])).toBeNull();
    });

    it("names the size a box has, if it is one of S, M, L", () => {
        expect(sizeOf({ w: 4, h: 4 })).toBe("S");
        expect(sizeOf({ w: 6, h: 5 })).toBe("M");
        expect(sizeOf({ w: 12, h: 6 })).toBe("L");
        expect(sizeOf({ w: 7, h: 5 })).toBeNull();
        expect(sizeOf({ w: 1, h: 6 }, 1)).toBe("L");
        expect(sizeOf({ w: 1, h: 4 }, 1)).toBe("S");
    });
});

describe("Compare layout, imaging record (v3)", () => {
    const IMAGING = {
        layout: "curtain" as const,
        panes: ["c1-0", "c2-0", null, null],
        syncViews: true,
        filters: [
            { brightness: 120, contrast: 90, saturation: 100, greyscale: true },
            ...Array.from({ length: 4 }, () => ({
                brightness: 100,
                contrast: 100,
                saturation: 100,
                greyscale: false,
            })),
        ],
        stack: {
            analysis: "a1",
            layers: [{ canvas: "c1-0", opacity: 60, on: false, tint: "cyan" }],
        },
        grouping: "tag" as const,
    };

    it("round-trips and is written with the version 3", () => {
        expect(readImaging()).toBeUndefined();
        writeImaging(IMAGING);
        expect(readImaging()).toEqual(IMAGING);
        expect(
            JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY)!),
        ).toMatchObject({ version: 3, imaging: IMAGING });
    });

    it("stays when the boxes, hidden, folded or tools are written", () => {
        writeImaging(IMAGING);
        writeLayout({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } });
        writeHidden(["auto:micro"]);
        writeFolded({ "auto:micro": true });
        writeTools([{ kind: "periodic", params: {} }]);
        expect(readImaging()).toEqual(IMAGING);
    });

    it("survives clearBoxes and forgetWindows", () => {
        writeImaging(IMAGING);
        writeLayout({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } });
        clearBoxes();
        expect(readImaging()).toEqual(IMAGING);
        expect(readLayout()).toEqual({});
        writeLayout({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } });
        forgetWindows([]);
        expect(readImaging()).toEqual(IMAGING);
        expect(readLayout()).toEqual({});
    });

    it("is erased by writing undefined, and the record goes when nothing is left", () => {
        writeImaging(IMAGING);
        writeImaging(undefined);
        expect(readImaging()).toBeUndefined();
        expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
    });

    it("reads a v2 record with no imaging and keeps its other parts", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: { "auto:micro": { x: 0, y: 0, w: 6, h: 5 } },
                hidden: ["auto:micro"],
                folded: { "auto:micro": true },
            }),
        );
        expect(readImaging()).toBeUndefined();
        expect(readHidden()).toEqual(["auto:micro"]);
        expect(readFolded()).toEqual({ "auto:micro": true });
        expect(readLayout()).toEqual({
            "auto:micro": { x: 0, y: 0, w: 6, h: 5 },
        });
        writeImaging(IMAGING);
        expect(readHidden()).toEqual(["auto:micro"]);
    });

    it("reads a bare T2 box record with no imaging", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } }),
        );
        expect(readImaging()).toBeUndefined();
        expect(readLayout()).toEqual({
            "auto:micro": { x: 0, y: 0, w: 6, h: 5 },
        });
    });

    it("drops what is not an imaging record and repairs what is half there", () => {
        const stored = (imaging: unknown) =>
            window.localStorage.setItem(
                LAYOUT_STORAGE_KEY,
                JSON.stringify({ version: 3, boxes: {}, imaging }),
            );
        stored("nope");
        expect(readImaging()).toBeUndefined();
        stored({
            layout: "cube",
            panes: [1, "c1", null],
            filters: [{ brightness: 900 }],
            grouping: 3,
        });
        const repaired = readImaging()!;
        expect(repaired.layout).toBe("single");
        expect(repaired.panes).toEqual([null, "c1", null, null]);
        expect(repaired.filters).toHaveLength(5);
        expect(repaired.filters[0].brightness).toBe(200);
        expect(repaired.filters[0].contrast).toBe(100);
        expect(repaired.grouping).toBe("analysis");
        expect(repaired.syncViews).toBe(false);
        expect(repaired.stack).toEqual({ analysis: null, layers: [] });
    });

    it("round-trips the choice about the gallery, and reads a record without it as no choice", () => {
        writeImaging({ ...IMAGING, gallery: false });
        expect(readImaging()?.gallery).toBe(false);
        writeImaging({ ...IMAGING, gallery: true });
        expect(readImaging()?.gallery).toBe(true);
        writeImaging(IMAGING);
        expect(readImaging()).not.toHaveProperty("gallery");
    });

    it("drops a choice about the gallery that is not a boolean", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 3,
                boxes: {},
                imaging: { ...IMAGING, gallery: "yes" },
            }),
        );
        expect(readImaging()).not.toHaveProperty("gallery");
    });

    it("reads the old linkAll as nothing: the record opens unsynced", () => {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 3,
                boxes: {},
                imaging: { ...IMAGING, syncViews: undefined, linkAll: true },
            }),
        );
        expect(readImaging()?.syncViews).toBe(false);
        expect(readImaging()).not.toHaveProperty("linkAll");
    });

    it("reads nothing, and writes nothing, when storage is blocked", () => {
        const spy = vi
            .spyOn(Storage.prototype, "getItem")
            .mockImplementation(() => {
                throw new Error("blocked");
            });
        expect(readImaging()).toBeUndefined();
        spy.mockRestore();
    });
});

describe("Compare layout, xrf record (v3)", () => {
    const XRF = {
        detector: "sdd" as const,
        anodes: { a1: "Rh" as const, a2: "none" as const },
        elements: ["Fe", "Pb", "S"],
    };

    function store(record: unknown, version = 3) {
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({ version, boxes: {}, xrf: record }),
        );
    }

    it("round-trips under version 3 and keeps the rest as stored", () => {
        expect(readXrfSettings()).toBeUndefined();
        writeHidden(["auto:micro"]);
        writeXrfSettings(XRF);
        expect(readXrfSettings()).toEqual(XRF);
        expect(readHidden()).toEqual(["auto:micro"]);
        expect(
            JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY)!),
        ).toMatchObject({ version: 3, xrf: XRF });
        writeXrfSettings(undefined);
        expect(readXrfSettings()).toBeUndefined();
        expect(readHidden()).toEqual(["auto:micro"]);
    });

    it("removes the record when nothing else is stored", () => {
        writeXrfSettings(XRF);
        writeXrfSettings(undefined);
        expect(window.localStorage.getItem(LAYOUT_STORAGE_KEY)).toBeNull();
    });

    it("reads records written without xrf, in version 2 and 3", () => {
        for (const version of [2, 3]) {
            window.localStorage.setItem(
                LAYOUT_STORAGE_KEY,
                JSON.stringify({
                    version,
                    boxes: { "auto:micro": { x: 0, y: 0, w: 6, h: 5 } },
                }),
            );
            expect(readXrfSettings()).toBeUndefined();
            expect(readLayout()["auto:micro"]).toBeDefined();
        }
    });

    it.each([
        ["an unknown detector", { ...XRF, detector: "ge" }],
        ["a non-record", "sdd"],
        ["an anode off the list", { ...XRF, anodes: { a1: "Fe" } }],
        ["an anode that is not a string", { ...XRF, anodes: { a1: 3 } }],
        ["anodes that are an array", { ...XRF, anodes: ["Rh"] }],
        ["a lowercase symbol", { ...XRF, elements: ["fe"] }],
        ["a three-letter symbol", { ...XRF, elements: ["Fee"] }],
        ["a repeated symbol", { ...XRF, elements: ["Fe", "Fe"] }],
        ["elements that are not an array", { ...XRF, elements: "Fe" }],
        ["a symbol that is not a string", { ...XRF, elements: [26] }],
    ])("drops a record with %s", (_, record) => {
        store(record);
        expect(readXrfSettings()).toBeUndefined();
    });

    it("drops a record over its bounds and keeps the layout", () => {
        const many = Object.fromEntries(
            Array.from({ length: 201 }, (_, index) => [`a${index}`, "Rh"]),
        );
        store({ ...XRF, anodes: many });
        expect(readXrfSettings()).toBeUndefined();
        const symbols = Array.from({ length: 31 }, (_, index) =>
            `A${String.fromCharCode(97 + (index % 26))}`.replace(
                /^A(.)$/,
                index < 26 ? "A$1" : "B$1",
            ),
        );
        store({ ...XRF, elements: symbols });
        expect(readXrfSettings()).toBeUndefined();
        const fine = Object.fromEntries(
            Array.from({ length: 200 }, (_, index) => [`a${index}`, "Rh"]),
        );
        store({ ...XRF, anodes: fine });
        expect(Object.keys(readXrfSettings()!.anodes)).toHaveLength(200);
    });

    it("does not let an xrf record disturb the other records", () => {
        writeImaging(undefined);
        store({ detector: "x" });
        expect(readTools()).toEqual([]);
    });
});
