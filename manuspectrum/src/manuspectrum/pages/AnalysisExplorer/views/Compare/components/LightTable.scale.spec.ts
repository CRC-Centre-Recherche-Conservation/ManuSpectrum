import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import LightTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LightTable.vue";

import {
    ANNOUNCE_KEY,
    WINDOW_ACTIONS_KEY,
    WINDOW_FRAME_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    imagingEntry,
    layerOf,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { TableFrame } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-side-by-side", () => ({}));

/** The real leaflet and leaflet-iiif, on a fake image server that answers only the info.json. */
const SERVED: Record<string, { width: number; height: number }> = {
    big: { width: 1378, height: 1355 },
    small: { width: 600, height: 677 },
};
const L_FRAME: TableFrame = { size: "L", enlarged: false, phone: false };

function line(): MapLine {
    const analysis = analysisHit(1);
    return {
        key: `an:${analysis.id}:-`,
        slot: 1,
        analysis,
        file: imagingEntry({
            id: `${analysis.id}:imaging:0`,
            layers: ["big", "small"].map((name, index) =>
                layerOf({
                    index,
                    id: `c1-${index}`,
                    label: `L1.${index}`,
                    image: {
                        service: `https://iiif.example/${name}`,
                        url: null,
                        width: SERVED[name].width,
                        height: SERVED[name].height,
                    },
                }),
            ),
        }),
        named: null,
    };
}

let wrapper: VueWrapper | null = null;
let errors: unknown[] = [];

function onError(event: ErrorEvent): void {
    errors.push(event.error ?? event.message);
}

beforeEach(() => {
    setActivePinia(createPinia());
    window.localStorage.clear();
    L.control.sideBySide = vi.fn(() => {
        const control = {
            addTo: vi.fn(() => control),
            remove: vi.fn(),
            setLeftLayers: vi.fn(() => control),
            setRightLayers: vi.fn(() => control),
            getPosition: () => 400,
            _range: document.createElement("input"),
        };
        return control;
    }) as unknown as typeof L.control.sideBySide;
    errors = [];
    window.addEventListener("error", onError);
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) => {
            const name = Object.keys(SERVED).find((key) =>
                url.includes(`/${key}/`),
            ) as string;
            return Promise.resolve({
                json: () =>
                    Promise.resolve({
                        "@context": "http://iiif.io/api/image/2/context.json",
                        profile: ["http://iiif.io/api/image/2/level1.json"],
                        ...SERVED[name],
                    }),
            });
        }),
    );
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
        configurable: true,
        get: () => 900,
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
        configurable: true,
        get: () => 500,
    });
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    window.removeEventListener("error", onError);
    vi.unstubAllGlobals();
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientWidth;
    delete (HTMLElement.prototype as unknown as Record<string, unknown>)
        .clientHeight;
});

async function settle(): Promise<void> {
    for (let turn = 0; turn < 6; turn += 1) await flushPromises();
}

describe("two canvases served at different sizes, on the real leaflet-iiif", () => {
    it("says « Different scale » in a synced grid of two, with no error thrown in the tile layer", async () => {
        wrapper = mount(LightTable, {
            attachTo: document.body,
            props: { maps: [line()], windowId: "auto:chemical-imaging" },
            global: {
                provide: {
                    [WINDOW_RESIZE_KEY as symbol]: ref(0),
                    [WINDOW_FRAME_KEY as symbol]: ref(L_FRAME),
                    [ANNOUNCE_KEY as symbol]: () => undefined,
                    [WINDOW_ACTIONS_KEY as symbol]: {
                        register: () => () => undefined,
                    },
                },
            },
        });
        await wrapper.find('[data-layout="grid2"]').trigger("click");
        await wrapper.find('[data-action="sync-views"]').trigger("click");
        await settle();
        expect(errors).toEqual([]);
        expect(wrapper.findAll(".scale-badge")).toHaveLength(1);
    });
});
