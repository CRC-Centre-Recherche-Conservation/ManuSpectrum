import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import MapView from "@/manuspectrum/pages/AnalysisExplorer/views/Map/MapView.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    eventsResponse,
    label,
    mapEvent,
    mapPlace,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { FakeMap } from "@/manuspectrum/pages/AnalysisExplorer/testing/maplibre.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    BORDERS_LAYER,
    TERRITORIES_SOURCE,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/stage-layers.ts";

import type { Pinia } from "pinia";
import type { VueWrapper } from "@vue/test-utils";
import type { EventsResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const webgl = vi.hoisted(() => ({ available: true }));

vi.mock("maplibre-gl", async () =>
    (
        await import(
            "@/manuspectrum/pages/AnalysisExplorer/testing/maplibre.ts"
        )
    ).maplibreModule(),
);

vi.mock("@/manuspectrum/pages/AnalysisExplorer/views/Map/webgl.ts", () => ({
    webglAvailable: () => webgl.available,
}));

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const LAPIS = "http://material.test/lapis";
const PARIS = uuid(10);
const ROUEN = uuid(11);

const fetchMock = vi.fn();
const announce = vi.fn();
let pinia: Pinia;
let wrapper: VueWrapper | null = null;

function response(): EventsResponse {
    return eventsResponse({
        events: [
            mapEvent({
                component: { id: uuid(50), name: label("Initial") },
                materials: [
                    {
                        id: LAPIS,
                        name: label("Lapis lazuli"),
                        reliability: null,
                        characterization: uuid(200),
                    },
                ],
            }),
            mapEvent({
                id: "production:d2:p2",
                document: { id: uuid(2), name: label("Ms 60") },
                carrier: {
                    id: uuid(2),
                    model: "document",
                    name: label("Ms 60"),
                },
                place: ROUEN,
                date: { start: 1401, end: 1450, approximate: false },
                analyses: [uuid(101)],
            }),
            mapEvent({
                id: "production:d3:-",
                document: { id: uuid(3), name: label("Ms 61") },
                place: null,
                placeSource: null,
                analyses: [],
            }),
        ],
        places: {
            [PARIS]: mapPlace(),
            [ROUEN]: mapPlace({
                id: ROUEN,
                name: label("Rouen"),
                lngLat: [1.1, 49.44],
            }),
        },
        unplaced: 1,
        materials: {
            [LAPIS]: {
                uri: LAPIS,
                label: label("Lapis lazuli"),
                colours: [],
                swatch: null,
            },
        },
        analysisNames: {
            [uuid(100)]: label("X01"),
            [uuid(101)]: label("X02"),
        },
    });
}

async function mountView(): Promise<VueWrapper> {
    wrapper = mount(MapView, {
        attachTo: document.body,
        global: {
            plugins: [pinia, PrimeVue],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        },
    });
    await flushPromises();
    await flushPromises();
    return wrapper;
}

function eventCalls(): string[] {
    return fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.includes("explorer-events"));
}

function modeButton(view: VueWrapper, text: string) {
    const found = view
        .findAll(".mode-switch button")
        .find((button) => button.text() === text);
    if (!found) throw new Error(`no mode button ${text}`);
    return found;
}

