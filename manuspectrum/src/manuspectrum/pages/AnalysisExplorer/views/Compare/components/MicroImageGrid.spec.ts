import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import MicroImageGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MicroImageGrid.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    fileEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    AN1,
    F1,
    ITEMS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    fileNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { AnalysisHit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

let stop: (() => void) | null = null;
let attached: VueWrapper | null = null;

function imageOf(index: number): FileLine {
    const item = ITEMS[index] as { key: string; analysis: AnalysisHit };
    return {
        key: item.key,
        slot: index,
        analysis: item.analysis,
        file: fileEntry({
            id: uuid(900 + index),
            name: `M${index}.jpg`,
            dataKind: "micro-imaging",
        }),
    };
}

function mountGrid(): { view: VueWrapper; linked: LinkedSelection } {
    const started = startLinkedSelection();
    stop = started.stop;
    const view = mount(MicroImageGrid, {
        attachTo: document.body,
        props: { images: [imageOf(0), imageOf(1)] },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
            stubs: { MicroImagePreview: true },
        },
    });
    attached = view;
    return { view, linked: started.linked };
}

function rels(view: VueWrapper, attribute: string): (string | undefined)[] {
    return view.findAll("figure").map((figure) => figure.attributes(attribute));
}

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    attached?.unmount();
    attached = null;
    stop?.();
    stop = null;
    vi.useRealTimers();
});

describe("MicroImageGrid", () => {
    it("captions each image with its slot, analysis and file", () => {
        const { view } = mountGrid();
        expect(
            view.findAll("figcaption").map((caption) => caption.text()),
        ).toEqual([
            `A1${imageOf(0).analysis.name.value}M0.jpg`,
            `A2${imageOf(1).analysis.name.value}M1.jpg`,
        ]);
        expect(rels(view, "data-rel")).toEqual([undefined, undefined]);
    });

    it("selects an image's analysis from its name and outlines it", async () => {
        const { view } = mountGrid();
        const record = view.findAll("button.record")[0];
        await record.trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            analysisNode(AN1),
        ]);
        expect(record.attributes("aria-pressed")).toBe("true");
        expect(rels(view, "data-rel")).toEqual(["self", "none"]);
        expect(
            view.findAll(".slot").map((slot) => slot.attributes("data-rel")),
        ).toEqual(["direct", "none"]);
    });

    it("highlights the images linked to a node selected and fades the others", async () => {
        const { view, linked } = mountGrid();
        linked.toggle(fileNode(F1));
        await view.vm.$nextTick();
        expect(rels(view, "data-rel")).toEqual(["direct", "none"]);
    });

    it("previews an image's analysis under the mouse, fading nothing", async () => {
        vi.useFakeTimers();
        const { view } = mountGrid();
        await view
            .findAll("figure")[1]
            .trigger("pointerenter", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(rels(view, "data-preview")).toEqual([undefined, "self"]);
        expect(rels(view, "data-rel")).toEqual([undefined, undefined]);
    });
});
