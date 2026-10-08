import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";

import PeriodRuleMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/PeriodRuleMenu.vue";

import type { PeriodMatch } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function mountMenu(match: PeriodMatch = "overlap") {
    return mount(PeriodRuleMenu, { attachTo: document.body, props: { match } });
}

describe("PeriodRuleMenu", () => {
    it("offers the rule in a menu button, closed at first", async () => {
        const wrapper = mountMenu();
        const button = wrapper.get("[data-action=rule]");
        expect(button.attributes("aria-haspopup")).toBe("menu");
        expect(button.attributes("aria-expanded")).toBe("false");
        expect(wrapper.find("[role=menu]").exists()).toBe(false);
        await button.trigger("click");
        expect(button.attributes("aria-expanded")).toBe("true");
        const items = wrapper.findAll("[role=menuitemradio]");
        expect(items.map((item) => item.get(".rule-name").text())).toEqual([
            "Overlaps the period",
            "Entirely within the period",
        ]);
        expect(items.map((item) => item.get(".rule-detail").text())).toEqual([
            "Keeps documents whose dates touch the period",
            "Keeps documents dated entirely inside the period",
        ]);
        expect(items.map((item) => item.attributes("aria-checked"))).toEqual([
            "true",
            "false",
        ]);
        expect(button.attributes("aria-controls")).toBe(
            wrapper.get("[role=menu]").attributes("id"),
        );
        wrapper.unmount();
    });

    it("emits the rule chosen and closes", async () => {
        const wrapper = mountMenu();
        await wrapper.get("[data-action=rule]").trigger("click");
        await wrapper.findAll("[role=menuitemradio]")[1].trigger("click");
        expect(wrapper.emitted("change")).toEqual([["within"]]);
        expect(wrapper.find("[role=menu]").exists()).toBe(false);
        wrapper.unmount();
    });

    it("does not emit when the rule already held is chosen", async () => {
        const wrapper = mountMenu();
        await wrapper.get("[data-action=rule]").trigger("click");
        await wrapper.findAll("[role=menuitemradio]")[0].trigger("click");
        expect(wrapper.emitted("change")).toBeUndefined();
        wrapper.unmount();
    });

    it("opens with ArrowDown, moves with the arrows and closes with Escape, giving the focus back", async () => {
        const wrapper = mountMenu();
        const button = wrapper.get<HTMLButtonElement>("[data-action=rule]");
        await button.trigger("keydown", { key: "ArrowDown" });
        await nextTick();
        const items = wrapper.findAll<HTMLButtonElement>(
            "[role=menuitemradio]",
        );
        expect(document.activeElement).toBe(items[0].element);
        await wrapper.get("[role=menu]").trigger("keydown", {
            key: "ArrowDown",
        });
        expect(document.activeElement).toBe(items[1].element);
        await wrapper.get("[role=menu]").trigger("keydown", {
            key: "Escape",
        });
        expect(wrapper.find("[role=menu]").exists()).toBe(false);
        expect(document.activeElement).toBe(button.element);
        wrapper.unmount();
    });
});
