import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import ActiveFiltersBar from "@/manuspectrum/pages/AnalysisExplorer/components/ActiveFiltersBar.vue";
import {
    FLOOR,
    THRESHOLD_MAX,
    THRESHOLD_MIN,
    THRESHOLD_STEP,
    TIE_SHARE,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/territories.ts";
import { LOW_WEIGHT } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";
import MapView from "@/manuspectrum/pages/AnalysisExplorer/views/Map/MapView.vue";
import MapTimeline from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapTimeline.vue";

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
import { installDialog } from "@/manuspectrum/pages/AnalysisExplorer/testing/dialog.ts";
import {
    FakeMap,
    SNAPSHOT_URL,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/maplibre.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    BORDERS_LAYER,
    OHM_LAYERS,
    TERRITORIES_SOURCE,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/stage-layers.ts";
import { toMercator } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";

import type { Pinia } from "pinia";
import type { VueWrapper } from "@vue/test-utils";
import type {
    EventsResponse,
    Label,
    MapEvent,
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
const LARGE_SNAPSHOT = "data:image/png;base64,LARGE";
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
                        colours: [],
                        matches: true,
                        componentColours: [],
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
                ancestors: [],
            },
        },
        analysisNames: {
            [uuid(100)]: label("X01"),
            [uuid(101)]: label("X02"),
        },
    });
}

/** `response()` with the lapis also attested in three documents at `lngLat`, a place far from Paris. */
function farResponse(lngLat: [number, number]): EventsResponse {
    const base = response();
    const far = uuid(12);
    return {
        ...base,
        events: [
            ...base.events,
            ...[4, 5, 6].map((n) =>
                mapEvent({
                    id: `production:d${n}:p${n}`,
                    document: { id: uuid(n), name: label(`Ms ${n}`) },
                    carrier: {
                        id: uuid(n),
                        model: "document",
                        name: label(`Ms ${n}`),
                    },
                    place: far,
                    materials: base.events[0].materials,
                }),
            ),
        ],
        places: {
            ...base.places,
            [far]: mapPlace({ id: far, name: label("Far"), lngLat }),
        },
    };
}

function serve(payload: EventsResponse): void {
    fetchMock.mockImplementation(async (url: string) =>
        url.includes("explorer-events")
            ? jsonResponse(payload)
            : jsonResponse({ values: [], total: 0 }),
    );
}

