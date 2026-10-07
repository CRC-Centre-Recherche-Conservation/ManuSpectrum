import { describe, expect, it } from "vitest";

import {
    GALLERY_OPEN_REM,
    GALLERY_REM,
    TAB_REM,
    TABLE_MIN_REM,
    galleryOpensWith,
    galleryPlace,
    isMultiPane,
    shownLayout,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";

const S = { size: "S", enlarged: false, phone: false } as const;
const M = { size: "M", enlarged: false, phone: false } as const;
const L = { size: "L", enlarged: false, phone: false } as const;
const ENLARGED = { size: "M", enlarged: true, phone: false } as const;
const BY_HAND = { size: null, enlarged: false, phone: false } as const;

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

    it("never folds the selected layout at any other size", () => {
        for (const frame of [M, L, ENLARGED, BY_HAND]) {
            for (const layout of [
                "single",
                "curtain",
                "grid2",
                "grid4",
                "stack",
            ] as const) {
                expect(shownLayout(layout, frame)).toBe(layout);
            }
        }
    });

    it("keeps four panes in M and in a window resized by hand", () => {
        expect(shownLayout("grid4", M)).toBe("grid4");
        expect(shownLayout("grid4", BY_HAND)).toBe("grid4");
    });
});

describe("isMultiPane", () => {
    it("is true for the two grids only", () => {
        expect(
            ["single", "curtain", "stack"].map(isMultiPane as never),
        ).toEqual([false, false, false]);
        expect(isMultiPane("grid2")).toBe(true);
        expect(isMultiPane("grid4")).toBe(true);
    });
});

describe("galleryPlace", () => {
    it("puts the gallery to the right of the table at every size, S included", () => {
        for (const frame of [S, M, L, ENLARGED, BY_HAND]) {
            expect(galleryPlace(frame, true)).toBe("right");
        }
    });

    it("hides it when closed", () => {
        expect(galleryPlace(L, false)).toBe("hidden");
        expect(galleryPlace(M, false)).toBe("hidden");
        expect(galleryPlace(S, false)).toBe("hidden");
    });
});

describe("galleryOpensWith", () => {
    it("opens beside the table from the width of the table plus the gallery", () => {
        expect(galleryOpensWith(M, 1, GALLERY_OPEN_REM)).toBe(true);
        expect(galleryOpensWith(M, 1, GALLERY_OPEN_REM - 0.1)).toBe(false);
        expect(galleryOpensWith(L, 1, 30)).toBe(false);
        expect(galleryOpensWith(BY_HAND, 1, 80)).toBe(true);
    });

    it("holds 40 rem for the table", () => {
        expect(GALLERY_OPEN_REM).toBe(TABLE_MIN_REM + GALLERY_REM + 0.5);
        expect(TAB_REM).toBe(1.75);
    });

    it("falls back on the size while the width is not measured", () => {
        expect(galleryOpensWith(L, 1)).toBe(true);
        expect(galleryOpensWith(ENLARGED, 1)).toBe(true);
        expect(galleryOpensWith(M, 9)).toBe(false);
        expect(galleryOpensWith(S, 9)).toBe(false);
    });
});

describe("on a phone", () => {
    const PHONE = { size: "M", enlarged: false, phone: true } as const;
    const PHONE_S = { size: "S", enlarged: false, phone: true } as const;
    const PHONE_ENLARGED = { size: "M", enlarged: true, phone: true } as const;

    it("keeps one pane, the curtain and the stack, and shows one pane for the grids", () => {
        expect(shownLayout("single", PHONE)).toBe("single");
        expect(shownLayout("curtain", PHONE)).toBe("curtain");
        expect(shownLayout("stack", PHONE)).toBe("stack");
        expect(shownLayout("grid2", PHONE)).toBe("single");
        expect(shownLayout("grid4", PHONE_ENLARGED)).toBe("single");
    });

    it("puts the gallery in a strip under the table, enlarged or not, and none in S", () => {
        expect(galleryPlace(PHONE, true)).toBe("strip");
        expect(galleryPlace(PHONE_ENLARGED, true)).toBe("strip");
        expect(galleryPlace(PHONE, false)).toBe("hidden");
        expect(galleryPlace(PHONE_S, true)).toBe("hidden");
    });

    it("opens the strip as before: enlarged, folded in M, never in S", () => {
        expect(galleryOpensWith(PHONE_ENLARGED, 1)).toBe(true);
        expect(galleryOpensWith(PHONE, 1)).toBe(false);
        expect(galleryOpensWith(PHONE, 5)).toBe(true);
        expect(galleryOpensWith(PHONE_S, 9)).toBe(false);
    });
});
