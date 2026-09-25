import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import AnalysisExplorer from "@/manuspectrum/pages/AnalysisExplorer/AnalysisExplorer.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    analysisPayload,
    documentPayload,
    searchResponse,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const KEY = "ch:00000000-0000-4000-8000-000000000001:-";
let pinia: Pinia;

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    window.localStorage.clear();
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) =>
            url.includes("explorer-items")
                ? jsonResponse({ items: [], missing: [] })
                : jsonResponse(searchResponse()),
        ),
    );
});

afterEach(() => vi.unstubAllGlobals());

describe("AnalysisExplorer", () => {
    it("records the server's connection flag", () => {
        window.history.replaceState(null, "", "/en/discover");
        mount(AnalysisExplorer, {
            props: { connected: true },
            global: { plugins: [pinia] },
        });
        expect(useExplorerStore().session.connected).toBe(true);
    });

    it("opens the screen the URL names", async () => {
        window.history.replaceState(null, "", "/en/discover?q=gold");
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(wrapper.find(".corpus-results").exists()).toBe(true);
        expect(wrapper.find(".active-filters").exists()).toBe(true);
    });

    it("prompts for a shared Selection and removes sel from the URL", async () => {
        window.history.replaceState(null, "", `/en/discover?sel=${KEY}`);
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(window.location.search).toBe("");
        expect(wrapper.find(".shared-selection").exists()).toBe(true);
        await wrapper.find(".shared-selection .replace").trigger("click");
        expect(wrapper.find(".shared-selection").exists()).toBe(false);
        expect(wrapper.find("[aria-live=polite].announcer").text()).toBe(
            "Your Selection now holds the 1 shared item.",
        );
        expect(useExplorerStore().basket.map((item) => item.key)).toEqual([
            KEY,
        ]);
    });

    it("moves the focus to the heading of each new screen", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) =>
                url.includes("explorer-document")
                    ? jsonResponse(documentPayload())
                    : jsonResponse(searchResponse()),
            ),
        );
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        const store = useExplorerStore();
        store.setFilter("q", "gold");
        store.setCorpusScreen("results");
        await flushPromises();
        expect(document.activeElement?.id).toBe("explorer-results-title");
        store.openDocument(uuid(1));
        await flushPromises();
        expect(document.activeElement?.classList.contains("name")).toBe(true);
        store.setCorpusScreen("home");
        await flushPromises();
        expect(document.activeElement?.classList.contains("promise")).toBe(
            true,
        );
        wrapper.unmount();
    });

    it("moves the focus to the screen heading when the shared Selection prompt closes", async () => {
        window.history.replaceState(null, "", `/en/discover?sel=${KEY}`);
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        await wrapper.find(".shared-selection .dismiss").trigger("click");
        await flushPromises();
        expect(document.activeElement?.classList.contains("promise")).toBe(
            true,
        );
        wrapper.unmount();
    });

    it("opens an analysis from the results in two history steps, the document then its card", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) => {
                if (url.includes("explorer-search")) {
                    return jsonResponse(
                        searchResponse({
                            results: [
                                analysisHit(1, {
                                    canvas: "https://iiif.example/c1",
                                }),
                            ],
                        }),
                    );
                }
                if (url.includes("explorer-document")) {
                    return jsonResponse(documentPayload());
                }
                if (url.includes("explorer-analysis")) {
                    return jsonResponse(analysisPayload({ files: [] }));
                }
                return jsonResponse({ items: [], missing: [] });
            }),
        );
        window.history.replaceState(
            null,
            "",
            "/en/discover?screen=results&grain=analyses",
        );
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia, PrimeVue] },
        });
        await flushPromises();
        const pushState = vi.spyOn(window.history, "pushState");
        await wrapper.find(".analysis-row .link").trigger("click");
        await flushPromises();
        const urls = pushState.mock.calls.map(([, , url]) => String(url));
        pushState.mockRestore();
        expect(urls).toHaveLength(2);
        expect(urls[0]).toContain(`doc=${uuid(1)}`);
        expect(urls[0]).not.toContain("focus=");
        expect(urls[1]).toContain(`focus=analysis%3A${uuid(101)}`);
        wrapper.unmount();
    });

    it("moves the focus to the back button of a document that is not available", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) =>
                url.includes("explorer-document")
                    ? jsonResponse({}, 404)
                    : jsonResponse(searchResponse()),
            ),
        );
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            props: { connected: false },
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        useExplorerStore().openDocument(uuid(1));
        await flushPromises();
        expect(document.activeElement?.classList.contains("back")).toBe(true);
        wrapper.unmount();
    });
});
