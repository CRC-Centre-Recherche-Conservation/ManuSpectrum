import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import SizePicker from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/SizePicker.vue";

import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

enableAutoUnmount(afterEach);

const REVEAL_MS = 450;

function mountPicker(size: WindowSize | null = "M") {
    return mount(SizePicker, {
        props: { size, title: "XRF" },
        attachTo: document.body,
    });
}

function radio(
    wrapper: ReturnType<typeof mountPicker>,
    size: WindowSize,
): HTMLElement {
    return wrapper.find<HTMLElement>(`[data-action="size-${size}"]`).element;
}

function pointer(type: string, pointerType = "mouse"): Event {
    return Object.assign(new Event(type, { bubbles: true }), { pointerType });
}

function revealed(wrapper: ReturnType<typeof mountPicker>): boolean {
    return wrapper.classes().includes("revealed");
}

describe("SizePicker", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("is a group of radios S, M and L named after the window, the size it has checked and alone in the tab order", () => {
        const wrapper = mountPicker("M");
        const group = wrapper.find('[role="radiogroup"]');
        expect(group.attributes("aria-label")).toBe("Size of « XRF »");
        const radios = group.findAll('[role="radio"]');
        expect(radios.map((entry) => entry.text())).toEqual(["S", "M", "L"]);
        expect(radios.map((entry) => entry.attributes("aria-checked"))).toEqual(
            ["false", "true", "false"],
        );
        expect(radios.map((entry) => entry.attributes("tabindex"))).toEqual([
            "-1",
            "0",
            "-1",
        ]);
        expect(radio(wrapper, "L").getAttribute("aria-label")).toBe("Size L");
        expect(revealed(wrapper)).toBe(false);
    });

    it("shows the other sizes after a long hover, not before, and hides them when the pointer leaves", async () => {
        const wrapper = mountPicker();
        wrapper.element.dispatchEvent(pointer("pointerenter"));
        vi.advanceTimersByTime(REVEAL_MS - 1);
        await nextTick();
        expect(revealed(wrapper)).toBe(false);
        vi.advanceTimersByTime(1);
        await nextTick();
        expect(revealed(wrapper)).toBe(true);
        wrapper.element.dispatchEvent(pointer("pointerleave"));
        await nextTick();
        expect(revealed(wrapper)).toBe(false);
    });

    it("shows the other sizes at once on a tap, which chooses nothing yet", async () => {
        const wrapper = mountPicker("M");
        radio(wrapper, "M").dispatchEvent(pointer("pointerdown", "touch"));
        radio(wrapper, "M").click();
        await nextTick();
        expect(revealed(wrapper)).toBe(true);
        expect(wrapper.emitted("size-chosen")).toBeUndefined();
        radio(wrapper, "L").dispatchEvent(pointer("pointerdown", "touch"));
        radio(wrapper, "L").click();
        await nextTick();
        expect(wrapper.emitted("size-chosen")).toEqual([[{ size: "L" }]]);
        expect(revealed(wrapper)).toBe(false);
    });

    it("hides the sizes a tap showed when the reader taps elsewhere", async () => {
        const wrapper = mountPicker("M");
        radio(wrapper, "M").dispatchEvent(pointer("pointerdown", "touch"));
        radio(wrapper, "M").click();
        await nextTick();
        document.body.dispatchEvent(pointer("pointerdown", "touch"));
        await nextTick();
        expect(revealed(wrapper)).toBe(false);
    });

    it("chooses another size on a click, and nothing on the size it has", async () => {
        const wrapper = mountPicker("M");
        radio(wrapper, "M").click();
        await nextTick();
        expect(wrapper.emitted("size-chosen")).toBeUndefined();
        expect(revealed(wrapper)).toBe(true);
        radio(wrapper, "S").click();
        expect(wrapper.emitted("size-chosen")).toEqual([[{ size: "S" }]]);
    });

    it("chooses with the arrows, wrapping around, and follows with the focus", async () => {
        const wrapper = mountPicker("S");
        radio(wrapper, "S").focus();
        await wrapper
            .find('[data-action="size-S"]')
            .trigger("keydown", { key: "ArrowLeft" });
        expect(wrapper.emitted("size-chosen")?.at(-1)).toEqual([{ size: "L" }]);
        expect(document.activeElement).toBe(radio(wrapper, "L"));
        await wrapper.setProps({ size: "L" });
        await wrapper
            .find('[data-action="size-L"]')
            .trigger("keydown", { key: "ArrowDown" });
        expect(wrapper.emitted("size-chosen")?.at(-1)).toEqual([{ size: "S" }]);
        expect(document.activeElement).toBe(radio(wrapper, "S"));
    });

    it("says « Free » for a size set by hand, with no size checked and the first one in the tab order", () => {
        const wrapper = mountPicker(null);
        expect(wrapper.find(".current").text()).toBe("Free");
        const radios = wrapper.findAll('[role="radio"]');
        expect(
            radios.every(
                (entry) => entry.attributes("aria-checked") === "false",
            ),
        ).toBe(true);
        expect(radios.map((entry) => entry.attributes("tabindex"))).toEqual([
            "0",
            "-1",
            "-1",
        ]);
    });
});
