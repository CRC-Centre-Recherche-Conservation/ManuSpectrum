import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import ReturnPill from "@/manuspectrum/pages/AnalysisExplorer/components/ReturnPill.vue";

function mountPill(label = "Results · 3 documents") {
    return mount(ReturnPill, { props: { label } });
}

describe("ReturnPill", () => {
    it("is a button named by its label", () => {
        const button = mountPill().get("button.return-pill");
        expect(button.attributes("type")).toBe("button");
        expect(button.text()).toBe("Results · 3 documents");
    });

    it("draws a decorative left arrow", () => {
        const icon = mountPill().get("svg.icon");
        expect(icon.attributes("aria-hidden")).toBe("true");
        expect(icon.findAll("path").length).toBeGreaterThan(0);
    });

    it("emits click", async () => {
        const wrapper = mountPill();
        await wrapper.get("button").trigger("click");
        expect(wrapper.emitted("click")).toHaveLength(1);
    });

    it("exposes its button for a screen that moves the focus to it", () => {
        const wrapper = mountPill();
        expect(wrapper.vm.element).toBe(wrapper.get("button").element);
    });
});
