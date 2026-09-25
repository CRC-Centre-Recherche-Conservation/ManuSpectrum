import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionPanel.vue";

import { SELECTION_HINTS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    fileEntry,
    imagingEntry,
    label,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: () => "/en/api/explorer/items",
}));

afterEach(() => vi.unstubAllGlobals());

const KEY = `af:${uuid(101)}:${uuid(700)}`;
const GONE = `af:${uuid(102)}:${uuid(701)}`;

function mountPanel() {
    vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
            jsonResponse({
                items: [
                    {
                        key: KEY,
                        kind: "analysis-file",
                        analysis: analysisHit(1),
                        file: fileEntry(),
                    },
                ],
                missing: [GONE],
            }),
        ),
    );
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useExplorerStore();
    store.addManyToBasket([KEY, GONE]);
    return {
        wrapper: mount(SelectionPanel, { global: { plugins: [pinia] } }),
        store,
    };
}

describe("SelectionPanel", () => {
    it("holds a placeholder line in each row until its item is read", () => {
        const { wrapper } = mountPanel();
        const row = wrapper.find(`[data-key="${KEY}"]`);
        expect(row.find(".pending").exists()).toBe(true);
        expect(row.find(".pending").attributes("aria-label")).toBe("Loading…");
    });

    it("says the Selection is kept on this browser", () => {
        const { wrapper } = mountPanel();
        expect(wrapper.find(".kept").text()).toBe("Kept on this browser");
    });

    it("shows what the card knew of an item while it loads, and asks only for new keys", async () => {
        const fetchMock = vi.fn(async (url: string) =>
            jsonResponse({
                items: new URLSearchParams(url.split("?")[1])
                    .getAll("ids")
                    .map((key) => ({
                        key,
                        kind: "analysis-file",
                        analysis: analysisHit(1),
                        file: fileEntry(),
                    })),
                missing: [],
            }),
        );
        vi.stubGlobal("fetch", fetchMock);
        const pinia = createPinia();
        setActivePinia(pinia);
        const store = useExplorerStore();
        const hints = ref(new Map());
        const wrapper = mount(SelectionPanel, {
            global: {
                plugins: [pinia],
                provide: { [SELECTION_HINTS_KEY as symbol]: hints },
            },
        });
        store.addToBasket(KEY);
        await flushPromises();
        hints.value = new Map([
            [GONE, { title: label("Zone bleue"), kind: "spectrum" }],
        ]);
        store.addToBasket(GONE);
        await nextTick();
        expect(wrapper.find(`[data-key="${GONE}"]`).text()).toContain(
            "Zone bleue",
        );
        await flushPromises();
        const asked = fetchMock.mock.calls.map(([url]) =>
            new URLSearchParams(String(url).split("?")[1]).getAll("ids"),
        );
        expect(asked).toEqual([[KEY], [GONE]]);
    });

    it("lists the Selection with its A-labels and kinds", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        const first = wrapper.find(`[data-key="${KEY}"]`);
        expect(first.text()).toContain("A1");
        expect(first.text()).toContain("spectrum");
        expect(first.text()).toContain("Manuscript 1");
    });

    it("shows a whole analysis with its technique and what it holds", async () => {
        const key = `an:${uuid(101)}:-`;
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse({
                    items: [
                        {
                            key,
                            kind: "analysis",
                            analysis: analysisHit(1, {
                                technique: technique(
                                    "http://example.org/xrf",
                                    "X-ray fluorescence",
                                    4,
                                    uuid(900),
                                    "XRF",
                                ),
                            }),
                            files: [
                                fileEntry({ id: uuid(700) }),
                                fileEntry({ id: uuid(701) }),
                                imagingEntry(),
                            ],
                        },
                    ],
                    missing: [],
                }),
            ),
        );
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([key]);
        const wrapper = mount(SelectionPanel, { global: { plugins: [pinia] } });
        await flushPromises();
        const row = wrapper.find(`[data-key="${key}"]`);
        expect(row.find(".title").text()).toBe("MS1_f12_XRF_03");
        expect(row.find(".technique-tag .code").text()).toBe("XRF");
        expect(row.find(".technique-tag .dot").classes("dot--tech-4")).toBe(
            true,
        );
        expect(row.find(".kind").text()).toBe("2 spectra · 1 map");
        expect(row.text()).toContain("Manuscript 1");
    });

    it("says an analysis in the Selection holds no data to show", async () => {
        const key = `an:${uuid(101)}:-`;
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse({
                    items: [
                        {
                            key,
                            kind: "analysis",
                            analysis: analysisHit(1),
                            files: [],
                        },
                    ],
                    missing: [],
                }),
            ),
        );
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([key]);
        const wrapper = mount(SelectionPanel, { global: { plugins: [pinia] } });
        await flushPromises();
        expect(wrapper.find(`[data-key="${key}"] .kind`).text()).toBe(
            "no data to show",
        );
    });

    it("marks an item that is no longer available and lets the reader remove it", async () => {
        const { wrapper, store } = mountPanel();
        await flushPromises();
        const gone = wrapper.find(`[data-key="${GONE}"]`);
        expect(gone.text()).toContain("no longer available");
        await gone.find("button.remove").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([KEY]);
    });

    it("empties the Selection", async () => {
        const { wrapper, store } = mountPanel();
        await flushPromises();
        await wrapper.find("button.clear").trigger("click");
        expect(store.basket).toEqual([]);
    });

    it("does not offer Compare while the view is not built", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        expect(wrapper.find("button.compare").exists()).toBe(false);
    });

    it("writes a map layer's label apart from the analysis name and its language", async () => {
        const key = `im:${uuid(101)}:1`;
        vi.stubGlobal(
            "fetch",
            vi.fn(async () =>
                jsonResponse({
                    items: [
                        {
                            key,
                            kind: "imaging",
                            analysis: analysisHit(1, {
                                name: { value: "Analyse maXRF", lang: "fr" },
                            }),
                            file: imagingEntry(),
                        },
                    ],
                    missing: [],
                }),
            ),
        );
        const pinia = createPinia();
        setActivePinia(pinia);
        useExplorerStore().addManyToBasket([key]);
        const wrapper = mount(SelectionPanel, { global: { plugins: [pinia] } });
        await flushPromises();
        const title = wrapper.find(`[data-key="${key}"] .title`);
        expect(title.find('[lang="fr"]').text()).toBe("Analyse maXRF");
        expect(title.text()).toContain("Hg");
        expect(title.find('[lang="fr"]').text()).not.toContain("Hg");
    });
});
