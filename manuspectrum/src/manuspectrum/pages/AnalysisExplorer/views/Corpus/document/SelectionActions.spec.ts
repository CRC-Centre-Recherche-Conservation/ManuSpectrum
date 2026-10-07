import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import SelectionActions from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SelectionActions.vue";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisKey,
    characterizationKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const OWN = characterizationKey(uuid(1));
const EVIDENCE = [analysisKey(uuid(2)), analysisKey(uuid(3))];

function mountActions(withSecondary = true) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const announce = vi.fn();
    const wrapper = mount(SelectionActions, {
        attachTo: document.body,
        props: {
            title: "Add to the Selection",
            primary: { keys: [OWN, ...EVIDENCE], label: "With its 2 analyses" },
            secondary: withSecondary
                ? { keys: [OWN], label: "The material alone" }
                : null,
        },
        global: {
            plugins: [pinia],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        },
    });
    return { wrapper, announce, store: useExplorerStore() };
}

describe("SelectionActions", () => {
    it("is a group named by its title, the primary button first", () => {
        const { wrapper } = mountActions();
        const group = wrapper.get('[role="group"]');
        const titleId = group.attributes("aria-labelledby")!;
        expect(wrapper.get(`#${titleId}`).text()).toBe("Add to the Selection");
        const buttons = group.findAll("button");
        expect(buttons.map((button) => button.text())).toEqual([
            "With its 2 analyses",
            "The material alone",
        ]);
        expect(buttons[0].classes()).toContain("primary");
        expect(buttons[1].classes()).toContain("secondary");
    });

    it("adds every key of the primary button", async () => {
        const { wrapper, store, announce } = mountActions();
        await wrapper.get("button.primary").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([
            OWN,
            ...EVIDENCE,
        ]);
        expect(announce).toHaveBeenCalled();
    });

    it("adds the material alone from the secondary button", async () => {
        const { wrapper, store } = mountActions();
        await wrapper.get("button.secondary").trigger("click");
        expect(store.basket.map((item) => item.key)).toEqual([OWN]);
    });

    it("says where everything is once the primary keys are held", async () => {
        const { wrapper } = mountActions();
        await wrapper.get("button.primary").trigger("click");
        expect(wrapper.find("button").exists()).toBe(false);
        expect(wrapper.get(".held").text()).toBe(
            "In the Selection: A1 (with A2, A3)",
        );
    });

    it("says only the material's slot when the material alone is held", async () => {
        const { wrapper } = mountActions();
        await wrapper.get("button.secondary").trigger("click");
        expect(wrapper.get(".held").text()).toBe("In the Selection: A1");
        expect(wrapper.find("button.secondary").exists()).toBe(false);
        expect(wrapper.find("button.primary").exists()).toBe(true);
    });

    it("moves the focus to the held line that replaces the buttons", async () => {
        const { wrapper } = mountActions();
        (wrapper.get("button.primary").element as HTMLButtonElement).focus();
        await wrapper.get("button.primary").trigger("click");
        await wrapper.vm.$nextTick();
        expect(document.activeElement).toBe(wrapper.get(".held").element);
    });

    it("disables all or nothing, with the reason, when the keys do not fit", async () => {
        const { wrapper, store } = mountActions();
        store.addManyToBasket(
            Array.from({ length: 28 }, (_, n) => analysisKey(uuid(100 + n))),
        );
        await wrapper.vm.$nextTick();
        const primary = wrapper.get("button.primary");
        expect(primary.attributes("disabled")).toBeDefined();
        const reasonId = primary.attributes("aria-describedby")!;
        expect(wrapper.get(`#${reasonId}`).text()).toBe(
            "3 items, 2 places left",
        );
        expect(
            wrapper.get("button.secondary").attributes("disabled"),
        ).toBeUndefined();
        await primary.trigger("click");
        expect(store.basket).toHaveLength(28);
    });

    it("shows a single primary button without a secondary one", () => {
        const { wrapper } = mountActions(false);
        expect(wrapper.findAll("button")).toHaveLength(1);
        expect(wrapper.get("button").classes()).toContain("primary");
    });
});
