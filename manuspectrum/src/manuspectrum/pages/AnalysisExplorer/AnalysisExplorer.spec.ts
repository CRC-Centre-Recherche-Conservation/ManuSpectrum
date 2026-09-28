import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import AnalysisExplorer from "@/manuspectrum/pages/AnalysisExplorer/AnalysisExplorer.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { loadCompareView } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/load-compare-view.ts";
import {
    analysisHit,
    analysisPayload,
    documentMatch,
    documentPayload,
    searchResponse,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";
import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("gridstack", async () =>
    (
        await import(
            "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts"
        )
    ).gridstackModule(),
);

vi.mock(
    "@/manuspectrum/pages/AnalysisExplorer/views/Compare/load-compare-view.ts",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("@/manuspectrum/pages/AnalysisExplorer/views/Compare/load-compare-view.ts")
            >();
        return { loadCompareView: vi.fn(actual.loadCompareView) };
    },
);

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const KEY = "ch:00000000-0000-4000-8000-000000000001:-";
const EMPTY_SYNTHESIS: SynthesisResponse = {
    coverage: [],
    canvases: [],
    techniques: [],
    pairs: [],
    elements: [],
    materials: [],
    unpublishedCount: 0,
};
let pinia: Pinia;

beforeEach(() => {
    forgetPayloads();
    pinia = createPinia();
    setActivePinia(pinia);
    window.localStorage.clear();
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
            if (url.includes("explorer-synthesis")) {
                return jsonResponse(EMPTY_SYNTHESIS);
            }
            return url.includes("explorer-items")
                ? jsonResponse({ items: [], missing: [] })
                : jsonResponse(searchResponse());
        }),
    );
});

afterEach(() => vi.unstubAllGlobals());

