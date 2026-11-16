import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { defineComponent, nextTick } from "vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    applySnapshot,
    fromQuery,
    historyMode,
    snapshotOf,
    toQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { useUrlState } from "@/manuspectrum/public/useUrlState.ts";

const TARGET = {
    document: uuid(1),
    canvas: "https://iiif.example/c2",
    focus: { kind: "analysis", id: uuid(101) },
} as const;

const OTHER = {
    document: uuid(2),
    canvas: null,
    focus: { kind: "analysis", id: uuid(102) },
} as const;

/** The wiring of `AnalysisExplorer.vue`; `keepOrigin` off leaves the entry state out. */
const wiring = { keepOrigin: true };

const Harness = defineComponent({
    setup() {
        const store = useExplorerStore();
        useUrlState({
            snapshot: () => snapshotOf(store),
            toQuery,
            apply: (query, entry) =>
                applySnapshot(
                    store,
                    fromQuery(query),
                    wiring.keepOrigin ? entry : undefined,
                ),
            entryState: () =>
                wiring.keepOrigin
                    ? { documentOrigin: store.documentOrigin }
                    : null,
            historyMode,
        });
        return () => null;
    },
});

function popped(): Promise<void> {
    return new Promise((resolve) =>
        window.addEventListener("popstate", () => resolve(), { once: true }),
    );
}

async function back(): Promise<void> {
    const arrived = popped();
    window.history.back();
    await arrived;
    await nextTick();
}

let wrapper: ReturnType<typeof mount>;

beforeEach(() => {
    wiring.keepOrigin = true;
    window.history.replaceState(null, "", "/en/discover?view=compare");
    setActivePinia(createPinia());
    wrapper = mount(Harness);
});

afterEach(() => wrapper.unmount());

describe("opening a Selection item in its document", () => {
    it("adds one history entry, and Back restores Compare", async () => {
        const store = useExplorerStore();
        const before = window.history.length;
        store.openInDocument(TARGET);
        await nextTick();
        expect(window.history.length).toBe(before + 1);
        const query = new URLSearchParams(window.location.search);
        expect(query.get("doc")).toBe(TARGET.document);
        expect(query.get("canvas")).toBe(TARGET.canvas);
        expect(query.get("focus")).toBe(`analysis:${uuid(101)}`);
        expect(query.get("view")).toBeNull();

        await back();
        expect(store.view).toBe("compare");
        expect(store.document).toBeNull();
        expect(store.focus).toBeNull();
    });

    it("keeps the document on the same page when the card closes, with no entry, and Back still restores Compare", async () => {
        const store = useExplorerStore();
        store.openInDocument(TARGET);
        await nextTick();
        const opened = window.history.length;

        store.focusOn(null);
        await nextTick();
        expect(window.history.length).toBe(opened);
        expect(store.corpusScreen).toBe("document");
        expect(store.document).toEqual({
            id: TARGET.document,
            canvas: TARGET.canvas,
        });
        expect(store.focus).toBeNull();
        expect(new URLSearchParams(window.location.search).get("doc")).toBe(
            TARGET.document,
        );

        await back();
        expect(store.view).toBe("compare");
        expect(store.document).toBeNull();
    });

    it("comes back to the document with its origin when going forward again", async () => {
        const store = useExplorerStore();
        store.setView("compare");
        store.openInDocument(TARGET);
        await nextTick();
        await back();
        const forward = popped();
        window.history.forward();
        await forward;
        await nextTick();
        expect(store.document?.id).toBe(TARGET.document);
        expect(store.documentOrigin).toBe("compare");
    });

    describe.each([
        ["the same document", TARGET],
        ["another document", OTHER],
    ])(
        "opened from Compare over a document of the results (%s)",
        (_name, to) => {
            async function walk() {
                window.history.replaceState(null, "", "/en/discover?q=x");
                wrapper.unmount();
                wrapper = mount(Harness);
                const store = useExplorerStore();
                store.openDocument(TARGET.document);
                await nextTick();
                store.setView("compare");
                await nextTick();
                store.openInDocument(to);
                await nextTick();
                expect(store.documentOrigin).toBe("compare");
                await back();
                expect(store.view).toBe("compare");
                await back();
                return store;
            }

            it("gives the document its own origin again after two Backs", async () => {
                const store = await walk();
                expect(store.document?.id).toBe(TARGET.document);
                expect(store.documentOrigin).toBe("results");
            });

            it("loses it without the entry state", async () => {
                wiring.keepOrigin = false;
                const store = await walk();
                expect(store.documentOrigin).toBe("compare");
            });
        },
    );

    it("restores the origin a reloaded document entry carries, and ignores an invalid one", () => {
        for (const [stored, expected] of [
            ["compare", "compare"],
            ["nowhere", "home"],
        ]) {
            wrapper.unmount();
            window.history.replaceState(
                { documentOrigin: stored },
                "",
                `/en/discover?doc=${TARGET.document}`,
            );
            setActivePinia(createPinia());
            wrapper = mount(Harness);
            expect(useExplorerStore().documentOrigin).toBe(expected);
        }
    });
});
