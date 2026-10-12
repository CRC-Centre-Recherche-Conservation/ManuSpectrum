import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";

import MaterialsControl from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MaterialsControl.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    facet,
    facetValue,
    label,
    mapEvent,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { Pinia } from "pinia";
import type {
    MapColour,
    MapEvent,
    MapMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) => `/en/${name}`,
}));

const BLUE = "http://colour.test/blue";
const RED = "http://colour.test/red";
const NAMES = ["Lapis lazuli", "Azurite", "Vermilion", "Lead white", "Minium"];
const URIS = NAMES.map((_, index) => `http://material.test/m${index + 1}`);

const fetchMock = vi.fn();
const announce = vi.fn();
let pinia: Pinia;

function material(index: number, colours: string[]): MapMaterial {
    return {
        uri: URIS[index],
        label: label(NAMES[index]),
        colours,
        swatch: null,
    };
}

const materials: Record<string, MapMaterial> = {
    [URIS[0]]: material(0, [BLUE, RED]),
    [URIS[1]]: material(1, [BLUE]),
    [URIS[2]]: material(2, [RED]),
    [URIS[3]]: material(3, []),
    [URIS[4]]: material(4, [RED]),
};

const colours: Record<string, MapColour> = {
    [BLUE]: { uri: BLUE, label: label("Blue"), swatch: "#2244aa" },
    [RED]: { uri: RED, label: label("Red"), swatch: "#aa2222" },
};

function events(): MapEvent[] {
    return URIS.map((uri, index) =>
        mapEvent({
            id: `production:${index}`,
            document: { id: uuid(index + 1), name: label(`Ms ${index}`) },
            component: { id: uuid(50 + index), name: label(`f. ${index}`) },
            materials: [
                {
                    id: uri,
                    name: label(NAMES[index]),
                    reliability: null,
                    characterization: uuid(200 + index),
                },
            ],
        }),
    );
}

function mountControl(
    shown: MapEvent[] = events(),
    known: Record<string, MapMaterial> = materials,
) {
    return mount(MaterialsControl, {
        props: { events: shown, materials: known, colours },
        global: {
            plugins: [pinia, PrimeVue],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        },
    });
}

function rowOf(wrapper: ReturnType<typeof mountControl>, name: string) {
    const row = wrapper
        .findAll("li.row")
        .find((item) => item.find(".label").text() === name);
    if (!row) throw new Error(`no row ${name}`);
    return row;
}