describe("AnalysisExplorer", () => {
    it("shows the Compare view when it is chosen", async () => {
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        await flushPromises();
        useExplorerStore().setView("compare");
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(wrapper.find(".compare-view").exists()).toBe(true);
        expect(wrapper.find(".corpus-home").exists()).toBe(false);
        wrapper.unmount();
    });

    it("says the Compare view could not be loaded, and loads it again on Retry", async () => {
        const failure = vi.spyOn(console, "error").mockImplementation(() => {});
        vi.mocked(loadCompareView).mockRejectedValueOnce(
            new Error("Loading chunk explorer-compare failed."),
        );
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        useExplorerStore().setView("compare");
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(wrapper.find(".compare-view").exists()).toBe(false);
        expect(wrapper.find(".unavailable-state").text()).toContain(
            "The service is not answering right now.",
        );
        await wrapper.find(".unavailable-state .retry").trigger("click");
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(wrapper.find(".unavailable-state").exists()).toBe(false);
        expect(wrapper.find(".compare-view").exists()).toBe(true);
        failure.mockRestore();
        wrapper.unmount();
    });

    it("shows that the Compare view is loading", async () => {
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        useExplorerStore().setView("compare");
        await nextTick();
        expect(wrapper.find(".compare-loading").attributes("role")).toBe(
            "status",
        );
        expect(wrapper.find(".compare-loading").text()).toBe(
            "Loading the Compare view…",
        );
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(wrapper.find(".compare-loading").exists()).toBe(false);
        wrapper.unmount();
    });

    it("reads the Selection once for every Compare view it opens", async () => {
        const fetchMock = vi.fn(async (url: string) => {
            if (url.includes("explorer-synthesis")) {
                return jsonResponse(EMPTY_SYNTHESIS);
            }
            return url.includes("explorer-items")
                ? jsonResponse({ items: [], missing: [KEY] })
                : jsonResponse(searchResponse());
        });
        vi.stubGlobal("fetch", fetchMock);
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        const store = useExplorerStore();
        store.addToBasket(KEY);
        for (const view of ["compare", "corpus", "compare"] as const) {
            forgetPayloads();
            store.setView(view);
            await flushPromises();
            await vi.dynamicImportSettled();
            await flushPromises();
        }
        expect(wrapper.find(".compare-view .loading").exists()).toBe(false);
        expect(
            fetchMock.mock.calls.filter(([url]) =>
                url.includes("explorer-items"),
            ),
        ).toHaveLength(1);
        wrapper.unmount();
    });

    it("closes the Selection drawer on « Compare » and gives the focus to the Compare heading", async () => {
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia, PrimeVue] },
            attachTo: document.body,
        });
        useExplorerStore().addToBasket(KEY);
        await flushPromises();
        await wrapper.find(".selection-drawer .opener").trigger("click");
        await flushPromises();
        document
            .querySelector<HTMLButtonElement>(
                ".explorer-selection-drawer button.compare",
            )!
            .click();
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(document.querySelector(".explorer-selection-drawer")).toBeNull();
        expect(
            wrapper
                .find(".selection-drawer .opener")
                .attributes("aria-expanded"),
        ).toBe("false");
        expect(document.activeElement?.id).toBe("explorer-compare-title");
        wrapper.unmount();
    });

    it("says once, politely, that an old Selection was emptied", async () => {
        window.localStorage.setItem(
            "ms-explorer-basket-v1",
            JSON.stringify([{ key: KEY, slot: 0 }]),
        );
        window.localStorage.setItem("ms-explorer-basket-touched-v1", "1");
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        await flushPromises();

        const notice = wrapper.find(".selection-expired");
        expect(notice.text()).toContain("more than 90 days");
        expect(wrapper.find(".announcer").text()).toContain(
            "more than 90 days",
        );
        expect(useExplorerStore().basket).toEqual([]);
        await notice.find("button").trigger("click");
        expect(wrapper.find(".selection-expired").exists()).toBe(false);
    });

    it("opens the screen the URL names", async () => {
        window.history.replaceState(null, "", "/en/discover?q=gold");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(wrapper.find(".corpus-results").exists()).toBe(true);
        expect(wrapper.find(".active-filters").exists()).toBe(true);
    });

    it("names the screen shown on the page body, for the page intro", async () => {
        window.history.replaceState(null, "", "/en/discover?q=gold");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
        });
        await flushPromises();
        expect(document.body.dataset.explorerScreen).toBe("results");
        useExplorerStore().setCorpusScreen("home");
        await flushPromises();
        expect(document.body.dataset.explorerScreen).toBe("home");
        wrapper.unmount();
        expect(document.body.dataset.explorerScreen).toBeUndefined();
    });

    it("puts the back link and the Selection button in the intro line of the page", async () => {
        const bar = document.createElement("div");
        bar.id = "ms-explorer-intro-bar";
        document.body.append(bar);
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        expect(bar.querySelector(".selection-drawer .opener")).not.toBeNull();
        useExplorerStore().openDocument(uuid(1));
        await flushPromises();
        expect(bar.querySelector(".explorer-back")?.textContent).toContain(
            "Back to the explorer home",
        );
        expect(wrapper.find(".corpus-document .explorer-back").exists()).toBe(
            false,
        );
        wrapper.unmount();
        bar.remove();
    });

    it("mounts the share button just before the Selection button", async () => {
        const bar = document.createElement("div");
        bar.id = "ms-explorer-intro-bar";
        document.body.append(bar);
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            props: { miradorUrl: "https://viewer.example/" },
            global: { plugins: [pinia, PrimeVue] },
            attachTo: document.body,
        });
        await flushPromises();
        expect(bar.querySelector(".share-export")).toBeNull();

        useExplorerStore().openDocument(uuid(1));
        await flushPromises();

        const owners = [...bar.querySelectorAll("button.opener")].map(
            (button) =>
                button.closest(".share-export")
                    ? "share"
                    : button.closest(".selection-drawer")
                      ? "selection"
                      : null,
        );
        expect(owners).toEqual(["share", "selection"]);
        wrapper.unmount();
        bar.remove();
    });

    it("prompts for a shared Selection and removes sel from the URL", async () => {
        window.history.replaceState(null, "", `/en/discover?sel=${KEY}`);
        const wrapper = mount(AnalysisExplorer, {
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
                url.includes("explorer-document-match")
                    ? jsonResponse(documentMatch())
                    : url.includes("explorer-document")
                      ? jsonResponse(documentPayload())
                      : jsonResponse(searchResponse()),
            ),
        );
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
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

    it("moves the focus to the heading of the view chosen in the tabs, and back", async () => {
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        const tabs = wrapper.findAll(".view-tabs .tab");
        await tabs[1].trigger("click");
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(document.activeElement?.id).toBe("explorer-compare-title");
        await tabs[0].trigger("click");
        await flushPromises();
        expect(document.activeElement?.classList.contains("promise")).toBe(
            true,
        );
        wrapper.unmount();
    });

    it("leaves the keyboard focus alone on a view the address opens", async () => {
        window.history.replaceState(null, "", "/en/discover?view=compare");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        await vi.dynamicImportSettled();
        await flushPromises();
        expect(wrapper.find(".compare-view").exists()).toBe(true);
        expect(document.activeElement).toBe(document.body);
        wrapper.unmount();
    });

    it("leaves the keyboard focus alone when the address names the same document again", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (url: string) =>
                url.includes("explorer-document-match")
                    ? jsonResponse(documentMatch())
                    : url.includes("explorer-document")
                      ? jsonResponse(documentPayload())
                      : jsonResponse(searchResponse()),
            ),
        );
        window.history.replaceState(null, "", "/en/discover");
        const wrapper = mount(AnalysisExplorer, {
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        const store = useExplorerStore();
        store.openDocument(uuid(1));
        await flushPromises();
        const back = wrapper.find(".explorer-back");
        (back.element as HTMLButtonElement).focus();
        store.$patch((state) => {
            state.document = { id: uuid(1), canvas: null };
        });
        await flushPromises();
        expect(document.activeElement).toBe(back.element);
        wrapper.unmount();
    });

    it("moves the focus to the screen heading when the shared Selection prompt closes", async () => {
        window.history.replaceState(null, "", `/en/discover?sel=${KEY}`);
        const wrapper = mount(AnalysisExplorer, {
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
                if (url.includes("explorer-document-match")) {
                    return jsonResponse(documentMatch());
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
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await flushPromises();
        useExplorerStore().openDocument(uuid(1));
        await flushPromises();
        expect(
            document.activeElement?.classList.contains("explorer-back"),
        ).toBe(true);
        wrapper.unmount();
    });
});
