import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    AN1,
    AN2,
    CH1,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

let stop: (() => void) | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    stop?.();
    stop = null;
});

describe("FocusPip", () => {
    it("draws a « + » while the thing relates to no slot, hidden from assistive technologies", () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const view = mount(FocusPip, {
            props: { node: analysisNode(AN1) },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        expect(view.attributes("aria-hidden")).toBe("true");
        expect(
            view.findAll("b").map((digit) => digit.attributes("data-n")),
        ).toEqual(["+"]);
        expect(view.text()).toBe("");
    });

    it("draws no « + » on a thing related to no slot while the focus is full", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const view = mount(FocusPip, {
            props: { node: elementNode("Zz") },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        started.linked.toggle(elementNode("Cu"));
        started.linked.toggle(analysisNode(AN1));
        started.linked.toggle(analysisNode(AN2));
        await view.vm.$nextTick();
        expect(view.find(".ms-focus-pip b.add").exists()).toBe(true);
        started.linked.toggle(materialNode(CH1));
        await view.vm.$nextTick();
        expect(view.find(".ms-focus-pip").exists()).toBe(false);
    });

    it("draws one digit per slot on its hue, its own underlined first, evidence hollow", async () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const view = mount(FocusPip, {
            props: { node: materialNode(CH1) },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        started.linked.toggle(elementNode("Cu"));
        started.linked.toggle(analysisNode(AN1));
        started.linked.toggle(materialNode(CH1));
        await view.vm.$nextTick();
        const digits = view.findAll("b");
        expect(digits.map((digit) => digit.attributes("data-n"))).toEqual([
            "3",
            "1",
            "2",
        ]);
        expect(digits.map((digit) => digit.classes())).toEqual([
            ["own"],
            [],
            ["ev"],
        ]);
        expect(digits[0].attributes("style")).toBe("--h: var(--focus-3);");
    });
});
