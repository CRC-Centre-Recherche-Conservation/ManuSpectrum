import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import HiddenWindowsMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/HiddenWindowsMenu.vue";

import type { VueWrapper } from "@vue/test-utils";
import type { HiddenWindowEntry } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

const XRF: HiddenWindowEntry = { id: "auto:xy:xrf", title: "XRF", added: 0 };
const MAPS: HiddenWindowEntry = {
    id: "auto:maps",
    title: "Element maps",
    added: 0,
};

let wrapper: VueWrapper | null = null;

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

function mountMenu(windows: HiddenWindowEntry[]): VueWrapper {
    wrapper = mount(HiddenWindowsMenu, {
        attachTo: document.body,
        props: { windows },
    });
    return wrapper;
}

function button(view: VueWrapper) {
    return view.find("button.hidden-windows-button");
}

function items(view: VueWrapper) {
    return view.findAll('[role="menuitem"]');
}

describe("HiddenWindowsMenu", () => {
    it("is there, disabled but focusable, while no window is hidden", async () => {
        const view = mountMenu([]);
        expect(button(view).text()).toBe("Hidden windows (0)");
        expect(button(view).attributes("aria-disabled")).toBe("true");
        expect(button(view).attributes("disabled")).toBeUndefined();
        await button(view).trigger("click");
        await button(view).trigger("keydown", { key: "ArrowDown" });
        expect(button(view).attributes("aria-expanded")).toBe("false");
        expect(view.find('[role="menu"]').exists()).toBe(false);
    });

    it("lists each hidden window to show, with the spectra it gained", async () => {
        const view = mountMenu([XRF, { ...MAPS, added: 2 }]);
        expect(button(view).text()).toBe("Hidden windows (2)");
        expect(button(view).attributes("aria-haspopup")).toBe("menu");
        await button(view).trigger("click");
        expect(view.find('[role="menu"]').attributes("aria-labelledby")).toBe(
            button(view).attributes("id"),
        );
        expect(items(view).map((item) => item.text())).toEqual([
            "Show XRF",
            "Show Element maps2 spectra added",
        ]);
        expect(items(view)[0].find(".badge").exists()).toBe(false);
        expect(items(view)[1].find(".badge").text()).toBe("2 spectra added");
        expect(document.activeElement).toBe(items(view)[0].element);
    });

    it("opens on the last entry with ArrowUp and closes on Escape", async () => {
        const view = mountMenu([XRF, MAPS]);
        await button(view).trigger("keydown", { key: "ArrowUp" });
        expect(document.activeElement).toBe(items(view)[1].element);
        await view.find('[role="menu"]').trigger("keydown", {
            key: "Escape",
        });
        expect(view.find('[role="menu"]').exists()).toBe(false);
        expect(document.activeElement).toBe(button(view).element);
    });

    it("emits the window chosen and closes", async () => {
        const view = mountMenu([XRF, MAPS]);
        await button(view).trigger("click");
        await items(view)[1].trigger("click");
        expect(view.emitted("show")).toEqual([[{ id: MAPS.id }]]);
        expect(view.find('[role="menu"]').exists()).toBe(false);
    });

    it("closes when the last hidden window goes", async () => {
        const view = mountMenu([XRF]);
        await button(view).trigger("click");
        await view.setProps({ windows: [] });
        expect(view.find('[role="menu"]').exists()).toBe(false);
        expect(button(view).attributes("aria-expanded")).toBe("false");
    });
});