/** The first corner of every territory cell the map holds. */
function cellCorners(map: FakeMap): number[][] {
    const source = map.getSource(TERRITORIES_SOURCE);
    const drawn = (source?.setDataCalls.at(-1) ?? source?.data) as {
        features: {
            geometry: { coordinates: number[][][] };
            properties: { layer: string };
        }[];
    };
    return drawn.features
        .filter((feature) => feature.properties.layer === "cell")
        .map((feature) => feature.geometry.coordinates[0][0]);
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

    it("ticks a colour head into the Corpus colour filter and names its chip", async () => {
        const blue = "http://colour.test/blue";
        const coloured = response();
        coloured.materials[LAPIS].colours = [blue];
        coloured.colours = {
            [blue]: { uri: blue, label: label("Blue"), swatch: "#2244aa" },
        };
        fetchMock.mockImplementation(async (url: string) =>
            url.includes("explorer-events")
                ? jsonResponse(coloured)
                : jsonResponse({ values: [], total: 0 }),
        );
        const labels = ref(new Map<string, Label>());
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
        const head = wrapper.get(".colour-group .head input[type=checkbox]");
        expect(head.attributes("aria-label")).toBe("Filter: colour Blue");
        await head.setValue(true);
        expect(useExplorerStore().filters.colour).toEqual([blue]);
        await flushPromises();
        expect(wrapper.get(".active-filters").text()).toContain("Colour: Blue");
    });

    it("titles the rail Filters, as the Corpus rail does", async () => {
        const view = await mountView();
        expect(view.get(".rail-title").text()).toBe("Filters");
    });

    it("leaves the Corpus filters to the active-filter chips, with no rail note", async () => {
        const view = await mountView();
        expect(view.find(".rail-note").exists()).toBe(false);
        expect(view.text()).not.toContain("the Corpus filters");
    });

    it("passes the ticked covering materials to the materials control", async () => {
        const pigment = "http://material.test/blue-pigment";
        const covered = response();
        covered.materials[LAPIS] = {
            uri: LAPIS,
            label: label("Lapis lazuli"),
            colours: [],
            swatch: null,
            ancestors: [pigment],
        };
        covered.coveringMaterials = { [pigment]: label("Blue pigment") };
        serve(covered);
        useExplorerStore().setFacet("material", [pigment]);
        const view = await mountView();
        const head = view.get(".materials-control .covering-head");
        expect(head.get(".head-label").text()).toBe("Blue pigment");
        expect(
            view
                .get(".materials-control li.row input[type=checkbox]")
                .attributes("aria-disabled"),
        ).toBe("true");
    });

    it("lists a material that does not meet the filters in the rail only, without a pip or a panel line", async () => {
        const azurite = "http://material.test/azurite";
        const filtered = response();
        filtered.events[0].materials.push({
            id: azurite,
            name: label("Azurite"),
            reliability: null,
            characterization: uuid(201),
            colours: [],
            matches: false,
            componentColours: [],
        });
        filtered.materials[azurite] = {
            uri: azurite,
            label: label("Azurite"),
            colours: [],
            swatch: null,
            ancestors: [],
        };
        fetchMock.mockImplementation(async (url: string) =>
            url.includes("explorer-events")
                ? jsonResponse(filtered)
                : jsonResponse({ values: [], total: 0 }),
        );
        useExplorerStore().setMapState({ track: [azurite] });
        const view = await mountView();
        expect(view.get(".materials-control").text()).toContain("Azurite");
        const map = FakeMap.last();
        expect(
            map.featureStates.some(
                ([target, state]) => target.id === PARIS && state.t1 !== 0,
            ),
        ).toBe(false);
        await view.get(`.place-list [data-place='${PARIS}']`).trigger("click");
        await flushPromises();
        const panel = view.get(".map-panel").text();
        expect(panel).toContain("Lapis lazuli");
        expect(panel).toContain("Azurite not attested");
        expect(panel).not.toContain("Azurite1 doc");
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
        await modeButton(view, "Map series").trigger("click");
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

    it("states the tie share, the low-reliability weight and the default threshold the note prints", () => {
        expect(TIE_SHARE).toBe(0.55);
        expect(LOW_WEIGHT).toBe(0.5);
        expect(FLOOR).toBe(0.5);
        expect(Math.sqrt(Math.log(1 / FLOOR)).toFixed(2)).toBe("0.83");
        expect(Math.exp(-1)).toBeCloseTo(0.37, 2);
        expect([THRESHOLD_MIN, THRESHOLD_MAX, THRESHOLD_STEP]).toEqual([
            0.25, 3, 0.25,
        ]);
    });

    it("explains the influence model behind the note's info button", async () => {
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS], mode: "territories" });
        const view = await mountView();
        const note = view.get(".territory-note");
        const button = note.get(".method button");
        const label = document.getElementById(
            button.attributes("aria-labelledby") ?? "",
        );
        expect(label?.textContent).toBe("About the influence model");
        const method =
            document.getElementById(button.attributes("aria-describedby") ?? "")
                ?.textContent ?? "";
        expect(method).toContain("It weighs 1, or 0.5 when every");
        expect(method).toContain("at d = r it still weighs about 37%");
        expect(method).toContain("0.83 r at the default 0.5");
        expect(method).toContain("less than 55% of the top two");
        expect(method).toContain("not observed data");
        expect(note.text()).toContain("see ⓘ for the method");
    });

    it("redraws the territories under the influence threshold the reader commits", async () => {
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS], mode: "territories" });
        const view = await mountView();
        const map = FakeMap.last();
        const before = cellCorners(map).length;
        const note = view.get(".territory-note");
        const slider = note.get("#explorer-map-threshold");
        expect(note.get("label[for='explorer-map-threshold']").text()).toBe(
            "Influence threshold",
        );
        expect(slider.attributes()).toMatchObject({
            min: "0.25",
            max: "3",
            step: "0.25",
            "aria-valuetext": "at least 0.5 attestations",
        });
        expect(note.get("output[for='explorer-map-threshold']").text()).toBe(
            "≥ 0.5",
        );
        (slider.element as HTMLInputElement).value = "1";
        await slider.trigger("input");
        expect(slider.attributes("aria-valuetext")).toBe(
            "at least 1 attestation",
        );
        (slider.element as HTMLInputElement).value = "2.5";
        await slider.trigger("input");
        expect(note.get("output[for='explorer-map-threshold']").text()).toBe(
            "≥ 2.5",
        );
        expect(store.mapState.threshold).toBe(0.5);
        await slider.trigger("change");
        await flushPromises();
        expect(store.mapState.threshold).toBe(2.5);
        expect(cellCorners(map).length).toBeLessThan(before);
        expect(cellCorners(map).length).toBeGreaterThan(0);
    });

    it("keeps the territories as they are while a place is hovered or opened", async () => {
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS], mode: "territories" });
        const view = await mountView();
        const source = FakeMap.last().getSource(TERRITORIES_SOURCE);
        const drawn = source?.setDataCalls.length ?? 0;
        const row = view.get(`.place-list [data-place='${ROUEN}']`);
        await row.trigger("mouseenter");
        await row.trigger("click");
        await flushPromises();
        expect(view.find(".map-panel").exists()).toBe(true);
        expect(source?.setDataCalls.length).toBe(drawn);
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
        expect(note.text()).toContain(
            "Influence zones: a spatial model, not observed data",
        );
        expect(note.text()).toContain("Gaussian kernel estimate");
        expect(note.text()).toContain(
            "Lower-reliability attestations count half",
        );
        expect(note.get("label").text()).toBe("Kernel radius");
        expect(note.get("input[type='range']").attributes("title")).toContain(
            "falls to about 37%",
        );
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

    it("keeps the approximate dates while ticked, and leaves their events off the map and the timeline when unticked", async () => {
        const base = response();
        base.events[1].date = { start: 1401, end: 1450, approximate: true };
        fetchMock.mockImplementation(async () => jsonResponse(base));
        const view = await mountView();
        const box = view.get(
            ".map-timeline .approximate input[type='checkbox']",
        );
        expect(view.get(".map-timeline .approximate").text()).toBe(
            "Include approximate dates (“c.”)",
        );
        expect((box.element as HTMLInputElement).checked).toBe(true);
        const rouen = `.place-list [data-place='${ROUEN}']`;
        expect(view.find(rouen).exists()).toBe(true);
        const timeline = view.getComponent(MapTimeline);
        expect(timeline.props("events")).toHaveLength(3);
        await box.setValue(false);
        await flushPromises();
        expect(view.find(rouen).exists()).toBe(false);
        expect(view.find(`.place-list [data-place='${PARIS}']`).exists()).toBe(
            true,
        );
        expect(
            timeline.props("events").map((event: MapEvent) => event.id),
        ).not.toContain("production:d2:p2");
        expect(
            view.findAll(".event-types input[type='checkbox']"),
        ).toHaveLength(3);
        expect(view.find(".map-rail .approximate").exists()).toBe(false);
    });

    it("counts the reliability levels and the events without the approximate dates once they are left out", async () => {
        const base = response();
        base.events[0].date = { start: 1300, end: 1350, approximate: true };
        base.events[0].materials[0].reliability = "sure";
        fetchMock.mockImplementation(async () =>
            jsonResponse({
                ...base,
                certaintyScale: {
                    levels: [
                        {
                            id: "sure",
                            uri: "sure",
                            label: label("Certain"),
                            rank: 0,
                        },
                    ],
                },
            }),
        );
        const view = await mountView();
        const levelCount = () => view.get(".levels .value .count").text();
        const typeCount = () => view.get(".event-types .count").text();
        expect(levelCount()).toBe("1");
        expect(typeCount()).toBe("3");
        await view
            .get(".map-timeline .approximate input[type='checkbox']")
            .setValue(false);
        await flushPromises();
        expect(levelCount()).toBe("0");
        expect(typeCount()).toBe("2");
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
            "Narrow the period on the timeline to see its borders.",
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
        expect(map.layoutCalls.slice(-2)).toEqual(
            OHM_LAYERS.map((id) => [id, "visibility", "visible"]),
        );
    });

    it("folds the legend by default and keeps the reader's choice across modes", async () => {
        const view = await mountView();
        const store = useExplorerStore();
        const toggle = () => view.get(".legend .toggle");
        expect(toggle().attributes("aria-expanded")).toBe("false");
        await toggle().trigger("click");
        expect(store.mapState.legend).toBe(true);
        await modeButton(view, "Map series").trigger("click");
        await modeButton(view, "Places").trigger("click");
        await flushPromises();
        expect(toggle().attributes("aria-expanded")).toBe("true");
        expect(view.get("div.legend").classes()).toContain("open");
    });

    it("lays the territories' grid over the view shown, rebuilt once the map stands still", async () => {
        serve(farResponse([116.4, 39.9]));
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS], mode: "territories" });
        await mountView();
        const map = FakeMap.last();
        expect(cellCorners(map).some(([lng]) => lng > 100)).toBe(true);
        vi.useFakeTimers();
        try {
            map.shown = [
                [-5, 42],
                [8, 52],
            ];
            map.fire("moveend");
            vi.advanceTimersByTime(150);
        } finally {
            vi.useRealTimers();
        }
        await flushPromises();
        const corners = cellCorners(map);
        expect(corners.length).toBeGreaterThan(0);
        expect(corners.every(([lng]) => lng > -9 && lng < 12)).toBe(true);
    });

    it("draws no zone and asks to zoom in when the view is too wide for the radius", async () => {
        const store = useExplorerStore();
        store.setMapState({ track: [LAPIS], mode: "territories", radius: 60 });
        const view = await mountView();
        const map = FakeMap.last();
        expect(cellCorners(map).length).toBeGreaterThan(0);
        const zoomIn =
            "Zoom in to see the influence zones: at this scale the grid is coarser than the kernel radius.";
        expect(view.text()).not.toContain(zoomIn);
        vi.useFakeTimers();
        try {
            map.shown = [
                [-180, -80],
                [180, 80],
            ];
            map.fire("moveend");
            vi.advanceTimersByTime(150);
        } finally {
            vi.useRealTimers();
        }
        await flushPromises();
        expect(cellCorners(map)).toEqual([]);
        expect(view.get(".territory-note .coarse").text()).toBe(zoomIn);
        expect(view.text()).not.toContain("Nothing to draw");
    });

    it("fits places around the Pacific across the antimeridian", async () => {
        const base = farResponse([-178.4, -18.1]);
        serve({
            ...base,
            places: {
                ...base.places,
                [PARIS]: mapPlace({ lngLat: [166.45, -22.27] }),
                [ROUEN]: mapPlace({ id: ROUEN, lngLat: [174.76, -36.85] }),
            },
        });
        await mountView();
        const [[west], [east]] = FakeMap.last().fitCalls[0][0] as [
            [number, number],
            [number, number],
        ];
        expect(west).toBeGreaterThan(150);
        expect(east).toBeGreaterThan(180);
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
        await modeButton(view, "Map series").trigger("click");
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

    it("enlarges a map of the series on a snapshot taken at the dialog's size, then adds its material to the ticked ones on the map", async () => {
        const restore = installDialog();
        try {
            const store = useExplorerStore();
            const view = await mountView();
            const map = FakeMap.last();
            await modeButton(view, "Map series").trigger("click");
            await flushPromises();
            map.fire("idle");
            await flushPromises();
            const fits = () =>
                map.fitCalls.filter(([, options]) => options?.padding === 0);
            expect(fits()).toHaveLength(1);
            view.get<HTMLButtonElement>(
                ".small-multiples [data-action='enlarge']",
            ).element.click();
            await flushPromises();
            expect(fits()).toHaveLength(2);
            const [[west, south], [east, north]] = fits()[1][0] as [
                [number, number],
                [number, number],
            ];
            const [x0, y0] = toMercator([west, south]);
            const [x1, y1] = toMercator([east, north]);
            expect((x1 - x0) / (y1 - y0)).toBeCloseTo(960 / 600, 3);
            const dialog = view.get(".series-map-dialog");
            expect(dialog.get(".drawing image").attributes("href")).toBe(
                SNAPSHOT_URL,
            );
            map.canvas.toDataURL = () => LARGE_SNAPSHOT;
            map.fire("idle");
            await flushPromises();
            expect(dialog.get(".drawing image").attributes("href")).toBe(
                LARGE_SNAPSHOT,
            );
            await dialog.get(".show").trigger("click");
            await flushPromises();
            expect(store.filters.material).toEqual([LAPIS]);
            expect(store.mapState.mode).toBe("places");
        } finally {
            restore();
        }
    });

    it("keeps the ticked materials, without a duplicate, when an enlarged map of the series shows its material", async () => {
        const restore = installDialog();
        try {
            const store = useExplorerStore();
            const other = "http://material.test/none-0";
            store.setFilter("material", [other, LAPIS]);
            store.setMapState({ mode: "multiples" });
            const view = await mountView();
            FakeMap.last().fire("idle");
            await flushPromises();
            view.get<HTMLButtonElement>(
                ".small-multiples [data-action='enlarge']",
            ).element.click();
            await flushPromises();
            await view.get(".series-map-dialog .show").trigger("click");
            await flushPromises();
            expect([...store.filters.material].sort()).toEqual(
                [other, LAPIS].sort(),
            );
            expect(store.mapState.mode).toBe("places");
        } finally {
            restore();
        }
    });

    it("leaves out of the series, and of its pages, a ticked material attested at no mapped place", async () => {
        const store = useExplorerStore();
        store.setFilter("material", [
            LAPIS,
            ...Array.from(
                { length: 12 },
                (_, n) => `http://material.test/none-${n}`,
            ),
        ]);
        store.setMapState({ mode: "multiples" });
        const view = await mountView();
        const titles = view
            .findAll(".small-multiples figure .title")
            .map((title) => title.text());
        expect(titles).toEqual(["Lapis lazuli"]);
        expect(view.find(".small-multiples .pager").exists()).toBe(false);
    });

    it("shows a century of the series as the period on the map", async () => {
        const restore = installDialog();
        try {
            const store = useExplorerStore();
            store.setMapState({ mode: "multiples", multiples: "century" });
            const view = await mountView();
            view.get<HTMLButtonElement>(
                ".small-multiples [data-action='enlarge']",
            ).element.click();
            await flushPromises();
            await view.get(".series-map-dialog .show").trigger("click");
            await flushPromises();
            expect(store.mapState.brush).toEqual([1301, 1400]);
            expect(store.mapState.mode).toBe("places");
            const focused = document.activeElement as HTMLElement | null;
            expect(focused?.textContent?.trim()).toBe("Places");
            expect(focused?.getAttribute("aria-pressed")).toBe("true");
        } finally {
            restore();
        }
    });

    it("keeps only the answer of the newest snapshot ask", async () => {
        const store = useExplorerStore();
        const view = await mountView();
        const map = FakeMap.last();
        await modeButton(view, "Map series").trigger("click");
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

    it("drops the mini maps' picture while the new bounds' one is awaited", async () => {
        const store = useExplorerStore();
        const view = await mountView();
        const map = FakeMap.last();
        await modeButton(view, "Map series").trigger("click");
        await flushPromises();
        map.fire("idle");
        await flushPromises();
        expect(view.find(".small-multiples image").exists()).toBe(true);
        store.setMapState({ radius: 300 });
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
        await modeButton(view, "Map series").trigger("click");
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

    it("credits the map's sources in one line under the map, OpenHistoricalMap only while its borders show", async () => {
        const store = useExplorerStore();
        const view = await mountView();
        expect(view.find(".third-party").exists()).toBe(false);
        const credits = view.get(".stage > .frame + .credits");
        expect(credits.text()).toBe(
            "© OpenStreetMap contributors(new tab) · © OpenMapTiles(new tab) · OpenFreeMap(new tab)",
        );
        expect(
            credits
                .findAll("a")
                .map((link) => [
                    link.attributes("href"),
                    link.attributes("rel"),
                    link.attributes("target"),
                ]),
        ).toEqual([
            ["https://www.openstreetmap.org/copyright", "noopener", "_blank"],
            ["https://www.openmaptiles.org/", "noopener", "_blank"],
            ["https://openfreemap.org/", "noopener", "_blank"],
        ]);
        store.setMapState({ borders: true });
        await flushPromises();
        expect(credits.findAll("a")).toHaveLength(3);
        store.setMapState({ brush: [1301, 1400] });
        await flushPromises();
        const ohm = view.findAll(".credits a")[3];
        expect(ohm.get("span").text()).toBe(
            "© OpenHistoricalMap contributors",
        );
        expect(ohm.attributes("href")).toBe(
            "https://www.openhistoricalmap.org/copyright",
        );
        expect(FakeMap.last().options.attributionControl).toBe(false);
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
