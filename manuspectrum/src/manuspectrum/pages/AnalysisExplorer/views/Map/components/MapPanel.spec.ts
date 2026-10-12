import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import MapPanel from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapPanel.vue";

import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import {
    ANNOUNCE_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    label,
    mapEvent,
    mapPlace,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Pinia } from "pinia";
import type { VueWrapper } from "@vue/test-utils";
import type {
    CertaintyScale,
    MapEvent,
    MapMaterial,
    MapPlace,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { PanelSubject } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/panel-groups.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

const PARIS = uuid(10);
const NORMANDY = uuid(11);
const LAPIS = "http://material.test/lapis";
const AZURITE = "http://material.test/azurite";
const SURE = "http://certainty.test/sure";
const DOUBT = "http://certainty.test/doubt";

const certainty: CertaintyScale = {
    levels: [
        { id: SURE, uri: SURE, label: label("Certain"), rank: 0 },
        { id: DOUBT, uri: DOUBT, label: label("Uncertain"), rank: 3 },
    ],
};

const places: Record<string, MapPlace> = {
    [PARIS]: mapPlace({
        authorities: { geonames: "2988507", wikidata: "Q90" },
    }),
    [NORMANDY]: mapPlace({
        id: NORMANDY,
        name: label("Normandy"),
        geometryKind: "area",
        unpublished: true,
    }),
};

const materials: Record<string, MapMaterial> = {
    [AZURITE]: {
        uri: AZURITE,
        label: label("Azurite"),
        colours: [],
        swatch: "#2244aa",
    },
    [LAPIS]: {
        uri: LAPIS,
        label: label("Lapis lazuli"),
        colours: [],
        swatch: null,
    },
};

function azurite(reliability: string | null = SURE) {
    return {
        id: AZURITE,
        name: label("Azurite"),
        reliability,
        characterization: uuid(300),
    };
}

/** Ms B (one analysis, own production) and Ms A (folio 2 then folio 1, three analyses), all in Paris. */
function events(): MapEvent[] {
    return [
        mapEvent({
            id: "production:b",
            document: { id: uuid(2), name: label("Ms B") },
            analyses: [uuid(101)],
            materials: [azurite(DOUBT)],
        }),
        mapEvent({
            id: "production:a2",
            document: { id: uuid(1), name: label("Ms A") },
            component: { id: uuid(52), name: label("f. 2") },
            analyses: [uuid(102)],
            materials: [azurite()],
        }),
        mapEvent({
            id: "modification:a1",
            type: "modification",
            document: { id: uuid(1), name: label("Ms A") },
            component: { id: uuid(51), name: label("f. 1") },
            date: { start: 1450, end: 1460, approximate: true },
            placeSource: "parent",
            analyses: [uuid(103), uuid(104)],
        }),
    ];
}

const analysisNames = {
    [uuid(101)]: label("B-XRF"),
    [uuid(102)]: label("A2-XRF"),
    [uuid(103)]: label("A1-Raman"),
    [uuid(104)]: label("A1-FORS"),
};
const ALL_KEYS = [101, 102, 103, 104].map((n) => analysisKey(uuid(n)));
const analysisTechniques = {
    [uuid(102)]: {
        code: "XRF",
        colour: 2,
        family: "http://technique.test/xrf",
    },
    [uuid(103)]: {
        code: "RAM",
        colour: 4,
        family: "http://technique.test/raman",
    },
};

/** One document, one Component, `count` analyses in one production. */
function crowded(count: number): MapEvent[] {
    return [
        mapEvent({
            id: "production:crowded",
            document: { id: uuid(7), name: label("Ms C") },
            component: { id: uuid(70), name: label("f. 1") },
            analyses: Array.from({ length: count }, (_, n) => uuid(1000 + n)),
        }),
    ];
}

async function unfold(wrapper: VueWrapper): Promise<void> {
    for (const button of wrapper.findAll(".panel-document .disclosure")) {
        if (button.attributes("aria-expanded") === "false") {
            await button.trigger("click");
        }
    }
}

const announce = vi.fn();
let pinia: Pinia;
const mounted: VueWrapper[] = [];

function mountPanel(
    props: {
        subject?: PanelSubject;
        events?: MapEvent[];
        tracked?: TrackedMaterial[];
    } = {},
) {
    const wrapper = mount(MapPanel, {
        props: {
            subject: { kind: "place", id: PARIS },
            events: events(),
            places,
            analysisNames,
            analysisTechniques,
            tracked: [],
            low: new Set([DOUBT]),
            materials,
            certainty,
            ...props,
        },
        global: {
            plugins: [pinia],
            provide: {
                [ANNOUNCE_KEY as symbol]: announce,
                [SELECTION_HINTS_KEY as symbol]: ref(
                    new Map<string, SelectionHint>(),
                ),
            },
        },
    });
    mounted.push(wrapper);
    return wrapper;
}

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    announce.mockReset();
    mount(
        defineComponent({
            setup() {
                useSelectionToggle().dismiss();
                return () => h("div");
            },
        }),
        { global: { plugins: [pinia] } },
    );
});

