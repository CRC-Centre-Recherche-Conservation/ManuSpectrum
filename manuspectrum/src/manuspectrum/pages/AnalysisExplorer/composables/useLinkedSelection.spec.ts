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
        expect(linked.summary.value).toBe("1 selected · 3 related");
        expect(announce).toHaveBeenLastCalledWith("1 selected · 3 related");
        expect(linked.counts.value).toMatchObject({ an: 1, ch: 2 });
        linked.toggle(elementNode("Cu"));
        expect(linked.summary.value).toBe("Nothing selected");
        expect(announce).toHaveBeenLastCalledWith("Nothing selected");
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
        expect(announce).toHaveBeenLastCalledWith("Nothing selected");
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
            "1 selected node is no longer linked to the Selection and was unselected.",
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
