import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { nextTick, ref } from "vue";

import NotInChartList from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/NotInChartList.vue";

import { SCREEN_FOCUS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    fileEntry,
    imagingEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Pinia } from "pinia";
import type { NotInChartEntry } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

let pinia: Pinia;

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
        reason: "imaging",
        analysis: HIT,
        file: imagingEntry(),
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
            "Element maps are not compared side by side yet.",
            "No spectrum, map or image to show.",
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

    it("opens an analysis that holds maps or nothing to show in its document", async () => {
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
});
