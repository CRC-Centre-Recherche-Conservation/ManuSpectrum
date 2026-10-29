import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";

describe("BusyStatus", () => {
    it("says loading on a first load, updating on a reload, nothing when idle", async () => {
        const wrapper = mount(BusyStatus, {
            props: { busy: true, first: true },
        });
        expect(wrapper.attributes("role")).toBe("status");
        expect(wrapper.text()).toBe("Loading…");
        await wrapper.setProps({ first: false });
        expect(wrapper.text()).toBe("Updating…");
        await wrapper.setProps({ busy: false });
        expect(wrapper.text()).toBe("");
    });
});
