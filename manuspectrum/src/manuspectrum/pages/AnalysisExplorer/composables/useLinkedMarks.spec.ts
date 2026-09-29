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

let unmountLast: () => void = () => undefined;

/** The marks of a component mounted under `linked`; `unmountLast` unmounts that component. */
function marksWith(linked: LinkedSelection | null): LinkedMarks {
    let marks: LinkedMarks | null = null;
    const view = mount(
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
    unmountLast = () => view.unmount();
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

    it("ends its preview when the thing previewed goes, not another's", () => {
        vi.useFakeTimers();
        const started = startLinkedSelection();
        stop = started.stop;
        const other = marksWith(started.linked);
        const gone = marksWith(started.linked);
        gone.enter(elementNode("Fe"), { pointerType: "mouse" });
        vi.runAllTimers();
        expect(started.linked.previewing.value).toBe(elementNode("Fe"));
        unmountLast();
        vi.runAllTimers();
        expect(started.linked.previewing.value).toBeNull();

        const left = marksWith(started.linked);
        left.enter(elementNode("Fe"), { pointerType: "mouse" });
        left.leave({ pointerType: "mouse" });
        vi.runAllTimers();
        other.enter(elementNode("Cu"), { pointerType: "mouse" });
        vi.runAllTimers();
        unmountLast();
        vi.runAllTimers();
        expect(started.linked.previewing.value).toBe(elementNode("Cu"));
    });

    it("gathers the focus attributes of a toggle: slots, ring, first hue, bloom and preview hue", async () => {
        vi.useFakeTimers();
        const started = startLinkedSelection();
        stop = started.stop;
        const marks = marksWith(started.linked);
        expect(marks.focus(analysisNode(AN1))).toEqual({
            "data-node": analysisNode(AN1),
            "data-rel": undefined,
            "data-slots": undefined,
            "data-preview": undefined,
            "data-bloom": undefined,
            style: undefined,
        });
        marks.toggle(elementNode("Cu"));
        marks.toggle(materialNode(CH1));
        const both = marks.focus([materialNode(CH1), analysisNode(AN2)]);
        expect(both["data-node"]).toBe(
            `${materialNode(CH1)} ${analysisNode(AN2)}`,
        );
        expect(both["data-rel"]).toBe("self");
        expect(both["data-slots"]).toBe("2 1");
        expect(both["data-bloom"]).toBe("even");
        expect(both.style).toEqual({
            "--ring":
                "conic-gradient(from -90deg, var(--focus-2) 0.0% 50.0%, var(--focus-1) 50.0% 100.0%)",
            "--h1": "var(--focus-2)",
        });
        expect(marks.slots(analysisNode(AN1))).toEqual([
            { slot: 1, level: "evidence" },
            { slot: 2, level: "evidence" },
        ]);
        expect(marks.hue(analysisNode(AN1))).toBe("var(--focus-1)");
        expect(marks.focus(analysisNode(AN2))["data-rel"]).toBe("none");
        expect(marks.hue(analysisNode(AN2))).toBeNull();
        vi.advanceTimersByTime(900);
        expect(marks.blooms(materialNode(CH1))).toBe(false);
        marks.enter(analysisNode(AN2), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        const previewed = marks.focus(analysisNode(AN2));
        expect(previewed["data-preview"]).toBe("self");
        expect(previewed.style).toEqual({ "--hp": "var(--focus-3)" });
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
