import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import {
    emptyFilters,
    useExplorerStore,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    applySnapshot,
    documentHref,
    fromQuery,
    historyMode,
    snapshotOf,
    toQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

import type { UrlSnapshot } from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";

const DOC = "0b3c6f4e-6a39-4e3c-9f7e-1d2c3b4a5f60";
const ANALYSIS = "7d1e2f3a-4b5c-4d6e-8f70-819203a4b5c6";

function home(): UrlSnapshot {
    return {
        view: "corpus",
        corpusScreen: "home",
        document: null,
        focus: null,
        folioView: "analyses",
        outside: true,
        filters: emptyFilters(),
    };
}

beforeEach(() => setActivePinia(createPinia()));

describe("toQuery / fromQuery", () => {
    it("serializes in a stable order and parses back to the same snapshot", () => {
        const snapshot: UrlSnapshot = {
            ...home(),
            corpusScreen: "results",
            filters: {
                ...emptyFilters(),
                q: "lead white",
                grain: "analyses",
                size: 25,
                empty: true,
                technique: ["http://x/xrf", "http://x/raman"].sort(),
                year: [2021, 2023],
                period: [1000, 1200],
            },
        };
        const query = toQuery(snapshot);
        expect(query.toString()).toBe(
            "screen=results&q=lead+white&grain=analyses&size=25&empty=1" +
                "&technique=http%3A%2F%2Fx%2Framan&technique=http%3A%2F%2Fx%2Fxrf&year=2021&year=2023&period=1000%2C1200",
        );
        expect(fromQuery(query)).toEqual(snapshot);
    });

    it("reads the period options, writes them only when they are not the defaults", () => {
        const snapshot = fromQuery(
            new URLSearchParams(
                "period=1300,1400&periodMatch=within&periodEvent=modification&undated=1",
            ),
        );
        expect(snapshot.filters).toMatchObject({
            period: [1300, 1400],
            periodMatch: "within",
            periodEvent: "modification",
            undated: true,
        });
        expect(toQuery(snapshot).toString()).toBe(
            "screen=results&period=1300%2C1400&periodMatch=within&periodEvent=modification&undated=1",
        );
        for (const raw of [
            "periodMatch=overlap&periodEvent=production&undated=0",
            "periodMatch=bogus&periodEvent=bogus&undated=no",
            "",
        ]) {
            const plain = fromQuery(new URLSearchParams(raw));
            expect(plain.filters).toMatchObject({
                periodMatch: "overlap",
                periodEvent: "production",
                undated: false,
            });
            expect(toQuery(plain).toString()).not.toMatch(
                /periodMatch|periodEvent|undated/,
            );
        }
        expect(
            fromQuery(new URLSearchParams("undated=true")).filters.undated,
        ).toBe(true);
    });

    it("reads only a page size the search offers, 10 by default", () => {
        expect(fromQuery(new URLSearchParams("size=50")).filters.size).toBe(50);
        expect(fromQuery(new URLSearchParams("size=7")).filters.size).toBe(10);
        expect(fromQuery(new URLSearchParams("")).filters.size).toBe(10);
        expect(
            toQuery({
                ...home(),
                corpusScreen: "results",
                filters: { ...emptyFilters(), size: 10 },
            }).toString(),
        ).toBe("screen=results");
    });

    it("writes nothing for the home screen", () => {
        expect(toQuery(home()).toString()).toBe("");
    });

    it("lands a homepage deep link with a query on the results", () => {
        expect(fromQuery(new URLSearchParams("q=XRF")).corpusScreen).toBe(
            "results",
        );
        expect(fromQuery(new URLSearchParams("")).corpusScreen).toBe("home");
    });

    it("opens a document from doc, canvas and focus", () => {
        const snapshot = fromQuery(
            new URLSearchParams(
                `doc=${DOC}&canvas=https%3A%2F%2Fiiif.example%2Fc1&focus=analysis:${ANALYSIS}`,
            ),
        );
        expect(snapshot.corpusScreen).toBe("document");
        expect(snapshot.document).toEqual({
            id: DOC,
            canvas: "https://iiif.example/c1",
        });
        expect(snapshot.focus).toEqual({ kind: "analysis", id: ANALYSIS });
    });

    it("reads the folio view of a document and omits the default one", () => {
        const snapshot = fromQuery(
            new URLSearchParams(
                `doc=${DOC}&fview=samples&focus=sample:${ANALYSIS}`,
            ),
        );
        expect(snapshot.folioView).toBe("samples");
        expect(snapshot.focus).toEqual({ kind: "sample", id: ANALYSIS });
        expect(toQuery(snapshot).get("fview")).toBe("samples");
        expect(
            toQuery({ ...snapshot, folioView: "analyses" }).has("fview"),
        ).toBe(false);
        expect(
            fromQuery(new URLSearchParams(`doc=${DOC}&fview=nowhere`))
                .folioView,
        ).toBe("analyses");
        expect(fromQuery(new URLSearchParams("fview=samples")).folioView).toBe(
            "analyses",
        );
    });

    it("writes outside=hide for a document and reads absent as shown", () => {
        const hidden = fromQuery(
            new URLSearchParams(`doc=${DOC}&outside=hide`),
        );
        expect(hidden.outside).toBe(false);
        expect(toQuery(hidden).get("outside")).toBe("hide");
        const shown = fromQuery(new URLSearchParams(`doc=${DOC}`));
        expect(shown.outside).toBe(true);
        expect(toQuery(shown).has("outside")).toBe(false);
        expect(
            fromQuery(new URLSearchParams(`doc=${DOC}&outside=show`)).outside,
        ).toBe(true);
        expect(fromQuery(new URLSearchParams("outside=hide")).outside).toBe(
            true,
        );
        expect(toQuery({ ...home(), outside: false }).has("outside")).toBe(
            false,
        );
    });

    it("drops malformed values", () => {
        const snapshot = fromQuery(
            new URLSearchParams(
                `doc=not-a-uuid&focus=bogus:${ANALYSIS}&year=abc&year=1990&period=1200,1000&eventType=party&view=nowhere&q=${"x".repeat(300)}`,
            ),
        );
        expect(snapshot.document).toBeNull();
        expect(snapshot.focus).toBeNull();
        expect(snapshot.filters.year).toEqual([1990]);
        expect(snapshot.filters.period).toBeNull();
        expect(snapshot.filters.eventType).toEqual([]);
        expect(snapshot.view).toBe("corpus");
        expect(snapshot.filters.q).toHaveLength(200);
    });

    it("accepts an uppercase doc id and normalizes it to lowercase", () => {
        const snapshot = fromQuery(
            new URLSearchParams(`doc=${DOC.toUpperCase()}`),
        );
        expect(snapshot.document).toEqual({ id: DOC, canvas: null });
    });

    it("rejects a right-shaped id whose version nibble is not a recognized UUID version", () => {
        // "9" is not a UUID version (uuid's validate() accepts 1-8): right shape, still rejected.
        const badVersion = "0b3c6f4e-6a39-9e3c-9f7e-1d2c3b4a5f60";
        expect(
            fromQuery(new URLSearchParams(`doc=${badVersion}`)).document,
        ).toBeNull();
    });

    it("accepts comma-separated lists like the API", () => {
        expect(
            fromQuery(new URLSearchParams("part=b,a&part=c")).filters.part,
        ).toEqual(["a", "b", "c"]);
    });

    it("builds a document link that keeps the filters", () => {
        const snapshot: UrlSnapshot = {
            ...home(),
            corpusScreen: "results",
            filters: { ...emptyFilters(), q: "gold" },
        };
        expect(documentHref(snapshot, DOC)).toBe(`?doc=${DOC}&q=gold`);
        expect(documentHref({ ...snapshot, folioView: "samples" }, DOC)).toBe(
            `?doc=${DOC}&q=gold`,
        );
    });

    it("opens a document on a folio, focused on a record in the folio view that draws it", () => {
        const snapshot = { ...home(), view: "compare" as const };
        const href = documentHref(snapshot, DOC, "https://iiif.example/c1", {
            kind: "characterization",
            id: ANALYSIS,
        });
        const back = fromQuery(new URLSearchParams(href.slice(1)));
        expect(back.view).toBe("corpus");
        expect(back.document).toEqual({
            id: DOC,
            canvas: "https://iiif.example/c1",
        });
        expect(back.focus).toEqual({ kind: "characterization", id: ANALYSIS });
        expect(back.folioView).toBe("characterizations");
    });
});

describe("colour in the address", () => {
    it("reads the legacy partColour into colour and never writes it back", () => {
        const snapshot = fromQuery(
            new URLSearchParams("partColour=b&colour=a&partColour=a"),
        );
        expect(snapshot.filters.colour).toEqual(["a", "b"]);
        expect(toQuery(snapshot).toString()).toBe(
            "screen=results&colour=a&colour=b",
        );
    });

    it("ignores an old colourScope and drops it from the canonical address", () => {
        for (const raw of [
            "colourScope=part",
            "colourScope=material",
            "colourScope=all",
        ]) {
            const snapshot = fromQuery(new URLSearchParams(raw));
            expect("colourScope" in snapshot.filters).toBe(false);
            expect(snapshot.corpusScreen).toBe("home");
            expect(toQuery(snapshot).toString()).toBe("");
            expect(documentHref(snapshot, DOC)).toBe(`?doc=${DOC}`);
        }
        const coloured = fromQuery(
            new URLSearchParams("colour=a&colourScope=part"),
        );
        expect(toQuery(coloured).toString()).toBe("screen=results&colour=a");
    });
});

describe("historyMode", () => {
    it("historyMode pushes on screen, view, document and first focus, replaces otherwise", () => {
        const start = home();
        const results = { ...start, corpusScreen: "results" as const };
        const filtered = {
            ...results,
            filters: { ...results.filters, q: "lead" },
        };
        const opened = {
            ...results,
            corpusScreen: "document" as const,
            document: { id: DOC, canvas: null },
        };
        const focused = {
            ...opened,
            focus: { kind: "analysis" as const, id: ANALYSIS },
        };
        const refocused = {
            ...opened,
            focus: { kind: "analysis" as const, id: DOC },
        };
        expect(historyMode(start, start)).toBe("none");
        expect(historyMode(start, results)).toBe("push");
        expect(historyMode(results, filtered)).toBe("replace");
        expect(historyMode(results, opened)).toBe("push");
        expect(historyMode(opened, focused)).toBe("push");
        expect(historyMode(focused, refocused)).toBe("replace");
        expect(historyMode(focused, opened)).toBe("replace");
        expect(
            historyMode(opened, {
                ...opened,
                document: { id: DOC, canvas: "c2" },
            }),
        ).toBe("replace");
        expect(
            historyMode(opened, { ...opened, folioView: "characterizations" }),
        ).toBe("replace");
    });
});

describe("store round trip", () => {
    it("applies a snapshot and reads it back, keeping an unavailable view on corpus", () => {
        const store = useExplorerStore();
        const snapshot = fromQuery(
            new URLSearchParams(`view=map&doc=${DOC}&technique=t1`),
        );
        applySnapshot(store, snapshot);
        expect(store.view).toBe("corpus");
        expect(store.document?.id).toBe(DOC);
        expect(snapshotOf(store)).toEqual({ ...snapshot, view: "corpus" });
    });

    it("applies and reads back the outside state", () => {
        const store = useExplorerStore();
        applySnapshot(
            store,
            fromQuery(new URLSearchParams(`doc=${DOC}&outside=hide`)),
        );
        expect(store.showOutside).toBe(false);
        expect(snapshotOf(store).outside).toBe(false);
        applySnapshot(store, fromQuery(new URLSearchParams(`doc=${DOC}`)));
        expect(store.showOutside).toBe(true);
    });

    it("returning home from filtered results writes a URL that reads back as home, without filters", () => {
        const store = useExplorerStore();
        store.setFilter("grain", "analyses");
        store.setFilter("technique", ["http://x/xrf"]);
        store.setCorpusScreen("results");
        store.setCorpusScreen("home");
        const snapshot = fromQuery(toQuery(snapshotOf(store)));
        expect(snapshot.corpusScreen).toBe("home");
        expect(snapshot.filters).toEqual({
            ...emptyFilters(),
            grain: "analyses",
        });
    });

    it("applies the folio view of a snapshot and reads it back", () => {
        const store = useExplorerStore();
        const snapshot = fromQuery(
            new URLSearchParams(`doc=${DOC}&fview=characterizations`),
        );
        applySnapshot(store, snapshot);
        expect(store.folioView).toBe("characterizations");
        expect(snapshotOf(store)).toEqual(snapshot);
    });

    it("records where a document screen was entered from", () => {
        const store = useExplorerStore();
        applySnapshot(store, fromQuery(new URLSearchParams(`doc=${DOC}`)));
        expect(store.documentOrigin).toBe("home");
        applySnapshot(store, fromQuery(new URLSearchParams("screen=results")));
        applySnapshot(store, fromQuery(new URLSearchParams(`doc=${DOC}`)));
        expect(store.documentOrigin).toBe("results");
    });
    it("opens the folio view of a focused sample or identified material when the address names none", () => {
        const sample = fromQuery(
            new URLSearchParams(`doc=${DOC}&focus=sample:${DOC}`),
        );
        const material = fromQuery(
            new URLSearchParams(`doc=${DOC}&focus=characterization:${DOC}`),
        );
        const chosen = fromQuery(
            new URLSearchParams(
                `doc=${DOC}&focus=sample:${DOC}&fview=analyses`,
            ),
        );
        expect(sample.folioView).toBe("samples");
        expect(material.folioView).toBe("characterizations");
        expect(chosen.folioView).toBe("analyses");
    });
});

describe("place in the address", () => {
    it("reads place as a list, an old single value as a list of one", () => {
        expect(
            fromQuery(new URLSearchParams("place=p1")).filters.place,
        ).toEqual(["p1"]);
        const several = fromQuery(
            new URLSearchParams("place=p2&place=p1&place=p2"),
        );
        expect(several.filters.place).toEqual(["p1", "p2"]);
        expect(several.corpusScreen).toBe("results");
    });

    it("writes one place parameter per place, sorted, and nothing without any", () => {
        const snapshot = fromQuery(new URLSearchParams("place=p2&place=p1"));
        expect(toQuery(snapshot).toString()).toBe(
            "screen=results&place=p1&place=p2",
        );
        expect(toQuery(fromQuery(new URLSearchParams(""))).toString()).toBe("");
    });
});
