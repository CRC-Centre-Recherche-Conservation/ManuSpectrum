import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";

describe("UnavailableState", () => {
    it("says the same thing for every 404 and offers the way home", async () => {
        const wrapper = mount(UnavailableState, {
            props: { status: "unavailable" },
        });
        expect(wrapper.text()).toContain(
            "This item is not available. It may not exist, or it may not be public.",
        );
        expect(wrapper.find(".retry").exists()).toBe(false);
        await wrapper.find(".home").trigger("click");
        expect(wrapper.emitted("home")).toHaveLength(1);
    });

    it("keeps an error state with Retry", async () => {
        const wrapper = mount(UnavailableState, { props: { status: "error" } });
        expect(wrapper.text()).toContain(
            "The service is not answering right now.",
        );
        await wrapper.find(".retry").trigger("click");
        expect(wrapper.emitted("retry")).toHaveLength(1);
    });
});
