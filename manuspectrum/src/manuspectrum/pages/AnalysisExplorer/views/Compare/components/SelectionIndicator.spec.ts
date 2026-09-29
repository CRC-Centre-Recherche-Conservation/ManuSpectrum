import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { computed, effectScope, ref, shallowRef } from "vue";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import SelectionIndicator from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/SelectionIndicator.vue";

import { useLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { uuid } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    AN1,
    AN2,
    BASKET,
    BY_KEY,
    C2,
    CH1,
    D1,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { EffectScope } from "vue";
import type { Pinia } from "pinia";
import type { VueWrapper } from "@vue/test-utils";
import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

const OTHER = uuid(2);

let pinia: Pinia;
let scope: EffectScope;
let announce: ReturnType<typeof vi.fn>;
let wrapper: VueWrapper | null = null;

function linkedOf(synthesis: SynthesisResponse): LinkedSelection {
    scope = effectScope();
    const keys = BASKET.map((item) => item.key);
    return scope.run(() =>
        useLinkedSelection({
            items: {
                byKey: ref(new Map(BY_KEY)),
                missing: ref(new Set<string>()),
                settled: computed(() => true),
                status: ref<RequestStatus>("ready"),
                retry: () => undefined,
            },
            synthesis: {
                status: ref<RequestStatus>("ready"),
                data: shallowRef(synthesis),
                loaded: ref([...keys].sort().join(",")),
                retry: () => undefined,
            },
            announce,
        }),
    )!;
}

function mountIndicator(synthesis: SynthesisResponse = SYNTHESIS): {
    view: VueWrapper;
    linked: LinkedSelection;
} {
    const linked = linkedOf(synthesis);
    wrapper = mount(SelectionIndicator, {
        attachTo: document.body,
        global: {
            plugins: [pinia],
            provide: { [LINKED_SELECTION_KEY as symbol]: linked },
        },
    });
    return { view: wrapper, linked };
}

function button(view: VueWrapper) {
    return view.find("button.selection-indicator-button");
}

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    announce = vi.fn();
    useExplorerStore().addManyToBasket(BASKET.map((item) => item.key));
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    scope.stop();
    vi.useRealTimers();
});

