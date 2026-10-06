import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import SwitchButton from "@/manuspectrum/pages/AnalysisExplorer/components/SwitchButton.vue";

function mountSwitch(props: { checked: boolean; disabled?: boolean }) {
    return mount(SwitchButton, {
        props,
        attrs: { "data-action": "demo", title: "Why" },
        slots: { default: "Link zoom" },
    });
}

describe("SwitchButton", () => {
    it("is a switch named by its text, carrying the attributes it is given", () => {
        const view = mountSwitch({ checked: false });
        const button = view.find("button");
        expect(button.attributes("role")).toBe("switch");
        expect(button.attributes("aria-checked")).toBe("false");
        expect(button.attributes("data-action")).toBe("demo");
        expect(button.attributes("title")).toBe("Why");
        expect(button.text()).toBe("Link zoom");
    });

    it("says it is on", () => {
        const view = mountSwitch({ checked: true });
        expect(view.find("button").attributes("aria-checked")).toBe("true");
    });

    it("emits toggle on a click, disabled or not, and says it is disabled", async () => {
        const view = mountSwitch({ checked: false, disabled: true });
        const button = view.find("button");
        expect(button.attributes("aria-disabled")).toBe("true");
        await button.trigger("click");
        expect(view.emitted("toggle")).toHaveLength(1);
    });
});
