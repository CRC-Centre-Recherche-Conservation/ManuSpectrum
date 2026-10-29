import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";

describe("LoadingSpinner", () => {
    it("is decorative and takes its size from a prop", () => {
        const wrapper = mount(LoadingSpinner, { props: { size: "medium" } });
        expect(wrapper.attributes("aria-hidden")).toBe("true");
        expect(wrapper.classes()).toContain("loading-spinner--medium");
        expect(mount(LoadingSpinner).classes()).toContain(
            "loading-spinner--small",
        );
    });
});
