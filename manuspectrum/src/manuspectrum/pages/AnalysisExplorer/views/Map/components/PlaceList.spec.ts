import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";

import PlaceList from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/PlaceList.vue";

import {
    label,
    mapPlace,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { PlaceSummary } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

function summary(
    id: string,
    name: string,
    documents: number,
    components: number,
    overrides: Partial<PlaceSummary> = {},
): PlaceSummary {
    return {
        id,
        name: label(name),
        lngLat: [2, 48],
        kind: "point",
        extentKm: null,
        documents: new Set(
            Array.from({ length: documents }, (_, n) => `d${n}`),
        ),
        components: new Set(
            Array.from({ length: components }, (_, n) => `c${n}`),
        ),
        analyses: new Set(),
        events: [],
        tracked: new Map(),
        dashed: false,
        unpublished: false,
        ...overrides,
    };
}

const SUMMARIES = [
    summary("p1", "Paris", 9, 14),
    summary("p2", "Évreux", 1, 1, { unpublished: true }),
    summary("p3", "avranches", 2, 0, { kind: "area", dashed: true }),
];

function mountList(
    props: Partial<InstanceType<typeof PlaceList>["$props"]> = {},
) {
    return mount(PlaceList, {
        props: { summaries: SUMMARIES, unplaced: 0, selected: null, ...props },
        global: { plugins: [PrimeVue] },
    });
}

describe("PlaceList", () => {
    it("lists the places by folded name, each named by its counts", () => {
        const wrapper = mountList();
        const rows = wrapper.findAll("li button.place");
        expect(rows.map((row) => row.find(".name").text())).toEqual([
            "avranches",
            "Évreux",
            "Paris",
        ]);
        expect(rows[2].attributes("aria-label")).toBe(
            "Paris — 9 documents, 14 Components",
        );
        expect(rows[1].attributes("aria-label")).toBe(
            "Évreux — 1 document, 1 Component",
        );
        expect(rows[2].find(".counts").text()).toBe("9 · 14");
        expect(rows[0].classes()).toContain("attributed");
        expect(rows[1].find(".unpublished").exists()).toBe(true);
    });

    it("marks the selected place and emits select and hover", async () => {
        const wrapper = mountList({ selected: "p1" });
        const paris = wrapper.find("button.place[data-place=p1]");
        expect(paris.attributes("aria-current")).toBe("true");
        expect(
            wrapper
                .find("button.place[data-place=p2]")
                .attributes("aria-current"),
        ).toBeUndefined();
        await paris.trigger("click");
        expect(wrapper.emitted("select")).toEqual([["p1"]]);
        await paris.trigger("mouseenter");
        await paris.trigger("mouseleave");
        expect(wrapper.emitted("hover")).toEqual([["p1"], [null]]);
    });

    it("offers the events without a mapped place only when there are some", async () => {
        expect(mountList().find("button.more").exists()).toBe(false);
        const wrapper = mountList({ unplaced: 3 });
        const more = wrapper.find("button.more");
        expect(more.text()).toBe("3 events without a mapped place");
        await more.trigger("click");
        expect(wrapper.emitted("unplaced")).toEqual([[]]);
    });

    it("folds into a summary of its counts", async () => {
        const wrapper = mountList({ unplaced: 3, open: false });
        expect(wrapper.find(".collapsible-section .title").text()).toBe(
            "Places (3)",
        );
        expect(wrapper.find(".collapsible-section .summary").text()).toBe(
            "3 places · 3 without a mapped place",
        );
        await wrapper.find(".collapsible-section .toggle").trigger("click");
        expect(wrapper.find(".collapsible-section .summary").exists()).toBe(
            false,
        );
    });

    describe("with many places", () => {
        const many = Array.from({ length: 12 }, (_, n) =>
            summary(`m${n}`, `Place ${String(n).padStart(2, "0")}`, 1, 1),
        );
        const places = {
            m3: mapPlace({ id: "m3", name: label("Place 03"), parent: "nor" }),
            nor: mapPlace({
                id: "nor",
                name: label("Normandie"),
                parent: "m3",
            }),
        };

        it("shows eight rows, the selected one too, then more on demand", async () => {
            const wrapper = mountList({ summaries: many, selected: "m10" });
            const names = () =>
                wrapper.findAll("button.place .name").map((row) => row.text());
            expect(names()).toHaveLength(9);
            expect(names()).toContain("Place 10");
            const more = wrapper.get("button.show-more");
            expect(more.text()).toBe("Show 3 more");
            await more.trigger("click");
            expect(names()).toHaveLength(12);
            expect(wrapper.find("button.show-more").exists()).toBe(false);
        });

        it("searches the folded names of the places and of their parents, every match shown", async () => {
            const wrapper = mountList({ summaries: many, places });
            const search = wrapper.get("input[type=search]");
            await search.setValue("NORMANDÍE");
            expect(
                wrapper.findAll("button.place .name").map((row) => row.text()),
            ).toEqual(["Place 03"]);
            await search.setValue("place");
            expect(wrapper.findAll("button.place")).toHaveLength(12);
            await search.setValue("lyon");
            expect(wrapper.find(".no-match").text()).toBe("No match");
        });

        it("ignores the search once its field is hidden", async () => {
            const wrapper = mountList({ summaries: many });
            await wrapper.get("input[type=search]").setValue("place 03");
            expect(wrapper.findAll("button.place")).toHaveLength(1);
            await wrapper.setProps({ summaries: many.slice(0, 5) });
            expect(wrapper.find("input[type=search]").exists()).toBe(false);
            expect(wrapper.findAll("button.place")).toHaveLength(5);
            expect(wrapper.find(".no-match").exists()).toBe(false);
        });

        it("offers no search for a short list", () => {
            expect(mountList().find("input[type=search]").exists()).toBe(false);
        });
    });
});
