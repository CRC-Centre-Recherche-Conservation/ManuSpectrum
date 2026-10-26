import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import ScaleBadge from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ScaleBadge.vue";

import type { VueWrapper } from "@vue/test-utils";

let wrapper: VueWrapper | null = null;

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

describe("ScaleBadge", () => {
    it("says the scale differs and gives both served sizes in its description", () => {
        wrapper = mount(ScaleBadge, {
            props: {
                size: { w: 600, h: 1202 },
                against: { w: 1529, h: 2405 },
            },
        });
        expect(wrapper.text()).toContain("Different scale");
        const chip = wrapper.find(".scale-badge-chip");
        const description = wrapper.find(
            `#${chip.attributes("aria-describedby")}`,
        );
        expect(description.text()).toBe("600 × 1202 px against 1529 × 2405 px");
    });

    it("can be reached by keyboard", () => {
        wrapper = mount(ScaleBadge, {
            props: { size: { w: 1, h: 2 }, against: { w: 3, h: 4 } },
        });
        expect(wrapper.find(".scale-badge-chip").attributes("tabindex")).toBe(
            "0",
        );
    });
});
