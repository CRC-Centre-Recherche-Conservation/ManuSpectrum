import { afterEach, describe, expect, it } from "vitest";

import {
    LAYOUT_STORAGE_KEY,
    clearLayout,
    flowLayout,
    forgetWindows,
    keepWindows,
    parseLayout,
    readFolded,
    readHidden,
    readLayout,
    readingOrder,
    sizeOf,
    writeFolded,
    writeHidden,
    writeLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

afterEach(() => window.localStorage.clear());

describe("Compare window layout", () => {
    it("is stored under its own key and read back", () => {
        writeLayout({ "auto:micro": { x: 0, y: 0, w: 6, h: 5 } });
        expect(
            JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY)!),
        ).toEqual({
            version: 2,
            boxes: { "auto:micro": { x: 0, y: 0, w: 6, h: 5 } },
            hidden: [],
            folded: {},
        });
        expect(readLayout()).toEqual({
            "auto:micro": { x: 0, y: 0, w: 6, h: 5 },
        });
        clearLayout();
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
        clearLayout();
        expect(readHidden()).toEqual([]);
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

    it("names the size a box has, if it is one of S, M, L", () => {
        expect(sizeOf({ w: 4, h: 4 })).toBe("S");
        expect(sizeOf({ w: 6, h: 5 })).toBe("M");
        expect(sizeOf({ w: 12, h: 6 })).toBe("L");
        expect(sizeOf({ w: 7, h: 5 })).toBeNull();
        expect(sizeOf({ w: 1, h: 6 }, 1)).toBe("L");
        expect(sizeOf({ w: 1, h: 4 }, 1)).toBe("S");
    });
});