beforeEach(() => {
    forgetPayloads();
    pinia = createPinia();
    setActivePinia(pinia);
    fetchMock.mockReset();
    announce.mockReset();
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("MaterialsControl", () => {
    it("groups the materials by observed colour, the uncoloured last", () => {
        const wrapper = mountControl();
        const headings = wrapper.findAll(".colour-group h4 .name");
        expect(headings.map((heading) => heading.text())).toEqual([
            "Blue",
            "Red",
            "No colour recorded",
        ]);
        expect(wrapper.find(".colour-group .counts").text()).toBe(
            "2 doc · 2 comp",
        );
    });

    it("ticks a material into the material filter and unticks it", async () => {
        const store = useExplorerStore();
        const wrapper = mountControl();
        const box = rowOf(wrapper, "Azurite").find("input[type=checkbox]");
        expect(box.attributes("aria-label")).toBe("Filter: Azurite");
        await box.setValue(true);
        expect(store.filters.material).toEqual([URIS[1]]);
        await rowOf(wrapper, "Azurite")
            .find("input[type=checkbox]")
            .setValue(false);
        expect(store.filters.material).toEqual([]);
    });

    it("follows into slots 1 to 4 and refuses a fifth with a notice", async () => {
        const store = useExplorerStore();
        const wrapper = mountControl();
        for (const name of NAMES.slice(0, 4)) {
            await rowOf(wrapper, name).find("button.follow").trigger("click");
        }
        expect(store.mapState.track).toEqual(URIS.slice(0, 4));
        const followed = rowOf(wrapper, "Vermilion").find("button.follow");
        expect(followed.attributes("aria-pressed")).toBe("true");
        expect(followed.attributes("aria-label")).toBe(
            "Stop following Vermilion (colour 3)",
        );
        expect(followed.text()).toBe("3");
        expect(followed.attributes("data-bloom")).toBe("odd");
        expect(wrapper.find("[role=status].refused").exists()).toBe(false);

        await rowOf(wrapper, "Minium").find("button.follow").trigger("click");
        expect(store.mapState.track).toEqual(URIS.slice(0, 4));
        expect(wrapper.find("[role=status].refused").text()).toBe(
            "Four materials are followed already: stop following one first.",
        );
        expect(announce).toHaveBeenLastCalledWith(
            "Four materials are followed already: stop following one first.",
        );

        await wrapper.find(".chip-row .unpin").trigger("click");
        expect(store.mapState.track).toEqual([null, ...URIS.slice(1, 4)]);
        await rowOf(wrapper, "Minium").find("button.follow").trigger("click");
        expect(store.mapState.track).toEqual([URIS[4], ...URIS.slice(1, 4)]);
        expect(wrapper.find("[role=status].refused").exists()).toBe(false);
        expect(announce).toHaveBeenCalledWith("Following Minium (colour 1).");
    });

    it("heads the two controls « Show » and « Follow », and explains Follow on each button", () => {
        const wrapper = mountControl();
        expect(
            wrapper.findAll(".columns span").map((entry) => entry.text()),
        ).toEqual(["Show", "Follow"]);
        const follow = rowOf(wrapper, "Vermilion").get("button.follow");
        const help = wrapper.get(
            `[id="${follow.attributes("aria-describedby")}"]`,
        );
        expect(help.text()).toBe(
            "Follow gives the material its own colour on the map, its territory and its line in the timeline (four at most). Show only shows or hides its events.",
        );
    });

    it("shows a followed chip per slot, and the any / all toggle from two", async () => {
        const store = useExplorerStore();
        const wrapper = mountControl();
        store.toggleTrack(URIS[0]);
        await flushPromises();
        expect(wrapper.findAll(".chip-row")).toHaveLength(1);
        expect(wrapper.find(".track-mode").exists()).toBe(false);
        store.toggleTrack(URIS[2]);
        await flushPromises();
        expect(
            wrapper.findAll(".chip-row .chip-label").map((c) => c.text()),
        ).toEqual(["Lapis lazuli", "Vermilion"]);
        const all = wrapper.find(".track-mode button[data-mode=all]");
        expect(all.attributes("aria-pressed")).toBe("false");
        await all.trigger("click");
        expect(store.trackMode).toBe("all");
        expect(all.attributes("aria-pressed")).toBe("true");
    });

    it("says when a followed material is not attested in the kept events", async () => {
        const store = useExplorerStore();
        const wrapper = mountControl(events().slice(1));
        store.toggleTrack(URIS[0]);
        await flushPromises();
        const chip = wrapper.find(".chip-row");
        expect(chip.classes()).toContain("absent");
        expect(chip.find(".absent-note").text()).toBe(
            "not attested in the kept events",
        );
        expect(chip.find(".chip-label").text()).toBe("Lapis lazuli");
    });

    it("narrows the rows to the facet search answer", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse({
                ...facet("material", 0),
                values: [facetValue(URIS[1], "Azurite")],
                total: 1,
            }),
        );
        const wrapper = mountControl();
        await wrapper.find("input[type=search]").setValue("azur");
        await flushPromises();
        const url = String(fetchMock.mock.calls[0][0]);
        expect(url).toContain("/en/manuspectrum:explorer-facet?");
        expect(new URLSearchParams(url.split("?")[1]).get("find")).toBe("azur");
        expect(
            wrapper.findAll("li.row .label").map((row) => row.text()),
        ).toEqual(["Azurite"]);
    });

    it("says « No match » when the search answers nothing", async () => {
        fetchMock.mockResolvedValue(
            jsonResponse({ ...facet("material", 0), values: [], total: 0 }),
        );
        const wrapper = mountControl();
        await wrapper.find("input[type=search]").setValue("zzz");
        await flushPromises();
        expect(wrapper.findAll("li.row")).toHaveLength(0);
        expect(wrapper.find(".no-match").text()).toBe("No match");
    });

    it("shows five rows per colour, ticked and followed ones above the cut", async () => {
        const many = Array.from({ length: 8 }, (_, n) => ({
            uri: `http://material.test/blue${n}`,
            label: label(`Blue ${n}`),
            colours: [BLUE],
            swatch: null,
        }));
        const shown = many.map((entry, n) =>
            mapEvent({
                id: `production:blue${n}`,
                document: { id: uuid(300 + n), name: label(`Ms ${n}`) },
                component: { id: uuid(400 + n), name: label(`f. ${n}`) },
                materials: [
                    {
                        id: entry.uri,
                        name: entry.label,
                        reliability: null,
                        characterization: uuid(500 + n),
                    },
                ],
            }),
        );
        const known = Object.fromEntries(many.map((m) => [m.uri, m]));
        const store = useExplorerStore();
        store.setFacet("material", [many[7].uri]);
        store.toggleTrack(many[6].uri);
        const wrapper = mountControl(shown, known);
        const labels = () =>
            wrapper.findAll("li.row .label").map((row) => row.text());
        expect(labels()).toHaveLength(5);
        expect(labels().slice(0, 2).sort()).toEqual(["Blue 6", "Blue 7"]);
        const more = wrapper.get(".colour-group .more");
        expect(more.text()).toBe("Show 3 more");
        await more.trigger("click");
        expect(labels()).toHaveLength(8);
        expect(wrapper.find(".colour-group .more").exists()).toBe(false);
        fetchMock.mockResolvedValue(
            jsonResponse({
                ...facet("material", 0),
                values: many.map((m) => facetValue(m.uri, m.label.value)),
                total: 8,
            }),
        );
        const searched = mountControl(shown, known);
        await searched.find("input[type=search]").setValue("blue");
        await flushPromises();
        expect(searched.findAll("li.row")).toHaveLength(8);
    });

    it("keeps the counts and the other colours on the label's second line", () => {
        const row = rowOf(mountControl(), "Lapis lazuli");
        const meta = row.get(".value .meta");
        expect(meta.find(".others").exists()).toBe(true);
        expect(meta.find(".row-counts").text()).toBe("1 · 1");
        expect(row.get(".value .label").attributes("title")).toBe(
            "Lapis lazuli",
        );
    });

    it("isolates a followed chip's slot while it is hovered or focused", async () => {
        useExplorerStore().toggleTrack(URIS[1]);
        const wrapper = mountControl();
        const chip = wrapper.get(".chip-row");
        await chip.trigger("mouseenter");
        await chip.trigger("mouseleave");
        await chip.get(".unpin").trigger("focusin");
        await chip.get(".unpin").trigger("focusout");
        expect(wrapper.emitted("isolate")).toEqual([[1], [null], [1], [null]]);
    });

    it("draws the other colours as decorative swatches", () => {
        const wrapper = mountControl();
        const swatches = rowOf(wrapper, "Lapis lazuli").find(".others");
        expect(swatches.attributes("aria-hidden")).toBe("true");
        expect(swatches.attributes("title")).toBe(
            "observed colour, not an identity",
        );
        expect(swatches.findAll(".swatch")).toHaveLength(1);
    });
});
