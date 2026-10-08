import { describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick, ref } from "vue";
import { mount } from "@vue/test-utils";

import { useAnchoredPopover } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";

import type { AnchoredPopoverOptions } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";

function setup(options?: AnchoredPopoverOptions) {
    const open = ref(false);
    const state = { style: ref<Record<string, string>>({}) };
    const Host = defineComponent({
        setup() {
            const popover = ref<HTMLElement | null>(null);
            const anchor = ref<HTMLElement | null>(null);
            state.style = useAnchoredPopover(
                open,
                popover,
                anchor,
                options,
            ).style;
            return () => [
                h("button", { ref: anchor }),
                h("div", { ref: popover, popover: "manual" }),
            ];
        },
    });
    const view = mount(Host, { attachTo: document.body });
    const element = view.find("div").element as HTMLElement;
    const anchor = view.find("button").element;
    return { open, state, view, element, anchor };
}

describe("useAnchoredPopover", () => {
    it("shows the popover in the top layer while open and hides it after", async () => {
        const { open, element, view } = setup();
        let shown = false;
        element.showPopover = vi.fn(() => (shown = true));
        element.hidePopover = vi.fn(() => (shown = false));
        element.matches = vi.fn(() => shown) as never;
        open.value = true;
        await nextTick();
        expect(element.showPopover).toHaveBeenCalledTimes(1);
        open.value = false;
        await nextTick();
        expect(element.hidePopover).toHaveBeenCalledTimes(1);
        view.unmount();
    });

    it("places the popover under its anchor, kept inside the viewport", async () => {
        const { open, state, element, anchor, view } = setup();
        anchor.getBoundingClientRect = () =>
            ({ left: 5000, top: 100, bottom: 130, width: 40 }) as DOMRect;
        Object.defineProperty(element, "offsetWidth", { value: 300 });
        Object.defineProperty(element, "scrollHeight", { value: 200 });
        open.value = true;
        await nextTick();
        expect(state.style.value.insetBlockStart).toBe("134px");
        expect(state.style.value.insetInlineStart).toBe(
            `${window.innerWidth - 300 - 8}px`,
        );
        expect(state.style.value["--anchor-width"]).toBe("40px");
        view.unmount();
    });

    it("opens above the anchor when there is more room there", async () => {
        const { open, state, element, anchor, view } = setup();
        const bottom = window.innerHeight - 20;
        anchor.getBoundingClientRect = () =>
            ({ left: 10, top: bottom - 30, bottom, width: 40 }) as DOMRect;
        Object.defineProperty(element, "offsetWidth", { value: 100 });
        Object.defineProperty(element, "scrollHeight", { value: 200 });
        open.value = true;
        await nextTick();
        expect(state.style.value.insetBlockStart).toBe(
            `${bottom - 30 - 4 - 200}px`,
        );
        view.unmount();
    });

    it("lines up with the anchor's end, above first, with the given offset", async () => {
        const { open, state, element, anchor, view } = setup({
            prefer: "above",
            align: "end",
            offset: 0,
        });
        anchor.getBoundingClientRect = () =>
            ({
                left: 300,
                right: 340,
                top: 200,
                bottom: 230,
                width: 40,
            }) as DOMRect;
        Object.defineProperty(element, "offsetWidth", { value: 100 });
        Object.defineProperty(element, "scrollHeight", { value: 50 });
        open.value = true;
        await nextTick();
        expect(state.style.value.insetInlineStart).toBe("240px");
        expect(state.style.value.insetBlockStart).toBe("150px");
        view.unmount();
    });

    it("falls back below when preferring above leaves less room there", async () => {
        const { open, state, element, anchor, view } = setup({
            prefer: "above",
            offset: 0,
        });
        anchor.getBoundingClientRect = () =>
            ({
                left: 10,
                right: 50,
                top: 20,
                bottom: 50,
                width: 40,
            }) as DOMRect;
        Object.defineProperty(element, "offsetWidth", { value: 100 });
        Object.defineProperty(element, "scrollHeight", { value: 50 });
        open.value = true;
        await nextTick();
        expect(state.style.value.insetBlockStart).toBe("50px");
        view.unmount();
    });

    it("places the popover again when a layout shift moves the anchor, without a scroll or a resize", async () => {
        const { open, state, element, anchor, view } = setup();
        let top = 100;
        anchor.getBoundingClientRect = () =>
            ({ left: 10, top, bottom: top + 30, width: 40 }) as DOMRect;
        Object.defineProperty(element, "offsetWidth", { value: 100 });
        Object.defineProperty(element, "scrollHeight", { value: 50 });
        open.value = true;
        await nextTick();
        expect(state.style.value.insetBlockStart).toBe("134px");
        top = 160;
        await new Promise((resolve) => requestAnimationFrame(resolve));
        await new Promise((resolve) => requestAnimationFrame(resolve));
        expect(state.style.value.insetBlockStart).toBe("194px");
        view.unmount();
    });

    it("stops following once closed", async () => {
        const { open, state, anchor, view } = setup();
        let top = 100;
        anchor.getBoundingClientRect = () =>
            ({ left: 10, top, bottom: top + 30, width: 40 }) as DOMRect;
        open.value = true;
        await nextTick();
        open.value = false;
        await nextTick();
        const placed = state.style.value.insetBlockStart;
        top = 300;
        await new Promise((resolve) => requestAnimationFrame(resolve));
        await new Promise((resolve) => requestAnimationFrame(resolve));
        expect(state.style.value.insetBlockStart).toBe(placed);
        view.unmount();
    });

    it("tells the caller when the anchor leaves the visible area, and only while open", async () => {
        const watchers: {
            callback: (entries: { isIntersecting: boolean }[]) => void;
            disconnect: ReturnType<typeof vi.fn>;
        }[] = [];
        vi.stubGlobal(
            "IntersectionObserver",
            class {
                disconnect = vi.fn();
                callback: (entries: { isIntersecting: boolean }[]) => void;
                constructor(
                    callback: (entries: { isIntersecting: boolean }[]) => void,
                ) {
                    this.callback = callback;
                    watchers.push(this);
                }
                observe() {}
            },
        );
        const onLost = vi.fn();
        const { open, view } = setup({ onLost });
        expect(watchers).toHaveLength(0);
        open.value = true;
        await nextTick();
        expect(watchers).toHaveLength(1);
        watchers[0].callback([{ isIntersecting: true }]);
        expect(onLost).not.toHaveBeenCalled();
        watchers[0].callback([{ isIntersecting: false }]);
        expect(onLost).toHaveBeenCalledTimes(1);
        open.value = false;
        await nextTick();
        expect(watchers[0].disconnect).toHaveBeenCalled();
        view.unmount();
        vi.unstubAllGlobals();
    });
});
