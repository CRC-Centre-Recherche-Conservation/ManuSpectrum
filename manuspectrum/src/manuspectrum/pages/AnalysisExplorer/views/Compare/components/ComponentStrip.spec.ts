import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import ComponentStrip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ComponentStrip.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    AN1,
    BASKET,
    BY_KEY_WITH_COMPONENT,
    K1,
    SYNTHESIS_WITH_COMPONENT,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    analysisNode,
    componentNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { selectionComponents } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/selection-components.ts";

import type { SelectionComponent } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/selection-components.ts";

const INITIAL: SelectionComponent = {
    id: K1,
    name: label("Initial T"),
    folios: ["f. 5"],
    analyses: 3,
    materials: 1,
};
const BORDER: SelectionComponent = {
    id: uuid(952),
    name: label("Border"),
    folios: ["f. 45", "f. 57"],
    analyses: 1,
    materials: 0,
};

let stop: (() => void) | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    stop?.();
    stop = null;
});

describe("ComponentStrip", () => {
    it("shows nothing without a component", () => {
        const view = mount(ComponentStrip, { props: { components: [] } });
        expect(view.find(".component-strip").exists()).toBe(false);
    });

    it("shows one chip per component with its folios and counts, then the legend of the counts", () => {
        const view = mount(ComponentStrip, {
            props: { components: [INITIAL, BORDER] },
        });
        expect(view.find(".heading").text()).toBe("Components");
        const chips = view.findAll(".chip");
        expect(chips.map((chip) => chip.find(".name").text())).toEqual([
            "Initial T",
            "Border",
        ]);
        expect(chips[1].find(".folios").text()).toBe("f. 45, f. 57");
        expect(chips[0].find(".counts").text()).toBe("3 · 1");
        expect(chips[0].attributes("aria-label")).toBe(
            "Initial T, f. 5: 3 analyses, 1 identified material",
        );
        expect(chips[0].attributes("lang")).toBeUndefined();
        expect(chips[0].find(".name").attributes("lang")).toBe("en");
        expect(view.find(".legend").text()).toBe(
            "analyses · identified materials",
        );
    });

    it("pins the component clicked and presses its chip", async () => {
        const view = mount(ComponentStrip, {
            props: { components: [INITIAL] },
        });
        await view.find(".chip").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            componentNode(K1),
        ]);
        expect(view.find(".chip").attributes("aria-pressed")).toBe("true");
    });

    it("marks a component linked to the focus with its slot", async () => {
        const started = startLinkedSelection(
            () => undefined,
            SYNTHESIS_WITH_COMPONENT,
            BY_KEY_WITH_COMPONENT,
        );
        stop = started.stop;
        const view = mount(ComponentStrip, {
            props: {
                components: selectionComponents(
                    BASKET,
                    BY_KEY_WITH_COMPONENT,
                    SYNTHESIS_WITH_COMPONENT,
                ),
            },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            },
        });
        started.linked.toggle(analysisNode(AN1));
        await view.vm.$nextTick();
        const chip = view.find(".chip");
        expect(chip.attributes("data-node")).toBe(componentNode(K1));
        expect(chip.attributes("data-slots")).toBe("1");
    });
});
