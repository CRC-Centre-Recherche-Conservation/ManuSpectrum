import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CollapsibleSection from "@/manuspectrum/pages/AnalysisExplorer/components/CollapsibleSection.vue";

function mountSection(open: boolean, summary?: string) {
    return mount(CollapsibleSection, {
        props: { title: "Cite", open, summary },
        slots: {
            default: "<p class='body'>The body</p>",
            actions: "<button class='act' type='button'>Copy</button>",
        },
    });
}

describe("CollapsibleSection", () => {
    it("names its toggle by the title and reports its state", () => {
        const wrapper = mountSection(false);
        const toggle = wrapper.get("button.toggle");
        expect(toggle.text()).toContain("Cite");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(
            mountSection(true).get("button.toggle").attributes("aria-expanded"),
        ).toBe("true");
    });

    it("points its toggle at the body it hides", () => {
        const wrapper = mountSection(false);
        const controls = wrapper
            .get("button.toggle")
            .attributes("aria-controls");
        expect(controls).toBeTruthy();
        expect(wrapper.get(".content").attributes("id")).toBe(controls);
    });

    it("hides the body when closed and shows it when open", () => {
        expect(mountSection(false).get(".content").isVisible()).toBe(false);
        expect(mountSection(true).get(".content").isVisible()).toBe(true);
    });

    it("keeps the actions in the header, closed or open", () => {
        for (const open of [false, true]) {
            const wrapper = mountSection(open);
            expect(wrapper.get(".head .act").isVisible()).toBe(true);
            expect(wrapper.get(".content").find(".act").exists()).toBe(false);
        }
    });

    it("shows the one-line summary only while closed", () => {
        expect(mountSection(false, "Smith 2024").find(".summary").text()).toBe(
            "Smith 2024",
        );
        expect(mountSection(true, "Smith 2024").find(".summary").exists()).toBe(
            false,
        );
    });

    it("emits toggle with the next state", async () => {
        const wrapper = mountSection(false);
        await wrapper.get("button.toggle").trigger("click");
        expect(wrapper.emitted("toggle")).toEqual([[true]]);
        await wrapper.setProps({ open: true });
        await wrapper.get("button.toggle").trigger("click");
        expect(wrapper.emitted("toggle")?.[1]).toEqual([false]);
    });
});
