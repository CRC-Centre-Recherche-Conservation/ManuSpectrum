import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, shallowRef } from "vue";
import { flushPromises, mount } from "@vue/test-utils";

import { useWindowFocus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowFocus.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { WindowFocus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowFocus.ts";

const FRAME_MS = 20;

let wrapper: VueWrapper | null = null;

function mountFocus(): { focus: WindowFocus; body: HTMLElement } {
    let focus: WindowFocus | null = null;
    const body = shallowRef<HTMLElement | null>(null);
    wrapper = mount(
        defineComponent({
            setup() {
                focus = useWindowFocus(body);
                return () =>
                    h("div", {
                        ref: (element) => {
                            body.value = element as HTMLElement | null;
                        },
                    });
            },
        }),
        { attachTo: document.body },
    );
    return { focus: focus!, body: body.value! };
}

function lit(node: string, slots: string): HTMLElement {
    const element = document.createElement("button");
    element.dataset.node = node;
    element.dataset.slots = slots;
    return element;
}

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe("useWindowFocus", () => {
    it("reads the toggles added in one frame once, on the next frame", async () => {
        const { focus, body } = mountFocus();
        await flushPromises();
        const frames = vi.spyOn(window, "requestAnimationFrame");
        body.append(lit("el:Cu", "1"));
        await flushPromises();
        body.append(lit("el:Pb", "1 2"));
        await flushPromises();
        expect(frames).toHaveBeenCalledTimes(1);
        expect(focus.linkedCount.value).toBe(0);
        await vi.advanceTimersByTimeAsync(FRAME_MS);
        expect(focus.linkedCount.value).toBe(2);
        expect(focus.slots.value).toEqual([1, 2]);
    });

    it("reads nothing again when what is added or removed holds no toggle", async () => {
        const { focus, body } = mountFocus();
        body.append(lit("el:Cu", "1"));
        await flushPromises();
        await vi.advanceTimersByTimeAsync(FRAME_MS);
        expect(focus.linkedCount.value).toBe(1);
        const reads = vi.spyOn(body, "querySelectorAll");
        const plain = document.createElement("p");
        plain.append(document.createElement("span"), "text");
        body.append(plain);
        await flushPromises();
        plain.remove();
        await flushPromises();
        await vi.advanceTimersByTimeAsync(FRAME_MS);
        expect(reads).not.toHaveBeenCalled();
    });

    it("reads again when a toggle is removed inside what leaves, or its marks change", async () => {
        const { focus, body } = mountFocus();
        const row = document.createElement("div");
        const toggle = lit("el:Cu", "1");
        row.append(toggle);
        body.append(row, lit("el:Pb", "2"));
        await flushPromises();
        await vi.advanceTimersByTimeAsync(FRAME_MS);
        expect(focus.slots.value).toEqual([1, 2]);
        toggle.dataset.slots = "3";
        await flushPromises();
        await vi.advanceTimersByTimeAsync(FRAME_MS);
        expect(focus.slots.value).toEqual([2, 3]);
        row.remove();
        await flushPromises();
        await vi.advanceTimersByTimeAsync(FRAME_MS);
        expect(focus.slots.value).toEqual([2]);
        expect(focus.linkedCount.value).toBe(1);
    });
});
