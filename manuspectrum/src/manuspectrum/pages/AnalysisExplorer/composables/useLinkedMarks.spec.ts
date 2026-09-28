import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
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

import type { LinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";

let stop: (() => void) | null = null;

function marksWith(linked: LinkedSelection | null): LinkedMarks {
    let marks: LinkedMarks | null = null;
    mount(
        defineComponent({
            setup() {
                marks = useLinkedMarks();
                return () => h("span");
            },
        }),
        {
            global: {
                provide: linked
                    ? { [LINKED_SELECTION_KEY as symbol]: linked }
                    : {},
            },
        },
    );
    return marks!;
}

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    stop?.();
    stop = null;
    vi.useRealTimers();
});

describe("useLinkedMarks", () => {
    it("marks nothing while nothing is selected", () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const marks = marksWith(started.linked);
        expect(marks.active.value).toBe(false);
        expect(marks.rel(analysisNode(AN1))).toBeUndefined();
    });

    it("gives the strongest level of the ids a thing stands for, none when unlinked", () => {
        const started = startLinkedSelection();
        stop = started.stop;
        const marks = marksWith(started.linked);
        marks.toggle(materialNode(CH1));
        expect(marks.active.value).toBe(true);
        expect(marks.rel(materialNode(CH1))).toBe("self");
        expect(marks.rel([analysisNode(AN2), analysisNode(AN1)])).toBe(
            "evidence",
        );
        expect(marks.rel(analysisNode(AN2))).toBe("none");
        expect(marks.pressed(materialNode(CH1))).toBe("true");
        expect(marks.pressed(analysisNode(AN1))).toBe("false");
    });

    it("previews what a node under the mouse links, never under a finger", () => {
        vi.useFakeTimers();
        const started = startLinkedSelection();
        stop = started.stop;
        const marks = marksWith(started.linked);
        marks.enter(elementNode("Fe"), { pointerType: "touch" });
        vi.runAllTimers();
        expect(marks.previewRel(analysisNode(AN1))).toBeUndefined();
        marks.enter(elementNode("Fe"), { pointerType: "mouse" });
        vi.runAllTimers();
        expect(marks.previewRel(elementNode("Fe"))).toBe("self");
        expect(marks.previewRel(analysisNode(AN1))).toBe("direct");
        expect(marks.previewRel(analysisNode(AN2))).toBeUndefined();
        expect(marks.rel(analysisNode(AN1))).toBeUndefined();
        marks.toggle(elementNode("Fe"));
        expect(marks.previewRel(analysisNode(AN1))).toBeUndefined();
        marks.leave({ pointerType: "mouse" });
        vi.runAllTimers();
        expect(marks.previewRel(analysisNode(AN1))).toBeUndefined();
    });

    it("toggles in the store outside a Compare view", () => {
        const marks = marksWith(null);
        marks.toggle(elementNode("Fe"));
        expect(useExplorerStore().compare.selection).toEqual([
            elementNode("Fe"),
        ]);
        expect(marks.pressed(elementNode("Fe"))).toBe("true");
        expect(marks.rel(elementNode("Fe"))).toBeUndefined();
    });
});
