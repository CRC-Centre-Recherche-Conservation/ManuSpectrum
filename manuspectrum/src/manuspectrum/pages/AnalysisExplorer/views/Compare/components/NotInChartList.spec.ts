import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import NotInChartList from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/NotInChartList.vue";

import {
    LINKED_SELECTION_KEY,
    SCREEN_FOCUS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    fileEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    AN2,
    ITEMS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { Pinia } from "pinia";
import type { VueWrapper } from "@vue/test-utils";
import type { AnalysisHit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { NotInChartEntry } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

let pinia: Pinia;
let stopLinked: (() => void) | null = null;

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
});

const HIT = analysisHit(1, { canvas: "https://iiif.example/c3" });
const RAW = fileEntry({
    name: "S1.mca",
    role: "raw",
    dataKind: "file",
    downloadUrl: "/files/s1.mca",
    previewUrl: null,
});
const OTHER = fileEntry({
    name: "notes.pdf",
    role: "other",
    dataKind: "file",
    downloadUrl: "javascript:alert(1)",
    previewUrl: null,
});
const GONE = `an:${uuid(199)}:-`;

const ENTRIES: NotInChartEntry[] = [
    {
        key: `af:${HIT.id}:1`,
        slot: 0,
        reason: "raw-file",
        analysis: HIT,
        file: RAW,
    },
    {
        key: `af:${HIT.id}:2`,
        slot: 1,
        reason: "file",
        analysis: HIT,
        file: OTHER,
    },
    {
        key: `an:${HIT.id}:-`,
        slot: 2,
        reason: "no-data",
        analysis: HIT,
        file: null,
    },
    {
        key: `an:${uuid(102)}:-`,
        slot: 3,
        reason: "no-data",
        analysis: analysisHit(2),
        file: null,
    },
    { key: GONE, slot: 4, reason: "missing", analysis: null, file: null },
];

function mountList() {
    return mount(NotInChartList, {
        props: { entries: ENTRIES },
        global: { plugins: [pinia] },
    });
}

function line(wrapper: ReturnType<typeof mountList>, index: number) {
    return wrapper.findAll("li")[index];
}

