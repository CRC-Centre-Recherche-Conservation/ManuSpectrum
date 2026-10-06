import { describe, expect, it } from "vitest";

import {
    galleryOpensWith,
    galleryPlace,
    shownLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";

const S = { size: "S", enlarged: false } as const;
const M = { size: "M", enlarged: false } as const;
const L = { size: "L", enlarged: false } as const;
const ENLARGED = { size: "M", enlarged: true } as const;
const BY_HAND = { size: null, enlarged: false } as const;

describe("shownLayout", () => {
    it("forces one pane in S, whatever the layout", () => {
        for (const layout of [
            "single",
            "curtain",
            "grid2",
            "grid4",
            "stack",
        ] as const) {
            expect(shownLayout(layout, S)).toBe("single");
        }
    });

    it("folds four panes to two in M and keeps every other layout", () => {
        expect(shownLayout("grid4", M)).toBe("grid2");
        expect(shownLayout("curtain", M)).toBe("curtain");
        expect(shownLayout("stack", M)).toBe("stack");
    });

    it("keeps four panes in L and enlarged", () => {
        expect(shownLayout("grid4", L)).toBe("grid4");
        expect(shownLayout("grid4", ENLARGED)).toBe("grid4");
    });

    it("reads a window resized by hand as M", () => {
        expect(shownLayout("grid4", BY_HAND)).toBe("grid2");
    });
});

describe("galleryPlace", () => {
    it("hides the gallery in S, open or not", () => {
        expect(galleryPlace(S, true)).toBe("hidden");
    });

    it("puts it below the table in M and to the right in L and enlarged", () => {
        expect(galleryPlace(M, true)).toBe("below");
        expect(galleryPlace(L, true)).toBe("right");
        expect(galleryPlace(ENLARGED, true)).toBe("right");
    });

    it("hides it when closed", () => {
        expect(galleryPlace(L, false)).toBe("hidden");
        expect(galleryPlace(M, false)).toBe("hidden");
    });
});

describe("galleryOpensWith", () => {
    it("opens for L and enlarged, folded in M, never in S", () => {
        expect(galleryOpensWith(L, 1)).toBe(true);
        expect(galleryOpensWith(ENLARGED, 1)).toBe(true);
        expect(galleryOpensWith(M, 1)).toBe(false);
        expect(galleryOpensWith(S, 9)).toBe(false);
    });

    it("opens in M for more analyses than panes", () => {
        expect(galleryOpensWith(M, 4)).toBe(false);
        expect(galleryOpensWith(M, 5)).toBe(true);
    });
});
