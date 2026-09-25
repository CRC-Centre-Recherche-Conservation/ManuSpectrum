import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import AddToSelection from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AddToSelection.vue";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const KEY = `af:${uuid(1)}:${uuid(2)}`;

function mountButton(keys: string[]) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const announce = vi.fn();
    const wrapper = mount(AddToSelection, {
        attachTo: document.body,
        props: { keys, label: "+ Selection" },
        global: {
            plugins: [pinia],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        },
    });
    return { wrapper, announce, store: useExplorerStore() };
}

describe("AddToSelection", () => {
    it("adds the keys and announces it", async () => {
        const { wrapper, announce, store } = mountButton([KEY]);
        await wrapper.find("button").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([KEY]);
        expect(announce).toHaveBeenCalledWith("Added to the Selection (1/30).");
        expect(wrapper.text()).toContain("In the Selection as A1");
    });

    it("is disabled with the reason when the keys do not fit", () => {
        const { wrapper, store } = mountButton([
            KEY,
            `af:${uuid(3)}:${uuid(4)}`,
        ]);
        store.addManyToBasket(
            Array.from(
                { length: 29 },
                (_, n) => `af:${uuid(100 + n)}:${uuid(200 + n)}`,
            ),
        );
        return wrapper.vm.$nextTick().then(() => {
            expect(wrapper.find("button").attributes("disabled")).toBeDefined();
            expect(wrapper.text()).toContain("2 items, 1 place left");
        });
    });

    it("points the disabled button at its own reason", async () => {
        const { wrapper, store } = mountButton([
            KEY,
            `af:${uuid(3)}:${uuid(4)}`,
        ]);
        store.addManyToBasket(
            Array.from(
                { length: 29 },
                (_, n) => `af:${uuid(100 + n)}:${uuid(200 + n)}`,
            ),
        );
        await wrapper.vm.$nextTick();
        const describedBy = wrapper
            .find("button")
            .attributes("aria-describedby");
        expect(describedBy).toBeTruthy();
        expect(describedBy).not.toContain(KEY);
        expect(wrapper.find(".reason").attributes("id")).toBe(describedBy);
    });

    it("keeps the keyboard focus on the line that replaces the button", async () => {
        const { wrapper } = mountButton([KEY]);
        const button = wrapper.find("button");
        (button.element as HTMLButtonElement).focus();
        await button.trigger("click");
        await flushPromises();
        expect(document.activeElement).toBe(wrapper.find(".held").element);
        wrapper.unmount();
    });
});
