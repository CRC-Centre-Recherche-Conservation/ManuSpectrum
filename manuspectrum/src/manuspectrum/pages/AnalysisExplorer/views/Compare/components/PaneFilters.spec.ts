import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import PaneFilters from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PaneFilters.vue";

import { NEUTRAL_FILTERS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { VueWrapper } from "@vue/test-utils";

let wrapper: VueWrapper | null = null;

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

function mountFilters(filters = { ...NEUTRAL_FILTERS }): VueWrapper {
    wrapper = mount(PaneFilters, { props: { filters, letter: "B" } });
    return wrapper;
}

describe("PaneFilters", () => {
    it("shows each value on a labelled 0 to 200 range", () => {
        const view = mountFilters({
            brightness: 120,
            contrast: 90,
            saturation: 100,
            greyscale: false,
        });
        const ranges = view.findAll('input[type="range"]');
        expect(ranges).toHaveLength(3);
        expect(ranges.map((range) => range.attributes("min"))).toEqual([
            "0",
            "0",
            "0",
        ]);
        expect(ranges.map((range) => range.attributes("max"))).toEqual([
            "200",
            "200",
            "200",
        ]);
        expect(
            ranges.map((range) => (range.element as HTMLInputElement).value),
        ).toEqual(["120", "90", "100"]);
        expect(view.find("label").text()).toBe("Brightness");
        expect(view.find("fieldset").attributes("aria-label")).toBe(
            "Filters of pane B",
        );
    });

    it("emits the field changed, as a number", async () => {
        const view = mountFilters();
        await view.findAll('input[type="range"]')[1].setValue("150");
        expect(view.emitted("change")).toEqual([[{ contrast: 150 }]]);
    });

    it("emits the greyscale switch", async () => {
        const view = mountFilters();
        await view.find('input[type="checkbox"]').setValue(true);
        expect(view.emitted("change")).toEqual([[{ greyscale: true }]]);
    });

    it("has nothing to reset while every value is neutral", () => {
        const view = mountFilters();
        expect(
            view.find('[data-action="reset"]').attributes("disabled"),
        ).toBeDefined();
    });

    it("emits a reset and an apply to every pane", async () => {
        const view = mountFilters({ ...NEUTRAL_FILTERS, greyscale: true });
        await view.find('[data-action="reset"]').trigger("click");
        await view.find('[data-action="apply-all"]').trigger("click");
        expect(view.emitted("reset")).toHaveLength(1);
        expect(view.emitted("apply-all")).toHaveLength(1);
    });
});
