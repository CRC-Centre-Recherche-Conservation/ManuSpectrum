import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import SelectionCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCheckbox.vue";

import {
    ANNOUNCE_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

const KEY = analysisKey(uuid(1));
const hints = ref(new Map<string, SelectionHint>());

function mountBox(props: Record<string, unknown> = {}) {
    return mount(SelectionCheckbox, {
        props: { itemKey: KEY, label: "Add Raman to the Selection", ...props },
        global: {
            provide: {
                [ANNOUNCE_KEY as symbol]: vi.fn(),
                [SELECTION_HINTS_KEY as symbol]: hints,
            },
        },
    });
}

beforeEach(() => {
    setActivePinia(createPinia());
    hints.value = new Map();
});

describe("SelectionCheckbox", () => {
    it("is a native checkbox named by its label", () => {
        const wrapper = mountBox();
        const input = wrapper.get('input[type="checkbox"]');
        expect(input.attributes("aria-label")).toBe(
            "Add Raman to the Selection",
        );
        expect((input.element as HTMLInputElement).checked).toBe(false);
        expect(wrapper.classes()).not.toContain("held");
    });

    it("adds the item when checked, with its hint", async () => {
        const store = useExplorerStore();
        const wrapper = mountBox({
            hint: { title: label("Raman"), kind: "analysis" },
        });
        await wrapper.get("input").setValue(true);
        expect(store.basket.map((item) => item.key)).toEqual([KEY]);
        expect(hints.value.get(KEY)?.title.value).toBe("Raman");
    });

    it("removes the item when unchecked", async () => {
        const store = useExplorerStore();
        store.addToBasket(KEY);
        const wrapper = mountBox();
        await wrapper.get("input").setValue(false);
        expect(store.basket).toEqual([]);
    });

    it("writes the slot and takes the held class when held", async () => {
        const store = useExplorerStore();
        store.addToBasket(analysisKey(uuid(2)));
        const wrapper = mountBox();
        await wrapper.get("input").setValue(true);
        expect(wrapper.classes()).toContain("held");
        expect(wrapper.get(".slot").text()).toBe("A2");
        expect((wrapper.get("input").element as HTMLInputElement).checked).toBe(
            true,
        );
    });

    it("uses the held label while held", async () => {
        const store = useExplorerStore();
        store.addToBasket(KEY);
        const wrapper = mountBox({ heldLabel: "Remove Raman" });
        expect(wrapper.get("input").attributes("aria-label")).toBe(
            "Remove Raman",
        );
    });

    it("is aria-disabled with its reason when the Selection is full and the item is not held", async () => {
        const store = useExplorerStore();
        store.addManyToBasket(
            Array.from({ length: 30 }, (_, n) => analysisKey(uuid(n + 10))),
        );
        const wrapper = mountBox();
        const input = wrapper.get("input");
        expect(input.attributes("aria-disabled")).toBe("true");
        expect(input.attributes("disabled")).toBeUndefined();
        const reasonId = input.attributes("aria-describedby");
        expect(reasonId).toBeTruthy();
        expect(wrapper.get(`#${reasonId}`).text()).toBe(
            "Selection full (30/30): remove items to add more.",
        );
        await input.trigger("click");
        expect(store.basket).toHaveLength(30);
    });

    it("stays usable when the Selection is full but the item is held", () => {
        const store = useExplorerStore();
        store.addManyToBasket(
            Array.from({ length: 30 }, (_, n) => analysisKey(uuid(n + 1))),
        );
        const wrapper = mountBox();
        expect(
            wrapper.get("input").attributes("aria-disabled"),
        ).toBeUndefined();
    });
});
