import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";

import PeriodFacet from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/PeriodFacet.vue";

import { rangeFacet } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    PeriodEvent,
    PeriodMatch,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const FIELD_DELAY_MS = 300;

interface Held {
    period: [number, number] | null;
    match: PeriodMatch;
    event: PeriodEvent;
    undated: boolean;
}

function mountFacet(held: Partial<Held> = {}) {
    return mount(PeriodFacet, {
        props: {
            facet: rangeFacet(),
            period: null,
            match: "overlap",
            event: "production",
            undated: false,
            ...held,
        },
    });
}

function field(wrapper: ReturnType<typeof mountFacet>, name: "from" | "to") {
    return wrapper.find<HTMLInputElement>(`input.field-${name}`);
}

/** Types in a field without leaving it: an `input` event only. */
async function type(
    wrapper: ReturnType<typeof mountFacet>,
    name: "from" | "to",
    text: string,
): Promise<void> {
    const input = field(wrapper, name);
    input.element.value = text;
    await input.trigger("input");
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("PeriodFacet event", () => {
    it("offers Production, checked, and Modification, disabled with its reason", () => {
        const wrapper = mountFacet();
        const group = wrapper.find("[role=radiogroup].event");
        expect(group.attributes("aria-label")).toBe("Dated event");
        const [production, modification] = group.findAll("[role=radio]");
        expect(production.text()).toBe("Production");
        expect(production.attributes("aria-checked")).toBe("true");
        expect(modification.text()).toBe("Modification");
        expect(modification.attributes("aria-checked")).toBe("false");
        expect(modification.attributes("aria-disabled")).toBe("true");
        const reason = wrapper.find(
            `#${modification.attributes("aria-describedby")}`,
        );
        expect(reason.text()).toBe("No data for this event yet");
    });

    it("does not emit when the disabled Modification is chosen", async () => {
        const wrapper = mountFacet();
        await wrapper.findAll("[role=radio]")[1].trigger("click");
        expect(wrapper.emitted("change")).toBeUndefined();
    });

    it("goes back to Production from a Modification the address asked for", async () => {
        const wrapper = mountFacet({ event: "modification" });
        const [production, modification] = wrapper.findAll("[role=radio]");
        expect(modification.attributes("aria-checked")).toBe("true");
        await production.trigger("click");
        expect(wrapper.emitted("change")?.[0]).toEqual([
            {
                period: null,
                match: "overlap",
                event: "production",
                undated: false,
            },
        ]);
    });
});

describe("PeriodFacet bounds", () => {
    it("rests on the bounds with empty fields when no period is held", () => {
        const wrapper = mountFacet();
        const [low, high] = wrapper.findAll("[role=slider]");
        expect(low.attributes("aria-valuenow")).toBe("1030");
        expect(high.attributes("aria-valuenow")).toBe("1465");
        expect(field(wrapper, "from").element.value).toBe("");
        expect(field(wrapper, "to").element.value).toBe("");
        expect(field(wrapper, "from").attributes("placeholder")).toBe("1030");
        expect(field(wrapper, "to").attributes("placeholder")).toBe("1465");
        expect(
            wrapper
                .findAll("button.century")
                .every(
                    (button) => button.attributes("aria-pressed") === "false",
                ),
        ).toBe(true);
    });

    it("shows the held period in the slider, the fields and the histogram alike", () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        const [low, high] = wrapper.findAll("[role=slider]");
        expect(low.attributes("aria-valuenow")).toBe("1201");
        expect(high.attributes("aria-valuenow")).toBe("1400");
        expect(field(wrapper, "from").element.value).toBe("1201");
        expect(field(wrapper, "to").element.value).toBe("1400");
        expect(
            wrapper
                .findAll("button.century")
                .map((button) => button.attributes("aria-pressed")),
        ).toEqual(["false", "false", "true", "true", "false"]);
    });

    it("follows the slider while it is dragged, then emits the period at its end", async () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        const slider = wrapper.findComponent({ name: "RangeSlider" });
        slider.vm.$emit("input", [1250, 1400]);
        await wrapper.vm.$nextTick();
        expect(field(wrapper, "from").element.value).toBe("1250");
        expect(wrapper.emitted("change")).toBeUndefined();
        slider.vm.$emit("change", [1250, 1400]);
        expect(wrapper.emitted("change")?.[0]).toEqual([
            {
                period: [1250, 1400],
                match: "overlap",
                event: "production",
                undated: false,
            },
        ]);
    });
});

