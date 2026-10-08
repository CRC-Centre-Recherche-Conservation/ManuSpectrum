import { describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick, ref } from "vue";
import { mount } from "@vue/test-utils";

import { useAnchoredPopover } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";

function setup() {
    const open = ref(false);
    const state = { style: ref<Record<string, string>>({}) };
    const Host = defineComponent({
        setup() {
            const popover = ref<HTMLElement | null>(null);
            const anchor = ref<HTMLElement | null>(null);
            state.style = useAnchoredPopover(open, popover, anchor).style;
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
});
