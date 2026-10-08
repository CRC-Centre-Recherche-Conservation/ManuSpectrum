import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import SelectAllCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectAllCheckbox.vue";

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

const KEYS = [1, 2, 3].map((n) => analysisKey(uuid(n)));
const hints = ref(new Map<string, SelectionHint>());

function mountAll(keys: string[] = KEYS, compact = false) {
    return mount(SelectAllCheckbox, {
        props: { keys, label: "Select all (3 shown)", compact },
        attachTo: document.body,
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
    document.body.innerHTML = "";
});

describe("SelectAllCheckbox", () => {
    it("is unchecked and not indeterminate when none is held", () => {
        const input = mountAll().get("input").element as HTMLInputElement;
        expect(input.checked).toBe(false);
        expect(input.indeterminate).toBe(false);
    });

    it("is natively indeterminate when part is held", () => {
        useExplorerStore().addToBasket(KEYS[0]);
        const input = mountAll().get("input").element as HTMLInputElement;
        expect(input.indeterminate).toBe(true);
        expect(input.checked).toBe(false);
    });

    it("adds every key with its hint on a click", async () => {
        const store = useExplorerStore();
        const wrapper = mountAll();
        await wrapper.setProps({
            hints: new Map([[KEYS[1], { title: label("Two"), kind: "x" }]]),
        });
        await wrapper.get("input").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual(KEYS);
        expect(hints.value.has(KEYS[1])).toBe(true);
        expect((wrapper.get("input").element as HTMLInputElement).checked).toBe(
            true,
        );
    });

    it("completes the missing keys from the mixed state", async () => {
        const store = useExplorerStore();
        store.addToBasket(KEYS[1]);
        const wrapper = mountAll();
        await wrapper.get("input").trigger("click");
        expect(store.basket).toHaveLength(3);
        expect(store.basket.find((item) => item.key === KEYS[1])?.slot).toBe(0);
    });

    it("removes every key when all are held", async () => {
        const store = useExplorerStore();
        store.addManyToBasket(KEYS);
        const wrapper = mountAll();
        expect((wrapper.get("input").element as HTMLInputElement).checked).toBe(
            true,
        );
        await wrapper.get("input").trigger("click");
        expect(store.basket).toEqual([]);
    });

    it("refuses with a reason, stays focusable and adds nothing", async () => {
        const store = useExplorerStore();
        store.addManyToBasket(
            Array.from({ length: 29 }, (_, n) => analysisKey(uuid(n + 10))),
        );
        const wrapper = mountAll();
        const input = wrapper.get("input");
        expect(input.attributes("aria-disabled")).toBe("true");
        expect(input.attributes("disabled")).toBeUndefined();
        const reasonId = input.attributes("aria-describedby");
        expect(wrapper.get(`#${reasonId}`).text()).toBe(
            "3 analyses to add, 1 place left",
        );
        (input.element as HTMLInputElement).focus();
        await input.trigger("click");
        expect(store.basket).toHaveLength(29);
        expect(document.activeElement).toBe(input.element);
    });

    describe("when the Selection cannot take the keys", () => {
        beforeEach(() => {
            useExplorerStore().addManyToBasket(
                Array.from({ length: 29 }, (_, n) => analysisKey(uuid(n + 10))),
            );
        });

        it("prints the reason next to a full-size checkbox", () => {
            const wrapper = mountAll();
            const reason = wrapper.get(".reason");
            expect(reason.classes()).not.toContain("visually-hidden");
            expect(wrapper.get("label").attributes("title")).toBeUndefined();
        });

        it("hides the reason of a compact checkbox but keeps it described and in the tooltip", () => {
            const wrapper = mountAll(KEYS, true);
            const reason = wrapper.get(".reason");
            expect(reason.classes()).toContain("visually-hidden");
            expect(wrapper.get("input").attributes("aria-describedby")).toBe(
                reason.attributes("id"),
            );
            expect(wrapper.get("label").attributes("title")).toBe(
                `Select all (3 shown)\n${reason.text()}`,
            );
        });
    });

    it("keeps the focus on the checkbox after an action", async () => {
        const wrapper = mountAll();
        const input = wrapper.get("input").element as HTMLInputElement;
        input.focus();
        await wrapper.get("input").trigger("click");
        expect(document.activeElement).toBe(input);
    });

    it("is aria-disabled without keys", () => {
        const wrapper = mountAll([]);
        expect(wrapper.get("input").attributes("aria-disabled")).toBe("true");
    });
});
