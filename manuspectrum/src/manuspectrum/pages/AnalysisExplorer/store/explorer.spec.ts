import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    emptyFilters,
    hasActiveFilters,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

function uuid(n: number): string {
    return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

function characterization(n: number): string {
    return `ch:${uuid(n)}:-`;
}

beforeEach(() => setActivePinia(createPinia()));

describe("filters", () => {
    it("defaults to the documents grain with only documents that have analyses", () => {
        const store = useExplorerStore();
        expect(store.filters.grain).toBe("documents");
        expect(store.filters.onlyWithAnalyses).toBe(true);
        expect(hasActiveFilters(store.filters)).toBe(false);
    });

    it("sorts and dedupes list values", () => {
        const store = useExplorerStore();
        store.setFilter("technique", ["b", "a", "b"]);
        store.setFilter("year", [2023, 1990, 2023]);
        expect(store.filters.technique).toEqual(["a", "b"]);
        expect(store.filters.year).toEqual([1990, 2023]);
    });

    it("clears one value, one key, or everything but the display options", () => {
        const store = useExplorerStore();
        store.setFilter("technique", ["a", "b"]);
        store.setFilter("q", "lead");
        store.setFilter("grain", "analyses");
        store.setFilter("onlyWithAnalyses", false);
        store.clearFilter("technique", "a");
        expect(store.filters.technique).toEqual(["b"]);
        store.clearFilter("q");
        expect(store.filters.q).toBe("");
        store.clearFilters();
        expect(store.filters).toEqual({
            ...emptyFilters(),
            grain: "analyses",
            onlyWithAnalyses: false,
        });
    });

    it("counts active filters, eventType excluded outside the map", () => {
        const store = useExplorerStore();
        store.setFilter("technique", ["a", "b"]);
        store.setFilter("eventType", ["production"]);
        expect(store.activeFilterCount).toBe(2);
    });
});

describe("navigation", () => {
    it("ignores a view that is not available yet", () => {
        const store = useExplorerStore();
        store.setView("map");
        expect(store.view).toBe("corpus");
    });

    it("opens a document on the corpus view and clears the focus", () => {
        const store = useExplorerStore();
        store.focusOn({ kind: "analysis", id: uuid(1) });
        store.openDocument(uuid(2), "https://iiif.example/canvas/1");
        expect(store.view).toBe("corpus");
        expect(store.corpusScreen).toBe("document");
        expect(store.document).toEqual({
            id: uuid(2),
            canvas: "https://iiif.example/canvas/1",
        });
        expect(store.focus).toBeNull();
    });

    it("leaving the document screen drops the document and the focus", () => {
        const store = useExplorerStore();
        store.openDocument(uuid(2));
        store.focusOn({ kind: "analysis", id: uuid(1) });
        store.setCorpusScreen("results");
        expect(store.document).toBeNull();
        expect(store.focus).toBeNull();
        store.setCorpusScreen("document");
        expect(store.corpusScreen).toBe("results");
    });
});

describe("document screen", () => {
    it("changes the page of the open document only", () => {
        const store = useExplorerStore();
        store.setCanvas("c2");
        expect(store.document).toBeNull();
        store.openDocument(uuid(1));
        store.setCanvas("c2");
        expect(store.document).toEqual({ id: uuid(1), canvas: "c2" });
    });

    it("sets a facet, reading years as integers", () => {
        const store = useExplorerStore();
        store.setFacet("year", ["2023", "x", "2021"]);
        store.setFacet("technique", ["t:b", "t:a"]);
        expect(store.filters.year).toEqual([2021, 2023]);
        expect(store.filters.technique).toEqual(["t:a", "t:b"]);
    });

    it("sets the folio view and resets it when a document opens or the screen changes", () => {
        const store = useExplorerStore();
        expect(store.folioView).toBe("analyses");
        store.openDocument(uuid(1));
        store.setFolioView("samples");
        expect(store.folioView).toBe("samples");
        store.openDocument(uuid(2));
        expect(store.folioView).toBe("analyses");
        store.setFolioView("characterizations");
        store.setCorpusScreen("results");
        expect(store.folioView).toBe("analyses");
    });

    it("shows the folio view of what a focus opens", () => {
        const store = useExplorerStore();
        store.openDocument(uuid(1));
        store.focusOn({ kind: "sample", id: uuid(2) });
        expect(store.folioView).toBe("samples");
        store.focusOn({ kind: "analysis", id: uuid(3) });
        expect(store.folioView).toBe("analyses");
        store.focusOn({ kind: "characterization", id: uuid(4) });
        expect(store.folioView).toBe("characterizations");
        store.focusOn({ kind: "file", id: uuid(5) });
        store.focusOn(null);
        expect(store.folioView).toBe("characterizations");
    });

    it("switches one folio layer", () => {
        const store = useExplorerStore();
        store.setLayer("zones", false);
        expect(store.layers).toEqual({
            points: true,
            zones: false,
            characterizations: true,
        });
    });
});

describe("Selection", () => {
    it("refuses the 31st item and says how many places are left", () => {
        const store = useExplorerStore();
        for (let n = 0; n < BASKET_LIMIT; n += 1) {
            expect(store.addToBasket(characterization(n)).refused).toBeNull();
        }
        expect(store.addToBasket(characterization(99))).toEqual({
            added: [],
            refused: "full",
            needed: 1,
            free: 0,
        });
        expect(store.basket).toHaveLength(BASKET_LIMIT);
    });

    it("adds many items all or nothing", () => {
        const store = useExplorerStore();
        for (let n = 0; n < 26; n += 1) store.addToBasket(characterization(n));
        const seven = Array.from({ length: 7 }, (_, n) =>
            characterization(100 + n),
        );
        expect(store.addManyToBasket(seven)).toEqual({
            added: [],
            refused: "full",
            needed: 7,
            free: 4,
        });
        expect(store.basket).toHaveLength(26);
        expect(store.addManyToBasket(seven.slice(0, 4)).added).toHaveLength(4);
    });

    it("refuses a batch with an invalid key", () => {
        const store = useExplorerStore();
        expect(
            store.addManyToBasket([characterization(1), "nope"]).refused,
        ).toBe("invalid");
        expect(store.basket).toHaveLength(0);
    });

    it("ignores an item already present", () => {
        const store = useExplorerStore();
        store.addToBasket(characterization(1));
        expect(store.addToBasket(characterization(1))).toEqual({
            added: [],
            refused: null,
            needed: 0,
            free: BASKET_LIMIT - 1,
        });
    });

    it("keeps each slot when another item leaves and reuses the lowest one", () => {
        const store = useExplorerStore();
        store.addManyToBasket([
            characterization(1),
            characterization(2),
            characterization(3),
        ]);
        store.removeFromBasket(characterization(2));
        expect(store.basket.map((item) => item.slot)).toEqual([0, 2]);
        store.addToBasket(characterization(4));
        expect(
            store.basket.find((item) => item.key === characterization(4))?.slot,
        ).toBe(1);
    });

    it("replaces with at most 30 items and reports the rest", () => {
        const store = useExplorerStore();
        store.addToBasket(characterization(500));
        const keys = Array.from({ length: 33 }, (_, n) => characterization(n));
        expect(store.replaceBasket(keys)).toEqual({
            kept: keys.slice(0, 30),
            truncated: 3,
        });
        expect(store.basket.map((item) => item.slot)).toEqual([
            ...Array(30).keys(),
        ]);
    });

    it("merges into the free places, keeping existing slots", () => {
        const store = useExplorerStore();
        for (let n = 0; n < 28; n += 1) store.addToBasket(characterization(n));
        const result = store.mergeBasket([
            characterization(0),
            characterization(200),
            characterization(201),
            characterization(202),
        ]);
        expect(result).toEqual({
            kept: [characterization(200), characterization(201)],
            truncated: 1,
        });
        expect(
            store.basket.find((item) => item.key === characterization(0))?.slot,
        ).toBe(0);
    });

    it("clears the Selection", () => {
        const store = useExplorerStore();
        store.addToBasket(characterization(1));
        store.clearBasket();
        expect(store.basket).toEqual([]);
    });
});

describe("Compare state", () => {
    it("opens and closes tools and sets tool filters", () => {
        const store = useExplorerStore();
        const id = store.openTool("periodic", { scope: "basket" });
        expect(store.compare.tools).toEqual([
            { id, kind: "periodic", params: { scope: "basket" } },
        ]);
        store.setToolFilter("element", "Cu");
        expect(store.compare.toolFilters.element).toBe("Cu");
        store.clearToolFilters();
        expect(store.compare.toolFilters).toEqual({
            element: null,
            cell: null,
            pair: null,
        });
        store.closeTool(id);
        expect(store.compare.tools).toEqual([]);
    });

    it("sets and removes an overlay", () => {
        const store = useExplorerStore();
        store.setOverlay("im:x:1", { element: "Pb", opacity: 0.6, on: true });
        expect(store.overlays["im:x:1"].element).toBe("Pb");
        store.setOverlay("im:x:1", null);
        expect(store.overlays).toEqual({});
    });
});