afterEach(() => {
    for (const wrapper of mounted.splice(0)) {
        if (wrapper.exists()) wrapper.unmount();
    }
});

describe("MapPanel", () => {
    it("titles a place with its counts and authority links", () => {
        const wrapper = mountPanel();
        expect(wrapper.find("h2").text()).toBe("Paris");
        expect(wrapper.find(".counts-line").text()).toBe(
            "2 documents · 2 Components · 4 analyses",
        );
        const links = wrapper.findAll("a.authority");
        expect(links.map((link) => link.attributes("href"))).toEqual([
            "https://www.geonames.org/2988507",
            "https://www.wikidata.org/wiki/Q90",
        ]);
        expect(links[0].attributes("aria-label")).toBe(
            "GeoNames record of Paris (new tab)",
        );
        expect(links[0].attributes("rel")).toBe("noopener");
        expect(wrapper.find(".meta").text()).not.toContain("Attributed place");
    });

    it("says an area place is attributed, with its Draft badge", () => {
        const wrapper = mountPanel({
            subject: { kind: "place", id: NORMANDY },
            events: events().map((event) => ({ ...event, place: NORMANDY })),
        });
        expect(wrapper.find("h2").text()).toBe("Normandy");
        expect(wrapper.find(".meta").text()).toContain("Attributed place");
        expect(wrapper.find(".meta .badge").text()).toBe("Draft");
        expect(wrapper.findAll("a.authority")).toHaveLength(0);
    });

    it("groups by document name, the document itself first, then each Component", async () => {
        const wrapper = mountPanel();
        await unfold(wrapper);
        const documents = wrapper.findAll(".panel-document");
        expect(documents.map((d) => d.find("h4 .group-title").text())).toEqual([
            "Ms A",
            "Ms B",
        ]);
        expect(
            documents[0].findAll(".component-title").map((c) => c.text()),
        ).toEqual(["f. 1", "f. 2"]);
        expect(documents[1].find(".component-title").text()).toBe(
            "Document itself",
        );
        expect(documents[0].text()).toContain("Attributed place");
        expect(documents[0].text()).toContain("c. 1450–1460");
    });

    it("adds every analysis of the page with the page select-all", async () => {
        const store = useExplorerStore();
        const wrapper = mountPanel();
        const page = wrapper.find(".page-select input");
        expect(page.attributes("aria-label")).toBe(
            "Add the analyses of Paris to the Selection",
        );
        await page.trigger("change");
        expect(store.basket.map((item) => item.key).sort()).toEqual(
            [...ALL_KEYS].sort(),
        );
    });

    it("refuses the page select-all when it does not fit, with the capacity notice", async () => {
        const store = useExplorerStore();
        store.addManyToBasket(
            Array.from({ length: 29 }, (_, n) => analysisKey(uuid(500 + n))),
        );
        const wrapper = mountPanel();
        await flushPromises();
        const page = wrapper.find(".page-select input");
        expect(page.attributes("aria-disabled")).toBe("true");
        await page.trigger("change");
        expect(store.basket).toHaveLength(29);
        expect(wrapper.find(".selection-capacity-notice").exists()).toBe(true);
    });

    it("opens Compare from the bulk line and from the footer", async () => {
        const store = useExplorerStore();
        const wrapper = mountPanel();
        expect(wrapper.find(".foot .compare").attributes("aria-disabled")).toBe(
            "true",
        );
        await wrapper.find(".page-select input").trigger("change");
        await flushPromises();
        expect(wrapper.find(".foot .compare").text()).toBe("Compare (4)");
        await wrapper
            .find(".bulk-status-line [data-action=compare]")
            .trigger("click");
        expect(store.view).toBe("compare");
    });

    it("writes a sentence for a followed material absent here", () => {
        const wrapper = mountPanel({
            tracked: [
                { uri: AZURITE, slot: 1 },
                { uri: LAPIS, slot: 2 },
            ],
            events: events().map((event) =>
                event.materials.length > 0
                    ? {
                          ...event,
                          materials: [
                              ...event.materials,
                              {
                                  id: LAPIS,
                                  name: label("Lapis lazuli"),
                                  reliability: null,
                                  characterization: uuid(301),
                              },
                          ],
                      }
                    : event,
            ),
        });
        expect(wrapper.find(".absence").exists()).toBe(false);
        const absent = mountPanel({
            tracked: [{ uri: LAPIS, slot: 2 }],
        });
        expect(absent.find(".absence").text()).toBe(
            "Lapis lazuli not attested among the 2 documents analysed here. This does not mean it was not used.",
        );
    });

    it("lists the materials here, followed first, pale when low only", async () => {
        const wrapper = mountPanel({ tracked: [{ uri: AZURITE, slot: 3 }] });
        await unfold(wrapper);
        const rows = wrapper.findAll(".attested li");
        expect(rows).toHaveLength(1);
        expect(rows[0].find(".label").text()).toBe("Azurite");
        expect(rows[0].find(".focus-slot-dot").text()).toBe("3");
        expect(rows[0].classes()).not.toContain("pale");
        expect(rows[0].find(".reliability").text()).toBe("Certain");
        const chips = wrapper.findAll(".event-materials .material");
        expect(chips.some((chip) => chip.classes().includes("pale"))).toBe(
            true,
        );
    });

    it("notes a production material no modification cites", async () => {
        const wrapper = mountPanel();
        await unfold(wrapper);
        const notes = wrapper.findAll(".placed-note");
        expect(notes).toHaveLength(2);
        expect(notes[0].text()).toBe(
            "placed on the production (no modification cites it)",
        );
    });

    it("opens the document in Corpus", async () => {
        const store = useExplorerStore();
        const wrapper = mountPanel();
        await unfold(wrapper);
        const link = wrapper.find(".panel-document a.open-corpus");
        expect(link.attributes("href")).toContain(`doc=${uuid(1)}`);
        await link.trigger("click");
        expect(store.view).toBe("corpus");
        expect(store.document?.id).toBe(uuid(1));
    });

    it("folds the documents of a subject with several, without mounting their body", async () => {
        const wrapper = mountPanel();
        const buttons = wrapper.findAll(".panel-document .disclosure");
        expect(buttons.map((b) => b.attributes("aria-expanded"))).toEqual([
            "false",
            "false",
        ]);
        expect(wrapper.find(".component-group").exists()).toBe(false);
        expect(buttons[0].find(".document-counts").text()).toBe(
            "2 Components · 3 analyses",
        );
        expect(
            buttons[0].findAll(".summary-tag .code").map((tag) => tag.text()),
        ).toEqual(["RAM", "XRF"]);
        await buttons[0].trigger("click");
        expect(buttons[0].attributes("aria-expanded")).toBe("true");
        const body = wrapper.get(`#${buttons[0].attributes("aria-controls")}`);
        expect(body.findAll(".component-group")).toHaveLength(2);
        expect(buttons[0].find(".summary-tag").exists()).toBe(false);
    });

    it("opens a lone small document", () => {
        const wrapper = mountPanel({
            subject: { kind: "document", id: uuid(2) },
        });
        expect(
            wrapper
                .get(".panel-document .disclosure")
                .attributes("aria-expanded"),
        ).toBe("true");
        expect(wrapper.find(".component-group").exists()).toBe(true);
    });

    it("marks each analysis with its technique", async () => {
        const wrapper = mountPanel();
        await unfold(wrapper);
        const rows = wrapper.findAll(".analysis-list li");
        const tagged = rows.filter((row) =>
            row.find(".technique-tag").exists(),
        );
        expect(tagged.map((row) => row.find(".code").text())).toEqual([
            "RAM",
            "XRF",
        ]);
        expect(tagged[0].find(".analysis-name").text()).toBe("A1-Raman");
    });

    it("shows five analyses of a crowded Component, then twenty more per click", async () => {
        const wrapper = mountPanel({
            subject: { kind: "document", id: uuid(7) },
            events: crowded(40),
        });
        expect(wrapper.find(".analysis-list").exists()).toBe(false);
        await unfold(wrapper);
        expect(wrapper.findAll(".analysis-list li")).toHaveLength(5);
        expect(wrapper.find(".capacity").text()).toContain(
            "40 analyses here: open the document in Corpus to filter them by technique.",
        );
        expect(wrapper.find(".capacity a.open-corpus").exists()).toBe(true);
        const more = wrapper.get(".component-group > .more");
        expect(more.text()).toBe("Show 20 more analyses");
        await more.trigger("click");
        expect(wrapper.findAll(".analysis-list li")).toHaveLength(25);
        expect(wrapper.get(".component-group > .more").text()).toBe(
            "Show 15 more analyses",
        );
        expect(
            wrapper.findAll("input[type=checkbox]").length,
        ).toBeLessThanOrEqual(60);
    });

    it("shows three events per Component, then the others", async () => {
        const many = Array.from({ length: 5 }, (_, n) =>
            mapEvent({
                id: `modification:${n}`,
                type: "modification",
                document: { id: uuid(7), name: label("Ms C") },
                component: { id: uuid(70), name: label("f. 1") },
                analyses: [],
            }),
        );
        const wrapper = mountPanel({
            subject: { kind: "document", id: uuid(7) },
            events: many,
        });
        expect(wrapper.findAll(".event")).toHaveLength(3);
        const more = wrapper.get(".component-group > .more");
        expect(more.text()).toBe("+ 2 events");
        await more.trigger("click");
        expect(wrapper.findAll(".event")).toHaveLength(5);
    });

    it("shows five documents, then ten more per click", async () => {
        const many = Array.from({ length: 17 }, (_, n) =>
            mapEvent({
                id: `production:${n}`,
                document: {
                    id: uuid(600 + n),
                    name: label(`Ms ${String(n).padStart(2, "0")}`),
                },
            }),
        );
        const wrapper = mountPanel({ events: many });
        expect(wrapper.findAll(".panel-document")).toHaveLength(5);
        const more = () => wrapper.get(".analyses > .more");
        expect(more().text()).toBe("+ 12 other documents");
        await more().trigger("click");
        expect(wrapper.findAll(".panel-document")).toHaveLength(15);
        await more().trigger("click");
        expect(wrapper.findAll(".panel-document")).toHaveLength(17);
        expect(wrapper.find(".analyses > .more").exists()).toBe(false);
    });

    it("lists eight materials, then the others", async () => {
        const many = Array.from({ length: 11 }, (_, n) =>
            mapEvent({
                id: `production:m${n}`,
                materials: [
                    {
                        id: `http://material.test/${n}`,
                        name: label(`Material ${String(n).padStart(2, "0")}`),
                        reliability: SURE,
                        characterization: uuid(700 + n),
                    },
                ],
            }),
        );
        const wrapper = mountPanel({ events: many });
        expect(wrapper.findAll(".attested li")).toHaveLength(8);
        const more = wrapper.get(".attested .more");
        expect(more.text()).toBe("Show 3 more materials");
        await more.trigger("click");
        expect(wrapper.findAll(".attested li")).toHaveLength(11);
        const meta = wrapper.get(".attested li .meta");
        expect(meta.get(".reliability").text()).toBe("Certain");
        expect(meta.get(".row-counts").text()).toBe("1 doc. · 0 comp.");
    });

    it("says « here » when the analyses do not fit in the Selection", async () => {
        const store = useExplorerStore();
        store.addManyToBasket(
            Array.from({ length: 29 }, (_, n) => analysisKey(uuid(500 + n))),
        );
        const wrapper = mountPanel();
        await flushPromises();
        expect(wrapper.get(".selection-capacity-notice .text").text()).toBe(
            "4 analyses here to add: tick them one by one or make room.",
        );
    });

    it("brushes the map on a period from its head", async () => {
        const wrapper = mountPanel({
            subject: { kind: "period", from: 1301, to: 1325 },
        });
        await wrapper.get(".brush-period").trigger("click");
        expect(wrapper.emitted("brush")).toEqual([[[1301, 1325]]]);
        expect(mountPanel().find(".brush-period").exists()).toBe(false);
    });

    it("titles the other subjects and closes", async () => {
        const period = mountPanel({
            subject: { kind: "period", from: 1301, to: 1325 },
        });
        expect(period.find("h2").text()).toBe("1301–1325");
        const unplaced = mountPanel({ subject: { kind: "unplaced" } });
        expect(unplaced.find("h2").text()).toBe(
            "Events without a mapped place",
        );
        const material = mountPanel({
            subject: { kind: "material", uri: AZURITE },
        });
        expect(material.find("h2").text()).toBe("Azurite");
        const document = mountPanel({
            subject: { kind: "document", id: uuid(2) },
        });
        expect(document.find("h2").text()).toBe("Ms B");
        await document.find(".foot .close").trigger("click");
        await document.trigger("keydown", { key: "Escape" });
        expect(document.emitted("close")).toHaveLength(2);
    });
});