describe("SelectionIndicator", () => {
    it("says nothing is in focus and explains how to focus, as a disclosure", async () => {
        const { view } = mountIndicator();
        expect(button(view).find(".summary").text()).toBe("No focus");
        expect(button(view).attributes("aria-expanded")).toBe("false");
        expect(button(view).attributes("aria-controls")).toBeUndefined();
        await button(view).trigger("click");
        const panel = view.find(".panel");
        expect(button(view).attributes("aria-expanded")).toBe("true");
        expect(button(view).attributes("aria-controls")).toBe(
            panel.attributes("id"),
        );
        expect(panel.find(".hint").text()).toContain(
            "Each click adds it to the focus",
        );
        expect(panel.find(".chips").exists()).toBe(false);
        expect(panel.find(".clear").exists()).toBe(false);
    });

    it("shows the slots in focus and lists one legend row per pinned node, which unpins it, and Clear the focus", async () => {
        const { view, linked } = mountIndicator();
        linked.toggle(elementNode("Cu"));
        linked.toggle(materialNode(CH1));
        await view.vm.$nextTick();
        expect(button(view).find(".summary").text()).toBe(
            "2 in focus · 2 related",
        );
        expect(
            button(view)
                .findAll(".dots .focus-slot-dot")
                .map((dot) => dot.text()),
        ).toEqual(["1", "2"]);
        expect(button(view).classes()).toContain("is-active");
        await button(view).trigger("click");
        expect(view.find(".chips").attributes("aria-label")).toBe("In focus");
        const rows = view.findAll(".chips .chip-row");
        expect(rows.map((row) => row.find(".chip-label").text())).toEqual([
            "Cu",
            "Blue of the mantle",
        ]);
        expect(rows.map((row) => row.find(".chip-kind").text())).toEqual([
            "Element",
            "Identified material",
        ]);
        expect(rows.map((row) => row.find(".chip-counts").text())).toEqual([
            "2 direct · 1 evidence",
            "0 direct · 1 evidence",
        ]);
        const unpins = view.findAll(".chips button.unpin");
        expect(unpins[0].attributes("aria-label")).toBe(
            "Take Cu out of the focus",
        );
        await unpins[0].trigger("click");
        expect(linked.selection.value).toEqual([materialNode(CH1)]);
        expect(linked.slots.value).toEqual([null, materialNode(CH1)]);
        expect(document.activeElement).toBe(
            view.find(".chips button.unpin").element,
        );
        expect(view.find(".chip-row .focus-slot-dot").text()).toBe("2");
        await view.find("button.clear").trigger("click");
        expect(view.find("button.clear").exists()).toBe(false);
        expect(linked.selection.value).toEqual([]);
        expect(view.find(".panel").exists()).toBe(false);
        expect(document.activeElement).toBe(button(view).element);
    });

    it("offers « any » or « all » once two nodes are pinned, as pressed buttons", async () => {
        const { view, linked } = mountIndicator();
        linked.toggle(elementNode("Cu"));
        await button(view).trigger("click");
        expect(view.find(".mode").exists()).toBe(false);
        expect(view.find(".heading-mode").text()).toBe(
            "what relates to any of them",
        );
        linked.toggle(elementNode("Ca"));
        await view.vm.$nextTick();
        const modes = view.findAll(".mode button");
        expect(modes.map((mode) => mode.text())).toEqual([
            "any of them",
            "all of them",
        ]);
        expect(modes.map((mode) => mode.attributes("aria-pressed"))).toEqual([
            "true",
            "false",
        ]);
        await modes[1].trigger("click");
        expect(linked.mode.value).toBe("all");
        expect(view.find(".heading-mode").text()).toBe(
            "what relates to all of them",
        );
        expect(
            view
                .findAll(".mode button")
                .map((mode) => mode.attributes("aria-pressed")),
        ).toEqual(["false", "true"]);
    });

    it("says which slot a previewed node would take while nothing is pinned", async () => {
        vi.useFakeTimers();
        const { view, linked } = mountIndicator();
        linked.preview(elementNode("Cu"), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        expect(button(view).find(".summary").text()).toBe(
            "Cu would be ① · 3 linked",
        );
        expect(button(view).classes()).toContain("is-preview");
    });

    it("promises no slot to a node previewed while the focus is full", async () => {
        vi.useFakeTimers();
        const { view, linked } = mountIndicator();
        for (const id of [
            elementNode("Cu"),
            elementNode("Ca"),
            materialNode(CH1),
            analysisNode(AN2),
        ]) {
            linked.toggle(id);
        }
        await view.vm.$nextTick();
        const summary = button(view).find(".summary").text();
        expect(summary).toBe(linked.summary.value);
        linked.preview(analysisNode(AN1), { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(200);
        expect(button(view).find(".summary").text()).toBe(summary);
        expect(button(view).classes()).not.toContain("is-preview");
        expect(button(view).attributes("style")).not.toContain("--hp");
    });

    it("opens the one document of the linked records on its folio and record", async () => {
        const { view, linked } = mountIndicator();
        linked.toggle(analysisNode(AN2));
        await button(view).trigger("click");
        const link = view.find("a.open-document");
        expect(link.text()).toBe("Open in the document");
        const query = new URLSearchParams(link.attributes("href")!.slice(1));
        expect(query.get("doc")).toBe(D1);
        expect(query.get("canvas")).toBe(C2);
        expect(query.get("focus")).toBe(`analysis:${AN2}`);
        await link.trigger("click");
        const store = useExplorerStore();
        expect(store.view).toBe("corpus");
        expect(store.document).toEqual({ id: D1, canvas: C2 });
        expect(store.focus).toEqual({ kind: "analysis", id: AN2 });
    });

    it("offers a menu of documents when the linked records span several", async () => {
        const { view, linked } = mountIndicator({
            ...SYNTHESIS,
            canvases: [
                ...SYNTHESIS.canvases.map((entry) => ({
                    ...entry,
                    analyses: entry.analyses.filter((id) => id !== AN1),
                })),
                {
                    canvas: "https://iiif.example/other",
                    label: "f. 1",
                    document: OTHER,
                    selected: true,
                    analyses: [AN1],
                    materials: [],
                },
            ],
        });
        linked.toggle(analysisNode(AN2));
        linked.toggle(analysisNode(AN1));
        await button(view).trigger("click");
        expect(view.find("a.open-document").exists()).toBe(false);
        const menuButton = view.find("button.documents-button");
        expect(menuButton.attributes("aria-haspopup")).toBe("menu");
        await menuButton.trigger("click");
        const entries = view.findAll('[role="menuitem"]');
        expect(entries.map((entry) => entry.text())).toEqual([
            "Manuscript 1",
            "Document",
        ]);
        expect(document.activeElement).toBe(entries[0].element);
        await view.find('[role="menu"]').trigger("keydown", { key: "Escape" });
        expect(view.find('[role="menu"]').exists()).toBe(false);
        expect(view.find(".panel").exists()).toBe(true);
    });

    it("closes on Escape without clearing, and on a pointer down outside", async () => {
        const { view, linked } = mountIndicator();
        linked.toggle(elementNode("Cu"));
        await button(view).trigger("click");
        await view.find(".panel").trigger("keydown", { key: "Escape" });
        expect(view.find(".panel").exists()).toBe(false);
        expect(document.activeElement).toBe(button(view).element);
        expect(linked.selection.value).toEqual([elementNode("Cu")]);
        await button(view).trigger("click");
        document.body.dispatchEvent(
            new Event("pointerdown", { bubbles: true }),
        );
        await view.vm.$nextTick();
        expect(view.find(".panel").exists()).toBe(false);
    });

    it("folds on Escape with the focus on its button, opened by a click or a hover, without clearing", async () => {
        vi.useFakeTimers();
        const { view, linked } = mountIndicator();
        linked.toggle(elementNode("Cu"));
        await button(view).trigger("click");
        (button(view).element as HTMLButtonElement).focus();
        await button(view).trigger("keydown", { key: "Escape" });
        expect(view.find(".panel").exists()).toBe(false);
        expect(linked.selection.value).toEqual([elementNode("Cu")]);

        await view
            .find(".selection-indicator")
            .trigger("pointerenter", { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(600);
        expect(view.find(".panel").exists()).toBe(true);
        (button(view).element as HTMLButtonElement).focus();
        await button(view).trigger("keydown", { key: "Escape" });
        expect(view.find(".panel").exists()).toBe(false);
        expect(linked.selection.value).toEqual([elementNode("Cu")]);
        expect(document.activeElement).toBe(button(view).element);
    });

    it("leaves Escape on its folded button to the linked selection, which clears", async () => {
        const { view, linked } = mountIndicator();
        linked.toggle(elementNode("Cu"));
        await view.vm.$nextTick();
        await button(view).trigger("keydown", { key: "Escape" });
        expect(linked.selection.value).toEqual([]);
    });

    it("opens after a long hover of a mouse and closes when it leaves", async () => {
        vi.useFakeTimers();
        const { view } = mountIndicator();
        await view
            .find(".selection-indicator")
            .trigger("pointerenter", { pointerType: "touch" });
        await vi.advanceTimersByTimeAsync(1000);
        expect(view.find(".panel").exists()).toBe(false);
        await view
            .find(".selection-indicator")
            .trigger("pointerenter", { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(300);
        expect(view.find(".panel").exists()).toBe(false);
        await vi.advanceTimersByTimeAsync(300);
        expect(view.find(".panel").exists()).toBe(true);
        await view
            .find(".selection-indicator")
            .trigger("pointerleave", { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(400);
        expect(view.find(".panel").exists()).toBe(false);
    });

    it("stays open when the mouse leaves a panel opened by a click", async () => {
        vi.useFakeTimers();
        const { view } = mountIndicator();
        await button(view).trigger("click");
        await view
            .find(".selection-indicator")
            .trigger("pointerleave", { pointerType: "mouse" });
        await vi.advanceTimersByTimeAsync(400);
        expect(view.find(".panel").exists()).toBe(true);
    });
});
