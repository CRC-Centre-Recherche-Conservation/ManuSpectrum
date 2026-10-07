import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    emptyFilters,
    hasActiveFilters,
    LIST_FILTER_KEYS,
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
    it("defaults to the documents grain, ten per page, without the documents that have no analysis", () => {
        const store = useExplorerStore();
        expect(store.filters.grain).toBe("documents");
        expect(store.filters.empty).toBe(false);
        expect(store.filters.size).toBe(10);
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
        store.setFilter("empty", true);
        store.setFilter("size", 50);
        store.clearFilter("technique", "a");
        expect(store.filters.technique).toEqual(["b"]);
        store.clearFilter("q");
        expect(store.filters.q).toBe("");
        store.clearFilters();
        expect(store.filters).toEqual({
            ...emptyFilters(),
            grain: "analyses",
            empty: true,
            size: 50,
        });
    });

    it("counts active filters, eventType excluded outside the map", () => {
        const store = useExplorerStore();
        store.setFilter("technique", ["a", "b"]);
        store.setFilter("eventType", ["production"]);
        expect(store.activeFilterCount).toBe(2);
    });

    it("holds the places as a sorted list and counts each of them", () => {
        const store = useExplorerStore();
        expect(store.filters.place).toEqual([]);
        store.setFilter("place", ["b", "a", "b"]);
        expect(store.filters.place).toEqual(["a", "b"]);
        expect(store.activeFilterCount).toBe(2);
        store.clearFilter("place", "a");
        expect(store.filters.place).toEqual(["b"]);
        store.clearFilters();
        expect(store.filters.place).toEqual([]);
    });
});

