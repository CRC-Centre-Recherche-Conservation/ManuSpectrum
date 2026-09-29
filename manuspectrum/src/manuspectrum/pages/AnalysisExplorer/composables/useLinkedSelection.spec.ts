import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { computed, effectScope, h, nextTick, ref, shallowRef } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";

import { useLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    AN1,
    BASKET,
    BY_KEY,
    CH1,
    CH2,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { EffectScope } from "vue";
import type {
    Item,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

let scope: EffectScope;
let announce: ReturnType<typeof vi.fn>;
const byKey = ref(new Map<string, Item>());
const settled = ref(true);
const status = ref<RequestStatus>("ready");
const data = shallowRef<SynthesisResponse | null>(null);
const loaded = ref<string | null>(null);

function sourceOf(keys: readonly string[]): string {
    return [...new Set(keys)].sort().join(",");
}

function start(): LinkedSelection {
    scope = effectScope();
    return scope.run(() =>
        useLinkedSelection({
            items: {
                byKey,
                missing: ref(new Set<string>()),
                settled: computed(() => settled.value),
                status: ref<RequestStatus>("ready"),
                retry: () => undefined,
            },
            synthesis: { status, data, loaded, retry: () => undefined },
            announce,
        }),
    )!;
}

function answer(synthesis: SynthesisResponse | null): void {
    data.value = synthesis;
    status.value = "ready";
    loaded.value = sourceOf(useExplorerStore().basket.map((item) => item.key));
}

beforeEach(() => {
    setActivePinia(createPinia());
    announce = vi.fn();
    const store = useExplorerStore();
    store.addManyToBasket(BASKET.map((item) => item.key));
    byKey.value = new Map(BY_KEY);
    settled.value = true;
    answer(SYNTHESIS);
});

afterEach(() => {
    scope.stop();
    vi.useRealTimers();
});

describe("useLinkedSelection", () => {
    it("toggles a node, says what is selected and linked, and levels the graph", () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        expect(linked.levelOf(elementNode("Cu"))).toBe("self");
        expect(linked.levelOf(materialNode(CH1))).toBe("direct");
        expect(linked.levelOf(analysisNode(AN1))).toBe("evidence");
        expect(linked.levelOf("el:Zz")).toBeNull();
        expect(linked.relatedCount.value).toBe(3);
        expect(linked.summary.value).toBe("1 in focus · 3 related");
        expect(announce).toHaveBeenLastCalledWith("1 in focus · 3 related");
        linked.toggle(elementNode("Cu"));
        expect(linked.summary.value).toBe("No focus");
        expect(announce).toHaveBeenLastCalledWith("No focus");
    });

    it("keeps each pinned node at its slot, fills the lowest hole and says what the next pin takes", () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        linked.toggle(elementNode("Ca"));
        linked.toggle(materialNode(CH1));
        linked.toggle(elementNode("Ca"));
        expect(linked.slots.value).toEqual([
            elementNode("Cu"),
            null,
            materialNode(CH1),
        ]);
        expect(linked.pinned.value).toEqual([
            { id: elementNode("Cu"), slot: 1 },
            { id: materialNode(CH1), slot: 3 },
        ]);
        expect(linked.selection.value).toEqual([
            elementNode("Cu"),
            materialNode(CH1),
        ]);
        expect(linked.slotOf(materialNode(CH1))).toBe(3);
        expect(linked.slotOf(elementNode("Ca"))).toBeNull();
        expect(linked.nextSlot.value).toBe(2);
        expect(linked.relations.value.get(materialNode(CH1))?.slots).toEqual([
            { slot: 3, level: "self" },
            { slot: 1, level: "direct" },
        ]);
    });

    it("refuses a fifth pin with a notice, no cue and no change, and refills a hole", () => {
        const linked = start();
        for (const id of [
            elementNode("Cu"),
            elementNode("Ca"),
            materialNode(CH1),
            materialNode(CH2),
        ]) {
            linked.toggle(id);
        }
        const cue = linked.cue.value;
        const slots = linked.slots.value;
        expect(linked.nextSlot.value).toBeNull();
        linked.toggle(analysisNode(AN1));
        expect(announce).toHaveBeenLastCalledWith(
            "The focus holds 4 items at most. Unpin one to add another.",
        );
        expect(linked.slots.value).toBe(slots);
        expect(linked.cue.value).toBe(cue);
        expect(linked.lastPinned.value).toBe(materialNode(CH2));
        linked.toggle(elementNode("Ca"));
        linked.toggle(analysisNode(AN1));
        expect(linked.slotOf(analysisNode(AN1))).toBe(2);
        expect(announce).toHaveBeenLastCalledWith(linked.summary.value);
    });

    it("promises no slot and lights nothing for an unpinned node previewed while the focus is full", async () => {
        vi.useFakeTimers();
        const linked = start();
        for (const id of [
            elementNode("Cu"),
            elementNode("Ca"),
            materialNode(CH1),
            materialNode(CH2),
        ]) {
            linked.toggle(id);
        }
        linked.preview(analysisNode(AN1), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBe(analysisNode(AN1));
        expect(linked.previewSlot.value).toBeNull();
        expect(linked.previewLevels.value.size).toBe(0);
        linked.preview(elementNode("Cu"), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewLevels.value.get(materialNode(CH1))).toBe(
            "direct",
        );
    });

    it("lights under « all » only what relates to every pinned node, says so, and resets it on clear", () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        linked.toggle(elementNode("Ca"));
        expect(linked.levelOf(materialNode(CH1))).toBe("direct");
        linked.setMode("all");
        expect(linked.mode.value).toBe("all");
        expect(announce).toHaveBeenLastCalledWith(linked.summary.value);
        expect(linked.levelOf(elementNode("Cu"))).toBe("self");
        expect(linked.relations.value.get(elementNode("Ca"))?.slots).toEqual([
            { slot: 2, level: "self" },
        ]);
        expect(linked.levelOf(materialNode(CH1))).toBeNull();
        linked.clear();
        expect(linked.mode.value).toBe("any");
    });

    it("marks the nodes that gained a slot, once per change, for the time of the cue", () => {
        vi.useFakeTimers();
        const linked = start();
        linked.toggle(elementNode("Cu"));
        const first = linked.cue.value;
        expect(first.nodes.has(elementNode("Cu"))).toBe(true);
        expect(first.nodes.has(materialNode(CH1))).toBe(true);
        linked.toggle(elementNode("Ca"));
        const second = linked.cue.value;
        expect(second.generation).toBe(first.generation + 1);
        expect(second.nodes.has(elementNode("Ca"))).toBe(true);
        expect(second.nodes.has(elementNode("Cu"))).toBe(false);
        linked.toggle(elementNode("Ca"));
        expect(linked.cue.value.nodes.size).toBe(0);
        linked.toggle(elementNode("Ca"));
        expect(linked.cue.value.nodes.size).toBeGreaterThan(0);
        vi.advanceTimersByTime(900);
        expect(linked.cue.value.nodes.size).toBe(0);
    });

    it("names the slot a previewed node would take and the element it rests on", async () => {
        vi.useFakeTimers();
        const linked = start();
        linked.toggle(elementNode("Cu"));
        const anchor = document.createElement("button");
        document.body.append(anchor);
        linked.preview(analysisNode(AN1), {
            pointerType: "mouse",
            currentTarget: anchor,
        });
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBe(analysisNode(AN1));
        expect(linked.previewAnchor.value).toBe(anchor);
        expect(linked.previewSlot.value).toBe(2);
        linked.preview(elementNode("Cu"), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewSlot.value).toBeNull();
        expect(linked.previewAnchor.value).toBeNull();
        anchor.remove();
    });

    it("ends a preview at once when the element it started on leaves the page", async () => {
        vi.useFakeTimers();
        const linked = start();
        const anchor = document.createElement("button");
        document.body.append(anchor);
        linked.preview(analysisNode(AN1), {
            pointerType: "mouse",
            currentTarget: anchor,
        });
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBe(analysisNode(AN1));
        anchor.remove();
        await nextTick();
        expect(linked.previewing.value).toBeNull();
        expect(linked.previewAnchor.value).toBeNull();
    });

    it("starts no preview on an element that left the page before its delay", async () => {
        vi.useFakeTimers();
        const linked = start();
        const anchor = document.createElement("button");
        document.body.append(anchor);
        linked.preview(analysisNode(AN1), {
            pointerType: "mouse",
            currentTarget: anchor,
        });
        anchor.remove();
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBeNull();
    });

    it("keeps the node a toggle pinned last, even once unpinned", () => {
        const linked = start();
        expect(linked.lastPinned.value).toBeNull();
        linked.toggle(elementNode("Cu"));
        linked.toggle(elementNode("Ca"));
        expect(linked.lastPinned.value).toBe(elementNode("Ca"));
        linked.toggle(elementNode("Cu"));
        expect(linked.lastPinned.value).toBe(elementNode("Ca"));
        linked.toggle(elementNode("Ca"));
        expect(linked.lastPinned.value).toBe(elementNode("Ca"));
    });

    it("names a node and offers its document", () => {
        const linked = start();
        linked.toggle(materialNode(CH1));
        expect(linked.labelOf(materialNode(CH1))?.value).toBe(
            "Blue of the mantle",
        );
        expect(linked.targets.value.map((target) => target.focus.id)).toEqual([
            CH1,
        ]);
    });

    it("clears on Escape, but not while a menu or dialog is open, nor when the key was handled", () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        const open = document.createElement("button");
        open.setAttribute("aria-expanded", "true");
        open.setAttribute("aria-haspopup", "menu");
        document.body.append(open);
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
        );
        expect(linked.selection.value).toEqual([elementNode("Cu")]);
        open.removeAttribute("aria-haspopup");
        open.setAttribute("aria-controls", "a-folded-window");
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
        );
        expect(linked.selection.value).toEqual([]);
        linked.toggle(elementNode("Cu"));
        open.remove();
        const handled = new KeyboardEvent("keydown", {
            key: "Escape",
            cancelable: true,
        });
        handled.preventDefault();
        document.dispatchEvent(handled);
        expect(linked.selection.value).toEqual([elementNode("Cu")]);
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
        );
        expect(linked.selection.value).toEqual([]);
        expect(announce).toHaveBeenLastCalledWith("No focus");
    });

    it("keeps the selection when Escape dismisses a tooltip shown", async () => {
        vi.useFakeTimers();
        const linked = start();
        linked.toggle(elementNode("Cu"));
        const tip = mount(HelpTip, {
            props: { text: "Download CSV" },
            slots: { default: () => h("button", { type: "button" }, "CSV") },
            attachTo: document.body,
        });
        try {
            tip.element.dispatchEvent(
                Object.assign(new Event("pointerenter"), {
                    pointerType: "mouse",
                }),
            );
            await vi.advanceTimersByTimeAsync(500);
            expect(
                document.querySelector('[role="tooltip"]:not([hidden])'),
            ).not.toBeNull();
            document.body.dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "Escape",
                    bubbles: true,
                    cancelable: true,
                }),
            );
            await nextTick();
            expect(
                document.querySelector('[role="tooltip"]:not([hidden])'),
            ).toBeNull();
            expect(linked.selection.value).toEqual([elementNode("Cu")]);
            document.body.dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "Escape",
                    bubbles: true,
                    cancelable: true,
                }),
            );
            expect(linked.selection.value).toEqual([]);
        } finally {
            tip.unmount();
        }
    });

    it("stops listening to Escape once disposed", () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        scope.stop();
        document.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
        );
        expect(useExplorerStore().compare.selection).toEqual([
            elementNode("Cu"),
        ]);
    });

    it("previews a node after a short delay, for a mouse only, and lets it go after a longer one", async () => {
        vi.useFakeTimers();
        const linked = start();
        linked.preview(elementNode("Cu"), {
            pointerType: "touch",
        } as PointerEvent);
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBeNull();
        linked.preview(elementNode("Cu"), {
            pointerType: "mouse",
        } as PointerEvent);
        await vi.advanceTimersByTimeAsync(40);
        expect(linked.previewing.value).toBeNull();
        await vi.advanceTimersByTimeAsync(80);
        expect(linked.previewing.value).toBe(elementNode("Cu"));
        expect(linked.previewLevels.value.get(materialNode(CH1))).toBe(
            "direct",
        );
        expect(linked.levelOf(materialNode(CH1))).toBeNull();
        linked.preview(null);
        await vi.advanceTimersByTimeAsync(90);
        expect(linked.previewing.value).toBe(elementNode("Cu"));
        linked.preview(elementNode("Cu"));
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBe(elementNode("Cu"));
        linked.preview(null);
        await vi.advanceTimersByTimeAsync(200);
        expect(linked.previewing.value).toBeNull();
        expect(announce).not.toHaveBeenCalled();
    });

    it("drops the selected nodes the Selection no longer links once items and synthesis answer for it", async () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        linked.toggle(analysisNode(AN1));
        announce.mockClear();
        const store = useExplorerStore();
        store.removeFromBasket(BASKET[0].key);
        status.value = "loading";
        await nextTick();
        expect(linked.selection.value).toHaveLength(2);
        answer({ ...SYNTHESIS, elements: [], materials: [], pairs: [] });
        await nextTick();
        expect(linked.selection.value).toEqual([analysisNode(AN1)]);
        expect(announce).toHaveBeenCalledWith(
            "1 node in focus is no longer linked to the Selection and left the focus.",
        );
    });

    it("keeps the selection while the synthesis answers for another Selection", async () => {
        const linked = start();
        linked.toggle(elementNode("Cu"));
        loaded.value = "stale";
        data.value = { ...SYNTHESIS, elements: [] };
        await nextTick();
        expect(linked.selection.value).toEqual([elementNode("Cu")]);
    });
});
