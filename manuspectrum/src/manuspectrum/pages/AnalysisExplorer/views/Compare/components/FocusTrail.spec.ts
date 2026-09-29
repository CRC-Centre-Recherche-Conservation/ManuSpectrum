import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import FocusTrail from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusTrail.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    AN1,
    CH1,
    CH2,
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
let anchor: HTMLButtonElement;

function mountTrail(linked: LinkedSelection): VueWrapper {
    wrapper = mount(FocusTrail, {
        attachTo: document.body,
        global: { provide: { [LINKED_SELECTION_KEY as symbol]: linked } },
    });
    return wrapper;
}

async function rest(linked: LinkedSelection, id: string): Promise<void> {
    linked.preview(id, { pointerType: "mouse", currentTarget: anchor });
    await vi.advanceTimersByTimeAsync(200);
    await nextTick();
}

function trail(): HTMLElement | null {
    return document.querySelector<HTMLElement>(".focus-trail");
}

beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    anchor = document.createElement("button");
    document.body.append(anchor);
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    stop?.();
    stop = null;
    anchor.remove();
    vi.useRealTimers();
});

describe("FocusTrail", () => {
    it("shows nothing under a toggle the focus does not light", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        mountTrail(started.linked);
        await rest(started.linked, analysisNode(AN1));
        expect(trail()).toBeNull();
    });

    it("lists each slot of a lit toggle and says the slot a click pins it in", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        mountTrail(started.linked);
        started.linked.toggle(elementNode("Cu"));
        started.linked.toggle(materialNode(CH1));
        await rest(started.linked, analysisNode(AN1));
        const shown = trail()!;
        expect(shown.getAttribute("aria-hidden")).toBe("true");
        expect(shown.getAttribute("role")).toBeNull();
        expect(
            [...shown.querySelectorAll("li")].map((row) =>
                row.textContent?.trim(),
            ),
        ).toEqual([
            "1Cucited as evidence",
            "2Blue of the mantlecited as evidence",
        ]);
        expect(shown.querySelector(".hint")?.textContent).toBe(
            "Click to pin as ③",
        );
    });

    it("says the focus is full instead of promising a slot", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        mountTrail(started.linked);
        for (const id of [
            elementNode("Cu"),
            elementNode("Ca"),
            materialNode(CH1),
            materialNode(CH2),
        ]) {
            started.linked.toggle(id);
        }
        await rest(started.linked, analysisNode(AN1));
        expect(trail()?.querySelector(".hint")?.textContent).toBe(
            "Focus full: unpin one to add this",
        );
    });

    it("says a pinned toggle is in the focus and a click unpins it", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        mountTrail(started.linked);
        started.linked.toggle(elementNode("Cu"));
        await rest(started.linked, elementNode("Cu"));
        expect(trail()?.querySelector("li")?.textContent).toContain(
            "in the focus",
        );
        expect(trail()?.querySelector(".hint")?.textContent).toBe(
            "Click to unpin",
        );
        started.linked.clear();
        await nextTick();
        expect(trail()).toBeNull();
    });

    it("is gone once its toggle leaves the page", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        mountTrail(started.linked);
        started.linked.toggle(elementNode("Cu"));
        await rest(started.linked, elementNode("Cu"));
        expect(trail()).not.toBeNull();
        anchor.remove();
        await nextTick();
        await nextTick();
        expect(trail()).toBeNull();
    });

    it("follows its toggle when the page scrolls", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        mountTrail(started.linked);
        started.linked.toggle(elementNode("Cu"));
        let bottom = 100;
        anchor.getBoundingClientRect = () => ({ left: 40, bottom }) as DOMRect;
        await rest(started.linked, elementNode("Cu"));
        expect(trail()?.style.getPropertyValue("--trail-top")).toBe("108px");
        bottom = 60;
        window.dispatchEvent(new Event("scroll"));
        await nextTick();
        expect(trail()?.style.getPropertyValue("--trail-top")).toBe("68px");
    });
});
