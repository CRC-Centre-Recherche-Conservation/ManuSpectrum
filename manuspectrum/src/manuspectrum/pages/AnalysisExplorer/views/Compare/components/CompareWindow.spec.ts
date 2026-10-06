import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, inject } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CompareWindow from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CompareWindow.vue";
import LinkedChip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LinkedChip.vue";

import {
    LINKED_SELECTION_KEY,
    WINDOW_FRAME_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    AN2,
    CH1,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";

let stop: (() => void) | null = null;
let wrapper: VueWrapper | null = null;

function mountWindow(linked: LinkedSelection): VueWrapper {
    wrapper = mount(CompareWindow, {
        attachTo: document.body,
        props: {
            title: "Tools",
            position: 1,
            total: 1,
            size: "M",
            folded: null,
        },
        slots: {
            default: () => [
                h(LinkedChip, { node: materialNode(CH1), text: "Blue" }),
                h(LinkedChip, { node: materialNode(CH1), text: "Blue again" }),
                h(LinkedChip, { node: analysisNode(AN2), text: "Raman" }),
            ],
        },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: linked },
        },
    });
    return wrapper;
}

/** Lets the window read its body again, on the frame after the change. */
async function settle(): Promise<void> {
    await flushPromises();
    await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
    );
    await flushPromises();
}

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    stop?.();
    stop = null;
    vi.useRealTimers();
});

describe("CompareWindow and the focus", () => {
    it("stays plain without a focus, then rims and counts what its body lights, each node once", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const view = mountWindow(started.linked);
        await settle();
        const frame = (): ReturnType<VueWrapper["find"]> =>
            view.find(".compare-window-frame");
        expect(frame().classes()).not.toContain("is-linked");
        expect(frame().classes()).not.toContain("is-quiet");
        expect(view.find(".linked-count").exists()).toBe(false);

        started.linked.toggle(elementNode("Cu"));
        await settle();
        expect(frame().classes()).toContain("is-linked");
        expect(view.find(".linked-count .text").text()).toBe("1 linked");
        expect(
            view
                .findAll(".linked-count .focus-slot-dot")
                .map((dot) => dot.text()),
        ).toEqual(["1"]);
        expect(frame().attributes("style")).toContain(
            "--rim: linear-gradient(90deg, var(--focus-1) 0.0% 100.0%)",
        );
        expect(frame().attributes("data-breath")).toMatch(/^(odd|even)$/);

        started.linked.toggle(analysisNode(AN2));
        await settle();
        expect(
            view
                .findAll(".linked-count .focus-slot-dot")
                .map((dot) => dot.text()),
        ).toEqual(["1", "2"]);
        expect(view.find(".linked-count .text").text()).toBe("2 linked");
    });

    it("turns quiet when the focus lights nothing in it", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const view = mountWindow(started.linked);
        started.linked.toggle(elementNode("Zz"));
        await settle();
        const frame = view.find(".compare-window-frame");
        expect(frame.classes()).toContain("is-quiet");
        expect(frame.classes()).not.toContain("is-linked");
    });

    it("half-shows its rim in the hue of the next slot while a preview lights something in it", async () => {
        vi.useFakeTimers();
        const started = startLinkedSelection();
        stop = started.stop;
        const view = mountWindow(started.linked);
        started.linked.preview(elementNode("Cu"), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        await flushPromises();
        await vi.advanceTimersByTimeAsync(50);
        const frame = view.find(".compare-window-frame");
        expect(frame.classes()).toContain("is-previewed");
        expect(frame.attributes("style")).toContain(
            "--rim: linear-gradient(var(--focus-1), var(--focus-1))",
        );
    });
});

describe("CompareWindow and its body's frame", () => {
    function probeText(): string | undefined {
        return document.body.querySelector(".probe")?.textContent ?? undefined;
    }

    const Probe = defineComponent({
        setup() {
            const frame = inject(WINDOW_FRAME_KEY);
            return () =>
                h(
                    "span",
                    { class: "probe" },
                    `${frame?.value.size}|${frame?.value.enlarged}`,
                );
        },
    });

    it("tells its body its size and whether it is enlarged", async () => {
        wrapper = mount(CompareWindow, {
            attachTo: document.body,
            props: {
                title: "Imaging",
                position: 1,
                total: 1,
                size: "L",
                folded: null,
            },
            slots: { default: () => h(Probe) },
        });
        expect(probeText()).toBe("L|false");
        await wrapper.setProps({ size: null, enlarged: true });
        await flushPromises();
        expect(probeText()).toBe("null|true");
    });
});