describe("NotInChartList", () => {
    it("says why each item is in no chart", () => {
        const wrapper = mountList();
        expect(
            wrapper.findAll(".reason").map((reason) => reason.text()),
        ).toEqual([
            "Instrument file: download only.",
            "File with no viewer: download only.",
            "No data to display.",
            "No data to display.",
            "No longer available.",
        ]);
        expect(line(wrapper, 0).find(".slot").text()).toBe("A1");
        expect(line(wrapper, 0).find(".title").text()).toBe(
            "MS1_f12_XRF_03 · S1.mca",
        );
        expect(line(wrapper, 3).find(".title").text()).toBe("MS2_f12_XRF_03");
    });

    it("offers a downloadable file, never an unsafe address", () => {
        const wrapper = mountList();
        const link = line(wrapper, 0).find("a.action");
        expect(link.attributes("href")).toBe("/files/s1.mca");
        expect(link.attributes("download")).toBe("");
        expect(link.text()).toBe("Download");
        expect(link.attributes("aria-label")).toBe("Download S1.mca");
        expect(line(wrapper, 1).find("a.action").exists()).toBe(false);
    });

    it("opens an analysis that holds nothing to show in its document", async () => {
        const wrapper = mountList();
        const store = useExplorerStore();
        const button = line(wrapper, 2).find("button.action");
        expect(button.text()).toBe("Open the analysis");
        expect(button.attributes("aria-label")).toBe(
            "Open the analysis MS1_f12_XRF_03",
        );
        await button.trigger("click");
        expect(store.view).toBe("corpus");
        expect(store.document).toEqual({
            id: HIT.document.id,
            canvas: "https://iiif.example/c3",
        });
        expect(store.focus).toEqual({ kind: "analysis", id: HIT.id });
    });

    it("takes an item no longer available out of the Selection on demand", async () => {
        const store = useExplorerStore();
        store.addManyToBasket([GONE]);
        const wrapper = mountList();
        const button = line(wrapper, 4).find("button.action");
        expect(button.text()).toBe("Remove from the Selection");
        await button.trigger("click");
        expect(store.basket).toEqual([]);
    });

    it("gives the focus to the next item's action once an item is taken out, else the one before", async () => {
        const first = `an:${uuid(198)}:-`;
        const entries: NotInChartEntry[] = [
            {
                key: first,
                slot: 5,
                reason: "missing",
                analysis: null,
                file: null,
            },
            ...ENTRIES,
        ];
        const wrapper = mount(NotInChartList, {
            props: { entries },
            global: { plugins: [pinia] },
            attachTo: document.body,
        });
        await line(wrapper, 0).find("button.action").trigger("click");
        await wrapper.setProps({ entries: ENTRIES });
        await nextTick();
        expect(document.activeElement).toBe(
            line(wrapper, 0).find(".action").element,
        );
        await line(wrapper, 4).find("button.action").trigger("click");
        await wrapper.setProps({ entries: ENTRIES.slice(0, 4) });
        await nextTick();
        expect(document.activeElement).toBe(
            line(wrapper, 3).find(".action").element,
        );
        wrapper.unmount();
    });

    it("hands the focus to the Compare heading once the last item is taken out", async () => {
        const headingFocus = ref(false);
        const wrapper = mount(NotInChartList, {
            props: { entries: ENTRIES.slice(4) },
            global: {
                plugins: [pinia],
                provide: { [SCREEN_FOCUS_KEY as symbol]: headingFocus },
            },
        });
        await line(wrapper, 0).find("button.action").trigger("click");
        expect(headingFocus.value).toBe(true);
    });

    describe("with the linked selection", () => {
        function mountLinked(): {
            wrapper: VueWrapper;
            linked: LinkedSelection;
        } {
            const started = startLinkedSelection();
            stopLinked = started.stop;
            const entries: NotInChartEntry[] = [0, 1].map((slot) => {
                const item = ITEMS[slot] as {
                    key: string;
                    analysis: AnalysisHit;
                };
                return {
                    key: item.key,
                    slot,
                    reason: "no-data",
                    analysis: item.analysis,
                    file: null,
                };
            });
            const wrapper = mount(NotInChartList, {
                props: {
                    entries: [
                        ...entries,
                        {
                            key: GONE,
                            slot: 4,
                            reason: "missing",
                            analysis: null,
                            file: null,
                        },
                    ],
                },
                global: {
                    plugins: [pinia],
                    provide: {
                        [LINKED_SELECTION_KEY as symbol]: started.linked,
                    },
                },
            });
            return { wrapper, linked: started.linked };
        }

        function rels(wrapper: VueWrapper, attribute: string) {
            return wrapper.findAll("li").map((li) => li.attributes(attribute));
        }

        afterEach(() => {
            stopLinked?.();
            stopLinked = null;
            vi.useRealTimers();
        });

        it("makes an analysis's title its toggle; an item with none has no toggle", async () => {
            const { wrapper } = mountLinked();
            const toggles = wrapper.findAll("button.record");
            expect(toggles).toHaveLength(2);
            await toggles[1].trigger("click");
            expect(useExplorerStore().compare.selection).toEqual([
                analysisNode(AN2),
            ]);
            expect(toggles[1].attributes("aria-pressed")).toBe("true");
            expect(rels(wrapper, "data-rel")).toEqual(["none", "self", "none"]);
        });

        it("highlights the items linked to the selection and marks the others unlinked", async () => {
            const { wrapper, linked } = mountLinked();
            expect(rels(wrapper, "data-rel")).toEqual([
                undefined,
                undefined,
                undefined,
            ]);
            linked.toggle(elementNode("Fe"));
            await wrapper.vm.$nextTick();
            expect(rels(wrapper, "data-rel")).toEqual([
                "direct",
                "none",
                "none",
            ]);
        });

        it("previews an item's analysis under the mouse", async () => {
            vi.useFakeTimers();
            const { wrapper } = mountLinked();
            await wrapper
                .findAll("li")[0]
                .trigger("pointerenter", { pointerType: "mouse" });
            vi.runAllTimers();
            await wrapper.vm.$nextTick();
            expect(rels(wrapper, "data-preview")).toEqual([
                "self",
                undefined,
                undefined,
            ]);
        });
    });
});
