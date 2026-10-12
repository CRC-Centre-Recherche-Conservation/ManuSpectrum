import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import ActiveFiltersBar from "@/manuspectrum/pages/AnalysisExplorer/components/ActiveFiltersBar.vue";
import MapView from "@/manuspectrum/pages/AnalysisExplorer/views/Map/MapView.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    ANNOUNCE_KEY,
    FACET_LABELS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
import type {
    EventsResponse,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

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

const Shell = defineComponent({
    setup: () => () => h("div", [h(ActiveFiltersBar), h(MapView)]),
});

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
    it("names the chip of a ticked material, from the events payload", async () => {
        const labels = ref(new Map<string, Label>());
        useExplorerStore().setFacet("material", [LAPIS]);
        wrapper = mount(Shell, {
            attachTo: document.body,
            global: {
                plugins: [pinia, PrimeVue],
                provide: {
                    [ANNOUNCE_KEY as symbol]: announce,
                    [FACET_LABELS_KEY as symbol]: labels,
                },
            },
        });
        await flushPromises();
        await flushPromises();
        expect(labels.value.get(`material:${LAPIS}`)?.value).toBe(
            "Lapis lazuli",
        );
        expect(labels.value.get(`place:${ROUEN}`)?.value).toBe("Rouen");
        const bar = wrapper.get(".active-filters").text();
        expect(bar).toContain("Lapis lazuli");
        expect(bar).not.toContain(LAPIS);
    });

    it("asks the events of the filters", async () => {
        useExplorerStore().setFilter("eventType", ["modification"]);
        await mountView();
        expect(eventCalls()).toHaveLength(1);
        expect(eventCalls()[0]).toContain("/en/manuspectrum:explorer-events?");
        expect(eventCalls()[0]).toContain("eventType=modification");
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
        const body = note.get(".note-body");
        const toggle = note.get(".note-toggle");
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect((body.element as HTMLElement).style.display).toBe("none");
        await toggle.trigger("click");
        expect(toggle.attributes("aria-expanded")).toBe("true");
        expect((body.element as HTMLElement).style.display).not.toBe("none");
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

    it("ticks the three event types while none is chosen, and clears the filter when all are ticked again", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        const boxes = view.findAll(".event-types input[type='checkbox']");
        expect(
            boxes.map((box) => (box.element as HTMLInputElement).checked),
        ).toEqual([true, true, true]);
        await boxes[2].setValue(false);
        expect(store.filters.eventType).toEqual(["modification", "production"]);
        await boxes[2].setValue(true);
        expect(store.filters.eventType).toEqual([]);
    });

    it("lists the four reliability levels, all ticked, and drops a level's materials when unticked", async () => {
        const level = (id: string, name: string, rank: number) => ({
            id,
            uri: id,
            label: label(name),
            rank,
        });
        const scale = {
            levels: [
                level("doubt", "Uncertain", 3),
                level("sure", "Certain", 0),
                level("likely", "Likely", 1),
                level("caution", "Use with caution", 2),
            ],
        };
        const base = response();
        base.events[0].materials[0].reliability = "sure";
        fetchMock.mockImplementation(async () =>
            jsonResponse({ ...base, certaintyScale: scale }),
        );
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS], legend: true });
        const view = await mountView();
        const rows = view.findAll(".levels .value");
        expect(rows.map((row) => row.find(".label").text())).toEqual([
            "Certain",
            "Likely",
            "Use with caution",
            "Uncertain",
        ]);
        expect(
            rows.map(
                (row) => (row.get("input").element as HTMLInputElement).checked,
            ),
        ).toEqual([true, true, true, true]);
        expect(rows[0].find(".count").text()).toBe("1");
        expect(view.get(".legend .followed .count").text()).toBe("1");
        await rows[0].get("input").setValue(false);
        await flushPromises();
        expect(view.get(".legend .followed .count").text()).toBe("0");
    });

    it("takes the places of a material event off the map when every level is unticked, followed or not", async () => {
        const level = (id: string, rank: number) => ({
            id,
            uri: id,
            label: label(id),
            rank,
        });
        const base = response();
        base.events[0].materials[0].reliability = "sure";
        fetchMock.mockImplementation(async () =>
            jsonResponse({
                ...base,
                certaintyScale: {
                    levels: [level("sure", 0), level("doubt", 3)],
                },
            }),
        );
        const view = await mountView();
        const place = `.place-list [data-place='${PARIS}']`;
        expect(view.find(place).exists()).toBe(true);
        await view.findAll(".levels .value")[0].get("input").setValue(false);
        await flushPromises();
        expect(view.find(place).exists()).toBe(false);
        expect(view.find(`.place-list [data-place='${ROUEN}']`).exists()).toBe(
            true,
        );
    });

    it("hides the historical borders without a period, and draws those of the period's middle year", async () => {
        const store = useExplorerStore();
        store.setMapState({ borders: true });
        const view = await mountView();
        const map = FakeMap.last();
        const hint = view.get(".stage-head .borders-hint");
        expect(hint.text()).toBe(
            "Narrow the period with the timeline slider to see its borders.",
        );
        expect(hint.element.previousElementSibling?.classList).toContain(
            "unplaced",
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

    it("folds the legend by default and keeps the reader's choice across modes", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        const toggle = () => view.get(".legend .toggle");
        expect(toggle().attributes("aria-expanded")).toBe("false");
        await toggle().trigger("click");
        expect(store.mapState.legend).toBe(true);
        await modeButton(view, "Small multiples").trigger("click");
        await modeButton(view, "Places").trigger("click");
        await flushPromises();
        expect(toggle().attributes("aria-expanded")).toBe("true");
        expect(view.get("div.legend").classes()).toContain("open");
    });

    it("isolates a followed material's territory while its legend row is hovered", async () => {
        const store = useExplorerStore();
        store.setMapState({
            track: [LAPIS],
            mode: "territories",
            legend: true,
        });
        const view = await mountView();
        const map = FakeMap.last();
        await view.get(".legend .followed li").trigger("mouseenter");
        expect(map.paintCalls.map(([layer]) => layer)).toEqual([
            "territory-cells",
            "territory-hatch",
            "territory-casing",
            "territory-edges",
        ]);
        await view.get(".legend .followed li").trigger("mouseleave");
        expect(map.paintCalls).toHaveLength(8);
        expect(map.paintCalls.at(-1)).toEqual([
            "territory-edges",
            "line-opacity",
            1,
        ]);
    });

    it("tells to hover the legend from three materials in « each material »", async () => {
        const store = useExplorerStore();
        store.setMapState({
            track: [LAPIS, "http://material.test/b"],
            mode: "territories",
        });
        const view = await mountView();
        expect(view.find(".territory-note .isolate-hint").exists()).toBe(false);
        store.setMapState({
            track: [LAPIS, "http://material.test/b", "http://material.test/c"],
        });
        await flushPromises();
        expect(view.get(".territory-note .isolate-hint").text()).toBe(
            "Hover a material in the legend to see its zone alone.",
        );
        store.setMapState({ colour: "dominant" });
        await flushPromises();
        expect(view.find(".territory-note .isolate-hint").exists()).toBe(false);
    });

    it("brushes the period a period panel shows", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        await view.get(".map-timeline button.bin").trigger("click");
        await flushPromises();
        await view.get(".map-panel .brush-period").trigger("click");
        expect(store.mapState.brush).not.toBeNull();
    });

    it("links the exports with the filters and the interface language, not the page's lang attribute", async () => {
        document.documentElement.lang = "fr-CA";
        useExplorerStore().setFilter("eventType", ["modification"]);
        const view = await mountView();
        const csv = view.find("a.export[data-format='csv']");
        const geojson = view.find("a.export[data-format='geojson']");
        expect(csv.attributes("href")).toBe(
            "/en/manuspectrum:explorer-events-csv?eventType=modification&lang=en",
        );
        expect(geojson.attributes("href")).toBe(
            "/en/manuspectrum:explorer-events-geojson?eventType=modification&lang=en",
        );
    });

    it("eases the map to a place picked in the list when it is off screen", async () => {
        const view = await mountView();
        const map = FakeMap.last();
        map.shown = [
            [1, 49],
            [2, 50],
        ];
        await view.find(`.place-list [data-place='${PARIS}']`).trigger("click");
        expect(map.easeCalls).toEqual([
            { center: [2.35, 48.85], duration: 420 },
        ]);
    });

    it("draws the borders of the period at every zoom, with no prompt to zoom in", async () => {
        const store = useExplorerStore();
        store.setMapState({ borders: true, brush: [1150, 1250] });
        const view = await mountView();
        const map = FakeMap.last();
        map.getZoom = () => 4;
        map.fire("moveend");
        await flushPromises();
        expect(view.find(".borders-hint").exists()).toBe(false);
        expect(view.find(".borders").text()).toContain(
            "Historical borders (1200)",
        );
        expect(
            map.layers.find((entry) => entry.layer.id === BORDERS_LAYER)?.layer,
        ).toMatchObject({ minzoom: 0, layout: { visibility: "visible" } });
    });

    it("asks a new snapshot only when the bounds change", async () => {
        const store = useExplorerStore();
        const view = await mountView();
        const map = FakeMap.last();
        await modeButton(view, "Small multiples").trigger("click");
        await flushPromises();
        const fits = () =>
            map.fitCalls.filter(([, options]) => options?.padding === 0);
        expect(fits()).toHaveLength(1);
        map.fire("idle");
        await flushPromises();
        store.setMapState({ track: [LAPIS] });
        await flushPromises();
        expect(fits()).toHaveLength(1);
        store.setMapState({ radius: 300 });
        await flushPromises();
        map.fire("idle");
        await flushPromises();
        expect(fits()).toHaveLength(2);
        const image = view.get(".small-multiples image");
        expect(image.attributes("href")).toBe("data:image/png;base64,AAAA");
        const [[west, south], [east, north]] = fits()[1][0] as [
            [number, number],
            [number, number],
        ];
        expect(map.jumpCalls).toHaveLength(2);
        expect(west).toBeLessThan(east);
        expect(south).toBeLessThan(north);
    });

    it("keeps only the answer of the newest snapshot ask", async () => {
        const store = useExplorerStore();
        const view = await mountView();
        const map = FakeMap.last();
        await modeButton(view, "Small multiples").trigger("click");
        await flushPromises();
        store.setMapState({ radius: 300 });
        await flushPromises();
        map.fire("idle");
        await flushPromises();
        expect(view.find(".small-multiples image").exists()).toBe(false);
        map.fire("idle");
        await flushPromises();
        expect(view.find(".small-multiples image").exists()).toBe(true);
    });

    it("drops the waiting snapshot when the reader leaves the small multiples", async () => {
        const store = useExplorerStore();
        const view = await mountView();
        const map = FakeMap.last();
        await modeButton(view, "Small multiples").trigger("click");
        await flushPromises();
        store.setMapState({ radius: 300 });
        await flushPromises();
        await modeButton(view, "Places").trigger("click");
        await flushPromises();
        const fits = map.fitCalls.length;
        map.fire("idle");
        await flushPromises();
        expect(map.fitCalls).toHaveLength(fits);
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
        store.setFilter("eventType", ["modification"]);
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

describe("MapView styles", () => {
    it("styles the rail without the view ancestor, so the drawer copy keeps them", () => {
        const source = readFileSync(`${__dirname}/MapView.vue`, "utf8");
        expect(source).toContain(".map-rail .disclosure {");
        expect(source).not.toContain(".map-view .map-rail");
    });

    it("gives the filters drawer the rail title's display voice", () => {
        const scss = readFileSync(
            `${__dirname}/../../../../../../media/css/explorer.scss`,
            "utf8",
        );
        expect(scss).toMatch(
            /\.p-drawer\.explorer-rail-drawer \.p-drawer-title \{\s*font-family: var\(--font-display\);/,
        );
    });
});
