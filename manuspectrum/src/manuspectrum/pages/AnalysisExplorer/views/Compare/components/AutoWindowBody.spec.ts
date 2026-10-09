import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import AutoWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/AutoWindowBody.vue";
import LightTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LightTable.vue";

import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    imagingEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    stubIiifLayer,
    stubSideBySide,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { ChemicalImagingWindow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("leaflet-side-by-side", () => ({}));

let wrapper: VueWrapper | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
    window.localStorage.clear();
    stubIiifLayer({ size: { w: 2000, h: 3000 } });
    stubSideBySide();
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

describe("AutoWindowBody", () => {
    it("draws the light table for the imaging window", async () => {
        const analysis = analysisHit(1);
        const window: ChemicalImagingWindow = {
            id: "auto:chemical-imaging",
            kind: "chemical-imaging",
            keys: [`an:${analysis.id}:-`],
            maps: [
                {
                    key: `an:${analysis.id}:-`,
                    slot: 1,
                    analysis,
                    file: imagingEntry(),
                    named: null,
                },
            ],
            folded: false,
        };
        wrapper = mount(AutoWindowBody, {
            attachTo: document.body,
            props: { window, title: "Imaging" },
            global: { provide: { [WINDOW_RESIZE_KEY as symbol]: ref(0) } },
        });
        await flushPromises();
        expect(wrapper.findComponent(LightTable).exists()).toBe(true);
        expect(wrapper.findComponent(LightTable).props("windowId")).toBe(
            "auto:chemical-imaging",
        );
    });
});