describe("PeriodFacet period equal to the bounds", () => {
    it("does not emit a null period when none is held and the slider ends on the bounds", () => {
        const wrapper = mountFacet();
        wrapper
            .findComponent({ name: "RangeSlider" })
            .vm.$emit("change", [1030, 1465]);
        expect(wrapper.emitted("change")).toBeUndefined();
    });

    it("clears the period when the slider ends on the bounds", () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        wrapper
            .findComponent({ name: "RangeSlider" })
            .vm.$emit("change", [1030, 1465]);
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: null,
        });
    });

    it("clears the period when the fields are typed back to the bounds", async () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        await type(wrapper, "from", "1030");
        await type(wrapper, "to", "1465");
        await field(wrapper, "to").trigger("change");
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: null,
        });
    });

    it("sends nothing when the fields are typed to the bounds with no period held", async () => {
        const wrapper = mountFacet();
        await type(wrapper, "from", "1030");
        await type(wrapper, "to", "1465");
        await field(wrapper, "to").trigger("change");
        expect(wrapper.emitted("change")).toBeUndefined();
    });
});

describe("PeriodFacet fields", () => {
    it("waits 300 ms after a typed year, then emits the period with the other bound at its end", async () => {
        const wrapper = mountFacet();
        await type(wrapper, "from", "1100");
        vi.advanceTimersByTime(FIELD_DELAY_MS - 1);
        expect(wrapper.emitted("change")).toBeUndefined();
        vi.advanceTimersByTime(1);
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: [1100, 1465],
        });
    });

    it("brings a year outside the bounds back to them and says so", async () => {
        const wrapper = mountFacet();
        await type(wrapper, "from", "900");
        vi.advanceTimersByTime(FIELD_DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(field(wrapper, "from").element.value).toBe("1030");
        expect(wrapper.find("[role=status]").text()).toBe(
            "From brought back to 1030",
        );
        await type(wrapper, "to", "1600");
        vi.advanceTimersByTime(FIELD_DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(field(wrapper, "to").element.value).toBe("1465");
        expect(wrapper.find("[role=status]").text()).toBe(
            "To brought back to 1465",
        );
    });

    it("keeps the lower year from passing the higher one", async () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        await type(wrapper, "from", "1450");
        vi.advanceTimersByTime(FIELD_DELAY_MS);
        await wrapper.vm.$nextTick();
        expect(field(wrapper, "from").element.value).toBe("1400");
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: [1400, 1400],
        });
    });

    it("commits at once on a change event, and an emptied pair clears the period", async () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        await type(wrapper, "from", "");
        await field(wrapper, "from").trigger("change");
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: [1030, 1400],
        });
        await wrapper.setProps({ period: [1030, 1400] });
        await type(wrapper, "from", "");
        await type(wrapper, "to", "");
        await field(wrapper, "to").trigger("change");
        expect(wrapper.emitted("change")?.[1][0]).toMatchObject({
            period: null,
        });
    });
});

describe("PeriodFacet histogram and options", () => {
    it("selects a century, and the same century again clears the period", async () => {
        const wrapper = mountFacet();
        await wrapper.findAll("button.century")[3].trigger("click");
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: [1301, 1400],
        });
        const again = mountFacet({ period: [1301, 1400] });
        await again.findAll("button.century")[3].trigger("click");
        expect(again.emitted("change")?.[0][0]).toMatchObject({ period: null });
    });

    it("clamps a century that reaches past the bounds", async () => {
        const wrapper = mountFacet();
        await wrapper.findAll("button.century")[0].trigger("click");
        await wrapper.findAll("button.century")[4].trigger("click");
        expect(
            (wrapper.emitted("change") ?? []).map(
                (call) => (call[0] as Held).period,
            ),
        ).toEqual([
            [1030, 1100],
            [1401, 1465],
        ]);
    });

    it("chooses between overlapping the period and lying entirely within it", async () => {
        const wrapper = mountFacet({ period: [1201, 1400] });
        const radios = wrapper.findAll<HTMLInputElement>("input[name$=match]");
        expect(
            wrapper.findAll(".match .text").map((text) => text.text()),
        ).toEqual(["Overlaps the period", "Entirely within the period"]);
        expect(radios.map((radio) => radio.element.checked)).toEqual([
            true,
            false,
        ]);
        await radios[1].setValue(true);
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            period: [1201, 1400],
            match: "within",
        });
    });

    it("counts the undated rows in a checkbox that is off by default", async () => {
        const wrapper = mountFacet();
        const box = wrapper.find<HTMLInputElement>("input.undated");
        expect(box.element.checked).toBe(false);
        expect(wrapper.find(".undated-label").text()).toBe(
            "Include undated (3)",
        );
        await box.setValue(true);
        expect(wrapper.emitted("change")?.[0][0]).toMatchObject({
            undated: true,
        });
    });
});
