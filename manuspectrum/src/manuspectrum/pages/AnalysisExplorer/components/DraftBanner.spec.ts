import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";

describe("DraftBanner", () => {
    it("renders nothing without drafts", () => {
        const wrapper = mount(DraftBanner, {
            props: { count: 0, scope: "results" },
        });
        expect(wrapper.find(".draft-banner").exists()).toBe(false);
    });

    it("counts the drafts of the whole result set in the results scope", () => {
        const wrapper = mount(DraftBanner, {
            props: { count: 3, scope: "results" },
        });
        expect(wrapper.find(".draft-banner").text()).toBe(
            "3 drafts in these results; they are marked “Draft”.",
        );
    });

    it("counts the drafts of the page in the page scope", () => {
        const wrapper = mount(DraftBanner, {
            props: { count: 1, scope: "page" },
        });
        expect(wrapper.find(".draft-banner").text()).toBe(
            "1 draft on this page; it is marked “Draft”.",
        );
    });
});
