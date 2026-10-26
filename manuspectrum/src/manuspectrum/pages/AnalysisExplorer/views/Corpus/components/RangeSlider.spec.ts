import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import RangeSlider from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RangeSlider.vue";

function mountSlider(value: [number, number] = [1200, 1400]) {
    return mount(RangeSlider, { props: { min: 1000, max: 1500, value } });
}

function thumbs(wrapper: ReturnType<typeof mountSlider>) {
    return wrapper.findAll("[role=slider]");
}

describe("RangeSlider", () => {
    it("has two named sliders with their bounds, value and century", () => {
        const wrapper = mountSlider();
        const [low, high] = thumbs(wrapper);
        expect(low.attributes("aria-label")).toBe("Earliest year");
        expect(high.attributes("aria-label")).toBe("Latest year");
        expect(low.attributes("aria-valuemin")).toBe("1000");
        expect(low.attributes("aria-valuemax")).toBe("1400");
        expect(low.attributes("aria-valuenow")).toBe("1200");
        expect(high.attributes("aria-valuemin")).toBe("1200");
        expect(high.attributes("aria-valuemax")).toBe("1500");
        expect(high.attributes("aria-valuenow")).toBe("1400");
        expect(low.attributes("aria-valuetext")).toBe("1200, 12th century");
        expect(high.attributes("aria-valuetext")).toBe("1400, 14th century");
        expect(low.attributes("tabindex")).toBe("0");
    });

    it("moves a year per arrow, 25 per Page key, to a bound on Home and End", async () => {
        const wrapper = mountSlider();
        const [low, high] = thumbs(wrapper);
        await low.trigger("keydown", { key: "ArrowRight" });
        await low.trigger("keydown", { key: "ArrowUp" });
        await low.trigger("keydown", { key: "ArrowLeft" });
        await low.trigger("keydown", { key: "PageUp" });
        await low.trigger("keydown", { key: "PageDown" });
        await low.trigger("keydown", { key: "Home" });
        await high.trigger("keydown", { key: "End" });
        await high.trigger("keydown", { key: "ArrowDown" });
        await high.trigger("keydown", { key: "PageDown" });
        expect(wrapper.emitted("change")).toEqual([
            [[1201, 1400]],
            [[1201, 1400]],
            [[1199, 1400]],
            [[1225, 1400]],
            [[1175, 1400]],
            [[1000, 1400]],
            [[1200, 1500]],
            [[1200, 1399]],
            [[1200, 1375]],
        ]);
        expect(wrapper.emitted("input")).toHaveLength(9);
    });

    it("never lets the lower thumb pass the higher one, nor a thumb leave the bounds", async () => {
        const wrapper = mountSlider([1390, 1400]);
        const [low, high] = thumbs(wrapper);
        await low.trigger("keydown", { key: "PageUp" });
        await low.trigger("keydown", { key: "End" });
        await high.trigger("keydown", { key: "PageDown" });
        await high.trigger("keydown", { key: "Home" });
        const clamped = mountSlider([1000, 1500]);
        await thumbs(clamped)[0].trigger("keydown", { key: "ArrowLeft" });
        await thumbs(clamped)[1].trigger("keydown", { key: "ArrowRight" });
        expect(wrapper.emitted("change")).toEqual([
            [[1400, 1400]],
            [[1400, 1400]],
            [[1390, 1390]],
            [[1390, 1390]],
        ]);
        expect(clamped.emitted("change")).toEqual([
            [[1000, 1500]],
            [[1000, 1500]],
        ]);
    });

    it("ignores other keys", async () => {
        const wrapper = mountSlider();
        await thumbs(wrapper)[0].trigger("keydown", { key: "a" });
        expect(wrapper.emitted("change")).toBeUndefined();
    });

    it("places the thumbs and the filled track by their share of the range", () => {
        const wrapper = mountSlider();
        const [low, high] = thumbs(wrapper);
        expect(low.attributes("style")).toContain("--at: 40%");
        expect(high.attributes("style")).toContain("--at: 80%");
        expect(wrapper.find(".track").attributes("style")).toContain(
            "--from: 40%",
        );
        expect(wrapper.find(".track").attributes("style")).toContain(
            "--to: 80%",
        );
    });

    it("sends the value while a thumb is dragged and the end of the drag once", async () => {
        const wrapper = mountSlider();
        const rail = wrapper.find(".track").element;
        rail.getBoundingClientRect = () =>
            ({ left: 0, width: 500, right: 500 }) as DOMRect;
        const [low] = thumbs(wrapper);
        await low.trigger("pointerdown", { clientX: 200, pointerId: 1 });
        await low.trigger("pointermove", { clientX: 250, pointerId: 1 });
        await low.trigger("pointerup", { clientX: 250, pointerId: 1 });
        expect(wrapper.emitted("input")).toEqual([[[1250, 1400]]]);
        expect(wrapper.emitted("change")).toEqual([[[1250, 1400]]]);
    });

    it("moves a thumb only while it is held", async () => {
        const wrapper = mountSlider();
        wrapper.find(".track").element.getBoundingClientRect = () =>
            ({ left: 0, width: 500, right: 500 }) as DOMRect;
        await thumbs(wrapper)[1].trigger("pointermove", { clientX: 100 });
        expect(wrapper.emitted("input")).toBeUndefined();
    });
});
