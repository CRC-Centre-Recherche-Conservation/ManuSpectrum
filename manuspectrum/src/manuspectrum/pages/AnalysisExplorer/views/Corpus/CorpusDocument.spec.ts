import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CorpusDocument from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/CorpusDocument.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentPayload,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string, parameters: Record<string, string>) =>
        `/en/${name}/${parameters.resourceid}`,
}));

let pinia: Pinia;

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
});

afterEach(() => vi.unstubAllGlobals());

describe("CorpusDocument", () => {
    it("shows the document name, holding and analysed pages", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse(documentPayload({ unlocated: [] }))),
        );
        const wrapper = mount(CorpusDocument, {
            props: { documentId: uuid(1) },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(wrapper.find("h2").text()).toBe("Manuscript 1");
        expect(wrapper.text()).toContain("Avranches, BM");
        expect(wrapper.findAll(".pages li").map((item) => item.text())).toEqual(
            ["f. 12r (3)"],
        );
    });

    it("shows S7 for an unknown or refused document", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse({}, 404)),
        );
        const wrapper = mount(CorpusDocument, {
            props: { documentId: uuid(1) },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(wrapper.text()).toContain("This item is not available.");
    });

    it("offers one way home when a document opened from the home is unavailable", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse({}, 404)),
        );
        const store = useExplorerStore();
        store.openDocument(uuid(1));
        const wrapper = mount(CorpusDocument, {
            props: { documentId: uuid(1) },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        const homeLabels = wrapper
            .findAll("button")
            .filter((button) => button.text() === "Back to the explorer home");
        expect(homeLabels).toHaveLength(1);
    });

    it("goes back to the results it was opened from", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse(documentPayload())),
        );
        const store = useExplorerStore();
        store.setFilter("technique", ["http://x/xrf"]);
        store.setCorpusScreen("results");
        store.openDocument(uuid(1));
        const wrapper = mount(CorpusDocument, {
            props: { documentId: uuid(1) },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        const back = wrapper.find(".back");
        expect(back.text()).toBe("Back to the results");
        await back.trigger("click");
        expect(store.corpusScreen).toBe("results");
        expect(store.document).toBeNull();
        expect(store.filters.technique).toEqual(["http://x/xrf"]);
    });

    it("goes back to the explorer home when opened from it", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => jsonResponse(documentPayload())),
        );
        const store = useExplorerStore();
        store.openDocument(uuid(1));
        const wrapper = mount(CorpusDocument, {
            props: { documentId: uuid(1) },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        const back = wrapper.find(".back");
        expect(back.text()).toBe("Back to the explorer home");
        await back.trigger("click");
        expect(store.corpusScreen).toBe("home");
    });
});