beforeEach(() => {
    forgetPayloads();
    pinia = createPinia();
    setActivePinia(pinia);
    FakeMap.reset();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    webgl.available = true;
    announce.mockReset();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (url: string) =>
        url.includes("explorer-events")
            ? jsonResponse(response())
            : jsonResponse({ values: [], total: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    document.documentElement.lang = "en";
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe("MapView", () => {
    it("asks the events of the filters", async () => {
        useExplorerStore().setFilter("eventType", ["analysis"]);
        await mountView();
        expect(eventCalls()).toHaveLength(1);
        expect(eventCalls()[0]).toContain("/en/manuspectrum:explorer-events?");
        expect(eventCalls()[0]).toContain("eventType=analysis");
    });

    it("writes the mode chosen in the map state and announces it", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        expect(modeButton(view, "Places").attributes("aria-pressed")).toBe(
            "true",
        );
        await modeButton(view, "Small multiples").trigger("click");
        expect(store.mapState.mode).toBe("multiples");
        expect(announce).toHaveBeenCalled();
        await flushPromises();
        expect(view.find(".small-multiples").exists()).toBe(true);
        await modeButton(view, "Places").trigger("click");
        expect(store.mapState.mode).toBe("places");
    });

    it("keeps Territories unavailable, with its reason, while no material is followed", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        const button = modeButton(view, "Territories");
        expect(button.attributes("aria-disabled")).toBe("true");
        expect(view.text()).toContain(
            "Follow at least one material to draw territories.",
        );
        await button.trigger("click");
        expect(store.mapState.mode).toBe("places");
    });

    it("draws territories for a followed material, with the influence note", async () => {
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS] });
        const view = await mountView();
        const button = modeButton(view, "Territories");
        expect(button.attributes("aria-disabled")).toBeUndefined();
        await button.trigger("click");
        await flushPromises();
        expect(store.mapState.mode).toBe("territories");
        const source = FakeMap.last().getSource(TERRITORIES_SOURCE);
        const drawn = source?.setDataCalls.at(-1) as {
            features: unknown[];
        };
        expect(drawn.features.length).toBeGreaterThan(0);
        const note = view.find(".territory-note");
        expect(note.attributes("role")).toBe("note");
        expect(note.text()).toContain("Influence model, not data");
        expect(note.find("input[type='range']").attributes("min")).toBe("60");
        expect(note.find("output").text()).toBe("150 km");
    });

    it("shows the place list and the timeline without WebGL, and builds no map", async () => {
        webgl.available = false;
        const view = await mountView();
        expect(view.find(".map-unavailable[role='status']").text()).toBe(
            "Map unavailable in this browser: the place list and the timeline still work.",
        );
        expect(view.find(".place-list").exists()).toBe(true);
        expect(view.find(".map-timeline").exists()).toBe(true);
        expect(FakeMap.instances).toHaveLength(0);
    });

    it("opens the panel on a place chosen in the list, and gives the focus back on close", async () => {
        const view = await mountView();
        expect(view.find(".side .hint").exists()).toBe(true);
        const row = view.find(`.place-list [data-place='${PARIS}']`);
        (row.element as HTMLElement).focus();
        await row.trigger("click");
        await flushPromises();
        expect(view.find(".map-panel").exists()).toBe(true);
        expect(view.find(".side .hint").exists()).toBe(false);
        expect(row.attributes("aria-current")).toBe("true");
        await view.find(".map-panel .foot .close").trigger("click");
        await flushPromises();
        expect(view.find(".map-panel").exists()).toBe(false);
        expect(document.activeElement).toBe(row.element);
    });

    it("lights a place of the list on the map while it is hovered", async () => {
        const view = await mountView();
        const map = FakeMap.last();
        await view
            .find(`.place-list [data-place='${ROUEN}']`)
            .trigger("mouseenter");
        await flushPromises();
        expect(
            map.featureStates.some(
                ([target, state]) =>
                    target.id === ROUEN && state.hover === true,
            ),
        ).toBe(true);
    });

    it("opens the events without a mapped place", async () => {
        const view = await mountView();
        const button = view.find(".unplaced");
        expect(button.text()).toBe("1 event without a mapped place");
        await button.trigger("click");
        await flushPromises();
        expect(view.find(".map-panel").text()).toContain(
            "Events without a mapped place",
        );
    });

    it("ticks the default event types while none is chosen, and clears the filter on the defaults again", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        const boxes = view.findAll(".event-types input[type='checkbox']");
        expect(
            boxes.map((box) => (box.element as HTMLInputElement).checked),
        ).toEqual([true, true, true, false, false]);
        await boxes[3].setValue(true);
        expect(store.filters.eventType).toEqual([
            "alteration",
            "analysis",
            "modification",
            "production",
        ]);
        await boxes[3].setValue(false);
        expect(store.filters.eventType).toEqual([]);
    });

    it("hides the historical borders without a period, and draws those of the period's middle year", async () => {
        const store = useExplorerStore();
        store.setMapState({ borders: true });
        const view = await mountView();
        const map = FakeMap.last();
        expect(view.text()).toContain(
            "Choose a period on the timeline to see its borders",
        );
        expect(
            map.layers.find((entry) => entry.layer.id === BORDERS_LAYER)?.layer
                .layout,
        ).toEqual({ visibility: "none" });
        store.setMapState({ brush: [1300, 1400] });
        await flushPromises();
        expect(view.find(".borders").text()).toContain(
            "Historical borders (1350)",
        );
        expect(map.layoutCalls.at(-1)).toEqual([
            BORDERS_LAYER,
            "visibility",
            "visible",
        ]);
    });

    it("links the exports with the filters and the page language", async () => {
        document.documentElement.lang = "fr";
        useExplorerStore().setFilter("eventType", ["analysis"]);
        const view = await mountView();
        const csv = view.find("a.export[data-format='csv']");
        const geojson = view.find("a.export[data-format='geojson']");
        expect(csv.attributes("href")).toBe(
            "/en/manuspectrum:explorer-events-csv?eventType=analysis&lang=fr",
        );
        expect(geojson.attributes("href")).toBe(
            "/en/manuspectrum:explorer-events-geojson?eventType=analysis&lang=fr",
        );
    });

    it("says which third-party services the map calls", async () => {
        const view = await mountView();
        expect(view.find(".third-party").text()).toBe(
            "Background tiles: OpenFreeMap © OpenMapTiles, data from OpenStreetMap; historical borders: OpenHistoricalMap contributors. These services receive your IP address when the map loads.",
        );
    });

    it("says when no event is kept, with a way out per filter", async () => {
        fetchMock.mockImplementation(async () =>
            jsonResponse(eventsResponse({ events: [], places: {} })),
        );
        const store = useExplorerStore();
        store.setView("map");
        store.setFilter("eventType", ["analysis"]);
        const view = await mountView();
        const empty = view.find(".no-events");
        expect(empty.text()).toContain("No event matches these filters.");
        expect(empty.findAll("button").length).toBeGreaterThan(0);
    });

    it("offers Retry when the events cannot be read", async () => {
        fetchMock.mockImplementation(async () => jsonResponse({}, 500));
        const view = await mountView();
        expect(view.find(".stage .unavailable-state").exists()).toBe(true);
        fetchMock.mockImplementation(async () => jsonResponse(response()));
        await view.find(".stage .unavailable-state .retry").trigger("click");
        await flushPromises();
        await flushPromises();
        expect(view.find(".stage .unavailable-state").exists()).toBe(false);
        expect(eventCalls().length).toBeGreaterThan(1);
    });
});
