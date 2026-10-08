import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import XrfLensMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XrfLensMenu.vue";

import type { VueWrapper } from "@vue/test-utils";
import type { AnodeRow } from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfLens.ts";

let wrapper: VueWrapper | null = null;

const INFERRED: AnodeRow = {
    analysis: "an-1",
    slot: 0,
    name: "Analysis one",
    inferred: "Ag",
    chosen: null,
};
const OPEN: AnodeRow = {
    analysis: "an-2",
    slot: 1,
    name: "Analysis two",
    inferred: null,
    chosen: "Rh",
};

function mountMenu(
    props: Partial<InstanceType<typeof XrfLensMenu>["$props"]> = {},
): VueWrapper {
    wrapper = mount(XrfLensMenu, {
        attachTo: document.body,
        props: {
            declared: true,
            instrument: true,
            overlaps: false,
            detector: "sdd",
            anodes: [INFERRED, OPEN],
            version: "4.5.8",
            ...props,
        },
    });
    return wrapper;
}

async function open(view: VueWrapper): Promise<void> {
    await view.find('[data-action="xrf-settings"]').trigger("click");
    await view.vm.$nextTick();
}

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

describe("XrfLensMenu", () => {
    it("is a popover button named « XRF lens settings », closed at first", () => {
        const view = mountMenu();
        const button = view.find('[data-action="xrf-settings"]');
        expect(button.attributes("data-popover")).toBe("xrf-settings");
        expect(button.attributes("aria-haspopup")).toBe("dialog");
        expect(button.attributes("aria-expanded")).toBe("false");
        expect(view.find(".panel").exists()).toBe(false);
    });

    it("opens on the first control, and Escape closes it and gives the focus back", async () => {
        const view = mountMenu();
        await open(view);
        const button = view.find('[data-action="xrf-settings"]');
        expect(button.attributes("aria-expanded")).toBe("true");
        expect(button.attributes("aria-controls")).toBe(
            view.find(".panel").attributes("id"),
        );
        expect(document.activeElement).toBe(
            view.find('input[data-layer="declared"]').element,
        );
        await view.find(".panel").trigger("keydown", { key: "Escape" });
        expect(view.find(".panel").exists()).toBe(false);
        expect(document.activeElement).toBe(button.element);
    });

    it("toggles the three layers, each shown as it stands", async () => {
        const view = mountMenu();
        await open(view);
        const boxes = view.findAll("input[data-layer]");
        expect(
            boxes.map((box) => [
                box.attributes("data-layer"),
                (box.element as HTMLInputElement).checked,
            ]),
        ).toEqual([
            ["declared", true],
            ["instrument", true],
            ["overlaps", false],
        ]);
        await boxes[2].setValue(true);
        expect(view.emitted("update-layer")).toEqual([
            [{ name: "overlaps", value: true }],
        ]);
    });

    it("chooses the detector resolution", async () => {
        const view = mountMenu();
        await open(view);
        const select = view.find('select[data-field="detector"]');
        expect(select.findAll("option").map((o) => o.text())).toEqual([
            "SDD (≈ 140 eV at Mn Kα)",
            "Si-PIN (≈ 180 eV at Mn Kα)",
        ]);
        await select.setValue("si-pin");
        expect(view.emitted("update-detector")).toEqual([
            [{ detector: "si-pin" }],
        ]);
    });

    it("shows an anode the conditions gave as inferred, with no choice, and a select for the others", async () => {
        const view = mountMenu();
        await open(view);
        const inferred = view.find('p[data-analysis="an-1"]');
        expect(inferred.text()).toContain("A1 · Analysis one");
        expect(inferred.text()).toContain("Ag, inferred from the conditions");
        expect(view.find('select[data-analysis="an-1"]').exists()).toBe(false);
        const select = view.find('select[data-analysis="an-2"]');
        expect((select.element as HTMLSelectElement).value).toBe("Rh");
        expect(select.findAll("option").map((o) => o.text())).toEqual([
            "Unknown",
            "Rh",
            "Ag",
            "W",
            "Mo",
            "Cr",
            "Cu",
            "Pd",
            "Ti",
            "Au",
            "Re",
            "None (no tube)",
        ]);
    });

    it("reports a manual anode, no tube, and a return to unknown", async () => {
        const view = mountMenu();
        await open(view);
        const select = view.find('select[data-analysis="an-2"]');
        await select.setValue("W");
        await select.setValue("none");
        await select.setValue("");
        expect(view.emitted("update-anode")).toEqual([
            [{ analysis: "an-2", anode: "W" }],
            [{ analysis: "an-2", anode: "none" }],
            [{ analysis: "an-2", anode: null }],
        ]);
    });

    it("credits the line table, once it is loaded", async () => {
        const view = mountMenu();
        await open(view);
        expect(view.find(".attribution").text()).toBe(
            "Lines: XrayDB 4.5.8 (CC0), Elam, Ravel & Sieber 2002",
        );
        await view.setProps({ version: "" });
        expect(view.find(".attribution").exists()).toBe(false);
    });
});
