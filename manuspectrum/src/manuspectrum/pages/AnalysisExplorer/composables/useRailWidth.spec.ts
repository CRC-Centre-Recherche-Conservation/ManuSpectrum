import { readFileSync } from "node:fs";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
    RAIL_STORAGE_KEY,
    useRailWidth,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useRailWidth.ts";

afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
});

describe("useRailWidth", () => {
    it("starts at the default width when nothing is stored", () => {
        expect(useRailWidth().wide.value).toBe(false);
    });

    it("reads the wide mode stored by this browser", () => {
        window.localStorage.setItem(RAIL_STORAGE_KEY, "wide");
        expect(useRailWidth().wide.value).toBe(true);
    });

    it("reads any other stored value as the default", () => {
        for (const stored of ["320", '{"width":26}', "true", ""]) {
            window.localStorage.setItem(RAIL_STORAGE_KEY, stored);
            expect(useRailWidth().wide.value).toBe(false);
        }
    });

    it("stores the wide mode and forgets it when narrowed again", () => {
        const rail = useRailWidth();
        rail.toggleWide();
        expect(rail.wide.value).toBe(true);
        expect(window.localStorage.getItem(RAIL_STORAGE_KEY)).toBe("wide");
        rail.toggleWide();
        expect(rail.wide.value).toBe(false);
        expect(window.localStorage.getItem(RAIL_STORAGE_KEY)).toBeNull();
    });

    it("keeps the choice for the tab when the storage is blocked", () => {
        const blocked = () => {
            throw new DOMException("blocked", "SecurityError");
        };
        vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked);
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
        const rail = useRailWidth();
        expect(() => rail.toggleWide()).not.toThrow();
        expect(rail.wide.value).toBe(true);
    });
});

describe("rail width tokens", () => {
    const read = (path: string) => readFileSync(`${__dirname}/${path}`, "utf8");

    it("widen the default column with the screen and offer a wide one", () => {
        const scss = read("../../../../../media/css/explorer.scss");
        expect(scss).toMatch(/--explorer-rail: 18rem;/);
        expect(scss).toMatch(
            /@media \(min-width: 100rem\) \{\s*--explorer-rail: 20rem;/,
        );
        expect(scss).toMatch(/--explorer-rail-wide: 26rem;/);
        expect(scss).toMatch(
            /\.analysis-explorer\.is-rail-wide \{\s*--explorer-rail-chosen: var\(--explorer-rail-wide\);/,
        );
        expect(scss).toMatch(
            /\.explorer-rail-drawer \{\s*inline-size: min\(26rem, calc\(100% - 3rem\)\);/,
        );
    });

    it("keep the content minimum of each view", () => {
        const scss = read("../../../../../media/css/explorer.scss");
        expect(scss).toContain("100% - 1.5rem - 36rem");
        expect(scss).toContain("100% - var(--explorer-side) - 2rem - 32rem");
        for (const [view, track] of [
            ["../views/Corpus/CorpusResults.vue", "--explorer-rail-track,"],
            [
                "../views/Corpus/CorpusDocument.vue",
                "--explorer-rail-track-staged,",
            ],
            ["../views/Map/MapView.vue", "--explorer-rail-track-staged,"],
        ]) {
            expect(read(view), view).toContain(`var(${track}`);
        }
    });
});