describe("colour filters", () => {
    it("holds one colour list, a scope defaulting to everywhere, and no part colour", () => {
        const store = useExplorerStore();
        expect(store.filters.colourScope).toBe("all");
        expect("partColour" in store.filters).toBe(false);
        expect(LIST_FILTER_KEYS).not.toContain("partColour");
        expect(LIST_FILTER_KEYS).toContain("colour");
        expect("colourLevel" in store).toBe(false);
        expect("setColourLevel" in store).toBe(false);
    });

    it("does not count the scope as a filter, and resets it with the others", () => {
        const store = useExplorerStore();
        store.setFilter("colourScope", "part");
        expect(store.activeFilterCount).toBe(0);
        expect(hasActiveFilters(store.filters)).toBe(false);
        store.setFilter("colour", ["c1"]);
        expect(store.activeFilterCount).toBe(1);
        store.clearFilters();
        expect(store.filters.colourScope).toBe("all");
        store.setFilter("colourScope", "material");
        store.clearFilter("colourScope");
        expect(store.filters.colourScope).toBe("all");
    });

    it("keeps the scope from the facet ticks, which only set the colour list", () => {
        const store = useExplorerStore();
        store.setFilter("colourScope", "part");
        store.setFacet("colour", ["c2", "c1"]);
        expect(store.filters.colour).toEqual(["c1", "c2"]);
        expect(store.filters.colourScope).toBe("part");
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

    it("removes several keys in one assignment, keeps the holes and returns the removed items with their slots", () => {
        const store = useExplorerStore();
        for (let n = 0; n < 5; n += 1) store.addToBasket(characterization(n));
        const before = store.basket;
        const removed = store.removeManyFromBasket([
            characterization(1),
            characterization(3),
            characterization(99),
        ]);
        expect(removed.map((item) => [item.key, item.slot])).toEqual([
            [characterization(1), 1],
            [characterization(3), 3],
        ]);
        expect(store.basket.map((item) => item.slot)).toEqual([0, 2, 4]);
        expect(store.basket).not.toBe(before);
    });

    it("leaves the basket object alone when no key is held", () => {
        const store = useExplorerStore();
        store.addToBasket(characterization(1));
        const before = store.basket;
        expect(store.removeManyFromBasket([characterization(9)])).toEqual([]);
        expect(store.basket).toBe(before);
    });

    it("restores removed items at their own slots", () => {
        const store = useExplorerStore();
        for (let n = 0; n < 5; n += 1) store.addToBasket(characterization(n));
        const removed = store.removeManyFromBasket([
            characterization(1),
            characterization(3),
        ]);
        const result = store.restoreBasketItems(removed);
        expect(result).toEqual({
            kept: [characterization(1), characterization(3)],
            truncated: 0,
        });
        expect(
            store.basket.map((item) => [item.key, item.slot]).sort(),
        ).toEqual([0, 1, 2, 3, 4].map((n) => [characterization(n), n]).sort());
    });

    it("restores into the lowest hole when the slot was taken meanwhile", () => {
        const store = useExplorerStore();
        for (let n = 0; n < 3; n += 1) store.addToBasket(characterization(n));
        const removed = store.removeManyFromBasket([characterization(0)]);
        store.addToBasket(characterization(50));
        expect(
            store.basket.find((item) => item.key === characterization(50))
                ?.slot,
        ).toBe(0);
        store.restoreBasketItems(removed);
        expect(
            store.basket.find((item) => item.key === characterization(0))?.slot,
        ).toBe(3);
    });

    it("skips items already held when restoring and truncates beyond 30", () => {
        const store = useExplorerStore();
        for (let n = 0; n < 29; n += 1) store.addToBasket(characterization(n));
        const removed = store.removeManyFromBasket([characterization(5)]);
        store.addToBasket(characterization(60));
        const result = store.restoreBasketItems([
            ...removed,
            { key: characterization(70), kind: "characterization", slot: 31 },
            { key: characterization(60), kind: "characterization", slot: 0 },
        ]);
        expect(result).toEqual({
            kept: [characterization(5)],
            truncated: 1,
        });
        expect(store.basket).toHaveLength(30);
    });

    it("clears the Selection", () => {
        const store = useExplorerStore();
        store.addToBasket(characterization(1));
        store.clearBasket();
        expect(store.basket).toEqual([]);
    });
});

describe("Compare state", () => {
    it("opens and closes tools", () => {
        const store = useExplorerStore();
        const id = store.openTool("periodic", { scope: "basket" });
        expect(store.compare.tools).toEqual([
            { id, kind: "periodic", params: { scope: "basket" } },
        ]);
        store.closeTool(id);
        expect(store.compare.tools).toEqual([]);
    });

    it("adds a node to the linked selection or removes it, and clears it", () => {
        const store = useExplorerStore();
        store.toggleSelection("el:Fe");
        store.toggleSelection("el:Cu");
        expect(store.compare.selection).toEqual(["el:Fe", "el:Cu"]);
        store.toggleSelection("el:Fe");
        expect(store.compare.selection).toEqual([null, "el:Cu"]);
        store.clearSelection();
        expect(store.compare.selection).toEqual([]);
    });

    it("pins in the lowest free slot and never renumbers the others", () => {
        const store = useExplorerStore();
        store.toggleSelection("el:Fe");
        store.toggleSelection("el:Cu");
        store.toggleSelection("el:Pb");
        store.toggleSelection("el:Cu");
        expect(store.compare.selection).toEqual(["el:Fe", null, "el:Pb"]);
        store.toggleSelection("el:Hg");
        expect(store.compare.selection).toEqual(["el:Fe", "el:Hg", "el:Pb"]);
        store.toggleSelection("el:Fe");
        store.toggleSelection("el:Pb");
        expect(store.compare.selection).toEqual([null, "el:Hg"]);
        store.toggleSelection("el:Hg");
        expect(store.compare.selection).toEqual([]);
    });

    it("refuses a fifth pin and refills a hole left by an unpin", () => {
        const store = useExplorerStore();
        for (const id of ["el:Fe", "el:Cu", "el:Pb", "el:Hg"]) {
            store.toggleSelection(id);
        }
        const full = store.compare;
        store.toggleSelection("el:Au");
        expect(store.compare).toBe(full);
        expect(store.compare.selection).toEqual([
            "el:Fe",
            "el:Cu",
            "el:Pb",
            "el:Hg",
        ]);
        store.toggleSelection("el:Cu");
        store.toggleSelection("el:Au");
        expect(store.compare.selection).toEqual([
            "el:Fe",
            "el:Au",
            "el:Pb",
            "el:Hg",
        ]);
    });

    it("holds the focus mode and resets it with the focus", () => {
        const store = useExplorerStore();
        expect(store.compare.mode).toBe("any");
        store.toggleSelection("el:Fe");
        store.setFocusMode("all");
        expect(store.compare.mode).toBe("all");
        store.clearSelection();
        expect(store.compare.mode).toBe("any");
    });

    it("prunes the selected nodes a test refuses and says which", () => {
        const store = useExplorerStore();
        store.toggleSelection("el:Fe");
        store.toggleSelection("el:Cu");
        expect(store.pruneSelection((id) => id !== "el:Fe")).toEqual(["el:Fe"]);
        expect(store.compare.selection).toEqual([null, "el:Cu"]);
        const kept = store.compare.selection;
        expect(store.pruneSelection(() => true)).toEqual([]);
        expect(store.compare.selection).toBe(kept);
    });

    it("names a tool by its kind and parameters and opens it once", () => {
        const store = useExplorerStore();
        const id = store.openTool("periodic", { scope: "basket", cell: "a b" });
        expect(id).toBe("tool:periodic:cell=a%20b&scope=basket");
        expect(
            store.openTool("periodic", { cell: "a b", scope: "basket" }),
        ).toBe(id);
        expect(store.compare.tools).toHaveLength(1);
        expect(store.openTool("coverage")).toBe("tool:coverage:-");
        expect(store.compare.tools.map((tool) => tool.id)).toEqual([
            id,
            "tool:coverage:-",
        ]);
    });

    it("sets and removes an overlay", () => {
        const store = useExplorerStore();
        store.setOverlay("im:x:1", { element: "Pb", opacity: 0.6, on: true });
        expect(store.overlays["im:x:1"].element).toBe("Pb");
        store.setOverlay("im:x:1", null);
        expect(store.overlays).toEqual({});
    });

    it("hides and shows an XY window's curve with the eye, one window at a time", () => {
        const store = useExplorerStore();
        store.toggleCurveVisibility("auto:xy:a", "an:1:-|f1");
        store.toggleCurveVisibility("auto:xy:a", "an:1:-|f2");
        store.toggleCurveVisibility("auto:xy:b", "an:2:-|f3");
        expect(store.hiddenCurves).toEqual({
            "auto:xy:a": ["an:1:-|f1", "an:1:-|f2"],
            "auto:xy:b": ["an:2:-|f3"],
        });
        store.toggleCurveVisibility("auto:xy:a", "an:1:-|f1");
        expect(store.hiddenCurves["auto:xy:a"]).toEqual(["an:1:-|f2"]);
    });

    it("shows every curve of one window the eye hid, leaving the others", () => {
        const store = useExplorerStore();
        store.toggleCurveVisibility("auto:xy:a", "an:1:-|f1");
        store.toggleCurveVisibility("auto:xy:b", "an:2:-|f3");
        store.showAllCurves("auto:xy:a");
        expect(store.hiddenCurves).toEqual({ "auto:xy:b": ["an:2:-|f3"] });
        expect(() => store.showAllCurves("auto:xy:a")).not.toThrow();
    });

    it("drops a window's eye-hidden ids a curve leaving it refuses, removing an empty window", () => {
        const store = useExplorerStore();
        store.toggleCurveVisibility("auto:xy:a", "an:1:-|f1");
        store.toggleCurveVisibility("auto:xy:a", "an:1:-|f2");
        store.pruneHiddenCurves("auto:xy:a", (id) => id === "an:1:-|f1");
        expect(store.hiddenCurves).toEqual({ "auto:xy:a": ["an:1:-|f1"] });
        store.pruneHiddenCurves("auto:xy:a", () => false);
        expect(store.hiddenCurves).toEqual({});
    });
});
