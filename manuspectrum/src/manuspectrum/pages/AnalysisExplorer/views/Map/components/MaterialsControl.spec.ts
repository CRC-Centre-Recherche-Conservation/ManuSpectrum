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
const GREEN = "http://colour.test/green";
const YELLOW = "http://colour.test/yellow";
const PURPLE = "http://colour.test/purple";
const OCHRE = "http://colour.test/ochre";
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
    [GREEN]: { uri: GREEN, label: label("Green"), swatch: "#22aa44" },
    [YELLOW]: { uri: YELLOW, label: label("Yellow"), swatch: "#ddcc22" },
    [PURPLE]: { uri: PURPLE, label: label("Purple"), swatch: "#7722aa" },
    [OCHRE]: { uri: OCHRE, label: label("Ochre"), swatch: "#cc8833" },
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
                    matches: true,
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
            "2 docs · 2 Comp.",
        );
    });

    it("heads a group with its whole colour name, the counts after it in the same wrapping line", () => {
        const head = mountControl().get(".colour-group h4 .head");
        const text = head.get(".head-text");
        expect(
            [...text.element.children].map((child) => child.className),
        ).toEqual(["name", "counts"]);
        expect(text.get(".name").attributes("title")).toBeUndefined();
        expect(
            [...head.element.children].map((child) => child.classList[0]),
        ).toEqual([undefined, "swatch", "head-text"]);
        expect(head.element.firstElementChild?.tagName).toBe("INPUT");
    });

    it("ticks a colour head into the Corpus colour filter and unticks it", async () => {
        const store = useExplorerStore();
        const wrapper = mountControl();
        const head = () => wrapper.findAll(".colour-group .head")[1];
        const box = head().get("input[type=checkbox]");
        expect(head().element.tagName).toBe("LABEL");
        expect(box.attributes("aria-label")).toBe("Filter: colour Red");
        await box.setValue(true);
        expect(store.filters.colour).toEqual([RED]);
        expect(store.filters.material).toEqual([]);
        expect(head().classes()).toContain("ticked");
        await head().get("input[type=checkbox]").setValue(false);
        expect(store.filters.colour).toEqual([]);
        expect(head().classes()).not.toContain("ticked");
    });

    it("shows a colour ticked in the Corpus as a ticked head", async () => {
        const store = useExplorerStore();
        store.setFacet("colour", [BLUE]);
        const wrapper = mountControl();
        const [blue, red] = wrapper.findAll(".colour-group .head");
        expect((blue.get("input").element as HTMLInputElement).checked).toBe(
            true,
        );
        expect(blue.classes()).toContain("ticked");
        expect((red.get("input").element as HTMLInputElement).checked).toBe(
            false,
        );
        store.setFacet("colour", []);
        await flushPromises();
        expect((blue.get("input").element as HTMLInputElement).checked).toBe(
            false,
        );
    });

    it("keeps the head of a ticked colour no row falls under, without counts", async () => {
        const store = useExplorerStore();
        store.setFacet("colour", [GREEN]);
        const wrapper = mountControl();
        const green = wrapper
            .findAll(".colour-group")
            .find((group) => group.get(".name").text() === "Green");
        expect(green).toBeDefined();
        expect(green?.findAll("li.row")).toHaveLength(0);
        expect(green?.find(".counts").exists()).toBe(false);
        await green?.get(".head input").setValue(false);
        expect(store.filters.colour).toEqual([]);
        expect(
            wrapper.findAll(".colour-group .name").map((name) => name.text()),
        ).not.toContain("Green");
    });

    it("gives the group without a recorded colour no checkbox", () => {
        const heads = mountControl().findAll(".colour-group .head");
        const none = heads[heads.length - 1];
        expect(none.get(".name").text()).toBe("No colour recorded");
        expect(none.element.tagName).toBe("SPAN");
        expect(none.find("input").exists()).toBe(false);
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
        expect(wrapper.find(".refused").exists()).toBe(false);

        await rowOf(wrapper, "Minium").find("button.follow").trigger("click");
        expect(store.mapState.track).toEqual(URIS.slice(0, 4));
        expect(wrapper.find(".refused").text()).toBe(
            "Four materials are followed already: stop following one first.",
        );
        expect(wrapper.find(".refused").attributes("role")).toBeUndefined();
        expect(announce).toHaveBeenLastCalledWith(
            "Four materials are followed already: stop following one first.",
        );

        await wrapper.find(".chip-row .unpin").trigger("click");
        expect(store.mapState.track).toEqual([null, ...URIS.slice(1, 4)]);
        await rowOf(wrapper, "Minium").find("button.follow").trigger("click");
        expect(store.mapState.track).toEqual([URIS[4], ...URIS.slice(1, 4)]);
        expect(wrapper.find(".refused").exists()).toBe(false);
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
                        matches: true,
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
        const counts = meta.get(".row-counts");
        expect(counts.text()).toBe("1 doc · 1 Comp.");
        expect(counts.attributes("title")).toBe("1 document, 1 Component");
        expect(meta.element.firstElementChild).toBe(counts.element);
        expect(meta.element.previousElementSibling).toBe(
            row.get(".value .label").element,
        );
        expect(
            [...row.element.children].map((child) => child.classList[0]),
        ).toEqual(["value", "help-tip"]);
        expect(row.element.lastElementChild?.classList).toContain("follow-tip");
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

    it("names the other observed colours of a row, and how many are not drawn", () => {
        const known = {
            ...materials,
            [URIS[0]]: material(0, [BLUE, RED, GREEN, YELLOW, PURPLE, OCHRE]),
        };
        const others = rowOf(mountControl(events(), known), "Lapis lazuli").get(
            ".others",
        );
        const name = "Also observed in: Red, Green, Yellow, Purple, and Ochre";
        expect(others.attributes("role")).toBe("img");
        expect(others.attributes("aria-label")).toBe(name);
        expect(others.attributes("title")).toBe(name);
        expect(others.findAll(".swatch")).toHaveLength(3);
        const more = others.get(".more-colours");
        expect(more.text()).toBe("+2");
        expect(more.attributes("title")).toBe("and 2 more colours");
    });

    it("says how the materials are grouped, with no separate counts legend", () => {
        const wrapper = mountControl();
        expect(wrapper.get(".grouping-hint").text()).toBe(
            "Grouped by the colour most often observed on each material; tick a colour to filter by it.",
        );
        expect(wrapper.get(".columns").element.nextElementSibling).toBe(
            wrapper.get(".grouping-hint").element,
        );
        expect(wrapper.find(".legend").exists()).toBe(false);
    });
});
