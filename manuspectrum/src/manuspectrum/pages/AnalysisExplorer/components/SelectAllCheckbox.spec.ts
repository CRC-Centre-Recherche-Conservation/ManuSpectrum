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

const announce = vi.fn();

function mountAll(
    keys: string[] = KEYS,
    compact = false,
    extra: Record<string, unknown> = {},
) {
    return mount(SelectAllCheckbox, {
        props: {
            keys,
            name: "Select all: the 3 analyses on this page",
            compact,
            ...extra,
        },
        attachTo: document.body,
        global: {
            provide: {
                [ANNOUNCE_KEY as symbol]: announce,
                [SELECTION_HINTS_KEY as symbol]: hints,
            },
        },
    });
}

beforeEach(() => {
    announce.mockClear();
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
        expect(input.attributes("aria-describedby")).toBeTruthy();
        (input.element as HTMLInputElement).focus();
        await input.trigger("click");
        expect(store.basket).toHaveLength(29);
        expect(document.activeElement).toBe(input.element);
    });

    it("shows « Select all » and names the box by its scope", () => {
        const wrapper = mountAll();
        expect(wrapper.get(".text").text()).toBe("Select all");
        expect(wrapper.get("input").attributes("aria-label")).toBe(
            "Select all: the 3 analyses on this page",
        );
    });

    describe("counter chip", () => {
        it("shows the total when none is held", () => {
            const chip = mountAll().get(".chip");
            expect(chip.text()).toBe("3");
            expect(chip.attributes("aria-hidden")).toBe("true");
            expect(chip.classes()).not.toContain("some");
        });

        it("shows held / total, tinted, when part is held", () => {
            useExplorerStore().addToBasket(KEYS[0]);
            useExplorerStore().addToBasket(KEYS[1]);
            const chip = mountAll().get(".chip");
            expect(chip.text()).toBe("2 / 3");
            expect(chip.classes()).toContain("some");
        });

        it("shows total / total when all are held", () => {
            useExplorerStore().addManyToBasket(KEYS);
            expect(mountAll().get(".chip").text()).toBe("3 / 3");
        });

        it("is not drawn on a compact checkbox", () => {
            expect(mountAll(KEYS, true).find(".chip").exists()).toBe(false);
        });
    });

    describe("when the Selection cannot take the keys", () => {
        beforeEach(() => {
            useExplorerStore().addManyToBasket(
                Array.from({ length: 29 }, (_, n) => analysisKey(uuid(n + 10))),
            );
        });

        it("keeps the reason out of sight and described by a hidden text", () => {
            const wrapper = mountAll();
            expect(wrapper.find(".reason").exists()).toBe(false);
            const hidden = wrapper.get(".visually-hidden");
            expect(hidden.text()).toBe("3 analyses to add, 1 place left");
            expect(wrapper.get("input").attributes("aria-describedby")).toBe(
                hidden.attributes("id"),
            );
        });

        it("is described by the notice it is given, with no text of its own", () => {
            const wrapper = mountAll(KEYS, false, { describedBy: "notice-1" });
            expect(wrapper.get("input").attributes("aria-describedby")).toBe(
                "notice-1",
            );
            expect(wrapper.find(".visually-hidden").exists()).toBe(false);
        });

        it("announces once that nothing was added when activated", async () => {
            const wrapper = mountAll();
            await wrapper.get("input").trigger("click");
            expect(announce).toHaveBeenCalledTimes(1);
            expect(announce).toHaveBeenCalledWith(
                "Not enough room: 3 to add, 1 place left. Nothing was added.",
            );
            expect(useExplorerStore().basket).toHaveLength(29);
        });

        it("announces the full Selection when no place is left", async () => {
            useExplorerStore().addToBasket(analysisKey(uuid(99)));
            const wrapper = mountAll();
            await wrapper.get("input").trigger("click");
            expect(announce).toHaveBeenCalledWith(
                "Selection full (30 / 30): nothing was added.",
            );
        });

        it("hides the label of a compact checkbox but keeps the tooltip", () => {
            const wrapper = mountAll(KEYS, true);
            expect(wrapper.get(".text").classes()).toContain("visually-hidden");
            expect(wrapper.get("label").attributes("title")).toBe(
                "Select all: the 3 analyses on this page\n3 analyses to add, 1 place left",
            );
        });
    });

    it("speaks the addition once when it adds", async () => {
        await mountAll().get("input").trigger("click");
        expect(announce).toHaveBeenCalledTimes(1);
        expect(announce.mock.calls[0][0]).toContain("3 analyses added");
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
