import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import SharedSelectionPrompt from "@/manuspectrum/pages/AnalysisExplorer/components/SharedSelectionPrompt.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const KEY_1 = "ch:00000000-0000-4000-8000-000000000001:-";
const KEY_2 = "ch:00000000-0000-4000-8000-000000000002:-";
let pinia: Pinia;

function mountPrompt(truncated = 0) {
    return mount(SharedSelectionPrompt, {
        props: { selection: { keys: [KEY_1, KEY_2], truncated, invalid: 0 } },
        global: { plugins: [pinia] },
    });
}

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
            jsonResponse({
                items: [
                    {
                        key: KEY_1,
                        kind: "characterization",
                        characterization: {
                            id: "x",
                            name: { value: "Vermilion, f. 12r", lang: "en" },
                        },
                    },
                ],
                missing: [KEY_2],
            }),
        ),
    );
});

afterEach(() => vi.unstubAllGlobals());

describe("SharedSelectionPrompt", () => {
    it("lists the shared items read-only and says how many are gone", async () => {
        const wrapper = mountPrompt();
        await flushPromises();
        expect(wrapper.text()).toContain("A shared Selection of 2 items");
        expect(wrapper.find(".items").text()).toContain("Vermilion, f. 12r");
        expect(wrapper.text()).toContain("1 item is no longer available.");
    });

    it("warns when the link carried more than 30 items", () => {
        expect(mountPrompt(3).text()).toContain(
            "Only the first 30 items were kept; 3 more were left out.",
        );
    });

    it("replaces the Selection", async () => {
        const store = useExplorerStore();
        store.addToBasket("ch:00000000-0000-4000-8000-000000000009:-");
        const wrapper = mountPrompt();
        await wrapper.find(".replace").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([KEY_1, KEY_2]);
        expect(wrapper.emitted("resolved")?.[0]).toEqual([
            "Your Selection now holds the 2 shared items.",
        ]);
    });

    it("merges into the Selection and reports what did not fit", async () => {
        const store = useExplorerStore();
        for (let n = 10; n < 39; n += 1) {
            store.addToBasket(`ch:00000000-0000-4000-8000-0000000000${n}:-`);
        }
        const wrapper = mountPrompt();
        await wrapper.find(".merge").trigger("click");
        expect(store.basket).toHaveLength(30);
        expect(wrapper.emitted("resolved")?.[0]).toEqual([
            "1 item added. 1 item could not be added: the Selection is full (30).",
        ]);
    });

    it("leaves the Selection alone when dismissed", async () => {
        const store = useExplorerStore();
        const wrapper = mountPrompt();
        await wrapper.find(".dismiss").trigger("click");
        expect(store.basket).toEqual([]);
        expect(wrapper.emitted("resolved")?.[0]).toEqual([""]);
    });
});
