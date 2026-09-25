import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";

import SelectionPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SelectionPanel.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    fileEntry,
    imagingEntry,
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
    it("lists the Selection with its A-labels and kinds", async () => {
        const { wrapper } = mountPanel();
        await flushPromises();
        const first = wrapper.find(`[data-key="${KEY}"]`);
        expect(first.text()).toContain("A1");
        expect(first.text()).toContain("spectrum");
        expect(first.text()).toContain("Manuscript 1");
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
